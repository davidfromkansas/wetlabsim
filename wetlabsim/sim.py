"""Real-time physics, the robot controller, sensors and cameras.

The world never pauses: physics runs against the wall clock in its own thread.
Agents only see what the real robot (a Franka Panda with its hand, or a UR5e with a
Robotiq 2F-85) and its cameras would report:
joint encoders, the controller's TCP pose, wrist force/torque, gripper status,
and camera images (colour + depth). Ground-truth object poses are only
available to the evaluator, never to the robot API.
"""
from __future__ import annotations

import bisect
import json
import pathlib
import queue
import threading
import time
from dataclasses import dataclass, field

import mujoco
import numpy as np

from . import scene as S
from . import tasks as T

CTRL_DT = 0.008                # trajectory sample period (s)
TRACKING_LIMIT = 0.25          # rad of joint tracking error before a protective stop
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


# ------------------------------------------------------------------- one robot
class Arm:
    """One robot in the world: its controller, gripper, wrist sensor and cameras.

    A scene usually has one (the robot cell, LIBERO); the playground's lab can have several,
    each attached with its own name prefix. The world (physics, time, rendering) is the Sim's.
    """

    def __init__(self, sim: "Sim", robot: str, prefix: str = "", uid: str = "robot",
                 world_cameras: str | None = None):
        self.sim = sim
        self.uid = uid
        self.prefix = prefix
        # One arm of a two-arm robot ("aloha:left") reports to the pair (TwoArm), which logs for it.
        self.side = robot.split(":")[1] if ":" in robot else ""
        self.parent: "TwoArm | None" = None
        self.robot = robot if self.side else S.robot_name(robot)
        self.P = S.profile_for(self.robot, prefix, world_cameras)
        self.rng = np.random.default_rng()
        self.events: list[dict] = []
        self._log_f = None
        self.run_dir = None
        self.recording_from = 0.0
        self.motion: Motion | None = None
        self.mode = "running"
        self.stop_reason = ""
        self.state_log: list[dict] = []
        self.task = None

    # world shortcuts
    @property
    def m(self):
        return self.sim.m

    @property
    def d(self):
        return self.sim.d

    @property
    def lock(self):
        return self.sim.lock

    def _index(self):
        """Look up the robot's joints, actuators, sites and bodies in the current model."""
        P, m = self.P, self.sim.m
        self.n_arm = len(P["arm_joints"])
        self.arm_qadr = np.array([m.joint(j).qposadr[0] for j in P["arm_joints"]])
        self.arm_dadr = np.array([m.joint(j).dofadr[0] for j in P["arm_joints"]])
        self.arm_act = np.array([m.actuator(a).id for a in P["arm_actuators"]])
        self.grip_act = m.actuator(P["grip_actuator"]).id
        self.grip_qadr = m.joint(P["grip_joint"]).qposadr[0]
        self.grip_dadr = m.joint(P["grip_joint"]).dofadr[0]
        self.tcp_site = m.site(P["tcp_site"]).id
        # A wrist force/torque sensor, where the robot has one (the ViperX has none).
        self.has_ft = bool(P.get("ft_site"))
        self.ft_site = m.site(P["ft_site"]).id if self.has_ft else -1
        self.ft_body = m.body(P["ft_body"]).id if self.has_ft else -1
        self.base_body = m.body(P["base_body"]).id
        self.ready_q = P["ready_q"]
        self.joint_lo = m.jnt_range[[m.joint(j).id for j in P["arm_joints"]], 0]
        self.joint_hi = m.jnt_range[[m.joint(j).id for j in P["arm_joints"]], 1]
        self.grip_force_base = m.actuator_forcerange[self.grip_act].copy()
        # A servo-driven gripper (ALOHA) is limited at its joint (the servo's effort limit).
        self.grip_jnt = m.joint(P["grip_joint"]).id
        self.grip_jnt_force_base = m.jnt_actfrcrange[self.grip_jnt].copy()
        self.sensors = P.get("sensors", ("ft_force", "ft_torque"))
        self._ik_data = mujoco.MjData(m)
        # this robot's own joints (arm, gripper, fingers): kept when the scene is rebuilt
        root = self.base_body
        self.bodies = {b for b in range(m.nbody) if self._in_subtree(b, root)}
        self.own_joints = [m.joint(j).name for j in range(m.njnt) if m.jnt_bodyid[j] in self.bodies]

    def _in_subtree(self, b, root):
        m = self.sim.m
        while b > 0:
            if b == root:
                return True
            b = m.body_parentid[b]
        return False

    def reset_pose(self):
        """Arm to its ready pose, gripper open (call with the lock held, before mj_forward)."""
        d = self.sim.d
        d.qpos[self.arm_qadr] = self.ready_q
        d.ctrl[self.arm_act] = self.ready_q
        d.ctrl[self.grip_act] = self._grip_ctrl(0.0)

    def reset_state(self):
        """Controller state back to power-on (motion, protective stop, gripper, wrist sensor)."""
        self.motion = None
        self.mode = "running"           # or "protective_stop"
        self.stop_reason = ""
        self.grip_target = 0.0
        self.grip_cmd = 0.0
        self.grip_rate = 255.0
        self.ft_offset = np.zeros(6)
        # A real wrist force estimate is off by up to its rated accuracy until it is tared.
        fb, tb = self.P.get("ft_bias", (0.0, 0.0))
        self.ft_bias = np.concatenate([self.rng.uniform(-fb, fb, 3), self.rng.uniform(-tb, tb, 3)])
        self.events = []
        self.state_log = []
        self.recording_from = self.sim.d.time

    def snapshot(self) -> dict:
        """This robot's joint positions and commands by name, to carry over a scene rebuild."""
        m, d = self.sim.m, self.sim.d
        q = {n: d.qpos[m.joint(n).qposadr[0]] for n in self.own_joints}
        return {"q": q, "arm_ctrl": d.ctrl[self.arm_act].copy(), "grip_ctrl": d.ctrl[self.grip_act]}

    def restore(self, snap: dict):
        m, d = self.sim.m, self.sim.d
        for n, v in snap["q"].items():
            j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n)
            if j >= 0:
                d.qpos[m.jnt_qposadr[j]] = v
        d.ctrl[self.arm_act] = snap["arm_ctrl"]
        d.ctrl[self.grip_act] = snap["grip_ctrl"]

    def log_event(self, event: str, **kw):
        if self.parent is not None:          # one arm of a pair: the pair's log, marked with the arm
            return self.parent.log_event(event, arm=self.side, **kw)
        ev = {"t": round(self.sim.d.time, 4), "event": event, **kw}
        if self.uid != "robot":
            ev["robot"] = self.uid
        self.events.append(ev)
        f = self._log_f or self.sim._log_f
        if f:
            f.write(json.dumps(ev) + "\n")
            f.flush()

    def open_log(self, run_dir):
        with self.lock:
            if self._log_f:
                self._log_f.close()
            self.run_dir = pathlib.Path(run_dir)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._log_f = open(self.run_dir / "states.jsonl", "a")

    def close_log(self):
        with self.lock:
            if self._log_f:
                self._log_f.close()
            self._log_f = None

    # ---------------------------------------------------------- controller
    def _control(self):
        d = self.sim.d
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
        step = self.grip_rate * self.sim.m.opt.timestep
        self.grip_cmd += np.clip(self.grip_target - self.grip_cmd, -step, step)
        d.ctrl[self.grip_act] = self._grip_ctrl(self.grip_cmd)
        # Safety checks (every 10 steps).
        if self.mode == "running" and int(d.time / self.sim.m.opt.timestep) % 10 == 0:
            err = np.max(np.abs(d.ctrl[self.arm_act] - d.qpos[self.arm_qadr]))
            reflex = self._reflex(self._ft_external()) if self.has_ft else ""
            if reflex:
                self._protective_stop(reflex)
            elif err > TRACKING_LIMIT:
                self._protective_stop(f"joint tracking error {err:.2f} rad (arm blocked)")

    def _protective_stop(self, reason: str):
        self.mode = "protective_stop"
        self.stop_reason = reason
        self.sim.d.ctrl[self.arm_act] = self.sim.d.qpos[self.arm_qadr]
        if self.motion:
            self.motion.result = "protective_stop: " + reason
            self.motion.done.set()
            self.motion = None
        self.log_event("protective_stop", reason=reason)

    # ------------------------------------------------------------------ IK
    def _fk(self, q):
        dd = self._ik_data
        dd.qpos[self.arm_qadr] = q
        mujoco.mj_kinematics(self.sim.m, dd)
        mujoco.mj_comPos(self.sim.m, dd)
        return dd.site_xpos[self.tcp_site].copy(), dd.site_xmat[self.tcp_site].reshape(3, 3).copy()

    def ik(self, pos_w, quat_w, q0, iters=200, tol_p=2e-4, tol_r=2e-3):
        """Damped least squares IK for the TCP. Returns joint angles or None."""
        q = np.array(q0, float)
        m = self.sim.m
        jacp = np.zeros((3, m.nv))
        jacr = np.zeros((3, m.nv))
        R_goal = mat_from_quat(quat_w)
        for _ in range(iters):
            p, R = self._fk(q)
            e_p = pos_w - p
            R_err = R_goal @ R.T
            e_r = np.zeros(3)
            mujoco.mju_quat2Vel(e_r, quat_from_mat(R_err), 1.0)
            if np.linalg.norm(e_p) < tol_p and np.linalg.norm(e_r) < tol_r:
                return q
            mujoco.mj_jacSite(m, self._ik_data, jacp, jacr, self.tcp_site)
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
        d = self.sim.d
        return d.xpos[self.base_body].copy(), d.xmat[self.base_body].reshape(3, 3).copy()

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
        speed = float(np.clip(speed, 0.001, self.P["cart_vmax"]))
        with self.lock:
            self._check_running()
            q_start = self.sim.d.ctrl[self.arm_act].copy()
            p0, R0 = self._fk(q_start)
            p1, R1 = self.to_world(pose[:3], mat_from_quat(quat_from_rotvec(pose[3:])))
        q0, q1 = quat_from_mat(R0), quat_from_mat(R1)
        dist = np.linalg.norm(p1 - p0)
        ang = 2 * np.arccos(min(1.0, abs(float(np.dot(q0, q1)))))
        T = max(1.875 * dist / speed, 1.875 * ang / self.P["rot_vmax"], 0.2)
        times = np.arange(0.0, T + CTRL_DT, CTRL_DT)
        times[-1] = T
        qs = np.zeros((len(times), self.n_arm))
        q = q_start
        for k, t in enumerate(times):
            s = quintic(t / T)
            sol = self.ik(p0 + s * (p1 - p0), slerp(q0, q1, s), q, iters=60 if k else 200)
            if sol is None or (k and np.max(np.abs(sol - q)) > 0.3):
                raise RobotError("target pose is unreachable along a straight line"
                                 f" (failed at {100*s:.0f}% of the path)")
            qs[k] = q = sol
        return self._start_motion(self._within_joint_limits(times, qs), qs,
                                  kind="move_l", target=pose.round(5).tolist())

    def move_j(self, joints, speed=1.0) -> Motion:
        q1 = np.asarray(joints, float)
        if q1.shape != (self.n_arm,):
            raise RobotError(f"joints must have {self.n_arm} values (radians)")
        if np.any(q1 < self.joint_lo) or np.any(q1 > self.joint_hi):
            raise RobotError("joint target outside joint limits")
        speed = float(np.clip(speed, 0.01, float(np.max(self.P["joint_vmax"]))))
        with self.lock:
            self._check_running()
            q0 = self.sim.d.ctrl[self.arm_act].copy()
        T = max(1.875 * np.max(np.abs(q1 - q0)) / speed, 0.2)
        times = np.arange(0.0, T + CTRL_DT, CTRL_DT)
        times[-1] = T
        qs = q0 + quintic(times / T)[:, None] * (q1 - q0)
        return self._start_motion(self._within_joint_limits(times, qs), qs,
                                  kind="move_j", target=q1.round(5).tolist())

    def move_j_ik(self, pose, speed=1.0) -> Motion:
        """Joint-space move to a tool pose (path is not a straight line)."""
        pose = np.asarray(pose, float)
        with self.lock:
            q0 = self.sim.d.ctrl[self.arm_act].copy()
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
            mo = Motion(self.sim.d.time, times, qs)
            self.motion = mo
            # How long the move will take (unless replaced or stopped first): the run's timeline
            # draws it as a bar.
            self.log_event("command", seconds=round(float(times[-1]), 3), **info)
            return mo

    def stop(self):
        with self.lock:
            if self.motion:
                self.motion.result = "stopped"
                self.motion.done.set()
                self.motion = None
            self.sim.d.ctrl[self.arm_act] = self.sim.d.qpos[self.arm_qadr]
            self.log_event("command", kind="stop")

    def unlock(self):
        with self.lock:
            self.sim.d.ctrl[self.arm_act] = self.sim.d.qpos[self.arm_qadr]
            self.mode = "running"
            self.stop_reason = ""
            self.log_event("command", kind="unlock_protective_stop")

    def _within_joint_limits(self, times, qs):
        """Stretch a trajectory in time until no joint exceeds its speed or acceleration limit
        (a real controller slows the motion down rather than tracking it badly)."""
        if len(times) < 3:
            return times
        dt = np.diff(times)
        v = np.diff(qs, axis=0) / dt[:, None]
        a = np.diff(v, axis=0) / dt[1:, None]
        k = max(1.0, np.max(np.abs(v) / self.P["joint_vmax"]),
                np.sqrt(np.max(np.abs(a) / self.P["joint_amax"])))
        return times * k

    def gripper_move(self, position, speed=255, force=150):
        position = float(np.clip(position, 0, 255))
        P = self.P
        m = self.sim.m
        with self.lock:
            self.grip_target = position
            sp = float(np.clip(speed, 0, 255)) / 255.0
            fo = float(np.clip(force, 0, 255)) / 255.0
            if "grip_speed_mm_s" in P:
                # Both fingers move at up to the rated speed; 0..255 spans the full stroke.
                full = 255.0 * 2 * P["grip_speed_mm_s"] / P["grip_stroke_mm"]
                self.grip_rate = max(0.1, sp) * full
                lo, hi = P["grip_force_n"]
                # The tendon force splits over both fingers, so it is twice the squeeze.
                f = 2 * (lo + (hi - lo) * fo)
                m.actuator_forcerange[self.grip_act] = [-f, f]
            elif "grip_ctrl_range" in P:
                self.grip_rate = 40.0 + 360.0 * sp
                m.jnt_actfrcrange[self.grip_jnt] = self.grip_jnt_force_base * (0.2 + 0.8 * fo)
            else:
                self.grip_rate = 40.0 + 360.0 * sp
                m.actuator_forcerange[self.grip_act] = self.grip_force_base * (0.2 + 0.8 * fo)
            self.log_event("command", kind="gripper", position=position, speed=speed, force=force)

    def zero_ft(self):
        if not self.has_ft:
            raise RobotError("this robot has no wrist force/torque sensor")
        with self.lock:
            self.ft_offset = self._ft_compensated(offset=False)

    # ------------------------------------------------------------- sensors
    def _reflex(self, w) -> str:
        """Reason for a protective stop if the external wrench is outside the safe range."""
        P = self.P
        (flo, fhi), (tlo, thi) = P["reflex_force"], P["reflex_torque"]
        f, t = w[:3], w[3:]
        if "reflex_force_norm" in P and np.linalg.norm(f) > P["reflex_force_norm"]:
            return f"wrist force {np.linalg.norm(f):.0f} N exceeded {P['reflex_force_norm']:.0f} N"
        for i, ax in enumerate("xyz"):
            if not flo[i] <= f[i] <= fhi[i]:
                return f"external force F{ax} {f[i]:.0f} N outside {flo[i]:.0f}..{fhi[i]:.0f} N (cartesian reflex)"
            if not tlo[i] <= t[i] <= thi[i]:
                return f"external torque M{ax} {t[i]:.1f} Nm outside {tlo[i]:.0f}..{thi[i]:.0f} Nm (cartesian reflex)"
        return ""

    def _ft_external(self) -> np.ndarray:
        """True external wrench at the flange (no sensor bias, no tare)."""
        return self._ft_compensated(offset=False) - self.ft_bias

    def _ft_compensated(self, offset=True) -> np.ndarray:
        """Wrist force/torque in the tool flange frame, with the gripper's weight removed,
        as the sensor reports it (including its bias)."""
        d, m = self.sim.d, self.sim.m
        raw_f = d.sensor(self.sensors[0]).data.copy()
        raw_t = d.sensor(self.sensors[1]).data.copy()
        R = d.site_xmat[self.ft_site].reshape(3, 3)
        mass = m.body_subtreemass[self.ft_body]
        Fg = R.T @ (mass * m.opt.gravity)
        r = R.T @ (d.subtree_com[self.ft_body] - d.site_xpos[self.ft_site])
        f = raw_f + Fg
        t = raw_t + np.cross(r, Fg)
        out = np.concatenate([f, t]) + self.ft_bias
        return out - self.ft_offset if offset else out

    def _grip_ctrl(self, position):
        """Actuator command for a gripper position on the 0 (open) .. 255 (closed) scale."""
        if "grip_ctrl_range" in self.P:          # the actuator's own units (ALOHA: finger travel, m)
            a, b = self.P["grip_ctrl_range"]
            return a + (b - a) * position / 255.0
        o = self.P["grip_ctrl_open"]
        return o + (255.0 - 2 * o) * position / 255.0   # o=0: same scale; o=255: reversed

    def gripper_status(self):
        d, P = self.sim.d, self.P
        q_open, q_closed = P["grip_open"], P.get("grip_closed", 0.0)
        pos = float(np.clip((d.qpos[self.grip_qadr] - q_open) / (q_closed - q_open) * 255.0, 0, 255))
        vel = abs(float(d.qvel[self.grip_dadr]))
        moving = bool(abs(self.grip_cmd - self.grip_target) > 0.5 or vel > 0.05)   # plain bool for JSON
        meet = P.get("grip_meet")      # where the fingers touch each other, when short of fully closed
        meet = 255.0 * (meet - q_open) / (q_closed - q_open) if meet is not None else 255.0
        if moving:
            obj = 0
        elif self.grip_target - pos > 6 and pos < meet - 6:
            obj = 2   # stopped early while closing: something is between the fingers
        elif pos - self.grip_target > 6:
            obj = 1   # stopped early while opening
        else:
            obj = 3   # reached the requested position, no object
        return {"position": round(pos, 1), "requested": round(self.grip_target, 1),
                "object_detected": obj in (1, 2), "status_code": obj, "moving": moving}

    def state(self) -> dict:
        with self.lock:
            d = self.sim.d
            q = d.qpos[self.arm_qadr] + self.rng.normal(0, 2e-5, self.n_arm)
            qd = d.qvel[self.arm_dadr].copy()
            pw, Rw = d.site_xpos[self.tcp_site].copy(), d.site_xmat[self.tcp_site].reshape(3, 3).copy()
            pb, Rb = self.to_base(pw, Rw)
            out = {
                "time": round(d.time, 4),
                "mode": self.mode,
                "protective_stop_reason": self.stop_reason,
                "moving": self.motion is not None,
                "joint_positions": q.round(5).tolist(),
                "joint_velocities": qd.round(4).tolist(),
                "tcp_pose": np.concatenate([pb, rotvec_from_quat(quat_from_mat(Rb))]).round(5).tolist(),
            }
            if self.has_ft:
                fn, tn = self.P["ft_noise"]
                ft = self._ft_compensated() + np.concatenate([self.rng.normal(0, fn, 3), self.rng.normal(0, tn, 3)])
                out["tcp_force"] = ft.round(3).tolist()
            out["gripper"] = self.gripper_status()
            out["realtime_factor"] = round(self.sim.rt_factor, 3)
            return out

    def ground_truth(self) -> dict:
        """Object poses (in this robot's base frame) for scoring only. Never exposed through
        the robot API."""
        with self.lock:
            m, d = self.sim.m, self.sim.d
            out = {}
            for i in range(m.nbody):
                name = m.body(i).name
                j = m.body_jntadr[i]
                if j >= 0 and m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE:
                    p = self.to_base(d.xpos[i])
                    out[name] = {"pos": p.round(5).tolist(), "quat": d.xquat[i].round(5).tolist()}
            # Soft objects (the playground's flexes) have no single pose: their shape's centre,
            # lowest and highest point, and extent along the base frame's axes.
            for f in range(m.nflex):
                a, n = int(m.flex_vertadr[f]), int(m.flex_vertnum[f])
                V = np.array([self.to_base(v) for v in d.flexvert_xpos[a:a + n]])
                out[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_FLEX, f)] = {
                    "pos": V.mean(0).round(5).tolist(), "low": round(float(V[:, 2].min()), 5),
                    "high": round(float(V[:, 2].max()), 5), "extent": np.ptp(V, 0).round(5).tolist(), "soft": True}
            # Objects' moving parts (a lid's hinge, a drawer's slide): radians or metres.
            joints = {m.joint(j).name: round(float(d.qpos[m.jnt_qposadr[j]]), 5) for j in range(m.njnt)
                      if m.body(m.jnt_bodyid[j]).name.startswith("obj_")
                      and int(m.jnt_type[j]) in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))}
            return {"time": round(d.time, 4), "task": self.task, "objects": out, "joints": joints}

    def calibration(self) -> dict:
        """Camera calibration as a lab would have it after a hand-eye calibration: intrinsics,
        the fixed camera's pose in the base frame, and the wrist camera's pose in the TCP frame.
        Poses use OpenCV camera axes (x right, y down, z forward)."""
        m = self.sim.m
        with self.lock:
            d = mujoco.MjData(m)
            d.qpos[:] = self.sim.d.qpos
        mujoco.mj_forward(m, d)
        bp, bR = d.xpos[self.base_body], d.xmat[self.base_body].reshape(3, 3)
        tp, tR = d.site_xpos[self.tcp_site], d.site_xmat[self.tcp_site].reshape(3, 3)
        out = {}
        for name, cam in self.P["cameras"].items():
            if name == "side":
                continue
            cid = m.camera(cam).id
            f = (CAM_H / 2) / np.tan(np.deg2rad(m.cam_fovy[cid]) / 2)
            Rw = d.cam_xmat[cid].reshape(3, 3) @ np.diag([1.0, -1.0, -1.0])
            pw = d.cam_xpos[cid]
            if name == "wrist":
                frame, p, R = "tcp", tR.T @ (pw - tp), tR.T @ Rw
            else:
                frame, p, R = "base", bR.T @ (pw - bp), bR.T @ Rw
            out[name] = {"intrinsics": {"fx": f, "fy": f, "cx": CAM_W / 2, "cy": CAM_H / 2,
                                        "width": CAM_W, "height": CAM_H, "distortion": [0, 0, 0, 0, 0]},
                         "pose_frame": frame, "position": p.round(5).tolist(),
                         "rotation": R.round(6).tolist(), "depth_units": "metres along the camera z axis"}
        return out

    def state_at(self, t: float) -> dict | None:
        """The logged robot readings closest before sim time t (for rewinding the viewer)."""
        log = self.state_log
        i = bisect.bisect_right([s["time"] for s in log], t) - 1
        return log[max(i, 0)] if log else None

    def render(self, camera: str, **kw) -> dict:
        return self.sim.render(camera, arm=self, **kw)


