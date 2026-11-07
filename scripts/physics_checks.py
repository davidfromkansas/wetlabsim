"""Physics checks to run after any change to MuJoCo or its settings, headless (no server).

    python scripts/physics_checks.py            # prints one JSON line per check

held_15ml   A 15 ml tube held at full grip for 60 s: how far it creeps in the fingers.
held_micro  The same for the 1.5 ml tube at the baseline's grip force, for 20 s.
release_*   Open the hand: the tube must fall away and touch no finger 1 s later.
sinking     Deepest overlap between any two resting objects on the default bench.
speed       Simulated seconds per wall second, controller included, nothing capping it.
"""
from __future__ import annotations

import json
import time

import mujoco
import numpy as np

from wetlabsim.sim import Sim


def _step(s, secs):
    for _ in range(int(round(secs / s.m.opt.timestep))):
        s._control()
        mujoco.mj_step(s.m, s.d)


def _go(s, pose, speed):
    mo = s.move_l(pose, speed)
    while not mo.done.is_set():
        _step(s, 0.05)
    _step(s, 0.3)


def _pos(s, name):
    return np.array(s.ground_truth()["objects"][name]["pos"])


def _touching_fingers(s, name):
    m, d = s.m, s.d
    body = m.body(name).id
    fingers = {m.body(b).id for b in ("left_finger", "right_finger")}
    for c in d.contact[:d.ncon]:
        b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
        if {b1, b2} & {body} and {b1, b2} & fingers:
            return True
    return False


def hold_and_release(name, grip_z, force, hold_s, open_to):
    s = Sim(robot="franka")
    s.reset("T19" if name == "microtube" else "T1")
    p = _pos(s, name)
    s.gripper_move(open_to, 255, 255)
    _step(s, 1.0)
    _go(s, [p[0], p[1], 0.25, np.pi, 0, 0], 0.3)
    _go(s, [p[0], p[1], grip_z(p), np.pi, 0, 0], 0.08)
    s.gripper_move(255, 255, force)
    _step(s, 1.5)
    _go(s, [p[0], p[1], 0.30, np.pi, 0, 0], 0.15)
    tcp0 = s.d.site_xpos[s.tcp_site].copy()
    p0 = _pos(s, name) - tcp0
    _step(s, hold_s)
    creep = float(np.linalg.norm(_pos(s, name) - s.d.site_xpos[s.tcp_site] - p0))
    held = {"check": f"held_{'micro' if name == 'microtube' else '15ml'}", "seconds": hold_s,
            "creep_mm": round(creep * 1000, 3), "mode": s.mode}
    z_before = _pos(s, name)[2]
    s.gripper_move(open_to, 255, 255)
    _step(s, 1.0)
    rel = {"check": f"release_{'micro' if name == 'microtube' else '15ml'}",
           "fell_mm": round(float(z_before - _pos(s, name)[2]) * 1000, 1),
           "still_touching_finger": _touching_fingers(s, name)}
    rel["ok"] = bool(rel["fell_mm"] > 50 and not rel["still_touching_finger"])
    return held, rel


def sinking():
    s = Sim(robot="franka")
    s.reset(None)
    _step(s, 3.0)
    m, d = s.m, s.d
    worst, pair = 0.0, None
    for c in d.contact[:d.ncon]:
        if c.dist < worst:
            worst = c.dist
            pair = (m.body(m.geom_bodyid[c.geom1]).name, m.body(m.geom_bodyid[c.geom2]).name)
    return {"check": "sinking", "deepest_overlap_mm": round(-worst * 1000, 3), "between": pair}


def speed():
    s = Sim(robot="franka")
    s.reset("T1")
    _step(s, 0.5)
    t = time.perf_counter()
    _step(s, 5.0)
    return {"check": "speed", "x_realtime": round(5.0 / (time.perf_counter() - t), 2),
            "timestep": s.m.opt.timestep}


if __name__ == "__main__":
    print(json.dumps({"mujoco": mujoco.__version__}))
    for row in hold_and_release("tube_red", lambda p: 0.10, 255, 60.0, 150):
        print(json.dumps(row), flush=True)
    for row in hold_and_release("microtube", lambda p: p[2] + 0.0224 - 0.008, 150, 20.0, 200):
        print(json.dumps(row), flush=True)
    print(json.dumps(sinking()), flush=True)
    print(json.dumps(speed()), flush=True)
