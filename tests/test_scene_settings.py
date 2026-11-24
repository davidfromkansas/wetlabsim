"""Scene settings (playground/settings.py) and repeat runs' station reset (playground/sim.py):
the session's MuJoCo settings reach the compiled model, bad ones are refused, and a station
goes back exactly to where a batch started."""
import mujoco
import numpy as np
import pytest

from playground import settings as ST
from playground import world as W
from playground.sim import PlaygroundSim


def test_defaults_read_back():
    lab = ST.read_model(W.build([], []))
    assert lab["option"]["integrator"] == "discrete"       # the Playground's own choice
    assert set(lab["flag"]) == set(ST.FLAGS) and len(ST.FLAGS) == 28
    mj = ST.mujoco_defaults()
    assert mj["option"]["timestep"] == pytest.approx(0.002)
    assert mj["option"]["integrator"] == "Euler"


def test_settings_reach_the_model():
    cfg = ST.clean({"option": {"timestep": 0.003, "solver": "CG", "gravity": [0, 0, -5]},
                    "flag": {"energy": True, "gravity": False},
                    "actuatorgroupdisable": [3],
                    "materials": {"prop": {"condim": 4}, "robot": {"friction": [0.8, 0.01, 0.001]}}})
    m = W.build([], W.default_stations(), cfg)
    r = ST.read_model(m)
    assert r["option"]["timestep"] == pytest.approx(0.003)
    assert r["option"]["solver"] == "CG"
    assert r["option"]["gravity"] == pytest.approx([0, 0, -5])
    assert r["flag"]["energy"] is True and r["flag"]["gravity"] is False
    assert r["actuatorgroupdisable"] == [3]
    # The robot's own geoms take the robot material (scene._set_material).
    robot = [g for g in range(m.ngeom) if m.geom_condim[g] == 3 and abs(m.geom_friction[g][0] - 0.8) < 1e-9]
    assert robot, "the robot material's friction did not reach the robot"
    # And a build without settings is the Playground's own again.
    assert ST.read_model(W.build([], []))["option"]["timestep"] != pytest.approx(0.003)


@pytest.mark.parametrize("raw", [
    {"option": {"timestep": 5}},
    {"option": {"iterations": 2.5}},
    {"option": {"solver": "magic"}},
    {"option": {"gravity": [0, 0]}},
    {"option": {"nope": 1}},
    {"flag": {"nope": True}},
    {"materials": {"prop": {"condim": 2}}},
    {"materials": {"glass": {"condim": 3}}},
    {"actuatorgroupdisable": [99]},
])
def test_bad_settings_refused(raw):
    with pytest.raises(ValueError):
        ST.clean(raw)


def test_apply_settings_and_station_reset():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    st = sim.station(uid)
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1])
    sim.placed = [W.Placed("t1", "tube_15ml", (x, y, st.top + 0.01), 0.0)]
    sim.rebuild()
    for _ in range(200):
        mujoco.mj_step(sim.m, sim.d)
    snap = sim.station_snapshot(uid)
    b = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_BODY, "obj_t1")
    x0, q0 = sim.d.xpos[b].copy(), sim.d.qpos.copy()
    assert len(snap["qpos_i"]) > 9                      # the arm and the tube on its table
    sim.d.qpos[snap["qpos_i"]] += 0.05
    mujoco.mj_forward(sim.m, sim.d)
    assert sim.restore_station(snap)
    assert np.allclose(sim.d.xpos[b], x0, atol=1e-6)
    assert np.allclose(sim.d.qpos, q0, atol=1e-9)
    # New settings rebuild the lab: an old snapshot no longer applies.
    sim.apply_settings({"option": {"timestep": 0.002}})
    assert sim.m.opt.timestep == pytest.approx(0.002)
    assert not sim.restore_station(snap)


def test_reset_station_to_before_last_run():
    """Reset (robot menu): back to the moment the last run started, even after a rebuild."""
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    st = sim.station(uid)
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1])
    sim.placed = [W.Placed("t1", "tube_15ml", (x, y, st.top + 0.01), 0.0)]
    sim.rebuild()
    for _ in range(200):
        mujoco.mj_step(sim.m, sim.d)
    snap = sim.station_snapshot(uid)
    b = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_BODY, "obj_t1")
    x0 = sim.d.xpos[b].copy()
    sim.d.qpos[snap["qpos_i"]] += 0.05
    mujoco.mj_forward(sim.m, sim.d)
    assert sim.reset_station(snap) is None
    assert np.allclose(sim.d.xpos[b], x0, atol=1e-6)
    # The lab rebuilt since (new settings): Reset still puts the tube back, by joint name.
    sim.apply_settings({"option": {"timestep": 0.002}})
    b = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_BODY, "obj_t1")
    j = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_JOINT, "obj_t1_joint")
    sim.d.qpos[sim.m.jnt_qposadr[j]] += 0.1
    mujoco.mj_forward(sim.m, sim.d)
    assert sim.reset_station(snap) is None
    assert np.allclose(sim.d.xpos[b], x0, atol=1e-6)
    sim.remove_station(uid)
    assert sim.reset_station(snap)          # the robot is gone: a plain-words error


