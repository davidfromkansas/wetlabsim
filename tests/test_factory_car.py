"""The factory and car assembly scenes: the two floor-standing arms with vacuum tools (Comau
N-220, FANUC CRX-30iA), the new factory, car and garage library items, and the two ready-made
scenes in Add station."""
import time

import mujoco
import numpy as np
import pytest

from playground import catalog, scenegen as G, site, world as W
from playground.sim import PlaygroundSim
from test_wetrobo import _go, _step
from wetlabsim import scene as S

DOWN = [0.0, 3.14159, 0.0]      # the vacuum tool's cups facing straight down (rotation vector)


def _at_pallet(robot):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station(robot, (0.0, 0.0), 0.0, "pallet", starter=False)
    return sim, uid


@pytest.mark.parametrize("robot", ["n220", "crx30ia"])
def test_big_arm_stands_on_the_floor_and_holds_still(robot):
    sim, uid = _at_pallet(robot)
    a, st = sim.arms[uid], sim.station(uid)
    assert st.floor_arm and st.open
    base = sim.d.xpos[a.base_body]
    assert abs(base[2]) < 0.01                                  # on the floor, not on the pallet
    q0 = sim.d.qpos[a.arm_qadr].copy()
    _step(sim, 2.0)
    assert np.abs(sim.d.qpos[a.arm_qadr] - q0).max() < 0.01     # holds its ready pose under its own weight
    assert a.suction and a.gripper_status()["object_detected"] is False
    sheet = site.site_sheet(sim.placed, st, sim.stations)
    assert "vacuum" in sheet.lower() and "pallet" in sheet.lower()
    sim.stop_threads()


def test_vacuum_tools_hold_what_their_cups_are_rated_for():
    # every cup at 60 kPa: six 150 mm cups on the Comau, four 80 mm cups on the FANUC
    assert S.vacuum_force("n220") == pytest.approx(6 * np.pi * 0.075 ** 2 * 60e3)
    assert S.vacuum_force("crx30ia") == pytest.approx(4 * np.pi * 0.04 ** 2 * 60e3)


@pytest.mark.parametrize("item", ["cardboard_box", "cardboard_box_flat"])
def test_crx_lifts_by_vacuum_and_lets_go(item):
    sim, uid = _at_pallet("crx30ia")
    st = sim.station(uid)
    x, y, _ = st.to_world(0.1, 0.0)
    obj = sim.add(item, sim.support(item, x, y, 0.0)["pos"], 0.0)
    a, m, d = sim.arms[uid], sim.m, sim.d
    _step(sim, 1.0)
    b = m.body(f"obj_{obj}").id
    z0 = float(d.xpos[b][2])
    bp, _ = a.base_tf()
    top = z0 + catalog.meta(item)["size"][2] - bp[2]
    bx, by = x - bp[0], y - bp[1]
    _go(sim, a.move_j_ik([bx, by, top + 0.15, *DOWN]))
    _go(sim, a.move_l([bx, by, top - 0.005, *DOWN]))
    assert a.gripper_status()["object_detected"] is False       # the vacuum is off: nothing held
    a.gripper_move(255)
    _step(sim, 0.6)
    assert a.gripper_status()["object_detected"] is True
    _go(sim, a.move_l([bx, by, top + 0.3, *DOWN]))
    _step(sim, 1.0)
    up = float(d.xpos[b][2])
    assert up - z0 > 0.2                                        # it came up with the tool
    a.gripper_move(0)
    _step(sim, 1.5)
    assert d.xpos[b][2] - z0 < 0.05                             # vacuum off: it dropped back
    assert a.gripper_status()["object_detected"] is False
    sim.stop_threads()


NEW = [i[0] for i in catalog.ITEMS if i[1] in ("Factory", "Car parts", "Garage")]


def test_new_tabs_are_in_the_library():
    ids = {i["id"] for i in catalog.available()}
    assert len(NEW) >= 80 and set(NEW) <= ids
    for i in NEW:
        assert (catalog.ASSETS / i / "thumb.png").exists(), i