class TwoArm(Arm):
    """A two-arm robot (ALOHA): one robot in the lab, one AI run, two arms. Each arm is an Arm
    of its own ("left", "right") with its own base frame, controller, gripper and wrist camera;
    its commands go to that arm (the robot API's /left/..., /right/...). The pair keeps the
    log, the run and the shared cameras, reads both arms, and stops both."""

    def __init__(self, sim: "Sim", robot: str, prefix: str = "", uid: str = "robot",
                 world_cameras: str | None = None):
        self.sim = sim
        self.uid = uid
        self.prefix = prefix
        self.side = ""
        self.parent = None
        self.robot = S.robot_name(robot)
        self.P = S.profile_for(self.robot, prefix, world_cameras)
        self.sides: dict[str, Arm] = {}
        for side in self.P["sides"]:
            a = Arm(sim, f"{self.robot}:{side}", prefix, uid)
            a.parent = self
            self.sides[side] = a
        self.rng = np.random.default_rng()
        self.events: list[dict] = []
        self._log_f = None
        self.run_dir = None
        self.recording_from = 0.0
        self.state_log: list[dict] = []
        self.task = None
        self.has_ft = False

    # The pair's status is its arms'.
    @property
    def mode(self):
        return "protective_stop" if any(a.mode != "running" for a in self.sides.values()) else "running"

    @property
    def stop_reason(self):
        return "; ".join(f"{s} arm: {a.stop_reason}" for s, a in self.sides.items() if a.stop_reason)

    @property
    def motion(self):
        """An arm's move still under way if there is one, else an arm's last move."""
        ms = [a.motion for a in self.sides.values() if a.motion is not None]
        return next((m for m in ms if not m.done.is_set()), ms[0] if ms else None)

    @motion.setter
    def motion(self, v):
        if v is None:              # a rebuild drops both arms' motions
            for a in self.sides.values():
                a.motion = None

    def _index(self):
        m = self.sim.m
        for a in self.sides.values():
            a._index()
        arms = list(self.sides.values())
        self.base_body = m.body(self.prefix + "base").id
        self.bodies = set().union(*(a.bodies for a in arms))
        self.own_joints = [j for a in arms for j in a.own_joints]
        self.n_arm = sum(a.n_arm for a in arms)
        self.arm_qadr = np.concatenate([a.arm_qadr for a in arms])
        self.arm_dadr = np.concatenate([a.arm_dadr for a in arms])
        self.arm_act = np.concatenate([a.arm_act for a in arms])
        self.joint_lo = np.concatenate([a.joint_lo for a in arms])
        self.joint_hi = np.concatenate([a.joint_hi for a in arms])
        self.ready_q = np.concatenate([a.ready_q for a in arms])
        self.P["arm_joints"] = [j for a in arms for j in a.P["arm_joints"]]

    def reset_pose(self):
        for a in self.sides.values():
            a.reset_pose()

    def reset_state(self):
        for a in self.sides.values():
            a.reset_state()
        self.events = []
        self.state_log = []
        self.recording_from = self.sim.d.time

    def snapshot(self) -> dict:
        return {s: a.snapshot() for s, a in self.sides.items()}

    def restore(self, snap: dict):
        for s, a in self.sides.items():
            if s in snap:
                a.restore(snap[s])

    def _control(self):
        for a in self.sides.values():
            a._control()

    # ------------------------------------------------------------ commands
    def _which(self):
        raise RobotError(f"this robot has {len(self.sides)} arms: send each command to one of them "
                         f"({', '.join(self.sides)})")

    def move_l(self, *a, **k):
        self._which()

    move_j = move_j_ik = gripper_move = move_l

    def zero_ft(self):
        raise RobotError("this robot has no wrist force/torque sensors")

    def stop(self):
        for a in self.sides.values():
            a.stop()

    def unlock(self):
        for a in self.sides.values():
            a.unlock()

    # ------------------------------------------------------------- sensors
    def gripper_status(self):
        return {s: a.gripper_status() for s, a in self.sides.items()}

    def state(self) -> dict:
        with self.lock:
            out = {"time": round(self.sim.d.time, 4), "mode": self.mode,
                   "protective_stop_reason": self.stop_reason, "moving": self.motion is not None}
            for s, a in self.sides.items():
                st = a.state()
                for k in ("time", "realtime_factor"):
                    st.pop(k, None)
                out[s] = st
            out["realtime_factor"] = round(self.sim.rt_factor, 3)
            return out

    def base_tf(self):
        """The pair's readings and its cameras' poses are in the left arm's base frame."""
        return self.sides[next(iter(self.sides))].base_tf()

    def calibration(self) -> dict:
        """Each arm's calibration, in that arm's own frames: the fixed cameras in its base frame,
        its wrist camera in its TCP frame."""
        return {s: a.calibration() for s, a in self.sides.items()}


