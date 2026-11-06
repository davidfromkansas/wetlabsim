"""Real-time physics, the robot controller, sensors and cameras.

The world never pauses: physics runs against the wall clock in its own thread.
Agents only see what a real UR5e + Robotiq 2F-85 + cameras would report:
joint encoders, the controller's TCP pose, wrist force/torque, gripper status,
and camera images (colour + depth). Ground-truth object poses are only
available to the evaluator, never to the robot API.
"""
from __future__ import annotations

import json
import pathlib
import queue
import threading
import time
from dataclasses import dataclass, field

import mujoco
import numpy as np

from . import scene as S

CTRL_DT = 0.008                # trajectory sample period (s)
PROTECTIVE_FORCE = 140.0       # N at the wrist before a protective stop
TRACKING_LIMIT = 0.25          # rad of joint tracking error before a protective stop
GRIP_JOINT = "gripper/right_driver_joint"
GRIP_RANGE = 0.8               # driver joint travel (rad) mapped to 0..255
CAM_W, CAM_H = 640, 480


# ---------------------------------------------------------------- pose helpers
def quat_from_rotvec(rv) -> np.ndarray:
    rv = np.asarray(rv, float)
    ang = np.linalg.norm(rv)
    q = np.zeros(4)
    if ang < 1e-12:
        q[0] = 1.0
        return q
    mujoco.mju_axisAngle2Quat(q, rv / ang, ang)
    return q


def rotvec_from_quat(q) -> np.ndarray:
    q = np.asarray(q, float)
    q = q / np.linalg.norm(q)
    if q[0] < 0:
        q = -q
    v = np.zeros(3)
    mujoco.mju_quat2Vel(v, q, 1.0)
    return v


def quat_from_mat(R) -> np.ndarray:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.asarray(R, float).reshape(9))
    return q


def mat_from_quat(q) -> np.ndarray:
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(q, float))
    return R.reshape(3, 3)


def slerp(q0, q1, s):
    q0, q1 = np.asarray(q0, float), np.asarray(q1, float)
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + s * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - s) * th) * q0 + np.sin(s * th) * q1) / np.sin(th)


def quintic(s):
    s = np.clip(s, 0.0, 1.0)
    return s ** 3 * (10 - 15 * s + 6 * s ** 2)


class RobotError(Exception):
    """Raised for commands a real controller would reject."""


@dataclass
class Motion:
    t0: float
    times: np.ndarray
    qs: np.ndarray
    done: threading.Event = field(default_factory=threading.Event)
    result: str = "running"


