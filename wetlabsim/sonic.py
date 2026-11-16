"""The Unitree G1's whole-body controller: NVIDIA's GEAR-SONIC.

SONIC is three neural networks NVIDIA trained for the G1 and released for its real robot
(Hugging Face nvidia/GEAR-SONIC, NVIDIA Open Model License; code github.com/NVlabs/
GR00T-WholeBodyControl, Apache 2.0):

* a kinematic planner that, given a movement style (walk, run, crawl, kneel, ...), a direction,
  speed, facing and body height, imagines the next couple of seconds of whole-body motion;
* an encoder that turns the next second of that motion into a small "motion token";
* a decoder, the controller itself, that reads the token and the robot's own sensors (pelvis
  IMU, the 29 joint encoders, its last outputs; 10 readings back) 50 times a second and sets
  position targets for all 29 body joints.

This is a Python port of NVIDIA's own deployment program for the real G1
(gear_sonic_deploy/src/g1/g1_deploy_onnx_ref: g1_deploy_onnx_ref.cpp, localmotion_kplanner.hpp,
policy_parameters.hpp, keyboard_handler.hpp), with its inputs, joint orders, scaling, gains,
planner schedule, blending and heading handling, using the default SONIC model and the V2
planner (the deploy script's defaults) on the CPU. As in NVIDIA's deploy, the arms can be given
to another controller: their targets are fed to SONIC as its "upper body" input, so it balances
for where the arms are going.
"""
from __future__ import annotations

import os
import pathlib
import threading
import urllib.request
from collections import deque

import numpy as np

# ------------------------------------------------------------------ model files
HF_REPO = "nvidia/GEAR-SONIC"
HF_REVISION = "6733128a3d8a523b1418b06bca3cdf61c8b0987f"      # pinned (Aug 26, 2026)
FILES = {"model_encoder.onnx": 50100513, "model_decoder.onnx": 40900688, "planner_sonic.onnx": 773952989}
MODEL_DIR = pathlib.Path(os.environ.get("WETLAB_SONIC_DIR")
                         or pathlib.Path(__file__).parent / "assets" / "unitree_g1" / "sonic")


def ensure_models(directory: pathlib.Path | str = MODEL_DIR) -> pathlib.Path:
    """The SONIC files, downloaded from Hugging Face once (the planner is 774 MB, too big for git)."""
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, size in FILES.items():
        f = directory / name
        if f.exists() and f.stat().st_size == size:
            continue
        url = f"https://huggingface.co/{HF_REPO}/resolve/{HF_REVISION}/{name}"
        tmp = f.with_suffix(".part")
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as out:
            while chunk := r.read(1 << 20):
                out.write(chunk)
        if tmp.stat().st_size != size:
            raise RuntimeError(f"SONIC download of {name} is incomplete")
        tmp.replace(f)
    return directory


# --------------------------------------------- policy_parameters.hpp (hardware joint order)
# Unitree's 29 body motors: left leg, right leg, waist, left arm, right arm.
_ARMATURE = {"5020": 0.003609725, "7520_14": 0.010177520, "7520_22": 0.025101925, "4010": 0.00425}
_EFFORT = {"5020": 25.0, "7520_14": 88.0, "7520_22": 139.0, "4010": 5.0}
_W, _ZETA = 10 * 2.0 * 3.1415926535, 2.0                     # 10 Hz, damping ratio 2
_STIFF = {k: a * _W * _W for k, a in _ARMATURE.items()}
_DAMP = {k: 2.0 * _ZETA * a * _W for k, a in _ARMATURE.items()}
_LEG = [("7520_22", 1), ("7520_22", 1), ("7520_14", 1), ("7520_22", 1), ("5020", 2), ("5020", 2)]
_ARM = [("5020", 1)] * 5 + [("4010", 1)] * 2
_MOTORS = _LEG + _LEG + [("7520_14", 1), ("5020", 2), ("5020", 2)] + _ARM + _ARM
KP = np.array([_STIFF[m] * g for m, g in _MOTORS])            # Nm/rad
KD = np.array([_DAMP[m] * g for m, g in _MOTORS])             # Nm s/rad
ACTION_SCALE = np.array([0.25 * _EFFORT[m] / _STIFF[m] for m, _ in _MOTORS])
DEFAULT_ANGLES = np.array([-0.312, 0, 0, 0.669, -0.363, 0, -0.312, 0, 0, 0.669, -0.363, 0, 0, 0, 0,
                           0.2, 0.2, 0, 0.6, 0, 0, 0, 0.2, -0.2, 0, 0.6, 0, 0, 0])