def test_reset_takes_back_only_what_the_run_moved():
    """Reset after a run: what the robot moved anywhere in the lab goes back, and the robot to
    its starting pose; objects the user moved or added afterwards stay as the user left them."""
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    st = sim.station(uid)
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1])
    x2, y2, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1] + 0.15)
    x3, y3, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1] - 0.15)
    sim.placed = [W.Placed("t1", "tube_15ml", (x, y, st.top + 0.01), 0.0),       # the robot moves it
                  W.Placed("t2", "tube_15ml", (2.5, 2.5, 0.01), 0.0),             # on the floor: knocked further
                  W.Placed("t3", "tube_15ml", (x2, y2, st.top + 0.01), 0.0),     # robot moves it, then the user
                  W.Placed("t4", "tube_15ml", (x3, y3, st.top + 0.01), 0.0)]     # nobody touches it
    sim.rebuild()
    for _ in range(300):
        mujoco.mj_step(sim.m, sim.d)
    before, start = sim.scene_snapshot(), sim.station_snapshot(uid)
    arm = sim.arms[uid]
    arm_q = [int(sim.m.joint(n).qposadr[0]) for n in arm.own_joints][:7]

    def jq(name):
        j = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_JOINT, f"obj_{name}_joint")
        return int(sim.m.jnt_qposadr[j])

    def at(name):
        return sim.d.xpos[mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{name}")].copy()

    home = {n: at(n) for n in ("t1", "t2", "t3", "t4")}
    # "The run": the robot's arm moves, t1 and t3 slide 10 cm, t2 rolls off 30 cm.
    sim.d.qpos[arm_q] += 0.2
    for n, dx in (("t1", 0.1), ("t2", 0.3), ("t3", 0.1)):
        sim.d.qpos[jq(n)] += dx
    mujoco.mj_forward(sim.m, sim.d)
    moved = sim.scene_changes(before)
    assert set(moved) == {"t1", "t2", "t3"}
    assert moved["t1"] == uid and moved["t2"] is None
    for o in moved:
        sim.touched[o] = "run1"
    # The user moves t3 and adds an object (that rebuilds the lab).
    pre = sim.scene_state()
    sim.move("t3", (x2, y2 + 0.3, st.top + 0.01))
    sim.mark_user_edits(pre)
    assert sim.touched["t3"] == "user"
    user_t3 = at("t3")
    new = sim.add("tube_15ml", (x3, y3 - 0.1, st.top + 0.01))
    new_at = at(new)
    owners = {o for o in moved if sim.touched.get(o) == "run1"}
    assert owners == {"t1", "t2"}
    assert sim.undo_run(uid, before, start, owners) is None
    assert np.allclose(at("t1"), home["t1"], atol=1e-6)
    assert np.allclose(at("t2"), home["t2"], atol=1e-6)
    assert np.allclose(at("t3"), user_t3, atol=1e-6)
    assert np.allclose(at("t4"), home["t4"], atol=1e-3)
    assert np.allclose(at(new), new_at, atol=1e-6)
    now = arm.snapshot()["q"]                                   # the robot is back in its starting pose
    assert all(abs(now[n] - v) < 1e-9 for n, v in start["arm"]["q"].items())
    sim.remove_station(uid)
    assert sim.undo_run(uid, before, start, owners)          # the robot is gone: a plain-words error


def test_run_video_layout_and_parts(tmp_path):
    from playground import runvideo as RV
    for n in (2, 3):
        big, smalls = RV.layout(n)
        assert len(smalls) == n
        for x, y, w, h in [big, *smalls]:
            assert x >= 0 and y >= RV.HEAD and x + w <= RV.W and y + h <= RV.H and w % 2 == 0 and h % 2 == 0
    f = tmp_path / "v.mp4"
    data = bytes(range(256)) * 30000          # ~7.7 MB: three parts
    f.write_bytes(data)
    chunks, man = RV.parts(f)
    assert b"".join(chunks) == data and man["size"] == len(data) and man["parts"] == [len(c) for c in chunks]
    assert all(len(c) <= RV.PART for c in chunks) and len(chunks) == 3
