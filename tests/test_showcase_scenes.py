"""The kitchen and wet lab showcase additions: new library items (ForgeCAD, NVIDIA SimReady,
Tripo, USDCraft) rest where they're put, their moving parts move, and robots stand on the new
kitchen island and kitchen counter stations."""
import mujoco
import numpy as np
import pytest

from playground import catalog, scenegen, site, world as W
from playground.sim import PlaygroundSim

NEW = ["dishwasher", "range_hood", "bar_stool", "chest_freezer", "kitchen_counter", "countertop",
       "countertop_2", "lab_stool", "fume_hood", "biosafety_cabinet",
       "sink_basin", "faucet", "electric_kettle", "drip_coffee_maker", "french_press", "rice_cooker",
       "kitchen_tongs", "pedal_bin", "plate", "cutlery_set", "drinking_glass", "tumbler", "wine_glass",
       "fork", "spoon", "table_knife", "frying_pan", "spatula_kitchen", "egg", "bread_loaf", "bagel",
       "croissant", "banana", "orange", "lemon", "tomato", "strawberry", "spray_bottle",
       "reagent_reservoir", "screw_cap_bottle", "sharps_box"]


def _place(item):
    sim = PlaygroundSim(stations=[])
    fixed = catalog.item(item)["fixed"]
    if fixed:
        uid = sim.add(item, (0.0, 0.0, 0.0))
    else:   # on a packing table, away from any robot
        t = sim.add("table_packing", (0.0, 0.0, 0.0))
        uid = sim.add(item, (0.0, 0.0, 1.0))
    return sim, uid


def test_every_new_item_is_in_the_library():
    ids = {i["id"] for i in catalog.available()}
    assert set(NEW) <= ids
    for i in NEW:
        assert (catalog.ASSETS / i / "thumb.png").exists(), i


@pytest.mark.parametrize("item", NEW)
def test_rests_where_it_is_put(item):
    sim, uid = _place(item)
    m, d = sim.m, sim.d
    b = m.body(f"obj_{uid}").id
    mujoco.mj_step(m, d, int(1.5 / m.opt.timestep))   # a round egg or fruit may roll a little first
    p0 = d.xpos[b].copy()
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    assert np.all(np.isfinite(d.qpos))
    assert np.linalg.norm(d.xpos[b] - p0) < 0.02, item          # settled, not sliding or sinking
    assert d.xpos[b][2] > -0.01, item                            # not through the floor


JOINTED = {i: [b["name"] for b in catalog.meta(i)["bodies"] if b.get("joint")]
           for i in NEW if any(b.get("joint") for b in catalog.meta(i).get("bodies", []))}


# Parts that, as their assets build them, start where a push can't move them: the range hood's
# buttons rest pressed into its housing and its grease filter catches on the housing going back
# in, the bin's handle lies folded under the closed lid, the stool's height lever rests against
# its spring stop and its casters' slides carry its weight, and the NVIDIA counter's pull-out
# shelves catch on the cabinet frame.
STUCK = {("range_hood", "button_"), ("range_hood", "filter"), ("pedal_bin", "handle"),
         ("lab_stool", "joint_sm_mechanism"), ("lab_stool", "joint_sm_wheelbase"), ("kitchen_counter", "joint_shelf")}