# The networks use Isaac Lab's joint order: x_isaac = x_hw[MJ_TO_ISAAC], x_hw = x_isaac[ISAAC_TO_MJ].
ISAAC_TO_MJ = np.array([0, 3, 6, 9, 13, 17, 1, 4, 7, 10, 14, 18, 2, 5, 8,
                        11, 15, 19, 21, 23, 25, 27, 12, 16, 20, 22, 24, 26, 28])
MJ_TO_ISAAC = np.array([0, 6, 12, 1, 7, 13, 2, 8, 14, 3, 9, 15, 22, 4, 10,
                        16, 23, 5, 11, 17, 24, 18, 25, 19, 26, 20, 27, 21, 28])
DEFAULT_ISAAC = DEFAULT_ANGLES[MJ_TO_ISAAC]
UPPER_ISAAC = np.array([2, 5, 8, 11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28])   # waist + arms
ARMS_ISAAC = UPPER_ISAAC[3:]
LOWER_ISAAC = np.array([0, 1, 3, 4, 6, 7, 9, 10, 13, 14, 17, 18])
NJ = 29
CONTROL_DT = 0.02          # 50 Hz
PLANNER_EVERY = 5          # the planner thread runs at 10 Hz
PLANNER_LATENCY = 4        # control ticks from asking the planner to using its answer (80 ms; it takes ~70)
LOOK_AHEAD = 2             # PlannerConfig.motion_look_ahead_steps
BLEND_FRAMES = 8
DEFAULT_HEIGHT = 0.788740  # PlannerConfig.default_height
ENC_DIM, DEC_DIM = 1762, 994

# --------------------------------------------------------- localmotion_kplanner.hpp
MODES = {"idle": 0, "slow_walk": 1, "walk": 2, "run": 3, "squat": 4, "kneel_two_legs": 5, "kneel": 6,
         "lying_face_down": 7, "crawl": 8, "boxing": 9, "walk_boxing": 10, "left_punch": 11,
         "right_punch": 12, "random_punch": 13, "elbow_crawl": 14, "left_hook": 15, "right_hook": 16,
         "forward_jump": 17, "stealth_walk": 18, "injured_walk": 19, "ledge_walk": 20,
         "carry_walk": 21, "stealth_walk_2": 22, "happy_walk": 23, "zombie_walk": 24,
         "gun_walk": 25, "scared_walk": 26}
STATIC = {0, 4, 5, 6, 7, 9}
STANDING = {0, 1, 2, 3, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26}
# keyboard_handler.hpp: speed ranges of the modes that take one (m/s); others use their own speed.
SPEED_RANGE = {1: (0.2, 0.8), 3: (1.5, 3.0), 8: (0.4, 1.0), 14: (0.7, 1.0),
               10: (0.7, 1.5), 11: (0.7, 1.5), 12: (0.7, 1.5), 13: (0.7, 1.5), 15: (0.7, 1.5), 16: (0.7, 1.5)}
HEIGHT_RANGE = (0.2, 0.8)  # for the squatting, kneeling and crawling modes
_REPLAN = {3: 0.1, 8: 0.2, 11: 1.0, 12: 1.0, 13: 1.0, 15: 1.0, 16: 1.0}   # seconds; others 1.0
# Idle re-adaptation (CurrentFrameAdvancement): blend the standing pose toward the robot's legs.
ADAPT_TRIGGER, ADAPT_STOP, RECOVER_TRIGGER = 0.10, 0.05, 0.045


