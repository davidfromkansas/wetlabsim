"""Library items with moving parts (tools/convert_simready.convert_articulated, world._add_jointed):
their hinges and slides move, caps stay on by a weld, and edits of the lab keep every part where
it is."""
import mujoco
import numpy as np

from playground import world as W
from playground.sim import PlaygroundSim


def _lab(item, fixed=False, away=None):
    sim = PlaygroundSim(stations=[])
    st = sim.station(sim.add_station("franka", (0, 0), 0.0, "table"))
    x, y, _ = st.to_world(st.robot_xy[0] + (away or (1.6 if fixed else 0.5)), st.robot_xy[1])
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


def test_screw_top_jar_lid_unscrews_on_its_thread():
    """ForgeCAD's jar: the lid turns up to 540 degrees and rises 6.35 mm as it turns (its unscrew
    clip), stays seated under its own weight, and the jar keeps the mass and centre it states."""
    sim, uid = _lab("screw_top_jar")
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, int(0.5 / m.opt.timestep))
    lift, turn = _joint(sim, uid, "lid_lift"), _joint(sim, uid, "lid_turn")
    q = lambda j: d.qpos[m.jnt_qposadr[j]]
    assert abs(q(lift)) < 1e-4 and abs(q(turn)) < 0.01         # seated
    assert abs(m.body_subtreemass[m.body(f"obj_{uid}").id] - 0.2306) < 1e-3
    _push(sim, turn, 0.02, 2.0)
    assert np.degrees(q(turn)) > 500
    assert abs(q(lift) - 0.00635 * q(turn) / np.radians(540)) < 3e-4


def _drive_to(sim, j, target, sec=3.0):
    """Move one joint toward a target as a hand would (a PD force on that joint only); the closest
    it got."""
    m, d = sim.m, sim.d
    a, v, b = m.jnt_qposadr[j], m.jnt_dofadr[j], m.jnt_bodyid[j]
    M = max(m.body_subtreemass[b], 0.01)
    lever = 1.0 if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_SLIDE else max(0.05, np.linalg.norm(d.xipos[b] - d.xanchor[j]))
    kp, kd, span = 400 * M * lever ** 2, 40 * M * lever ** 2, m.jnt_range[j][1] - m.jnt_range[j][0]
    best = d.qpos[a]
    for _ in range(int(sec / m.opt.timestep)):
        d.qfrc_applied[:] = 0
        d.qfrc_applied[v] = kp * np.clip(target - d.qpos[a], -0.2 * span, 0.2 * span) - kd * d.qvel[v] + d.qfrc_bias[v]
        mujoco.mj_step(m, d)
        best = d.qpos[a] if abs(d.qpos[a] - target) < abs(best - target) else best
    d.qfrc_applied[:] = 0
    return best


def test_forgecad_primitive_colliders_and_full_door_travel():
    """ForgeCAD's fridge collides as the boxes, cylinders and capsules its asset states (MuJoCo's
    own shapes), and each door and drawer travels its whole stated range."""
    sim, uid = _lab("french_door_fridge", fixed=True, away=2.6)      # clear of the robot's table
    m = sim.m
    shapes = {int(m.geom_type[g]) for g in range(m.ngeom) if m.geom(g).name.startswith(f"obj_{uid}") and m.geom_group[g] == 3}
    assert {int(mujoco.mjtGeom.mjGEOM_BOX), int(mujoco.mjtGeom.mjGEOM_CYLINDER), int(mujoco.mjtGeom.mjGEOM_CAPSULE)} <= shapes
    for part in ("door_1", "door_2", "freezer", "crisper_1"):
        j = _joint(sim, uid, part)
        lo, hi = m.jnt_range[j]
        assert _drive_to(sim, j, hi) > hi - 0.02 * (hi - lo), part


def test_static_frame_holds_loose_shelves():
    """The gondola's frame has no rigid body in its asset (USD Physics: static); it is the item's
    main part, and its six lift-out shelves rest on their brackets."""
    sim, uid = _lab("gondola_shelf", fixed=True, away=2.6)
    m, d = sim.m, sim.d
    shelves = W.part_bodies(m, uid)[:6]
    mujoco.mj_step(m, d, int(2.0 / m.opt.timestep))
    p = d.xipos[shelves].copy()
    mujoco.mj_step(m, d, int(2.0 / m.opt.timestep))
    assert np.abs(d.xipos[shelves] - p).max() < 1e-3
    assert d.xipos[shelves][:, 2].min() > 0.3              # on their brackets, not on the floor


def test_new_appliances_open_through_their_full_range():
    """Doors, drawers, baskets and lids of the Nov 13 kitchen and lab items reach both ends of the
    range their assets state."""
    for item, parts in (("microwave", ["door"]), ("air_fryer", ["basket"]), ("plate_reader", ["DrawerTravel"]),
                        ("lab_incubator", ["DoorOpen"]), ("toaster_tray", ["tray_slide"]),
                        ("espresso_machine", ["steam_wand_pivot"])):
        sim, uid = _lab(item)
        m, d = sim.m, sim.d
        mujoco.mj_step(m, d, int(0.5 / m.opt.timestep))
        snap = d.qpos.copy()
        for part in parts:
            j = _joint(sim, uid, part)
            lo, hi = m.jnt_range[j]
            for end in (hi, lo):
                d.qpos[:], d.qvel[:] = snap, 0
                assert abs(_drive_to(sim, j, end) - end) < 0.03 * (hi - lo), (item, part, end)