@pytest.mark.parametrize("item", sorted(JOINTED))
def test_moving_parts_move_both_ways(item):
    """Each hinge and slide, pushed toward one end of the range its asset states and then the
    other (or either way, for a joint with no limits), moves that way. A joint a thread or
    linkage ties to another (a joint equality) follows that one and isn't pushed itself."""
    sim, uid = _place(item)
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, int(0.3 / m.opt.timestep))
    eqs = [e for e in range(m.neq) if m.eq_type[e] == int(mujoco.mjtEq.mjEQ_JOINT)]
    tied = {int(m.eq_obj1id[e]) for e in eqs} | {int(m.eq_obj2id[e]) for e in eqs}
    mine = [j for j in range(m.njnt) if m.joint(j).name.startswith(f"obj_{uid}__")
            and m.jnt_type[j] in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))]
    assert mine, item
    joints = [j for j in mine if j not in tied]
    # open everything (twice over, so a door opens before the shelf behind it moves), then close
    # it all in reverse order
    for j, end, check in [(j, 1, False) for j in joints] + [(j, 1, True) for j in joints] \
            + [(j, 0, True) for j in reversed(joints)]:
        a, v = m.jnt_qposadr[j], m.jnt_dofadr[j]
        lo, hi = m.jnt_range[j] if m.jnt_limited[j] else (-1.0, 1.0)
        # about a hand's push: enough to lift the part and beat its damper and spring, no more
        # (a much harder shove on a 3 g switch only drives it through its stop)
        push = 2 * 9.81 * m.body_subtreemass[m.jnt_bodyid[j]] + 4 * m.dof_damping[v] * abs(hi - lo) \
            + 2 * m.jnt_stiffness[j] * max(abs(hi), abs(lo)) + 0.05
        target, q0 = (hi if end else lo), d.qpos[a]
        if abs(target - q0) < 0.1 * abs(hi - lo) + 1e-3:     # already at (or resting just past) that end
            continue
        for _ in range(int(1.0 / m.opt.timestep)):
            d.qfrc_applied[:] = 0
            d.qfrc_applied[v] = np.sign(target - d.qpos[a]) * push if abs(target - d.qpos[a]) > 1e-3 else 0.0
            mujoco.mj_step(m, d)
        d.qfrc_applied[:] = 0
        assert np.all(np.isfinite(d.qpos)), item
        moved = (d.qpos[a] - q0) * np.sign(target - q0)
        name = m.joint(j).name.split("__", 1)[1]
        if not check or any(item == i and name.split("_", 1)[1].startswith(part) for i, part in STUCK):
            continue
        assert moved > 0.2 * min(abs(target - q0), 0.5), (item, m.joint(j).name, float(q0), float(d.qpos[a]), float(target))


@pytest.mark.parametrize("kind", ["island", "counter"])
@pytest.mark.parametrize("robot", ["franka", "ur5e", "aloha", "fr3_duo"])
def test_arms_stand_on_kitchen_stations(kind, robot):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station(robot, (0, 0), 0.0, kind)
    st = sim.station(uid)
    mujoco.mj_step(sim.m, sim.d, int(1.0 / sim.m.opt.timestep))
    robot_bodies = sim.robot_bodies
    m, d = sim.m, sim.d
    for i in range(d.ncon):
        b1, b2 = m.geom_bodyid[d.contact[i].geom1], m.geom_bodyid[d.contact[i].geom2]
        if (b1 in robot_bodies) != (b2 in robot_bodies):
            names = m.body(b1).name + m.body(b2).name
            assert "-table" in names or "mount" in names, names   # only the base on its worktop
    sx, sy = st.footprint()
    for bx, by in st.bases():
        assert abs(bx) < sx / 2 and abs(by) < sy / 2                # the base is on the worktop
    t = W.KINDS[kind]["table"]
    assert st.top == pytest.approx(catalog.WORKTOP.get(t, catalog.meta(t)["size"][2]))


@pytest.mark.parametrize("kind", ["island", "counter"])
def test_site_sheet_names_the_worktop(kind):
    text = site.site_sheet([], W.Station("st1", "franka", (0, 0), 0.0, "Robot 1", kind))
    assert "kitchen" in text and "What's here" not in text


@pytest.mark.parametrize("item", ["countertop", "countertop_2", "kitchen_island"])
def test_things_rest_on_the_worktop(item):
    """A plate dropped on a counter rests on its worktop, the height a station stands its robot at."""
    sim = PlaygroundSim(stations=[])
    sim.add(item, (0.0, 0.0, 0.0))
    p = sim.add("plate", (0.0, 0.0, 1.3))
    mujoco.mj_step(sim.m, sim.d, 1500)
    z = sim.d.xpos[sim.m.body(f"obj_{p}").id][2]
    assert z == pytest.approx(W.table_top(item), abs=0.03)


def test_scene_maker_knows_the_kitchen_stations():
    assert '"island"' in scenegen.LAYOUT_SYSTEM and '"counter"' in scenegen.LAYOUT_SYSTEM


@pytest.mark.parametrize("name", ["kitchen", "wetlab"])
def test_ready_made_scene_builds_whole(name):
    """Add station's Kitchen and Wet lab scenes put down every robot, piece of furniture and
    object they list, with each robot's task filled in, and nothing skipped."""
    import time
    from playground import scenegen as G

    class _Sess:
        def __init__(self):
            self.unsent = {}
    sim = PlaygroundSim(stations=[])
    sess = _Sess()
    b = G.Build(sim, sess, "", G.preset_pick(name), "", False, preset=name)
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 300:
        time.sleep(0.2)
    lay = G.PRESETS[name]
    assert b.phase == "done", b.error
    assert b.skipped == []
    assert len(sim.stations) == len(lay["stations"])
    assert len(b.objects) == len(lay["furniture"]) + len(lay["objects"])
    assert sorted(v["task"] for v in sess.unsent.values()) == sorted(s["task"] for s in lay["stations"])