class RobotView:
    """What the robot API sees of one robot in a world with several (the playground's lab):
    the robot's own commands, sensors and cameras, with the world's time and recording.
    Used by the HTTP handler in place of the Sim for that robot's requests."""

    def __init__(self, sim: "Sim", arm: Arm):
        self.sim, self.arm = sim, arm

    def __getattr__(self, k):
        return getattr(self.arm, k)

    @property
    def events(self):
        return self.arm.events

    def qpos_at(self, t):
        return self.sim.qpos_at(t)

    def reset(self, task=None):
        """A run starting on this robot: only this robot starts over (the others keep going)."""
        with self.sim.lock:
            self.arm.reset_state()
            self.arm.task = task

    def open_log(self, run_dir):
        # A run's log goes to its own folder. When the run ends the robot cell opens a fresh
        # session log; here this robot just stops logging (the world's session log goes on).
        if pathlib.Path(run_dir).name.startswith("session-"):
            self.arm.close_log()
        else:
            self.arm.open_log(run_dir)

    def save_model(self, run_dir):
        self.sim.save_model(run_dir)

    def save_recording(self, path):
        return self.sim.save_recording(path, since=self.arm.recording_from)


# ------------------------------------------------------------------ simulator
class Sim:
    def __init__(self, run_dir: str | pathlib.Path | None = None, realtime: float = 1.0,
                 robot: str | None = None):
        self.robot = S.robot_name(robot)
        self.lock = threading.RLock()
        self.realtime = realtime
        self.paused = False             # the playground can pause the world; the robot cell never does
        self._model_ver = 0             # bumped when the scene is rebuilt (renderers follow)
        self.rt_factor = 1.0
        self.arms: dict[str, Arm] = {}
        self.m = self._make_model()
        self.d = mujoco.MjData(self.m)
        self._index()
        self.rng = np.random.default_rng()
        self.run_dir = pathlib.Path(run_dir) if run_dir else None
        self._log_f = None
        self._cap_rgba0 = {}
        self.task = None
        self.reset()
        self._running = False
        self._render_q: queue.PriorityQueue = queue.PriorityQueue()
        self._render_seq = 0

    def _make_model(self) -> mujoco.MjModel:
        return S.build_model(self.robot)

    def _make_arms(self) -> dict[str, Arm]:
        """The robots in the current model (one, unprefixed, in the robot cell)."""
        return {"robot": Arm(self, self.robot)}

    def _index(self):
        """Look up every robot's joints, actuators, sites and bodies in the current model.
        Robots that were there before keep their controller state."""
        old = self.arms
        new = self._make_arms()
        for uid, a in new.items():
            if uid in old and old[uid].robot == a.robot and old[uid].prefix == a.prefix:
                new[uid] = old[uid]
            new[uid]._index()
        self.arms = new

    # The first robot is the robot of a one-robot scene: the robot cell's API addresses it.
    @property
    def arm(self) -> Arm:
        if not self.arms:      # a playground lab with no robot yet
            raise RobotError("there's no robot in this lab")
        return next(iter(self.arms.values()))

    def __getattr__(self, k):
        # Robot-level readings and commands (P, ready_q, move_l, state, ...) of the scene's robot.
        if k in ("arms", "m", "d") or k.startswith("__"):
            raise AttributeError(k)
        arms = self.__dict__.get("arms")
        if not arms:
            raise AttributeError(k)
        return getattr(next(iter(arms.values())), k)

    @property
    def P(self):
        return self.arm.P

    @property
    def mode(self):
        return self.arm.mode

    @property
    def motion(self):
        return self.arm.motion

    # ---------------------------------------------------------------- setup
    def reset(self, task: str | None = None):
        """Start over, with the bench laid out for a task (tasks.py), or the default bench."""
        with self.lock:
            m, d = self.m, self.d
            mujoco.mj_resetData(m, d)
            for a in self.arms.values():
                a.reset_pose()
            self.task = task
            self._lay_out(task)
            mujoco.mj_forward(m, d)
            for _ in range(250):            # let things settle
                mujoco.mj_step(m, d)
            for a in self.arms.values():
                a.reset_state()
                a.task = task
            self.events: list[dict] = []
            self._wall0 = time.perf_counter()
            self._sim0 = self.d.time
            self.rt_factor = 1.0
            self.recording: list[tuple[float, np.ndarray]] = []   # (time, qpos) at 30 Hz for replay videos
            self._next_rec = self.d.time

    @property
    def state_log(self):
        return self.arm.state_log

    def _set_free(self, name: str, pos_b, quat):
        adr = self.m.jnt_qposadr[self.m.body_jntadr[self.m.body(name).id]]
        self.d.qpos[adr:adr + 3] = np.asarray(pos_b) + np.array(S.ROBOT_BASE)
        self.d.qpos[adr + 3:adr + 7] = quat

    def _lay_out(self, task):
        poses, colours = T.layout_for(task)
        m = self.m
        for name, rgba in self._cap_rgba0.items():     # undo the last task's recolouring
            m.geom_rgba[m.geom(name).id] = rgba
        for body, rgba in colours.items():
            g = m.geom(f"{body}_capvis").id
            self._cap_rgba0.setdefault(f"{body}_capvis", m.geom_rgba[g].copy())
            m.geom_rgba[g] = rgba
        for name, (pos, quat) in poses.items():
            self._set_free(name, pos, quat)

    def open_log(self, run_dir: str | pathlib.Path):
        with self.lock:
            if self._log_f:
                self._log_f.close()
            self.run_dir = pathlib.Path(run_dir)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._log_f = open(self.run_dir / "states.jsonl", "a")

    def log_event(self, event: str, **kw):
        self.arm.log_event(event, **kw)

    @property
    def events(self):
        return self.arm.events

    @events.setter
    def events(self, v):
        pass   # each robot keeps its own (reset clears them)

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
            if self.paused:
                with self.lock:
                    self._wall0, self._sim0 = wall, self.d.time   # time stands still
                last_check, sim_done = wall, 0.0
                time.sleep(0.005)
                continue
            with self.lock:
                m, d = self.m, self.d          # the scene may have been rebuilt
                arms = list(self.arms.values())
                target = self._sim0 + (wall - self._wall0) * self.realtime
                n = 0
                while d.time < target and n < 100:
                    for a in arms:
                        a._control()
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

    def ground_truth(self) -> dict:
        """Object poses for scoring only. Never exposed through the robot API."""
        out = self.arm.ground_truth()
        out["task"] = self.task
        return out

    def save_recording(self, path, since: float | None = None):
        with self.lock:
            rec = [r for r in self.recording if since is None or r[0] >= since - 1e-9]
        np.savez_compressed(path, time=np.array([t for t, _ in rec]), qpos=np.array([q for _, q in rec]))
        return len(rec)

    def _log_loop(self):
        while self._running:
            time.sleep(0.05)
            for a in list(self.arms.values()):
                f = a._log_f or (self._log_f if a is self.arm else None)
                if not f:
                    continue
                try:
                    s = a.state()
                except (KeyError, ValueError):
                    # The world was rebuilt under us (the playground switching scenes) and this
                    # arm's sensors are gone: skip it this tick rather than end the logger.
                    continue
                a.state_log.append(dict(s))
                # Keep memory bounded when the cell idles for hours between runs (a run resets both).
                if len(a.state_log) > 2 * 3600 * 20:
                    del a.state_log[:3600 * 20]
                s["ground_truth"] = a.ground_truth()["objects"]
                with self.lock:
                    f = a._log_f or (self._log_f if a is self.arm else None)
                    if f:
                        f.write(json.dumps(s) + "\n")
            if len(self.recording) > 2 * 3600 * 30:
                with self.lock:
                    del self.recording[:3600 * 30]

    # ------------------------------------------------------------- cameras
    def qpos_at(self, t: float):
        rec = self.recording
        if not rec:
            return None
        i = bisect.bisect_right([r[0] for r in rec], t) - 1
        return rec[max(i, 0)][1]

    def save_model(self, run_dir):
        """Keep the scene as it is now (task recolouring included) so this run can be replayed
        after the scene changes. Scenes are ~40 MB, so each distinct one is stored once in
        runs/_models/ and the run gets a pointer to it (model.ref)."""
        import hashlib
        run_dir = pathlib.Path(run_dir)
        with self.lock:
            buf = np.zeros(mujoco.mj_sizeModel(self.m), dtype=np.uint8)
            mujoco.mj_saveModel(self.m, None, buf)
        name = hashlib.sha256(buf.tobytes()).hexdigest()[:16] + ".mjb"
        store = run_dir.parent / "_models"
        store.mkdir(exist_ok=True)
        if not (store / name).exists():
            (store / name).write_bytes(buf.tobytes())
        (run_dir / "model.ref").write_text(name + "\n")

    def render(self, camera: str, depth: bool = False, priority: int = 0, timeout=30.0,
               qpos=None, at_time: float | None = None, model: mujoco.MjModel | None = None,
               arm: Arm | None = None) -> dict:
        """Render a robot's camera now, or (qpos given) the scene as it was at at_time. model:
        an older run's own scene, to replay it. arm: whose camera (default: the scene's robot)."""
        arm = arm or self.arm
        if camera not in arm.P["cameras"]:
            raise RobotError(f"unknown camera '{camera}', choose from {list(arm.P['cameras'])}")
        if priority == 0 and qpos is None:
            with self.lock:
                arm.log_event("camera", camera=camera)
        box: dict = {}
        ev = threading.Event()
        self._render_seq += 1
        self._render_q.put((priority, self._render_seq, camera, depth, box, ev, qpos, at_time, model, arm))
        if not ev.wait(timeout):
            raise RobotError("camera timed out")
        if "error" in box:
            raise RobotError(box["error"])
        return box

    def _render_loop(self):
        ver = None
        other: dict[int, tuple] = {}     # renderers for older runs' scenes
        while self._running:
            try:
                _, _, camera, depth, box, ev, qpos, at_time, model, arm = self._render_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if ver != self._model_ver:   # first frame, or the scene was rebuilt
                with self.lock:
                    ver, m = self._model_ver, self.m
                    rd = mujoco.MjData(m)
                if "rgb_r" in locals():
                    rgb_r.close()
                    dep_r.close()
                rgb_r = mujoco.Renderer(m, CAM_H, CAM_W)
                dep_r = mujoco.Renderer(m, CAM_H, CAM_W)
                dep_r.enable_depth_rendering()
            if model is not None:
                try:
                    if id(model) not in other:
                        if len(other) > 4:
                            other.clear()
                        other[id(model)] = (model, mujoco.MjData(model), mujoco.Renderer(model, CAM_H, CAM_W))
                    om, od, orr = other[id(model)]
                    od.qpos[:] = qpos
                    mujoco.mj_forward(om, od)
                    orr.update_scene(od, camera=arm.P["cameras"][camera])
                    box["rgb"] = orr.render().copy()
                    box["time"] = round(at_time or 0.0, 4)
                except Exception as e:  # noqa: BLE001
                    box["error"] = f"render failed: {e}"
                ev.set()
                continue
            try:
                with self.lock:
                    if self._model_ver != ver:   # rebuilt since this frame was asked for
                        self._render_q.put((0, -1, camera, depth, box, ev, qpos, at_time, model, arm))
                        continue
                    if qpos is None:
                        rd.qpos[:] = self.d.qpos
                        rd.qvel[:] = self.d.qvel
                        rd.time = self.d.time
                    else:
                        rd.qpos[:] = qpos
                        rd.qvel[:] = 0
                        rd.time = at_time or 0.0
                    bp, bR = arm.base_tf()
                    cam_name = arm.P["cameras"][camera]
                mujoco.mj_forward(m, rd)
                cid = m.camera(cam_name).id
                rgb_r.update_scene(rd, camera=cam_name)
                box["rgb"] = rgb_r.render().copy()
                if depth:
                    dep_r.update_scene(rd, camera=cam_name)
                    box["depth"] = dep_r.render().astype(np.float32)
                fovy = np.deg2rad(m.cam_fovy[cid])
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