def test_roller_conveyor_carries_a_tote_on_its_rollers():
    sim = PlaygroundSim(stations=[])
    sim.add("roller_conveyor", (0.0, 0.0, 0.0))
    spot = sim.support("lid_tote", 0.0, 0.0, 0.0)
    assert spot["surface"] == "Roller conveyor"
    uid = sim.add("lid_tote", spot["pos"], 0.0)
    b = sim.m.body(f"obj_{uid}").id
    mujoco.mj_step(sim.m, sim.d, 2000)
    z = float(sim.d.xpos[b][2])
    assert abs(z - catalog.WORKTOP["roller_conveyor"]) < 0.02     # on the rollers, between the rails
    sim.stop_threads()


def test_pallet_jack_linkage_loads():
    sim = PlaygroundSim(stations=[])
    sim.add("pallet_jack", (0.0, 0.0, 0.0))
    mujoco.mj_step(sim.m, sim.d, 1000)
    assert np.all(np.isfinite(sim.d.qpos))
    sim.stop_threads()


@pytest.mark.parametrize("name", ["factory", "car"])
def test_ready_made_scene_builds_whole(name):
    """Add station's Factory and Car assembly scenes put down every robot, piece of furniture and
    object they list, each robot with its task; resting things go to sleep (MuJoCo's sleep flag),
    so the scene steps quickly, and nothing has fallen or flown off."""

    class _Sess:
        def __init__(self):
            self.unsent = {}
    sim = PlaygroundSim(stations=[])
    sess = _Sess()
    b = G.Build(sim, sess, "", G.preset_pick(name), "", False, preset=name)
    b._run()
    lay = G.PRESETS[name]
    assert b.phase == "done", b.error
    assert b.skipped == []
    assert len(sim.stations) == len(lay["stations"]) == 8
    assert len(b.objects) == len(lay["furniture"]) + len(lay["objects"])
    assert sorted(v["task"] for v in sess.unsent.values()) == sorted(s["task"] for s in lay["stations"])
    m, d = sim.m, sim.d
    assert m.opt.enableflags & int(mujoco.mjtEnableBit.mjENBL_SLEEP)
    assert sim.settings["flag"]["sleep"] is True
    mujoco.mj_step(m, d, 3000)
    assert np.all(np.isfinite(d.qpos))
    loose = [i for i in range(m.nbody) if m.body(i).name.startswith("obj_")]
    assert d.xpos[loose][:, 2].min() > -0.05                    # nothing through the floor
    assert np.abs(d.xpos[loose][:, :2]).max() < 9.0             # nothing flew off
    asleep = int((np.asarray(d.tree_asleep) >= 0).sum())
    assert asleep > m.ntree // 2                                # the untouched parts are asleep
    t = time.perf_counter()
    mujoco.mj_step(m, d, 500)
    assert (time.perf_counter() - t) < 5.0                      # 0.5 s of physics, well under 5 s
    sim.stop_threads()


def test_wheeled_humanoid_drives_out_of_its_cell():
    """The RB-Y1's cell has no work-box walls: it backs over 1.5 m away from its table, far past where
    a table arm's walls would stand."""
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("rby1", (0.0, 0.0), 0.0, "table", starter=False)
    st, r = sim.station(uid), sim.arms[uid]
    assert st.open
    assert not any(sim.m.geom(g).name.startswith(f"{st.prefix}wall") for g in range(sim.m.ngeom))
    _step(sim, 0.5)
    x0 = float(sim.d.xpos[r.base_body][0])
    for _ in range(4):
        _go(sim, r.drive(-0.5, 0, 1.2))
    assert sim.d.xpos[r.base_body][0] - x0 < -1.5
    assert abs(sim.d.xpos[r.base_body][2]) < 0.2                 # still upright on its wheels
    sim.stop_threads()
