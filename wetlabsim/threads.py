"""Screw caps for the 15 ml tubes, in stock MuJoCo (no thread plugin).

Each cap is its own free body. While it is on a tube, a weld holds it at a pose that the
controller moves along the thread: turning the cap by an angle lifts it by pitch x angle /
2 pi. A plug inside the cap stands in for the thread crests, so a cap that has come off
rests on the rim, and twisting it the tightening way there catches the thread again.

Friction in the thread works like a real cap:
- A seated cap holds until the twist on it passes its breakaway torque. That torque is the
  tightest it was ever closed, or the starting tightness.
- Once it moves, a small running friction resists the turn.
- Twisting a seated cap the tightening way tightens it further.
The twist on a cap is worked out from its contact forces (the hand's fingers, mostly).

Cap state (on/off, turns from seated, tightness) is for scoring only; agents never see it.
"""
from __future__ import annotations

import math

import mujoco
import numpy as np

from . import scene as S

START_TIGHTNESS = 0.10    # N m, how tight the caps start (our estimate for hand-tight)
RUN_FRICTION = 0.004      # N m, while the cap turns on the thread
CATCH_TORQUE = 0.002      # N m, twist needed to start a loose cap turning
THREAD_DRAG = 0.002       # N m per rad/s: how fast a given extra twist turns the cap
MAX_SPIN = 12.0           # rad/s
TURN_LEN = 2 * math.pi * S.THREAD_LEN / S.THREAD_PITCH    # rad from seated to free (~2.1 turns)


def _rotz(a):
    return np.array([math.cos(a / 2), 0, 0, math.sin(a / 2)])


def _twist_angle(R):
    """Rotation of R about its z axis (R = relative orientation, cap in tube frame)."""
    return math.atan2(R[1, 0] - R[0, 1], R[0, 0] + R[1, 1])


class Cap:
    def __init__(self, m: mujoco.MjModel, colour: str):
        self.colour = colour
        self.tube = m.body(f"tube_{colour}").id
        self.cap = m.body(f"tube_{colour}_cap").id
        self.eq = m.equality(f"thread_{colour}").id
        self.skirt = np.array([m.geom(f"tube_{colour}_cap_skirt{k}").id for k in range(20)]
                              + [m.geom(f"tube_{colour}_cap_plug").id])
        geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] == self.cap]
        self.geoms = np.array(geoms)
        self.reset()

    def reset(self, on=True, theta=0.0, tight=START_TIGHTNESS):
        self.on = on
        self.theta = theta         # rad loosened from seated (0 = seated)
        self.tight = tight if on and theta == 0 else 0.0
        self.phase = 0.0           # weld twist = theta + phase
        self.torque = 0.0


