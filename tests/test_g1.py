"""The Unitree G1 humanoid in the playground: Menagerie's model with Dex3-1 hands, standing on
the floor at its table under NVIDIA's GR00T balance and walking policies (as LeRobot runs it)."""
import mujoco
import numpy as np
import pytest

from playground import site, world as W
from playground.sim import PlaygroundSim
from wetlabsim import robot_api as RA, scene as WS
from wetlabsim.sim import HandArm, Humanoid, RobotError

from test_playground_grip import _go, _step

pytest.importorskip("onnxruntime")


def _lab(item=None, side="left", kind="wetlab"):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("g1", (0, 0), 0.0, kind, starter=False)
    st = sim.station(uid)
    if item:   # 12 cm past the table's near edge, in front of one hand
        x, y, _ = st.to_world(-st.footprint()[0] / 2 + 0.12, 0.12 if side == "left" else -0.12)
        sim.placed = [W.Placed("t1", item, (x, y, st.top + 0.002), 0.0)]
        sim.rebuild()
    return sim, sim.arms[uid]


def test_model_is_menagerie_with_hands():
    m = mujoco.MjModel.from_xml_path(str(WS.ASSETS / "unitree_g1" / "g1_with_hands.xml"))
    assert m.nu == 43                     # 29 body joints + 2 x 7 hand joints
    assert m.body_subtreemass[1] == pytest.approx(35, abs=2)        # Unitree: about 35 kg
    for j in ("left_hand_thumb_0_joint", "right_hand_index_1_joint", "waist_pitch_joint"):
        assert m.joint(j).id >= 0


def test_one_robot_two_hands_three_cameras_and_sensors():
    sim, g = _lab()
    assert isinstance(g, Humanoid) and set(g.sides) == {"left", "right"}
    assert all(isinstance(a, HandArm) and a.n_arm == 7 and not a.has_ft for a in g.sides.values())
    assert set(g.P["cameras"]) == {"head", "left_wrist", "right_wrist", "side"}
    m = sim.m
    assert m.actuator_gainprm[m.actuator("st1/left_knee_joint").id, 0] == pytest.approx(300)   # LeRobot's kp
    st = g.state()
    assert set(st["body"]) >= {"imu", "joint_positions", "walking", "fallen"}
    assert set(st["left"]["hand"]["pressure"]) == {"palm", "thumb_pad", "thumb_tip", "index_pad", "index_tip",
                                                   "middle_pad", "middle_tip"}
    cal = g.calibration()
    assert cal["left"]["wrist"]["pose_frame"] == "tcp" and cal["right"]["head"]["pose_frame"] == "base"


@pytest.mark.parametrize("kind", ["wetlab", "table"])
def test_stands_still_on_the_floor_at_its_table(kind):
    sim, g = _lab(kind=kind)
    p0 = sim.d.xpos[g.base_body].copy()
    _step(sim, 4.0)
    p = sim.d.xpos[g.base_body]
    assert g.mode == "running" and not g.fallen
    assert np.linalg.norm(p[:2] - p0[:2]) < 0.12          # settles a few cm as it starts balancing
    assert p[2] == pytest.approx(WS.G1_STANDING_HEIGHT, abs=0.02)
    for a in g.sides.values():                             # arms hold the ready pose
        assert np.max(np.abs(sim.d.qpos[a.arm_qadr] - a.ready_q)) < 0.02
    own = g.bodies
    for c in sim.d.contact[:sim.d.ncon]:                   # only the feet touch anything
        b1, b2 = sim.m.geom_bodyid[c.geom1], sim.m.geom_bodyid[c.geom2]
        for b in (b1, b2):
            if b in own:
                assert "ankle_roll" in sim.m.body(b).name, sim.m.body(b).name


def test_walks_turns_and_crouches():
    sim, g = _lab()
    _step(sim, 1.0)
    p0 = sim.d.xpos[g.base_body].copy()
    _go(sim, g.walk(-0.3, 0, 0, 2.0))
    assert sim.d.xpos[g.base_body][0] - p0[0] < -0.3
    _go(sim, g.walk(0, 0, 0.5, 2.0))
    w, x, y, z = g.state()["body"]["imu"]["quaternion"]
    assert 2 * np.arctan2(z, w) > 0.4
    g.body_pose(height=0.65, pitch=0.3)
    _step(sim, 2.0)
    assert sim.d.xpos[g.base_body][2] < 0.7
    assert g.mode == "running" and not g.fallen
    with pytest.raises(RobotError):
        g.walk(3.0, 0, 0, 1.0)


