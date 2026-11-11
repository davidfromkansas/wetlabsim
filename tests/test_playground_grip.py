"""The playground's lab runs other solver options than the robot cell (playground/world.py:
discrete integrator, no noslip, impratio 100, for springy soft objects). Grasps must still hold."""
import mujoco
import numpy as np
import pytest

from playground import world as W
from playground.sim import PlaygroundSim


def _lab(robot, item, yaw=0.0):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station(robot, (0, 0), 0.0, "table")
    st = sim.station(uid)
    sim.placed = []
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1])
    sim.placed.append(W.Placed("t1", item, (x, y, st.top + 0.002), yaw))
    sim.rebuild()
    return sim, sim.arms[uid]


def _step(sim, sec):
    for _ in range(int(sec / sim.m.opt.timestep)):
        for a in sim.arms.values():
            a._control()
        mujoco.mj_step(sim.m, sim.d)


def _go(sim, mo):
    t = 0.0
    while not mo.done.is_set() and t < 15:
        _step(sim, 0.05)
        t += 0.05
    _step(sim, 0.3)


def _grab(sim, arm, pb, z):
    pose = lambda zz: [pb[0], pb[1], zz, np.pi, 0, 0]
    arm.gripper_move(0)
    _step(sim, 0.5)
    _go(sim, arm.move_l(pose(z + 0.15), 0.3))
    _go(sim, arm.move_l(pose(z), 0.08))
    arm.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    _go(sim, arm.move_l(pose(z + 0.15), 0.15))


def test_lab_uses_its_own_solver_options():
    sim, _ = _lab("franka", "glass_vial")
    assert sim.m.opt.integrator == mujoco.mjtIntegrator.mjINT_DISCRETE
    assert sim.m.opt.noslip_iterations == 0 and sim.m.opt.impratio == 100


@pytest.mark.parametrize("robot", ["franka", "ur5e"])
@pytest.mark.parametrize("item", ["glass_vial", "lab_bottle"])
def test_full_grip_holds_in_the_lab(robot, item):
    """Held at full strength for 20 s, the item barely moves in the hand (under discrete with
    noslip, the Franka Hand's tendon grip dropped these)."""
    sim, arm = _lab(robot, item)
    _step(sim, 1.0)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    h = W.catalog.meta(item)["size"][2]
    _grab(sim, arm, arm.to_base(p0), max(h - 0.035, 0.012))
    tcp = lambda: sim.d.site_xpos[arm.tcp_site].copy()
    r0 = sim.d.xpos[b] - tcp()
    _step(sim, 20.0)
    r1 = sim.d.xpos[b] - tcp()
    assert sim.d.xpos[b][2] - p0[2] > 0.1, "dropped"
    assert np.linalg.norm(r1 - r0) < 0.003
    assert arm.mode == "running"


def test_sponge_squeezes_and_springs_back():
    sim, arm = _lab("franka", "sponge", yaw=np.pi / 2)   # its 7 cm side across the fingers
    _step(sim, 1.0)
    f = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_FLEX, "obj_t1")
    a, n = sim.m.flex_vertadr[f], sim.m.flex_vertnum[f]
    V = lambda: sim.d.flexvert_xpos[a:a + n].copy()
    v0 = V()
    width = lambda P: float(np.ptp(np.array([arm.to_base(p) for p in P])[:, 1]))
    w0 = width(v0)
    _grab(sim, arm, arm.to_base(v0.mean(0)), 0.012)
    assert width(V()) < 0.8 * w0, "a full grip squeezes it"
    assert V()[:, 2].min() - v0[:, 2].min() > 0.1, "and lifts it"
    c = arm.to_base(v0.mean(0))
    _go(sim, arm.move_l([c[0], c[1], 0.014, np.pi, 0, 0], 0.08))     # set it down, then let go
    arm.gripper_move(0)
    _step(sim, 2.0)
    _go(sim, arm.move_l([c[0], c[1], 0.17, np.pi, 0, 0], 0.2))
    _step(sim, 1.0)
    size = lambda P: np.sort(np.ptp(P, 0))
    assert np.abs(size(V()) - size(v0)).max() < 0.005, "it springs back when let go"


@pytest.mark.parametrize("item", ["fuel_hose", "cloth", "sponge"])
def test_soft_items_keep_their_height_across_edits(item):
    """Every edit rebuilds the lab and lays soft objects out again where they lie: they mustn't
    sink (each rebuild once put them a flex radius lower: a hose 2 cm into the table)."""
    sim = PlaygroundSim(stations=[])
    st = sim.station(sim.add_station("franka", (0, 0), 0.0, "table"))
    uid = sim.add(item, (0.05, 0.0, st.top + 0.03))
    _step(sim, 1.5)
    f = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_FLEX, f"obj_{uid}")
    low = lambda: float(sim.d.flexvert_xpos[sim.m.flex_vertadr[f]:sim.m.flex_vertadr[f] + sim.m.flex_vertnum[f], 2].min())
    z0 = low()
    for _ in range(3):
        sim.rebuild()
        mujoco.mj_forward(sim.m, sim.d)
    assert abs(low() - z0) < 0.001
