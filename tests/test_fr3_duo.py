"""The two-arm FR3 Duo in the playground: Franka's kit as converted, one robot, two arms."""
import mujoco
import numpy as np
import pytest

from playground import site, world as W
from playground.sim import PlaygroundSim
from wetlabsim import scene as WS
from wetlabsim.sim import RobotError, TwoArm

from test_playground_grip import _go, _step


def _lab(item=None, at=(0.45, 0.2)):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("fr3_duo", (0, 0), 0.0, "table")
    st = sim.station(uid)
    if item:   # in front of the robot, in its origin frame (x forward, y left)
        rx, ry = st.robot_xy
        x, y, _ = st.to_world(rx + at[0], ry + at[1])
        sim.placed = [W.Placed("t1", item, (x, y, st.top + 0.002), 0.0)]
        sim.rebuild()
    return sim, sim.arms[uid]


def test_model_is_the_kits():
    m = mujoco.MjModel.from_xml_path(str(WS.ASSETS / "franka_fr3_duo" / "fr3_duo.xml"))
    # 7 joints per arm with the FR3's limits (FCI table), the kit's gains, 2F-85s attached.
    j4 = m.joint("left/joint4")
    assert np.allclose(m.jnt_range[j4.id], [-3.0770, -0.1169], atol=1e-3)
    assert np.allclose(m.jnt_range[m.joint("right/joint6").id], [0.4398, 4.6216], atol=1e-3)
    a1 = m.actuator("left/joint1")
    assert m.actuator_gainprm[a1.id, 0] == pytest.approx(4500, rel=1e-3)
    assert m.actuator_forcerange[m.actuator("right/joint7").id, 1] == pytest.approx(12)
    assert m.body_subtreemass[0] == pytest.approx(38.7, abs=0.2)    # the kit states 38.69 kg
    for c in ("head", "wrist_cam_left", "wrist_cam_right"):
        assert m.camera(c).id >= 0


def test_one_robot_two_arms_three_cameras():
    sim, pair = _lab()
    assert isinstance(pair, TwoArm) and set(pair.sides) == {"left", "right"}
    assert set(pair.P["cameras"]) == {"head", "left_wrist", "right_wrist", "side"}
    for side, a in pair.sides.items():
        assert a.n_arm == 7 and a.has_ft
        assert set(a.P["cameras"]) == {"head", "wrist"}
    assert {sim.body_station[b] for b in pair.bodies} == {"st1"}
    st = pair.state()
    assert set(st["left"]) >= {"joint_positions", "tcp_pose", "gripper", "tcp_force"}
    cal = pair.calibration()
    assert cal["left"]["wrist"]["pose_frame"] == "tcp" and cal["right"]["head"]["pose_frame"] == "base"


def test_both_arms_report_in_the_duo_frame():
    sim, pair = _lab()
    _step(sim, 0.5)
    L, R = pair.sides["left"], pair.sides["right"]
    st = sim.station("st1")
    # The origin: 200 mm above the table, upright.
    p, Rm = L.base_tf()
    assert p[2] == pytest.approx(st.top + 0.2, abs=1e-3) and np.allclose(Rm, np.eye(3), atol=1e-6)
    # Ready pose: grippers down, 45 cm ahead, 20 cm either side, 25 cm above the table.
    for a, y in ((L, 0.2), (R, -0.2)):
        pose = np.array(a.state()["tcp_pose"])
        assert np.allclose(pose[:3], [0.45, y, 0.05], atol=0.01), pose
    assert pair.mode == "running"


def test_ready_pose_holds_still_and_collision_free():
    sim, pair = _lab()
    _step(sim, 2.0)
    for a in pair.sides.values():
        assert np.max(np.abs(sim.d.qvel[a.arm_dadr])) < 0.01
        assert np.max(np.abs(sim.d.qpos[a.arm_qadr] - a.ready_q)) < 0.01
    own = pair.bodies
    for c in sim.d.contact[:sim.d.ncon]:
        b1, b2 = sim.m.geom_bodyid[c.geom1], sim.m.geom_bodyid[c.geom2]
        assert not (b1 in own and b2 in own), (sim.m.body(b1).name, sim.m.body(b2).name)


def test_the_pair_takes_no_motion_commands():
    sim, pair = _lab()
    with pytest.raises(RobotError, match="arms"):
        pair.move_l([0.4, 0, 0.1, np.pi, 0, 0])
    with pytest.raises(RobotError, match="arms"):
        pair.zero_ft()


def test_site_sheet():
    sim, pair = _lab()
    text = site.site_sheet([], sim.station("st1"))
    assert "FR3 Duo" in text and "z = -0.20" in text and "`head`" in text


def test_left_arm_picks_up_a_vial():
    sim, pair = _lab("glass_vial", at=(0.45, 0.2))
    L = pair.sides["left"]
    _step(sim, 1.0)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    pb = L.to_base(p0)
    z = pb[2] + W.catalog.meta("glass_vial")["size"][2] - 0.03
    pose = lambda zz: [pb[0], pb[1], zz, np.pi, 0, 0]
    L.gripper_move(0)
    _go(sim, L.move_l(pose(z + 0.12), 0.2))
    _go(sim, L.move_l(pose(z), 0.08))
    L.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    assert L.gripper_status()["object_detected"]
    _go(sim, L.move_l(pose(z + 0.15), 0.15))
    tcp = lambda: sim.d.site_xpos[L.tcp_site].copy()
    r0 = sim.d.xpos[b] - tcp()
    _step(sim, 4.0)
    assert sim.d.xpos[b][2] - p0[2] > 0.1, "dropped"
    assert np.linalg.norm(sim.d.xpos[b] - tcp() - r0) < 0.005
    assert pair.mode == "running"
