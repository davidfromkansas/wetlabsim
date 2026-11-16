"""Moving, turning and raising a station's robot on its own, apart from its table: the robot
stands fully on its table or fully off it, and a table arm that has nothing right under its
mount stands on a steel stand that reaches the floor (or the table top)."""
import math

import mujoco
import numpy as np
import pytest

from playground import site
from playground import world as W
from playground.sim import PlaygroundSim, RobotError


@pytest.fixture
def sim():
    s = PlaygroundSim()
    s.paused = True
    return s


def stand_box(s, uid="st1"):
    b = s.m.body(f"{uid}/stand0").id
    g = int(s.m.body_geomadr[b])
    return s.d.xpos[b].copy(), s.m.geom_size[g].copy()


def test_off_the_table_it_gets_a_stand_to_the_floor(sim):
    st = sim.station("st1")
    top = st.top
    sim.place_robot("st1", x=-1.15, y=0.0)
    p = sim.robot_place("st1")
    assert p["side"] == "off" and p["at"][2] == pytest.approx(top, abs=1e-3)   # same height as before
    pos, size = stand_box(sim)
    assert pos[2] - size[2] == pytest.approx(0.0, abs=1e-4)                    # on the floor
    assert pos[2] + size[2] == pytest.approx(top, abs=1e-4)                    # up to the mount
    # raise it: the stand grows with it
    sim.place_robot("st1", z=1.3)
    pos, size = stand_box(sim)
    assert 2 * size[2] == pytest.approx(1.3, abs=1e-4)
    # the arm holds on its stand while physics runs
    a = sim.arms["st1"]
    b0 = a.base_tf()[0].copy()
    for _ in range(500):
        mujoco.mj_step(sim.m, sim.d)
    assert np.linalg.norm(a.base_tf()[0] - b0) < 1e-6
    assert a.base_tf()[0][2] == pytest.approx(1.3, abs=1e-3)


def test_on_the_table_raised_it_gets_a_riser_and_never_straddles_the_edge(sim):
    st = sim.station("st1")
    sx, _ = st.footprint()
    sim.place_robot("st1", x=-0.5, z=st.top + 0.2)
    pos, size = stand_box(sim)
    assert pos[2] - size[2] == pytest.approx(st.top, abs=1e-4) and 2 * size[2] == pytest.approx(0.2, abs=1e-4)
    # right over the table's edge: it snaps fully on or fully off
    sim.place_robot("st1", x=-sx / 2, z=st.top)
    assert sim.robot_place("st1")["side"] in ("on", "off")
    # down onto the table top: no stand at all
    sim.place_robot("st1", x=-0.42, z=st.top)
    assert sim.robot_place("st1")["stand"] == 0.0
    with pytest.raises(KeyError):
        sim.m.body("st1/stand0")


def test_turn_and_back_to_its_spot(sim):
    st = sim.station("st1")
    sim.place_robot("st1", heading=math.radians(90))
    assert sim.robot_place("st1")["heading"] == pytest.approx(90.0)
    R = sim.arms["st1"].base_tf()[1]
    assert R[:, 0] == pytest.approx([0, 1, 0], abs=1e-6)        # it faces +y now
    x, y, _ = st.to_world(*st.home_xy)
    sim.place_robot("st1", x=x, y=y, z=st.home_z, heading=st.yaw)
    assert not st.moved


def test_limits(sim):
    with pytest.raises(RobotError):
        sim.place_robot("st1", x=-4.0)                          # too far from its table
    with pytest.raises(RobotError):
        sim.place_robot("st1", x=-1.2, z=3.0)                    # too high
    assert not sim.station("st1").moved                          # a refused move changes nothing


def test_floor_robot_moves_but_gets_no_stand(sim):
    st = W.Station("st9", "crx30ia", (0.0, 0.0), 0.0, "Big", "pallet", robot_at=(-1.0, 0.3), robot_z=1.0)
    assert st.standing and not st.liftable and st.stands() == [] and st.mount_z == 0.0


def test_site_sheet_follows_the_robot():
    st = W.Station("st1", "franka", (0.0, 0.0), 0.0, "Robot 1", robot_at=(-1.15, 0.0), robot_z=1.2)
    text = site.site_sheet([], st)
    assert "steel stand 120.0 cm tall on the floor" in text
    assert "The table top is the plane z = -0.21" in text and "The floor is the plane z = -1.20" in text
    st.robot_turn = math.radians(30)
    assert "corners at" in site.site_sheet([], st)
    # never names objects
    assert "What's here" not in text


def test_benchmark_robots_stay_put(sim):
    st = W.Station("st5", "franka", (4.0, 0.0), 0.0, "W", "wetrobo_y", task="lid")
    assert st.fixed_why()
    assert not W.Station("st6", "franka", (4.0, 0.0), 0.0, "W", "wetrobo_y", free=True).fixed_why()
    uid = sim.add_station("franka", (4.0, 0.0), 0.0, "wetrobo_y", task="lid")
    with pytest.raises(RobotError):
        sim.place_robot(uid, x=3.0)


def test_saved_layout_keeps_the_robot_where_it_was(sim):
    from playground import server as SV
    sim.place_robot("st1", x=-1.15, z=1.25, heading=math.radians(45))
    st = sim.station("st1")
    lay = {"stations": [{"uid": "st1", "robot": "franka", "pos": list(st.pos), "yaw": st.yaw, "name": "R",
                         "kind": "table", "mount": st.as_dict()["mount"]}], "objects": []}
    stations, _ = SV._world_from_layout(lay)
    assert stations[0].robot_z == pytest.approx(1.25) and stations[0].robot_turn == pytest.approx(st.robot_turn, abs=1e-3)
