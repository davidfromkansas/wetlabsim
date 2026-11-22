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


def test_loose_object_moves_and_turns_without_a_rebuild(lab):
    """A loose object is moved and turned by setting where it is (no recompile of the world),
    so the page needn't reload the scene; furniture still needs a rebuild."""
    sim, st = lab
    uid = sim.add("rubiks_cube", (st.pos[0] + 0.5, st.pos[1] - 0.1, st.top))
    ver, m = sim._model_ver, sim.m
    x, y, _ = _at(sim, uid)
    sim.translate(uid, x=x + 0.04)
    sim.orient(uid, axis="z", degrees=30)
    sim.translate(uid, lift=0.05)
    assert sim._model_ver == ver and sim.m is m
    assert _at(sim, uid) == pytest.approx([x + 0.04, y, 0.05], abs=3e-3)
    p = sim.find(uid)
    b = sim.m.body(f"obj_{uid}").id
    assert sim.d.xpos[b] == pytest.approx(p.pos, abs=1e-6)       # remembered for the next rebuild
    sim.rebuild()                                                # and kept by it
    assert _at(sim, uid) == pytest.approx([x + 0.04, y, 0.05], abs=3e-3)
