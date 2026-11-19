"""Run task N times side by side (playground/sim.py copy_station): exact copies of a station,
each in free floor space, never overlapping another station, furniture or a loose object."""
import mujoco
import numpy as np

from playground import libero as LB
from playground import world as W
from playground.sim import PlaygroundSim, SOFT_MAX


def _lab():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    st = sim.station(uid)
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1])
    sim.placed.append(W.Placed("t1", "tube_15ml", (x, y, st.top + 0.01), 0.0))
    sim.rebuild()
    for _ in range(100):
        mujoco.mj_step(sim.m, sim.d)
    return sim, uid


def _overlap(a, b):
    sx, sy = a.footprint()
    pts = [a.to_world(fx * sx / 2, fy * sy / 2) for fx in (-1, 0, 1) for fy in (-1, 0, 1)]
    return any(b.holds(px, py) for px, py, _ in pts) or a.holds(*b.pos)


def test_copies_are_exact_and_apart():
    sim, uid = _lab()
    other = sim.add_station("ur5e", (2.2, 0), 0.0, "table")      # a neighbour right beside it
    st = sim.station(uid)
    rider = [p for p in sim._on_table(st)]
    arm = sim.arm_of(uid)
    sim.d.qpos[arm.arm_qadr] = arm.ready_q + 0.1                     # an arm not in its ready pose
    mujoco.mj_forward(sim.m, sim.d)
    q0 = sim.d.qpos[arm.arm_qadr].copy()
    made, why = sim.copy_station(uid, 3)
    assert len(made) == 3 and why == ""
    sts = sim.stations
    for i, a in enumerate(sts):
        for b in sts[i + 1:]:
            assert not _overlap(a, b) and not _overlap(b, a), (a.uid, b.uid)
    for u in made:
        c = sim.station(u)
        assert c.robot == "franka" and c.yaw == st.yaw and "copy" in c.name
        on = sim._on_table(c)
        assert sorted(p.item for p in on) == sorted(p.item for p in rider)
        assert np.allclose(sim.d.qpos[sim.arm_of(u).arm_qadr], q0, atol=1e-9)
        # the copy's tube sits where the original's does, relative to its own table
        for p in on:
            o = next(r for r in rider if r.item == p.item)
            assert np.allclose(c.to_local(*p.pos[:2]), st.to_local(*o.pos[:2]), atol=1e-3)
    assert sim.station(other) is not None                          # nothing removed
    sim.remove_stations(made)
    assert [s.uid for s in sim.stations] == [uid, other]
    assert len(sim._on_table(sim.station(uid))) == len(rider)


def test_copies_avoid_loose_floor_objects():
    sim, uid = _lab()
    st = sim.station(uid)
    sx, _ = st.footprint()
    # a box on the floor exactly where the first copy would go
    sim.placed.append(W.Placed("f1", "tube_15ml", (st.pos[0] + sx + 0.4, st.pos[1], 0.0), 0.0))
    sim.rebuild()
    made, _ = sim.copy_station(uid, 1)
    c = sim.station(made[0])
    assert not c.holds(st.pos[0] + sx + 0.4, st.pos[1], 0.1)


def test_soft_limit_caps_copies():
    sim, uid = _lab()
    st = sim.station(uid)
    from playground import catalog
    soft = next(row[0] for row in catalog.ITEMS if catalog.item(row[0])["soft"])
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1] + 0.25)
    sim.placed.append(W.Placed("s1", soft, (x, y, st.top + 0.01), 0.0))
    sim.rebuild()
    made, why = sim.copy_station(uid, 3)
    assert len(made) == SOFT_MAX - 1 and "soft" in why


def test_no_work_box_walls():
    """Stations have no walls round them: robots' cameras see the whole scene, side-by-side
    copies included. LIBERO's own room walls (the same geom group) stay for the robot's cameras."""
    from playground import scene3d
    from wetlabsim.sim import _robot_view
    sim, uid = _lab()
    sim.copy_station(uid, 1)
    assert not [g for g in range(sim.m.ngeom) if sim.m.geom(g).name.split("/")[-1].startswith("wall")]
    assert _robot_view("overhead").geomgroup[W.WALL_GROUP] and not _robot_view("side").geomgroup[W.WALL_GROUP]
    assert W.WALL_GROUP not in scene3d.VISIBLE_GROUPS


def test_working_robot_outlined_by_its_bodies():
    """The 3D view outlines a working robot by its own bodies (the glow follows its shape)."""
    sim, uid = _lab()
    bodies = sorted(int(b) for b in sim.arms[uid].bodies)
    assert bodies and all(0 < b < sim.m.nbody for b in bodies)


def test_overhead_camera_over_its_table():
    """Every one-arm station's overhead camera hangs over its own table, below WALL_ABOVE."""
    kinds = dict(W.KINDS)          # plus tables no station uses yet: the pose is worked out
    for t in ("workbench", "instrument_trolley", "optical_table"):     # from any table's size
        kinds["try_" + t] = dict(W.KINDS["table"], table=t, robot_xy=(-0.2, 0.0))
    W.KINDS.update(kinds)
    try:
        _check_overhead(kinds)
    finally:
        for k in [k for k in W.KINDS if k.startswith("try_")]:
            del W.KINDS[k]


def _check_overhead(kinds):
    import math
    for kind in kinds:
        for yaw in (0.0, 1.0, math.pi):
            # a LIBERO station needs its task (its room and LIBERO's own cameras come with it)
            task = LB.tasks()[0].id if kind == "libero" else ""
            st = W.Station("st1", "franka", (1.0, -2.0), yaw, kind=kind, task=task)
            m = W.build([], [st])
            sx, sy = st.footprint()
            x, y, z = m.cam_pos[m.camera("st1/overhead").id]
            lx, ly = st.to_local(x, y)
            if kind == "libero":
                assert abs(lx) < sx / 2 and abs(ly) < sy / 2, (kind, yaw, lx, ly)
                continue
            assert abs(lx) < sx / 2 + 0.05 and abs(ly) < sy / 2 + 0.05, (kind, yaw, lx, ly, z)
            assert z < st.top + st.WALL_ABOVE + 0.01 or st.floor_arm, (kind, yaw, z)
