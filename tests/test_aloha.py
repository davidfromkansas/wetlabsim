"""The two-arm ALOHA in the playground: one robot, two arms, each its own robot API."""
import mujoco
import numpy as np
import pytest

from playground import site, world as W
from playground.sim import PlaygroundSim
from wetlabsim import robot_api as RA
from wetlabsim.sim import RobotError, TwoArm

from test_playground_grip import _go, _step


def _lab(item=None):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("aloha", (0, 0), 0.0, "table")
    st = sim.station(uid)
    if item:   # 35 cm in front of the left arm (its base: station (-0.019, 0.469), facing -y)
        x, y, _ = st.to_world(-0.019, 0.469 - 0.35)
        sim.placed = [W.Placed("t1", item, (x, y, st.top + 0.002), 0.0)]
        sim.rebuild()
    return sim, sim.arms[uid]


def test_one_robot_two_arms_four_cameras():
    sim, pair = _lab()
    assert isinstance(pair, TwoArm) and set(pair.sides) == {"left", "right"}
    assert set(pair.P["cameras"]) == {"overhead", "low", "left_wrist", "right_wrist", "side"}
    for side, a in pair.sides.items():
        assert a.n_arm == 6 and not a.has_ft
        assert set(a.P["cameras"]) == {"overhead", "low", "wrist"}
        assert a.P["cameras"]["wrist"].endswith(f"wrist_cam_{side}")
    # Both arms' bodies belong to the station (picking the robot picks the station).
    assert {sim.body_station[b] for b in pair.bodies} == {"st1"}
    st = pair.state()
    assert set(st["left"]) >= {"joint_positions", "tcp_pose", "gripper"} and "tcp_force" not in st["left"]
    cal = pair.calibration()
    assert cal["left"]["wrist"]["pose_frame"] == "tcp" and cal["right"]["overhead"]["pose_frame"] == "base"


def test_arms_face_each_other():
    sim, pair = _lab()
    L, R = pair.sides["left"], pair.sides["right"]
    # The right arm's base, seen from the left arm: 0.938 m straight ahead.
    p = L.to_base(sim.d.xpos[R.base_body])
    assert np.allclose(p, [0.938, 0, 0], atol=1e-3)


def test_the_pair_takes_no_motion_commands():
    sim, pair = _lab()
    with pytest.raises(RobotError, match="arms"):
        pair.move_l([0.3, 0, 0.1, 0, 1.57, 0])
    with pytest.raises(RobotError):
        pair.zero_ft()
    pair.stop()      # stops both
    assert pair.mode == "running"


def test_left_arm_picks_up_a_vial():
    sim, pair = _lab("glass_vial")
    L = pair.sides["left"]
    _step(sim, 1.0)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    pb = L.to_base(p0)
    z = pb[2] + W.catalog.meta("glass_vial")["size"][2] - 0.03
    pose = lambda zz: [pb[0], pb[1], zz, 0, np.pi / 2, 0]
    L.gripper_move(0)
    _go(sim, L.move_l(pose(z + 0.12), 0.2))
    _go(sim, L.move_l(pose(z), 0.08))
    L.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    assert L.gripper_status()["object_detected"]
    _go(sim, L.move_l(pose(z + 0.15), 0.15))
    tcp = lambda: sim.d.site_xpos[L.tcp_site].copy()
    r0 = sim.d.xpos[b] - tcp()
    _step(sim, 5.0)
    assert sim.d.xpos[b][2] - p0[2] > 0.1, "dropped"
    assert np.linalg.norm(sim.d.xpos[b] - tcp() - r0) < 0.003
    assert pair.mode == "running"


def test_empty_close_is_not_an_object():
    sim, pair = _lab()
    a = pair.sides["right"]
    a.gripper_move(255)
    _step(sim, 1.5)
    g = a.gripper_status()
    assert not g["object_detected"] and g["status_code"] == 3


def test_robot_api_paths_per_arm():
    for m, p in [("GET", "/left/state"), ("GET", "/right/camera/wrist.png"), ("GET", "/camera/low.png"),
                 ("GET", "/camera/left_wrist.rgbd.npz"), ("POST", "/left/move_l"), ("POST", "/right/gripper"),
                 ("POST", "/stop")]:
        assert RA.allowed(m, p), (m, p)
    for m, p in [("GET", "/middle/state"), ("POST", "/left/eval/reset"), ("GET", "/left/camera/side.jpg"),
                 ("GET", "/left/pg/scene")]:
        assert not RA.allowed(m, p), (m, p)


def test_site_sheet():
    text = site.site_sheet([], W.Station("st1", "aloha", (0, 0), 0.0, "Robot 1"))
    assert "two Trossen ViperX 300 S arms" in text and "93.8 cm apart" in text
    assert "No force/torque sensing" in text
    assert "What's here" not in text


def test_wet_lab_bench_keeps_clear_of_both_bases():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("aloha", (0, 0), 0.0, "wetlab")
    st = sim.station(uid)
    assert sim.placed and not any(st.near_base(p.pos[0], p.pos[1]) for p in sim.placed)
    _step(sim, 1.0)
    robot = sim.robot_bodies
    touching = [i for i in range(sim.d.ncon)
                if (sim.m.geom_bodyid[sim.d.contact[i].geom1] in robot) != (sim.m.geom_bodyid[sim.d.contact[i].geom2] in robot)
                and "obj_" in sim.m.body(sim.m.geom_bodyid[sim.d.contact[i].geom1]).name + sim.m.body(sim.m.geom_bodyid[sim.d.contact[i].geom2]).name]
    assert not touching


def test_swap_refuses_when_things_stand_where_a_base_goes():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    st = sim.station(uid)
    x, y, _ = st.to_world(-0.019, 0.469)
    sim.placed.append(W.Placed("v1", "glass_vial", (x, y, st.top + 0.002), 0.0))
    sim.rebuild()
    with pytest.raises(RobotError, match="where"):
        sim.swap_robot(uid, "aloha")
    sim.remove("v1")
    sim.swap_robot(uid, "aloha")
    assert isinstance(sim.arms[uid], TwoArm)


def test_run_timeline_keeps_each_arm_apart():
    from wetlabsim import timeline as TL
    sim, pair = _lab()
    L, R = pair.sides["left"], pair.sides["right"]
    t0 = sim.d.time
    L.move_j([0.3, -0.9, 1.1, 0, -0.3, 0], 1.0)
    _step(sim, 0.3)
    R.move_j([-0.3, -0.9, 1.1, 0, -0.3, 0], 1.0)
    assert pair.motion is R.motion or not pair.motion.done.is_set()
    _step(sim, 0.5)
    L.gripper_move(255)
    _step(sim, 0.5)
    R.gripper_move(255)
    _step(sim, 4.0)
    L.gripper_move(0)
    _step(sim, 1.0)
    tl = TL.build([], list(pair.events), {"agent": "claude", "model": "opus", "sim_start": t0,
                                          "status": "finished"}, end=sim.d.time)
    moving = next(l for l in tl["lanes"] if l["id"] == "moving")["blocks"]
    # The right arm's move doesn't cut the left arm's short.
    assert [b["detail"] for b in moving] == ["left move j", "right move j"]
    assert moving[0]["end"] > moving[1]["start"]
    assert [f["label"] for f in tl["flags"]] == ["Both arms: Gripped", "Left arm: Let go"]
    # The run tag hangs over the middle of the pair, not over one arm.
    mid = (L.base_tf()[0] + R.base_tf()[0]) / 2
    assert np.allclose(sim.scene_info()["robots"][0]["base"], mid, atol=1e-3)