class Threads:
    """Moves the thread welds every physics step. Call step() before mj_step."""

    def __init__(self, m: mujoco.MjModel, d: mujoco.MjData):
        self.m, self.d = m, d
        self.caps = [Cap(m, c) for c, _ in S.TUBE_COLOURS]
        self.by_colour = {c.colour: c for c in self.caps}
        self._f = np.zeros(6)
        self._k = 0

    # ------------------------------------------------------------------ setup
    def place(self, colour: str, on: bool, theta: float = 0.0, tight: float = START_TIGHTNESS):
        """Set a cap's state at reset. If on, also put the cap on its tube at that turn
        (the tube must already be where it starts; call mj_forward after)."""
        c = self.by_colour[colour]
        c.reset(on, theta, tight)
        self.m.eq_active0[c.eq] = on
        self.d.eq_active[c.eq] = on
        self._set_skirt(c, on)
        if on:
            self._set_target(c, theta)
            pos, quat = self.cap_pose_on_tube(c, theta)
            adr = self.m.jnt_qposadr[self.m.body_jntadr[c.cap]]
            self.d.qpos[adr:adr + 3] = pos
            self.d.qpos[adr + 3:adr + 7] = quat

    def cap_pose_on_tube(self, c: Cap, theta: float):
        """World pose of a cap screwed onto its tube, theta rad from seated."""
        adr = self.m.jnt_qposadr[self.m.body_jntadr[c.tube]]
        tp, tq = self.d.qpos[adr:adr + 3].copy(), self.d.qpos[adr + 3:adr + 7].copy()
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, tq)
        rel = np.array([0, 0, S.CAP_SEAT + S.THREAD_PITCH * theta / (2 * math.pi)])
        q = np.zeros(4)
        mujoco.mju_mulQuat(q, tq, _rotz(theta))
        return tp + R.reshape(3, 3) @ rel, q

    # ------------------------------------------------------------------- step
    def step(self):
        for c in self.caps:
            if c.on:
                self._step_on(c)
            elif self._k % 10 == 0:
                self._try_catch(c)
        self._k += 1

    def _phi(self, c: Cap) -> float:
        Rt = self.d.xmat[c.tube].reshape(3, 3)
        Rc = self.d.xmat[c.cap].reshape(3, 3)
        return _twist_angle(Rt.T @ Rc)

    def _hand_torque(self, c: Cap) -> float:
        """Twist on the cap about the tube axis from its contacts, positive = loosening."""
        d, m = self.d, self.m
        n = d.ncon
        if n == 0:
            return 0.0
        g = d.contact.geom[:n]
        hits = np.nonzero(np.isin(g[:, 0], c.geoms) | np.isin(g[:, 1], c.geoms))[0]
        if len(hits) == 0:
            return 0.0
        axis = d.xmat[c.tube].reshape(3, 3)[:, 2]
        centre = d.xpos[c.cap]
        tau = 0.0
        for i in hits:
            con = d.contact[i]
            mujoco.mj_contactForce(m, d, i, self._f)
            f = con.frame.reshape(3, 3).T @ self._f[:3]          # force on geom2
            if con.geom1 in c.geoms:
                f = -f
            tau += float(np.dot(np.cross(con.pos - centre, f), axis))
        return tau

    def _step_on(self, c: Cap):
        tau = self._hand_torque(c)
        c.torque = tau
        if c.theta <= 0.0:
            c.theta = 0.0
            if tau < 0:                          # squeezing a seated cap tighter
                c.tight = max(c.tight, -tau)
            if tau <= max(c.tight, CATCH_TORQUE):
                return                           # holds
            c.tight = 0.0                        # broke loose
        # On the thread the cap turns as fast as the twist beyond running friction allows:
        # the weld then carries it round (and up or down the thread) at that rate.
        excess = abs(tau) - RUN_FRICTION
        if excess <= 0:
            return
        w = math.copysign(min(excess / THREAD_DRAG, MAX_SPIN), tau)
        c.theta += w * self.m.opt.timestep
        if c.theta <= 0.0:                       # just seated: the squeeze counts as tightness
            c.theta = 0.0
            c.tight = max(c.tight, -tau)
        elif c.theta >= TURN_LEN:                # off the thread
            self._release(c)
            return
        self._set_target(c, c.theta)

    def _set_target(self, c: Cap, theta: float):
        e = self.m.eq_data[c.eq]
        e[3:6] = [0, 0, S.CAP_SEAT + S.THREAD_PITCH * theta / (2 * math.pi)]
        e[6:10] = _rotz(theta + c.phase)

    def _set_skirt(self, c: Cap, on: bool):
        ct, ca = S.SKIRT_ON if on else S.SKIRT_OFF
        self.m.geom_contype[c.skirt] = ct
        self.m.geom_conaffinity[c.skirt] = ca

    def _release(self, c: Cap):
        c.on, c.theta, c.tight = False, TURN_LEN, 0.0
        self.d.eq_active[c.eq] = 0
        self._set_skirt(c, False)

    def _try_catch(self, c: Cap):
        """A loose cap resting square on its tube's rim catches the thread when twisted on."""
        d = self.d
        Rt = d.xmat[c.tube].reshape(3, 3)
        rel = Rt.T @ (d.xpos[c.cap] - d.xpos[c.tube])
        Rc = d.xmat[c.cap].reshape(3, 3)
        if (np.hypot(rel[0], rel[1]) < 0.002 and Rt[:, 2] @ Rc[:, 2] > math.cos(math.radians(10))
                and abs(rel[2] - (S.CAP_SEAT + S.THREAD_LEN)) < 0.002
                and self._hand_torque(c) < -CATCH_TORQUE):
            c.on, c.tight = True, 0.0
            c.theta = TURN_LEN - 0.05
            c.phase = self._phi(c) - c.theta     # so the weld's twist matches the cap's
            self._set_target(c, c.theta)
            d.eq_active[c.eq] = 1
            self._set_skirt(c, True)

    # ------------------------------------------------------------------ state
    def state(self) -> dict:
        return {c.colour: {"on": c.on, "turns_from_seated": round(c.theta / (2 * math.pi), 3),
                           "seated": c.on and c.theta <= 1e-6, "tightness_nm": round(c.tight, 4)}
                for c in self.caps}
