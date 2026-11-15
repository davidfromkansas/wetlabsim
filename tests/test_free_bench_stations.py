"""A benchmark's scene as a free station: a WetRobo lab with its kit, or one of LIBERO's rooms,
for any task you type. The same scene as the benchmark's, with no task, no goal check and no score."""
import mujoco
import pytest

from playground import libero as LB
from playground import server as SV
from playground import wetrobo as WR
from playground.sim import PlaygroundSim, RobotError


@pytest.mark.parametrize("lab,robot", [("x", "franka"), ("x", "piper"), ("y", "franka"), ("y", "piper")])
def test_a_wetrobo_lab_as_a_free_station(lab, robot):
    s = PlaygroundSim()
    uid = s.add_station(robot, (3.0, 0.0), 0.0, kind=WR.LABS[lab][0], free=True)
    st = s.station(uid)
    assert st.free and st.task == "" and st.robot == robot and st.name == f"WetRobo {WR.LABS[lab][1]}"
    items = {p.item for p in s._on_table(st)}
    assert set(WR.KIT) <= items                               # the same kit as the benchmark's lab
    for _ in range(500):
        mujoco.mj_step(s.m, s.d)
    assert s.wetrobo_goal(uid) is None                        # no goal, nothing checked
    d = st.as_dict()
    assert d["free"] is True and "wetrobo" not in d
    with pytest.raises(RobotError):                           # its kit is laid out for its own arm
        s.swap_robot(uid, "piper" if robot == "franka" else "franka")


def test_the_benchmark_station_still_needs_its_task():
    s = PlaygroundSim()
    with pytest.raises(RobotError):
        s.add_station("franka", (3.0, 0.0), 0.0, kind="wetrobo_x")
    uid = s.add_station("franka", (3.0, 0.0), 0.0, kind="wetrobo_x", task="lid")
    assert not s.station(uid).free and "wetrobo" in s.station(uid).as_dict()
    plain = s.add_station("franka", (8.0, 0.0), free=True)    # free means nothing on a plain table
    assert not s.station(plain).free


def test_liberos_rooms_each_once():
    rooms = LB.rooms()
    assert len(rooms) == 12 and len({r["name"] for r in rooms}) == 12
    assert {r["kind"] for r in rooms} == {"Kitchen table", "Floor", "Kitchen", "Living room", "Study"}
    for r in rooms:
        assert LB.task(r["id"]) and r["things"]


@pytest.mark.parametrize("room", ["open_the_middle_drawer_of_the_cabinet",
                                  "KITCHEN_SCENE6_put_the_yellow_and_white_mug_in_the_microwave_and_close_it"])
def test_a_libero_room_as_a_free_station(room):
    s = PlaygroundSim()
    uid = s.add_station("ur5e", (6.0, 0.0), 0.0, kind="libero", task=room, free=True)
    st = s.station(uid)
    assert st.free and st.libero and st.robot == "franka" and st.task == room
    assert st.name == "LIBERO " + LB.room_name(LB.task(room))
    assert s.libero_goal(uid) is None                         # the room, without LIBERO's goal
    d = st.as_dict()
    assert d["free"] is True and "libero" not in d
    assert "Site sheet" in s.libero_sheet(uid)                # its run gets the room's own site sheet
    for _ in range(300):
        mujoco.mj_step(s.m, s.d)
    snap = s.station_snapshot(uid)                            # repeat runs start from the room as it is
    assert s.restore_station(snap)


def test_free_stations_come_back_with_a_saved_session():
    layout = {"stations": [
        {"uid": "st1", "robot": "piper", "pos": [3.0, 0.0], "yaw": 0.0, "name": "WetRobo Lab Y", "kind": "wetrobo_y",
         "task": "", "setup": 0, "free": True},
        {"uid": "st2", "robot": "franka", "pos": [9.0, 0.0], "yaw": 0.0, "name": "LIBERO Study 1", "kind": "libero",
         "task": LB.rooms()[7]["id"], "setup": 0, "free": True},
        {"uid": "st3", "robot": "franka", "pos": [15.0, 0.0], "yaw": 0.0, "name": "x", "kind": "wetrobo_x", "task": ""},
    ], "objects": []}
    stations, _ = SV._world_from_layout(layout)
    assert [(st.uid, st.free, st.robot) for st in stations] == [("st1", True, "piper"), ("st2", True, "franka")]