# ------------------------------------------------------------------ quaternions [w x y z]
def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def qconj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def heading(q):
    """The yaw part of an orientation (calc_heading_quat_d)."""
    h = np.array([q[0], 0.0, 0.0, q[3]])
    return h / max(np.linalg.norm(h), 1e-9)


def qrot(q, v):
    return qmul(qmul(q, np.array([0.0, *v])), qconj(q))[1:]


def qmat(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def slerp(q0, q1, t):
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + t * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - t) * th) * q0 + np.sin(t * th) * q1) / np.sin(th)


def yaw_of(q) -> float:
    return float(2 * np.arctan2(q[3], q[0]))


class Clip:
    """A stretch of reference motion at 50 Hz: root position and orientation, joint positions
    and velocities (Isaac Lab order), as the deploy's MotionSequence."""

    def __init__(self, n: int = 0):
        self.pos = np.zeros((n, 3))
        self.quat = np.tile([1.0, 0, 0, 0], (n, 1))
        self.jpos = np.zeros((n, NJ))
        self.jvel = np.zeros((n, NJ))

    def __len__(self):
        return len(self.jpos)


class Command:
    """What the planner is asked for (the deploy's MovementState). Directions are unit vectors in
    the planner's frame (x along where the robot faced when SONIC started)."""

    def __init__(self, mode=0, move=(0.0, 0.0, 0.0), face=(1.0, 0.0, 0.0), speed=-1.0, height=-1.0):
        self.mode, self.speed, self.height = int(mode), float(speed), float(height)
        self.move, self.face = np.array(move, float), np.array(face, float)

    def key(self):
        return (self.mode, self.speed, self.height, tuple(self.move.round(6)), tuple(self.face.round(6)))

    @staticmethod
    def make(mode: str, move=(0.0, 0.0, 0.0), face=(1.0, 0.0, 0.0), speed=None, height=None) -> "Command":
        """With keyboard_handler.hpp's rules: a body height only for the squatting, kneeling and
        crawling modes (0.2 to 0.8 m; 0.8 if none is given), a speed only for the modes that take
        one (clamped to the mode's range; the slowest if none is given), no movement for the
        modes that stand still."""
        k = MODES[mode]
        h = -1.0 if k in STANDING else float(np.clip(0.8 if height is None else height, *HEIGHT_RANGE))
        if k in STATIC:
            return Command(k, (0, 0, 0), face, -1.0, h)
        sp = -1.0
        if k in SPEED_RANGE:
            lo, hi = SPEED_RANGE[k]
            sp = float(np.clip(lo if speed is None else speed, lo, hi))
        return Command(k, move, face, sp, h)


