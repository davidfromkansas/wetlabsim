"""Rotating objects in the playground (X, Y, Z about the world's axes) and dropping things on
the surface under a robot arm."""
import math

import mujoco
import numpy as np
import pytest

from playground import world as W
from playground.sim import PlaygroundSim, RobotError


@pytest.fixture(scope="module")
def lab():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    sim.placed = []
    sim.rebuild()
    return sim, sim.station(uid)


def _obj(sim, uid):
    return next(o for o in sim.scene_info()["objects"] if o["uid"] == uid)


def _settle(sim, sec=0.5):
    for _ in range(int(sec / sim.m.opt.timestep)):
        mujoco.mj_step(sim.m, sim.d)


@pytest.mark.parametrize("e", [(0, 165, 0), (90, 0, 0), (0, 180, 0), (30, -40, 120), (0, 90, 0)])
def test_angles_round_trip(e):
    R = W.euler_rot(e)
    assert np.allclose(W.euler_rot(W.rot_euler(R)), R, atol=1e-6)
    assert W.rot_euler(R) == pytest.approx(list(e), abs=0.11)


def test_drop_under_the_arm(lab):
    sim, st = lab
    hand = sim.d.xpos[sim.m.body(f"{st.uid}/hand").id]
    spot = sim.support("tube_15ml", float(hand[0]), float(hand[1]))
    assert spot["valid"], spot["reason"]
    assert spot["pos"][2] == pytest.approx(st.top, abs=0.002)       # on the table, not on the arm
    # something taller than the gap under the hand doesn't fit
    gap = hand[2] - st.top
    big = sim.support("refrigerator", float(hand[0]), float(hand[1]))
    assert not big["valid"] and ("arm" in big["reason"] or "base" in big["reason"]), (gap, big)


def test_not_on_the_base(lab):
    sim, st = lab
    x, y, _ = st.to_world(*st.robot_xy)
    spot = sim.support("apple", x, y)
    assert not spot["valid"] and "base" in spot["reason"]


def test_lay_a_tube_down_and_back(lab):
    sim, st = lab
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1] + 0.25)
    uid = sim.add("tube_15ml", (x, y, st.top + 0.0005), 0.0)
    sim.orient(uid, euler=[90, 0, 0])
    o = _obj(sim, uid)
    assert o["euler"] == pytest.approx([90, 0, 0], abs=0.5)
    b = sim.m.body(f"obj_{uid}").id
    # it lies on the table (its middle about a tube's radius up), not inside it
    assert o["mid"][2] == pytest.approx(st.top + 0.0113, abs=0.004)
    _settle(sim)
    z = sim.d.xmat[b].reshape(3, 3)[:, 2]
    assert abs(z[2]) < 0.1                                      # still lying down
    assert sim.d.xpos[b][2] > st.top - 0.002
    sim.orient(uid, axis="z", degrees=30)                      # turned about the vertical, still lying
    assert abs(sim.d.xmat[b].reshape(3, 3)[2, 2]) < 0.1
    sim.orient(uid, euler=[0, 0, 0])
    assert _obj(sim, uid)["euler"] == pytest.approx([0, 0, 0], abs=0.5)
    assert sim.d.xpos[b][2] == pytest.approx(st.top, abs=0.002)
    sim.remove(uid)


def test_moving_keeps_the_tilt(lab):
    sim, st = lab
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1] - 0.25)
    uid = sim.add("mug", (x, y, st.top + 0.0005), 0.0)
    sim.orient(uid, euler=[180, 0, 0])
    p = sim.find(uid)
    sim.move(uid, (p.pos[0] + 0.05, p.pos[1], p.pos[2]))
    assert _obj(sim, uid)["euler"][0] == pytest.approx(180, abs=0.5) or \
        abs(_obj(sim, uid)["euler"][1]) == pytest.approx(180, abs=0.5)
    sim.remove(uid)


def test_furniture_only_turns_about_z(lab):
    sim, st = lab
    uid = sim.add("refrigerator", (2.0, 2.0, 0.0005), 0.0)
    assert not _obj(sim, uid)["tilt"]
    with pytest.raises(RobotError):
        sim.orient(uid, axis="x", degrees=15)
    sim.orient(uid, axis="z", degrees=90)
    assert _obj(sim, uid)["euler"] == pytest.approx([0, 0, 90], abs=0.5)
    sim.remove(uid)
