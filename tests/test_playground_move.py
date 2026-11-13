"""Moving objects in the playground along the world's X, Y and Z (the object card's Move mode)."""
import mujoco
import pytest

from playground.sim import PlaygroundSim, RobotError


@pytest.fixture(scope="module")
def lab():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    sim.placed = []
    sim.rebuild()
    return sim, sim.station(uid)


def _at(sim, uid):
    return next(o for o in sim.scene_info(sel=uid)["objects"] if o["uid"] == uid)["at"]


def test_move_along_x_and_y(lab):
    sim, st = lab
    uid = sim.add("rubiks_cube", (st.pos[0] + 0.6, st.pos[1] - 0.2, st.top))
    x, y, lift = _at(sim, uid)
    assert lift == 0.0
    sim.translate(uid, x=x + 0.05)
    assert _at(sim, uid) == pytest.approx([x + 0.05, y, 0.0], abs=2e-3)
    sim.translate(uid, y=y + 0.03)
    assert _at(sim, uid) == pytest.approx([x + 0.05, y + 0.03, 0.0], abs=2e-3)


def test_lift_holds_until_physics_then_falls(lab):
    sim, st = lab
    uid = sim.add("rubiks_cube", (st.pos[0] + 0.6, st.pos[1] + 0.2, st.top))
    sim.translate(uid, lift=0.10)
    assert _at(sim, uid)[2] == pytest.approx(0.10, abs=2e-3)
    for _ in range(int(1.0 / sim.m.opt.timestep)):
        mujoco.mj_step(sim.m, sim.d)
    assert _at(sim, uid)[2] < 0.005          # dropped back onto the table


def test_never_into_the_table(lab):
    sim, st = lab
    uid = sim.add("rubiks_cube", (st.pos[0] + 0.6, st.pos[1], st.top))
    sim.translate(uid, lift=-0.2)                        # down is stopped at the surface
    b = sim.m.body(f"obj_{uid}").id
    assert sim.d.xpos[b][2] >= st.top - 1e-3


def test_limits(lab):
    sim, st = lab
    uid = sim.add("rubiks_cube", (st.pos[0] + 0.6, st.pos[1] + 0.1, st.top))
    with pytest.raises(RobotError):
        sim.translate(uid, lift=5.0)                     # too high
    with pytest.raises(RobotError):
        sim.translate(uid, x=20.0)                       # off the floor