class Sonic:
    """SONIC for one robot: call step() 50 times a second with the robot's sensor readings."""

    _sessions = None
    _lock = threading.Lock()

    @classmethod
    def sessions(cls):
        with cls._lock:
            if cls._sessions is None:
                import onnxruntime as ort
                d = ensure_models()
                so = ort.SessionOptions()
                so.intra_op_num_threads = 1      # 3.7 ms per tick for both on one core
                so.inter_op_num_threads = 1
                so.log_severity_level = 3
                sp = ort.SessionOptions()
                sp.intra_op_num_threads = 2      # ~70 ms per plan
                sp.inter_op_num_threads = 1
                sp.log_severity_level = 3
                cls._sessions = tuple(ort.InferenceSession(str(d / n), sess_options=o, providers=["CPUExecutionProvider"])
                                      for n, o in (("model_encoder.onnx", so), ("model_decoder.onnx", so),
                                                   ("planner_sonic.onnx", sp)))
        return cls._sessions

    def __init__(self):
        self.enc, self.dec, self.plan = self.sessions()
        self._plan_shapes = {i.name: [s if isinstance(s, int) else 1 for s in i.shape] for i in self.plan.get_inputs()}
        self.reset()

    def reset(self):
        self.clip = Clip()
        self.frame = 0
        self.tick = 0
        self.hist: deque | None = None
        self.last_action = np.zeros(NJ)
        self.init_base = np.array([1.0, 0, 0, 0])     # HeadingState.init_base_quat
        self.init_ref = np.array([1.0, 0, 0, 0])      # init_ref_data_root_rot_array_
        self.cmd = Command()
        self.last_cmd = Command()
        self.replan_t = 0.0
        self.seed = 1234
        self.arms: tuple[np.ndarray, np.ndarray] | None = None    # see set_arms
        self._pending = None                          # (thread, box, fgen, ready tick)
        self._readapt = None
        self.plans = 0

    # ---------------------------------------------------------------- planner
    def _infer_plan(self, context: np.ndarray, cmd: Command) -> Clip:
        allowed = np.zeros(11, np.int64)
        allowed[3:6] = 1                              # LocalMotionPlannerTensorRT: 9 to 11 tokens
        feeds = {"context_mujoco_qpos": context.astype(np.float32), "target_vel": np.float32([cmd.speed]),
                 "mode": np.int64([cmd.mode]), "movement_direction": cmd.move.astype(np.float32),
                 "facing_direction": cmd.face.astype(np.float32), "random_seed": np.int64([self.seed]),
                 "height": np.float32([cmd.height]), "has_specific_target": np.int64([0]),
                 "specific_target_positions": np.zeros(12, np.float32),
                 "specific_target_headings": np.zeros(4, np.float32), "allowed_pred_num_tokens": allowed}
        feeds = {k: v.reshape(self._plan_shapes[k]) for k, v in feeds.items()}
        qpos, n = self.plan.run(None, feeds)
        n = int(np.asarray(n).reshape(-1)[0])
        qpos = qpos.reshape(-1, 36)[:n].astype(np.float64)
        if not 1 < n <= 64 or np.isnan(qpos).any():
            raise RuntimeError("the SONIC planner gave no motion")
        # ResampleGeneratedSequence50Hz: 30 Hz -> 50 Hz, joints to Isaac Lab order.
        T = int(np.floor(n / 30.0 * 50))
        c = Clip(T)
        for f in range(T):
            f30 = f / 50.0 * 30
            f0 = int(np.floor(f30))
            f1 = min(f0 + 1, n - 1)
            w1 = f30 - f0
            c.pos[f] = (1 - w1) * qpos[f0, :3] + w1 * qpos[f1, :3]
            c.quat[f] = slerp(qpos[f0, 3:7], qpos[f1, 3:7], w1)
            c.jpos[f] = ((1 - w1) * qpos[f0, 7:] + w1 * qpos[f1, 7:])[MJ_TO_ISAAC]
        c.jvel[:-1] = (c.jpos[1:] - c.jpos[:-1]) * 50.0
        c.jvel[-1] = c.jvel[-2]
        return c

    def _context(self, gen_frame: int) -> np.ndarray:
        """UpdateContextFromMotion: 4 frames at 30 Hz from the current motion, from gen_frame."""
        c = self.clip
        ctx = np.zeros((4, 36))
        for n in range(4):
            f50 = (gen_frame / 50.0 + n / 30.0) * 50.0
            f0 = min(int(np.floor(f50)), len(c) - 1)
            f1 = min(f0 + 1, len(c) - 1)
            w1 = f50 - f0
            ctx[n, 3:7] = slerp(c.quat[f0], c.quat[f1], w1)
            ctx[n, :3] = (1 - w1) * c.pos[f0] + w1 * c.pos[f1]
            ctx[n, 7 + MJ_TO_ISAAC] = (1 - w1) * c.jpos[f0] + w1 * c.jpos[f1]
        return ctx

    def _blend(self, new: Clip, fgen: int):
        """CurrentFrameAdvancement: rebase the motion on the current frame and cross-fade the new
        plan in over 8 frames from where it was generated."""
        old = self.clip
        L = fgen - self.frame + len(new)
        if L <= 0:
            return
        start = max(0, fgen - self.frame)
        out = Clip(L)
        for f in range(L):
            fo = int(np.clip(f + self.frame, 0, len(old) - 1))
            fn = int(np.clip(f + self.frame - fgen, 0, len(new) - 1))
            wn = float(np.clip((f - start) / BLEND_FRAMES, 0, 1))
            out.jpos[f] = (1 - wn) * old.jpos[fo] + wn * new.jpos[fn]
            out.jvel[f] = (1 - wn) * old.jvel[fo] + wn * new.jvel[fn]
            out.pos[f] = (1 - wn) * old.pos[fo] + wn * new.pos[fn]
            out.quat[f] = slerp(old.quat[fo], new.quat[fn], wn)
        self.clip, self.frame = out, 0
        self._readapt = None

    def _start_plan(self, context, cmd, fgen):
        box = {}

        def run():
            try:
                box["clip"] = self._infer_plan(context, cmd)
            except Exception as e:  # noqa: BLE001
                box["error"] = e
        t = threading.Thread(target=run, daemon=True, name="sonic-planner")
        t.start()
        self._pending = (t, box, fgen, self.tick + PLANNER_LATENCY)
        self.plans += 1

    def _planner_tick(self):
        """Planner(): decide whether to plan again (10 Hz), as NVIDIA's planner thread does."""
        c, lc = self.cmd, self.last_cmd
        self.replan_t += PLANNER_EVERY * CONTROL_DT
        due = self.replan_t >= _REPLAN.get(c.mode, 1.0)
        if due:
            self.replan_t = 0.0
        changed = c.mode != lc.mode or not np.array_equal(c.face, lc.face) or c.height != lc.height
        moved = c.speed != lc.speed or not np.array_equal(c.move, lc.move)
        if not (changed or (c.mode not in STATIC and (moved or (due and c.speed != 0)))):
            return
        self.last_cmd = Command(c.mode, c.move, c.face, c.speed, c.height)
        fgen = self.frame + LOOK_AHEAD
        self._start_plan(self._context(fgen), self.last_cmd, fgen)

    # ------------------------------------------------------------------ policy
    def _apply_delta(self):
        return qmul(heading(self.init_base), qconj(heading(self.init_ref)))

    def start(self, quat, q_hw):
        """Planner Initialize(): stand from the robot's current joints, facing where it faces."""
        ctx = np.zeros((4, 36))
        ctx[:, 2] = DEFAULT_HEIGHT
        ctx[:, 3] = 1.0
        ctx[:, 7:] = q_hw
        self.clip, self.frame = self._infer_plan(ctx, Command()), 0
        self.init_base = np.asarray(quat, float).copy()
        self.init_ref = self.clip.quat[0].copy()
        self.plans += 1

    def step(self, quat, gyro, q_hw, dq_hw) -> np.ndarray:
        """One 50 Hz tick from the pelvis IMU (orientation [w x y z], angular velocity) and the 29
        body joints (hardware order): the 29 position targets (hardware order)."""
        quat = np.asarray(quat, float)
        q_hw, dq_hw = np.asarray(q_hw, float), np.asarray(dq_hw, float)
        if len(self.clip) == 0:
            self.start(quat, q_hw)
        if self._pending and self.tick >= self._pending[3]:
            t, box, fgen, _ = self._pending
            t.join()
            self._pending = None
            if "error" in box:
                raise box["error"]
            self._blend(box["clip"], fgen)
        if self.tick % PLANNER_EVERY == 0 and self._pending is None:
            self._planner_tick()
        # The policy's 10-reading history (oldest first).
        entry = (np.asarray(gyro, float), q_hw[MJ_TO_ISAAC] - DEFAULT_ISAAC, dq_hw[MJ_TO_ISAAC],
                 self.last_action.copy(), qrot(qconj(quat), (0, 0, -1.0)))
        if self.hist is None:
            self.hist = deque([entry] * 10, maxlen=10)
        else:
            self.hist.append(entry)
        c = self.clip
        enc = np.zeros(ENC_DIM, np.float32)       # g1 mode (0): only its observations are filled
        delta = self._apply_delta()
        qinv = qconj(quat)
        for k in range(10):                       # 10 frames, 5 apart (100 ms)
            f = min(self.frame + 5 * k, len(c) - 1)
            jp, jv = c.jpos[f].copy(), c.jvel[f].copy()
            if self.arms is not None:
                jp[ARMS_ISAAC], jv[ARMS_ISAAC] = self.arms
            enc[4 + 29 * k:33 + 29 * k] = jp                        # motion_joint_positions_10frame_step5
            enc[294 + 29 * k:323 + 29 * k] = jv                     # motion_joint_velocities_10frame_step5
            r = qmat(qmul(qinv, qmul(delta, c.quat[f])))
            enc[601 + 6 * k:607 + 6 * k] = r[:, :2].reshape(-1)     # motion_anchor_orientation_10frame_step5
        token = self.enc.run(None, {"obs_dict": enc[None]})[0].reshape(-1)
        h = list(self.hist)
        dec = np.concatenate([token] + [np.concatenate([e[i] for e in h]) for i in range(5)]).astype(np.float32)
        a = self.dec.run(None, {"obs_dict": dec[None]})[0].reshape(-1).astype(np.float64)
        self.last_action = a
        self._advance(q_hw)
        self.tick += 1
        return DEFAULT_ANGLES + a[ISAAC_TO_MJ] * ACTION_SCALE

    def _advance(self, q_hw):
        c = self.clip
        nf = self.frame + 1
        if nf < len(c):
            self.frame = nf
            return
        self.frame = len(c) - 1
        if self.cmd.mode != 0:
            return
        # Standing at the end of the plan: the deploy's idle re-adaptation of the leg targets.
        f, idx = self.frame, LOWER_ISAAC
        if self._readapt is None:
            self._readapt = ["idle", c.jpos[f, idx].copy()]
        actual = q_hw[MJ_TO_ISAAC][idx]
        err = float(np.mean(np.abs(c.jpos[f, idx] - actual)))
        st = self._readapt[0]
        if st == "idle":
            st = "adapt" if err > ADAPT_TRIGGER else "recover" if err < RECOVER_TRIGGER else "idle"
        elif st == "adapt" and err < ADAPT_STOP:
            st = "idle"
        elif st == "recover" and err > ADAPT_TRIGGER:
            st = "adapt"
        self._readapt[0] = st
        if st == "adapt":
            c.jpos[f, idx] = 0.98 * c.jpos[f, idx] + 0.02 * actual
        elif st == "recover":
            c.jpos[f, idx] = 0.98 * c.jpos[f, idx] + 0.02 * self._readapt[1]

    def set_arms(self, q_hw=None, dq_hw=None):
        """Where another controller is taking the arms (14 joints, left then right, hardware
        order) and how fast, or None to let SONIC move them: the deploy's upper-body input, which
        puts these targets in the reference SONIC balances for."""
        if q_hw is None:
            self.arms = None
            return
        full_q, full_v = np.zeros(NJ), np.zeros(NJ)
        full_q[15:], full_v[15:] = q_hw, (np.zeros(14) if dq_hw is None else dq_hw)
        self.arms = (full_q[MJ_TO_ISAAC][ARMS_ISAAC], full_v[MJ_TO_ISAAC][ARMS_ISAAC])

    def plan_finished(self) -> bool:
        """True when the motion asked for has played out (nothing being planned, at the end)."""
        return self._pending is None and self.cmd.key() == self.last_cmd.key() and self.frame >= len(self.clip) - 1

    def reference_root(self):
        """Where SONIC is taking the pelvis now: its height (m) and orientation in the world [w x y z]."""
        f = min(self.frame, len(self.clip) - 1)
        return float(self.clip.pos[f, 2]), qmul(self._apply_delta(), self.clip.quat[f])

    # ---------------------------------------------------------------- readings
    def facing(self) -> float:
        """The planner's facing angle (rad, planner frame) at the current frame."""
        return yaw_of(self.clip.quat[self.frame]) if len(self.clip) else 0.0

    def world_yaw_of_planner(self) -> float:
        """How the planner's frame is turned in the world (rad)."""
        return yaw_of(self._apply_delta())
