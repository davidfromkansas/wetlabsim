"""A robot added on its own, with no table (station kind "bare"): it stands on whatever it is
dropped on (the floor, another station's table, furniture), a table arm on the floor gets a
steel stand at table height, and it moves anywhere without snapping back to a table."""
import mujoco
import pytest

from playground import site
from playground import world as W
from playground.sim import PlaygroundSim, RobotError


def _settle(sim, n=200):
    for _ in range(n):
        mujoco.mj_step(sim.m, sim.d)


def test_arm_on_the_floor_gets_a_stand():
    sim = PlaygroundSim(stations=[])
    spot = sim.robot_spot("franka", 1.0, 1.0)
    assert spot["valid"] and spot["ground"] == 0.0 and spot["surface"] == "the floor"
    uid = sim.add_station("franka", spot["pos"], 0.0, "bare", ground=spot["ground"])
    st = sim.station(uid)
    assert st.bare and st.table_item is None
    assert abs(st.mount_z - W.BARE_FLOOR_MOUNT) < 1e-9
    (_, _, _, lo, hi), = st.stands()
    assert lo == 0.0 and abs(hi - W.BARE_FLOOR_MOUNT) < 1e-9
    assert mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{W.table_uid(st)}") < 0   # no table
    _settle(sim)
    text = site._site_sheet(st)
    assert "table" not in text.lower() and "steel stand 75.0 cm tall on the floor" in text


def test_arm_on_another_stations_table():
    sim = PlaygroundSim(stations=[])
    t = sim.add_station("ur5e", (0, 0), 0.0, "table")
    tst = sim.station(t)
    x, y, _ = tst.to_world(0.4, 0.3)               # the far end of its table, clear of its UR5e
    spot = sim.robot_spot("franka", x, y)
    assert spot["valid"], spot["reason"]
    assert abs(spot["ground"] - tst.top) < 0.01
    uid = sim.add_station("franka", spot["pos"], 0.0, "bare", ground=spot["ground"])
    st = sim.station(uid)
    assert st.stands() == [] and abs(st.mount_z - tst.top) < 0.01
    _settle(sim)
    # on top of the other robot's base: no
    rx, ry, _ = tst.to_world(*tst.robot_xy)
    assert not sim.robot_spot("franka", rx, ry)["valid"]
    # half over the table's edge: no
    sx, _ = tst.footprint()
    ex, ey, _ = tst.to_world(sx / 2, 0.3)
    bad = sim.robot_spot("franka", ex, ey)
    assert not bad["valid"] and "edge" in bad["reason"]
    # moving that station carries the robot standing on its table along
    sim.move_station(t, (0.0, 2.0))
    assert abs(sim.station(uid).pos[1] - (spot["pos"][1] + 2.0)) < 1e-6


def test_humanoid_needs_the_floor():
    sim = PlaygroundSim(stations=[])
    t = sim.add_station("franka", (0, 0), 0.0, "table")
    x, y, _ = sim.station(t).to_world(0.3, 0.3)
    r = sim.robot_spot("g1", x, y)
    assert not r["valid"] and "floor" in r["reason"]
    assert sim.robot_spot("g1", 3.0, 0.0)["valid"]


def test_moving_it_far_never_snaps_back():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "bare")
    sim.place_robot(uid, x=4.0, y=-3.0)              # far from anything: stays there
    st = sim.station(uid)
    assert st.pos == (4.0, -3.0)
    sim.place_robot(uid, z=0.3)                       # lower its stand
    assert abs(sim.station(uid).mount_z - 0.3) < 1e-9
    t = sim.add_station("ur5e", (0, 0), 0.0, "table")
    x, y, _ = sim.station(t).to_world(0.4, 0.3)
    sim.place_robot(uid, x=x, y=y)                    # up onto that table: stands on it
    st = sim.station(uid)
    assert abs(st.ground - sim.station(t).top) < 0.01 and st.mount_z >= st.ground
    with pytest.raises(RobotError):
        rx, ry, _ = sim.station(t).to_world(*sim.station(t).robot_xy)
        sim.place_robot(uid, x=rx, y=ry)             # onto the UR5e's base


def test_saved_and_restored():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (1, 1), 0.0, "bare", ground=0.0)
    d = sim.station(uid).as_dict()
    assert d["kind"] == "bare" and d["ground"] == 0.0
    state = sim.scene_state()
    sim.remove_station(uid)
    assert not sim.placed                               # no table left behind
    sim.restore_scene(state)
    assert sim.station(uid).bare
