"""The Nov 12 lab additions (glassware, racks, plates, AutoBio extras, in-house builds): each loads
and comes to rest on a table, the robot can hold them, tubes go into racks, a stirring rod
stands in a beaker, and 24-well plates stack with their lids."""
import mujoco
import numpy as np
import pytest

from playground import catalog
from playground import world as W

from test_playground_grip import _grab, _lab, _step

NEW = [i for i, *_ in catalog.ITEMS[catalog.ITEMS.index(next(x for x in catalog.ITEMS if x[0] == "beaker_500")):]]


def _settle(placed, sec=2.0):
    m = W.build(placed, [])
    d = mujoco.MjData(m)
    for _ in range(int(sec / m.opt.timestep)):
        mujoco.mj_step(m, d)
    return m, d


def _bodies(m, uid):
    return [b for b in range(m.nbody) if m.body(b).name == f"obj_{uid}" or m.body(b).name.startswith(f"obj_{uid}__")]


def test_every_new_item_has_a_source_chip():
    names = {it["id"]: it["source"] for it in catalog.available()}
    assert len(NEW) >= 45
    for i in NEW:
        assert i in names, f"{i} not built"
        assert names[i] in catalog.SOURCE_NAMES.values()


@pytest.mark.parametrize("item", NEW)
def test_new_item_rests_on_the_floor(item):
    """Dropped from 2 cm: no part falls through, nothing blows up."""
    m, d = _settle([W.Placed("a", item, (0, 0, 0.02))], 3.0)
    assert np.isfinite(d.qpos).all()
    for b in _bodies(m, "a"):
        assert d.xpos[b][2] > -0.08, f"{m.body(b).name} fell through"
    root = m.body("obj_a").id
    assert np.linalg.norm(d.xpos[root][:2]) < 0.3


@pytest.mark.parametrize("item,yaw", [("beaker_50", 0.0), ("tube_10ml", 0.0), ("cryovial", 0.0),
                                      ("measuring_cylinder", 0.0), ("beaker_100_tall", 0.0),
                                      ("reagent_bottle", 0.0)])
def test_franka_holds_new_items_for_a_minute(item, yaw):
    sim, arm = _lab("franka", item, yaw)
    _step(sim, 1.5)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    h = catalog.meta(item)["size"][2]
    _grab(sim, arm, arm.to_base(p0), max(h - 0.03, 0.006) if h > 0.03 else h * 0.4)
    tcp = lambda: sim.d.site_xpos[arm.tcp_site].copy()
    r0 = sim.d.xpos[b] - tcp()
    _step(sim, 60.0)
    r1 = sim.d.xpos[b] - tcp()
    assert sim.d.xpos[b][2] - p0[2] > 0.1, "dropped"
    assert np.linalg.norm(r1 - r0) < 0.005


@pytest.mark.parametrize("rack,tube", [("rack_compact_blue", "test_tube_small"), ("rack_wire", "test_tube"),
                                       ("rack_two_tier", "test_tube"), ("tip_box", "pipette_tip"),
                                       ("rack_compact_pink", "cryovial")])
def test_tube_goes_into_a_rack(rack, tube):
    """Dropped over one of the rack's holes, a tube ends up standing in it, below the rack's top."""
    rs = catalog.meta(rack)["size"]
    found = False
    for x in np.linspace(-rs[0] / 2 + 0.008, rs[0] / 2 - 0.008, 25):
        for y in np.linspace(-rs[1] / 2 + 0.008, rs[1] / 2 - 0.008, 7):
            m, d = _settle([W.Placed("r", rack, (0, 0, 0)), W.Placed("t", tube, (x, y, rs[2] + 0.004))], 1.5)
            t = m.body("obj_t").id
            # standing (its own up axis near vertical) and sunk into the rack
            up = abs(d.xmat[t].reshape(3, 3)[2, 2])
            if up > 0.9 and min(d.xpos[b][2] for b in _bodies(m, "t")) < rs[2] - 0.01:
                found = True
                break
        if found:
            break
    assert found, f"no hole in {rack} took the {tube}"


def test_stirring_rod_leans_in_a_beaker():
    """A rod let go upright in a beaker ends leaning against its rim, still inside."""
    tilt = np.array([np.cos(np.pi / 4), 0, np.sin(np.pi / 4), 0])    # rod (along x) turned upright
    m, d = _settle([W.Placed("b", "beaker_500", (0, 0, 0)),
                    W.Placed("r", "stirring_rod", (0.012, 0, 0.112), 0.0, quat=tuple(tilt))], 3.0)
    r = m.body("obj_r").id
    assert abs(d.xpos[r][0]) < 0.06 and abs(d.xpos[r][1]) < 0.06, "it fell out"
    assert d.xpos[r][2] > 0.03


def test_24well_plates_stack_and_the_lid_stays():
    """Plate, lid, plate: lifting the top plate leaves the lid on the plate below."""
    H = catalog.meta("plate_24well")["size"][2]
    L = catalog.meta("plate_24well_lid")["size"][2]
    P = [W.Placed("p1", "plate_24well", (0, 0, 0)),
         W.Placed("l1", "plate_24well_lid", (0, 0, H - (L - 0.001) + 0.001)),    # its inside top on the deck
         W.Placed("p2", "plate_24well", (0, 0, H + 0.001 + 0.003))]
    m = W.build(P, [])
    d = mujoco.MjData(m)
    for _ in range(int(2.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    lid, top = m.body("obj_l1").id, m.body("obj_p2").id
    z_lid = d.xpos[lid][2]
    assert z_lid > H - L - 0.001, "the lid sits on the plate"
    assert d.xpos[top][2] > z_lid, "and the second plate on the lid"
    for _ in range(int(1.0 / m.opt.timestep)):
        d.xfrc_applied[top] = [0, 0, 1.0, 0, 0, 0]       # lift the top plate (32 g)
        mujoco.mj_step(m, d)
    assert d.xpos[top][2] > z_lid + 0.05
    assert abs(d.xpos[lid][2] - z_lid) < 0.002, "the lid stayed"


@pytest.mark.parametrize("item", ["tube_10ml", "cryovial", "beaker_50"])
def test_aloha_holds_new_items_for_a_minute(item):
    from test_aloha import _lab as _aloha_lab
    from test_playground_grip import _go
    sim, pair = _aloha_lab(item)
    L = pair.sides["left"]
    _step(sim, 1.5)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    pb = L.to_base(p0)
    z = pb[2] + max(catalog.meta(item)["size"][2] - 0.03, 0.01)
    pose = lambda zz: [pb[0], pb[1], zz, 0, np.pi / 2, 0]
    L.gripper_move(0)
    _go(sim, L.move_l(pose(z + 0.12), 0.2))
    _go(sim, L.move_l(pose(z), 0.08))
    L.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    _go(sim, L.move_l(pose(z + 0.15), 0.15))
    tcp = lambda: sim.d.site_xpos[L.tcp_site].copy()
    r0 = sim.d.xpos[b] - tcp()
    _step(sim, 60.0)
    assert sim.d.xpos[b][2] - p0[2] > 0.1, "dropped"
    # ALOHA's small grippers let a slim tube creep a few mm over a minute (still held)
    assert np.linalg.norm(sim.d.xpos[b] - tcp() - r0) < 0.01
