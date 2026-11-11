"""Library items with moving parts (tools/convert_simready.convert_articulated, world._add_jointed):
their hinges and slides move, caps stay on by a weld, and edits of the lab keep every part where
it is."""
import mujoco
import numpy as np

from playground import world as W
from playground.sim import PlaygroundSim


def _lab(item, fixed=False):
    sim = PlaygroundSim(stations=[])
    st = sim.station(sim.add_station("franka", (0, 0), 0.0, "table"))
    x, y, _ = st.to_world(st.robot_xy[0] + (1.6 if fixed else 0.5), st.robot_xy[1])
    uid = sim.add(item, (x, y, 0.0 if fixed else st.top + 0.002))
    return sim, uid


def _joint(sim, uid, part):
    m = sim.m
    return next(j for j in range(m.njnt) if m.joint(j).name.startswith(f"obj_{uid}__") and m.joint(j).name.endswith(part))


def _push(sim, j, f, sec=0.5):
    m, d = sim.m, sim.d
    d.qfrc_applied[:] = 0
    d.qfrc_applied[m.jnt_dofadr[j]] = f
    mujoco.mj_step(m, d, int(sec / m.opt.timestep))
    d.qfrc_applied[:] = 0


def test_a_lid_opens_within_its_limits():
    sim, uid = _lab("microcentrifuge")
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    j = _joint(sim, uid, "lid")
    assert m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE and m.jnt_limited[j]
    _push(sim, j, 5.0, 2.0)
    q = d.qpos[m.jnt_qposadr[j]]
    assert 0.3 < q <= m.jnt_range[j][1] + 0.02


def test_a_fixed_cabinets_drawers_slide_out():
    """Furniture stands fixed; its drawers (whose parts the asset says don't collide) still slide."""
    sim, uid = _lab("lab_fridge", fixed=True)
    m, d = sim.m, sim.d
    j = _joint(sim, uid, "crisper_fresh_slide")
    _push(sim, j, 40.0, 1.0)
    assert d.qpos[m.jnt_qposadr[j]] > 0.05


def test_caps_are_welded_and_labels_fixed():
    sim, uid = _lab("syringe")
    m = sim.m
    welds = [m.eq(i).name for i in range(m.neq) if m.eq(i).name.startswith(f"obj_{uid}__")]
    assert len(welds) == 1, welds                      # the cap; decals, hub and needle are fixed on
    j = _joint(sim, uid, "plunger_01_joint_00")
    assert m.jnt_type[j] == mujoco.mjtJoint.mjJNT_SLIDE


def test_edits_keep_moving_parts_where_they_are():
    sim, uid = _lab("microcentrifuge")
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    d.qpos[m.jnt_qposadr[_joint(sim, uid, "lid")]] = 0.8
    mujoco.mj_forward(m, d)
    before = {m.body(b).name: d.xpos[b].copy() for b in [m.body(f"obj_{uid}").id, *W.part_bodies(m, uid)]}
    sim.rebuild()
    mujoco.mj_forward(sim.m, sim.d)
    for name, p in before.items():
        assert np.linalg.norm(sim.d.xpos[sim.m.body(name).id] - p) < 1e-4, name


def test_moving_an_item_takes_its_cap_along():
    sim, uid = _lab("glass_jar")
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    lid = W.part_bodies(m, uid)[0]
    rel = d.xpos[lid] - d.xpos[m.body(f"obj_{uid}").id]
    p = sim.find(uid)
    sim.move(uid, (p.pos[0] + 0.1, p.pos[1], p.pos[2]))
    mujoco.mj_step(sim.m, sim.d, int(0.5 / sim.m.opt.timestep))
    m, d = sim.m, sim.d
    assert np.linalg.norm(d.xpos[lid] - d.xpos[m.body(f"obj_{uid}").id] - rel) < 0.003


def test_autobio_tubes_keep_their_caps_on():
    """AutoBio's tubes (tools/build_autobio.py): the screw cap is a separate part, welded on."""
    sim, uid = _lab("tube_15ml")
    m, d = sim.m, sim.d
    cap = W.part_bodies(m, uid)[0]
    assert any(m.eq(i).name.startswith(f"obj_{uid}__") for i in range(m.neq))
    g = next(i for i in range(m.ngeom) if m.geom_bodyid[i] == cap)
    b = m.body(f"obj_{uid}").id
    rel = d.xmat[b].reshape(3, 3).T @ (d.geom_xpos[g] - d.xpos[b])     # the cap, in the tube's frame
    d.qvel[m.jnt_dofadr[m.body_jntadr[b]] + 3] = 8.0         # knock it over
    mujoco.mj_step(m, d, int(3.0 / m.opt.timestep))
    assert d.xmat[b].reshape(3, 3)[2, 2] < 0.5
    now = d.xmat[b].reshape(3, 3).T @ (d.geom_xpos[g] - d.xpos[b])
    assert np.linalg.norm(now - rel) < 0.002


def test_springs_dampers_and_spinning_parts_follow_their_assets():
    """Drives become MuJoCo springs and dampers: a gauge's button springs back; a drill's chuck
    (a hinge with no limits, damped) turns when pushed and comes to rest, not spinning by itself."""
    sim, uid = _lab("pressure_gauge")
    m, d = sim.m, sim.d
    j = _joint(sim, uid, "button_03_joint_00")
    assert m.jnt_stiffness[j] > 0
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    q0 = d.qpos[m.jnt_qposadr[j]]
    _push(sim, j, -0.5)
    assert d.qpos[m.jnt_qposadr[j]] < q0 - 0.005
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    assert abs(d.qpos[m.jnt_qposadr[j]] - q0) < 0.001

    sim, uid = _lab("drill")
    m, d = sim.m, sim.d
    j = _joint(sim, uid, "chuck_01_joint_00")
    assert not m.jnt_limited[j] and m.dof_damping[m.jnt_dofadr[j]] > 0
    mujoco.mj_step(m, d, int(2.0 / m.opt.timestep))
    q0 = d.qpos[m.jnt_qposadr[j]]
    mujoco.mj_step(m, d, int(2.0 / m.opt.timestep))
    assert abs(d.qpos[m.jnt_qposadr[j]] - q0) < 0.01            # still on its own
    _push(sim, j, 0.01)
    q1 = d.qpos[m.jnt_qposadr[j]]
    assert q1 - q0 > 0.3
    mujoco.mj_step(m, d, int(2.0 / m.opt.timestep))
    assert abs(d.qvel[m.jnt_dofadr[j]]) < 0.05


def test_a_drawer_slides_out_of_its_cabinet():
    """A drawer on a runner slides inside the cabinet's body without catching on it."""
    sim, uid = _lab("drug_cabinet", fixed=True)
    m, d = sim.m, sim.d
    j = _joint(sim, uid, "drawer_02_joint_00")
    _push(sim, j, 30.0, 0.5)
    assert d.qpos[m.jnt_qposadr[j]] > 0.4


def test_a_fridge_door_closes_itself_near_shut_and_stays_open_wide():
    """Tripo's door-closer tendons (MuJoCo tendons with a spring deadband): a door let go a little
    open swings shut; opened wide it stays."""
    for start, shut in ((0.3, True), (1.2, False)):
        sim, uid = _lab("lab_fridge", fixed=True)
        m, d = sim.m, sim.d
        j = _joint(sim, uid, "door_fresh_hinge")
        d.qpos[m.jnt_qposadr[j]] = start
        mujoco.mj_step(m, d, int(3.0 / m.opt.timestep))
        q = d.qpos[m.jnt_qposadr[j]]
        assert (q < 0.02) if shut else (q > 1.1), (start, q)