# ------------------------------------------------------------------ simulator
class Sim:
    def __init__(self, run_dir: str | pathlib.Path | None = None, realtime: float = 1.0):
        self.m = S.build_model()
        self.d = mujoco.MjData(self.m)
        self.lock = threading.RLock()
        self.realtime = realtime
        m = self.m
        self.arm_qadr = np.array([m.joint(j).qposadr[0] for j in S.ARM_JOINTS])
        self.arm_dadr = np.array([m.joint(j).dofadr[0] for j in S.ARM_JOINTS])
        self.arm_act = np.array([m.actuator(a).id for a in S.ARM_ACTUATORS])
        self.grip_act = m.actuator("gripper/fingers_actuator").id
        self.grip_qadr = m.joint(GRIP_JOINT).qposadr[0]
        self.grip_dadr = m.joint(GRIP_JOINT).dofadr[0]
        self.tcp_site = m.site(S.TCP_SITE).id
        self.ft_site = m.site("gripper/ft_site").id
        self.ft_body = m.body("gripper/base_mount").id
        self.base_body = m.body("base").id
        self.joint_lo = m.jnt_range[[m.joint(j).id for j in S.ARM_JOINTS], 0]
        self.joint_hi = m.jnt_range[[m.joint(j).id for j in S.ARM_JOINTS], 1]
        self.grip_force_base = m.actuator_forcerange[self.grip_act].copy()
        self._ik_data = mujoco.MjData(m)
        self.rng = np.random.default_rng()
        self.run_dir = pathlib.Path(run_dir) if run_dir else None
        self._log_f = None
        self.reset()
        self._running = False
        self._render_q: queue.PriorityQueue = queue.PriorityQueue()
        self._render_seq = 0

    # ---------------------------------------------------------------- setup
    def reset(self):
        with self.lock:
            mujoco.mj_resetData(self.m, self.d)
            self.d.qpos[self.arm_qadr] = S.READY_Q
            self.d.ctrl[self.arm_act] = S.READY_Q
            self.d.ctrl[self.grip_act] = 0
            mujoco.mj_forward(self.m, self.d)
            for _ in range(250):            # let tubes settle in their racks
                mujoco.mj_step(self.m, self.d)
            self.motion: Motion | None = None
            self.mode = "running"           # or "protective_stop"
            self.stop_reason = ""
            self.grip_target = 0.0
            self.grip_cmd = 0.0
            self.grip_rate = 255.0
            self.ft_offset = np.zeros(6)
            self.events: list[dict] = []
            self._wall0 = time.perf_counter()
            self._sim0 = self.d.time
            self.rt_factor = 1.0
            self.recording: list[tuple[float, np.ndarray]] = []   # (time, qpos) at 30 Hz for replay videos
            self._next_rec = self.d.time

    def open_log(self, run_dir: str | pathlib.Path):
        with self.lock:
            if self._log_f:
                self._log_f.close()
            self.run_dir = pathlib.Path(run_dir)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._log_f = open(self.run_dir / "states.jsonl", "a")

    def log_event(self, event: str, **kw):
        ev = {"t": round(self.d.time, 4), "event": event, **kw}
        self.events.append(ev)
        if self._log_f:
            self._log_f.write(json.dumps(ev) + "\n")
            self._log_f.flush()

    # ------------------------------------------------------------ threads
    def start(self):
        self._running = True
        threading.Thread(target=self._physics_loop, daemon=True, name="physics").start()
        threading.Thread(target=self._render_loop, daemon=True, name="render").start()
        threading.Thread(target=self._log_loop, daemon=True, name="logger").start()

    def stop_threads(self):
        self._running = False

    def _physics_loop(self):
        m, d = self.m, self.d
        last_check = time.perf_counter()
        sim_done = 0.0
        while self._running:
            wall = time.perf_counter()
            with self.lock:
                target = self._sim0 + (wall - self._wall0) * self.realtime
                n = 0
                while d.time < target and n < 100:
                    self._control()
                    mujoco.mj_step(m, d)
                    n += 1
                    if d.time >= self._next_rec:
                        self.recording.append((d.time, d.qpos.copy()))
                        self._next_rec += 1 / 30
                sim_done += n * m.opt.timestep
                if target - d.time > 0.25:  # can't keep up: let time slip, like a dropped frame
                    self._wall0 += (target - d.time) / self.realtime
            if wall - last_check > 1.0:
                self.rt_factor = sim_done / (wall - last_check)
                sim_done, last_check = 0.0, wall
            time.sleep(0.0005)

    # ---------------------------------------------------------- controller
    def _control(self):
        d = self.d
        mo = self.motion
        if mo is not None:
            t = d.time - mo.t0
            if t >= mo.times[-1]:
                d.ctrl[self.arm_act] = mo.qs[-1]
                if np.max(np.abs(d.qvel[self.arm_dadr])) < 0.02 or t > mo.times[-1] + 1.0:
                    mo.result = "done"
                    mo.done.set()
                    self.motion = None
            else:
                i = np.searchsorted(mo.times, t)
                a = (t - mo.times[i - 1]) / (mo.times[i] - mo.times[i - 1])
                d.ctrl[self.arm_act] = mo.qs[i - 1] + a * (mo.qs[i] - mo.qs[i - 1])
        # Gripper: ramp the command at the requested speed (Robotiq-style).
        step = self.grip_rate * self.m.opt.timestep
        self.grip_cmd += np.clip(self.grip_target - self.grip_cmd, -step, step)
        d.ctrl[self.grip_act] = self.grip_cmd
        # Safety checks (every 10 steps).
        if self.mode == "running" and int(d.time / self.m.opt.timestep) % 10 == 0:
            err = np.max(np.abs(d.ctrl[self.arm_act] - d.qpos[self.arm_qadr]))
            f = np.linalg.norm(self._ft_compensated()[:3])
            if f > PROTECTIVE_FORCE:
                self._protective_stop(f"wrist force {f:.0f} N exceeded {PROTECTIVE_FORCE:.0f} N")
            elif err > TRACKING_LIMIT:
                self._protective_stop(f"joint tracking error {err:.2f} rad (arm blocked)")

    def _protective_stop(self, reason: str):
        self.mode = "protective_stop"
        self.stop_reason = reason
        self.d.ctrl[self.arm_act] = self.d.qpos[self.arm_qadr]
        if self.motion:
            self.motion.result = "protective_stop: " + reason
            self.motion.done.set()
            self.motion = None
        self.log_event("protective_stop", reason=reason)

    # ------------------------------------------------------------------ IK
    def _fk(self, q):
        dd = self._ik_data
        dd.qpos[self.arm_qadr] = q
        mujoco.mj_kinematics(self.m, dd)
        mujoco.mj_comPos(self.m, dd)
        return dd.site_xpos[self.tcp_site].copy(), dd.site_xmat[self.tcp_site].reshape(3, 3).copy()

    def ik(self, pos_w, quat_w, q0, iters=200, tol_p=2e-4, tol_r=2e-3):
        """Damped least squares IK for the TCP. Returns joint angles or None."""
        q = np.array(q0, float)
        jacp = np.zeros((3, self.m.nv))
        jacr = np.zeros((3, self.m.nv))
        R_goal = mat_from_quat(quat_w)
        for _ in range(iters):
            p, R = self._fk(q)
            e_p = pos_w - p
            R_err = R_goal @ R.T
            e_r = np.zeros(3)
            mujoco.mju_quat2Vel(e_r, quat_from_mat(R_err), 1.0)
            if np.linalg.norm(e_p) < tol_p and np.linalg.norm(e_r) < tol_r:
                return q
            mujoco.mj_jacSite(self.m, self._ik_data, jacp, jacr, self.tcp_site)
            J = np.vstack([jacp[:, self.arm_dadr], jacr[:, self.arm_dadr]])
            e = np.concatenate([e_p, e_r])
            lam = 1e-3
            dq = J.T @ np.linalg.solve(J @ J.T + lam * np.eye(6), e)
            n = np.linalg.norm(dq)
            if n > 0.2:
                dq *= 0.2 / n
            q = np.clip(q + dq, self.joint_lo, self.joint_hi)
        return None

    # ------------------------------------------------------- base frame
    def base_tf(self):
        """Robot base frame (world) position and rotation."""
        return self.d.xpos[self.base_body].copy(), self.d.xmat[self.base_body].reshape(3, 3).copy()

    def to_world(self, p_b, R_b=None):
        bp, bR = self.base_tf()
        pw = bp + bR @ np.asarray(p_b)
        return (pw, bR @ R_b) if R_b is not None else pw

    def to_base(self, p_w, R_w=None):
        bp, bR = self.base_tf()
        pb = bR.T @ (np.asarray(p_w) - bp)
        return (pb, bR.T @ R_w) if R_w is not None else pb

    # ------------------------------------------------------------ commands
    def _check_running(self):
        if self.mode != "running":
            raise RobotError(f"robot is in protective stop ({self.stop_reason}); call unlock_protective_stop()")

    def move_l(self, pose, speed=0.25, accel=None) -> Motion:
        """Straight-line tool move to pose [x,y,z,rx,ry,rz] (base frame, rotation vector)."""
        pose = np.asarray(pose, float)
        if pose.shape != (6,):
            raise RobotError("pose must be [x, y, z, rx, ry, rz]")
        speed = float(np.clip(speed, 0.001, 1.0))
        with self.lock:
            self._check_running()
            q_start = self.d.ctrl[self.arm_act].copy()
            p0, R0 = self._fk(q_start)
            p1, R1 = self.to_world(pose[:3], mat_from_quat(quat_from_rotvec(pose[3:])))
        q0, q1 = quat_from_mat(R0), quat_from_mat(R1)
        dist = np.linalg.norm(p1 - p0)
        ang = 2 * np.arccos(min(1.0, abs(float(np.dot(q0, q1)))))
        T = max(1.875 * dist / speed, 1.875 * ang / 1.0, 0.2)
        times = np.arange(0.0, T + CTRL_DT, CTRL_DT)
        times[-1] = T
        qs = np.zeros((len(times), 6))
        q = q_start
        for k, t in enumerate(times):
            s = quintic(t / T)
            sol = self.ik(p0 + s * (p1 - p0), slerp(q0, q1, s), q, iters=60 if k else 200)
            if sol is None or (k and np.max(np.abs(sol - q)) > 0.3):
                raise RobotError("target pose is unreachable along a straight line"
                                 f" (failed at {100*s:.0f}% of the path)")
            qs[k] = q = sol
        return self._start_motion(times, qs, kind="move_l", target=pose.round(5).tolist())

    def move_j(self, joints, speed=1.0) -> Motion:
        q1 = np.asarray(joints, float)
        if q1.shape != (6,):
            raise RobotError("joints must have 6 values (radians)")
        if np.any(q1 < self.joint_lo) or np.any(q1 > self.joint_hi):
            raise RobotError("joint target outside joint limits")
        speed = float(np.clip(speed, 0.01, 3.14))
        with self.lock:
            self._check_running()
            q0 = self.d.ctrl[self.arm_act].copy()
        T = max(1.875 * np.max(np.abs(q1 - q0)) / speed, 0.2)
        times = np.arange(0.0, T + CTRL_DT, CTRL_DT)
        times[-1] = T
        qs = q0 + quintic(times / T)[:, None] * (q1 - q0)
        return self._start_motion(times, qs, kind="move_j", target=q1.round(5).tolist())

    def move_j_ik(self, pose, speed=1.0) -> Motion:
        """Joint-space move to a tool pose (path is not a straight line)."""
        pose = np.asarray(pose, float)
        with self.lock:
            q0 = self.d.ctrl[self.arm_act].copy()
            pw, Rw = self.to_world(pose[:3], mat_from_quat(quat_from_rotvec(pose[3:])))
        sol = self.ik(pw, quat_from_mat(Rw), q0)
        if sol is None:
            raise RobotError("target pose is unreachable")
        return self.move_j(sol, speed)

    def _start_motion(self, times, qs, **info) -> Motion:
        with self.lock:
            self._check_running()
            if self.motion:
                self.motion.result = "replaced by a new command"
                self.motion.done.set()
            mo = Motion(self.d.time, times, qs)
            self.motion = mo
            self.log_event("command", **info)
            return mo

    def stop(self):
        with self.lock:
            if self.motion:
                self.motion.result = "stopped"
                self.motion.done.set()
                self.motion = None
            self.d.ctrl[self.arm_act] = self.d.qpos[self.arm_qadr]
            self.log_event("command", kind="stop")

    def unlock(self):
        with self.lock:
            self.d.ctrl[self.arm_act] = self.d.qpos[self.arm_qadr]
            self.mode = "running"
            self.stop_reason = ""
            self.log_event("command", kind="unlock_protective_stop")

    def gripper_move(self, position, speed=255, force=150):
        position = float(np.clip(position, 0, 255))
        with self.lock:
            self.grip_target = position
            self.grip_rate = 40.0 + 360.0 * float(np.clip(speed, 0, 255)) / 255.0
            scale = 0.2 + 0.8 * float(np.clip(force, 0, 255)) / 255.0
            self.m.actuator_forcerange[self.grip_act] = self.grip_force_base * scale
            self.log_event("command", kind="gripper", position=position, speed=speed, force=force)

    def zero_ft(self):
        with self.lock:
            self.ft_offset = self._ft_compensated(offset=False)

    # ------------------------------------------------------------- sensors
    def _ft_compensated(self, offset=True) -> np.ndarray:
        """Wrist force/torque in the tool flange frame, with the gripper's weight removed."""
        d, m = self.d, self.m
        raw_f = d.sensor("ft_force").data.copy()
        raw_t = d.sensor("ft_torque").data.copy()
        R = d.site_xmat[self.ft_site].reshape(3, 3)
        mass = m.body_subtreemass[self.ft_body]
        Fg = R.T @ (mass * m.opt.gravity)
        r = R.T @ (d.subtree_com[self.ft_body] - d.site_xpos[self.ft_site])
        f = raw_f + Fg
        t = raw_t + np.cross(r, Fg)
        out = np.concatenate([f, t])
        return out - self.ft_offset if offset else out

    def gripper_status(self):
        d = self.d
        pos = float(np.clip(d.qpos[self.grip_qadr] / GRIP_RANGE * 255.0, 0, 255))
        vel = abs(float(d.qvel[self.grip_dadr]))
        moving = bool(abs(self.grip_cmd - self.grip_target) > 0.5 or vel > 0.05)   # plain bool for JSON
        if moving:
            obj = 0
        elif self.grip_target - pos > 6:
            obj = 2   # stopped early while closing: something is between the fingers
        elif pos - self.grip_target > 6:
            obj = 1   # stopped early while opening
        else:
            obj = 3   # reached the requested position, no object
        return {"position": round(pos, 1), "requested": round(self.grip_target, 1),
                "object_detected": obj in (1, 2), "status_code": obj, "moving": moving}

    def state(self) -> dict:
        with self.lock:
            d = self.d
            q = d.qpos[self.arm_qadr] + self.rng.normal(0, 2e-5, 6)
            qd = d.qvel[self.arm_dadr].copy()
            pw, Rw = d.site_xpos[self.tcp_site].copy(), d.site_xmat[self.tcp_site].reshape(3, 3).copy()
            pb, Rb = self.to_base(pw, Rw)
            ft = self._ft_compensated() + np.concatenate([self.rng.normal(0, 0.3, 3), self.rng.normal(0, 0.02, 3)])
            return {
                "time": round(d.time, 4),
                "mode": self.mode,
                "protective_stop_reason": self.stop_reason,
                "moving": self.motion is not None,
                "joint_positions": q.round(5).tolist(),
                "joint_velocities": qd.round(4).tolist(),
                "tcp_pose": np.concatenate([pb, rotvec_from_quat(quat_from_mat(Rb))]).round(5).tolist(),
                "tcp_force": ft.round(3).tolist(),
                "gripper": self.gripper_status(),
                "realtime_factor": round(self.rt_factor, 3),
            }

    def ground_truth(self) -> dict:
        """Object poses for scoring only. Never exposed through the robot API."""
        with self.lock:
            out = {}
            for i in range(self.m.nbody):
                name = self.m.body(i).name
                if name.startswith("tube_"):
                    p = self.to_base(self.d.xpos[i])
                    out[name] = {"pos": p.round(5).tolist(), "quat": self.d.xquat[i].round(5).tolist()}
            return {"time": round(self.d.time, 4), "objects": out}

    def save_recording(self, path):
        with self.lock:
            rec = list(self.recording)
        np.savez_compressed(path, time=np.array([t for t, _ in rec]), qpos=np.array([q for _, q in rec]))
        return len(rec)

    def _log_loop(self):
        while self._running:
            time.sleep(0.05)
            if not self._log_f:
                continue
            s = self.state()
            s["ground_truth"] = self.ground_truth()["objects"]
            with self.lock:
                if self._log_f:
                    self._log_f.write(json.dumps(s) + "\n")

    # ------------------------------------------------------------- cameras
    def render(self, camera: str, depth: bool = False, priority: int = 0, timeout=30.0) -> dict:
        if camera not in S.CAMERAS:
            raise RobotError(f"unknown camera '{camera}', choose from {list(S.CAMERAS)}")
        if priority == 0:
            with self.lock:
                self.log_event("camera", camera=camera)
        box: dict = {}
        ev = threading.Event()
        self._render_seq += 1
        self._render_q.put((priority, self._render_seq, camera, depth, box, ev))
        if not ev.wait(timeout):
            raise RobotError("camera timed out")
        if "error" in box:
            raise RobotError(box["error"])
        return box

    def _render_loop(self):
        rd = mujoco.MjData(self.m)
        rgb_r = mujoco.Renderer(self.m, CAM_H, CAM_W)
        dep_r = mujoco.Renderer(self.m, CAM_H, CAM_W)
        dep_r.enable_depth_rendering()
        while self._running:
            try:
                _, _, camera, depth, box, ev = self._render_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                with self.lock:
                    rd.qpos[:] = self.d.qpos
                    rd.qvel[:] = self.d.qvel
                    rd.time = self.d.time
                    bp, bR = self.base_tf()
                mujoco.mj_forward(self.m, rd)
                cam_name = S.CAMERAS[camera]
                cid = self.m.camera(cam_name).id
                rgb_r.update_scene(rd, camera=cam_name)
                box["rgb"] = rgb_r.render().copy()
                if depth:
                    dep_r.update_scene(rd, camera=cam_name)
                    box["depth"] = dep_r.render().astype(np.float32)
                fovy = np.deg2rad(self.m.cam_fovy[cid])
                f = (CAM_H / 2) / np.tan(fovy / 2)
                box["intrinsics"] = {"fx": f, "fy": f, "cx": CAM_W / 2, "cy": CAM_H / 2,
                                     "width": CAM_W, "height": CAM_H}
                # Camera pose in the robot base frame, OpenCV convention (x right, y down, z forward).
                Rw = rd.cam_xmat[cid].reshape(3, 3) @ np.diag([1.0, -1.0, -1.0])
                pw = rd.cam_xpos[cid]
                box["pose"] = {"position": (bR.T @ (pw - bp)).round(5).tolist(),
                               "rotation": (bR.T @ Rw).round(6).tolist()}
                box["time"] = round(rd.time, 4)
            except Exception as e:  # noqa: BLE001
                box["error"] = f"render failed: {e}"
            ev.set()