def test_hands_close_open_and_set_joints():
    sim, g = _lab()
    L, R = g.sides["left"], g.sides["right"]
    L.gripper_move(255)
    _step(sim, 1.5)
    assert L.gripper_status()["status_code"] == 3           # a clean fist: no finger blocked
    assert np.allclose(L.hand_state()["joint_positions"], WS.g1_hand_closed("left"), atol=0.05)
    L.gripper_move(0)
    _step(sim, 1.0)
    assert np.allclose(L.hand_state()["joint_positions"], 0, atol=0.05)
    R.hand_move([0.3, -0.4, -0.8, 0.8, 0.8, 0.8, 0.8])
    _step(sim, 1.0)
    assert np.allclose(R.hand_state()["joint_positions"], [0.3, -0.4, -0.8, 0.8, 0.8, 0.8, 0.8], atol=0.05)
    with pytest.raises(RobotError, match="joint limits"):
        R.hand_move([0.3, 0.4, 0.8, -0.8, -0.8, -0.8, -0.8])     # the left hand's signs


@pytest.mark.parametrize("side", ["left", "right"])
def test_picks_up_a_vial_from_the_side(side):
    sim, g = _lab("glass_vial", side)
    A = g.sides[side]
    _step(sim, 2.0)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    pb = A.to_base(sim.d.xipos[b])                         # its centre
    s = 1 if side == "left" else -1
    zg = pb[2]
    P = lambda x, y, z: [x, y, z, 0, 0, 0]                   # fingers forward, palm toward the middle
    A.gripper_move(0)
    _go(sim, A.move_j_ik(P(pb[0] - 0.05, pb[1] + 0.03 * s, zg + 0.05), 1.0))
    _go(sim, A.move_l(P(pb[0] - 0.05, pb[1] + 0.03 * s, zg), 0.15))
    _go(sim, A.move_l(P(pb[0], pb[1], zg), 0.08))         # the TCP at the vial's centre
    A.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    assert A.gripper_status()["object_detected"]
    assert max(A.hand_state()["pressure"].values()) > 1.0
    up = np.array(A.state()["tcp_pose"])
    up[2] += 0.10
    _go(sim, A.move_l(up, 0.1))
    tcp = lambda: sim.d.site_xpos[A.tcp_site].copy()
    r0 = sim.d.xpos[b] - tcp()
    _step(sim, 3.0)
    assert sim.d.xpos[b][2] - p0[2] > 0.07, "dropped"
    assert np.linalg.norm(sim.d.xpos[b] - tcp() - r0) < 0.005
    assert g.mode == "running"


def test_lidar_sees_the_table():
    sim, g = _lab()
    _step(sim, 0.5)
    pts = g.lidar()["points"]
    assert len(pts) > 5000
    top = sim.station("st1").top - sim.d.xpos[g.base_body][2]
    # It hangs upside down in the head, looking down over the table.
    near_top = pts[(np.abs(pts[:, 2] - top) < 0.06) & (pts[:, 0] > 0.3) & (pts[:, 0] < 0.9)]
    assert len(near_top) > 200


def test_a_fall_stops_the_robot():
    sim, g = _lab()
    _step(sim, 1.0)
    with sim.lock:                                  # tipped well past what it can catch
        sim.d.qpos[g.free_qadr + 3:g.free_qadr + 7] = [np.cos(0.5), 0, np.sin(0.5), 0]
    _step(sim, 3.0)
    assert g.fallen and g.mode == "protective_stop"
    with pytest.raises(RobotError):
        g.walk(0.2, 0, 0, 1.0)
    with pytest.raises(RobotError):
        g.unlock()


def test_site_sheet_and_robot_api():
    sim, g = _lab()
    text = site.site_sheet([], sim.station("st1"))
    assert "Unitree G1" in text and "pelvis frame" in text and "`head`" in text and "floor" in text
    for path in ("/walk", "/stand", "/body", "/left/hand", "/right/hand"):
        assert RA.allowed("POST", path)
    assert RA.allowed("GET", "/lidar.npz") and RA.allowed("GET", "/camera/head.png")
