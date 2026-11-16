"""The Unitree G1 humanoid in the playground: Menagerie's model with Dex3-1 hands, standing on
the floor at its table under NVIDIA's GEAR-SONIC whole-body controller."""
import mujoco
import numpy as np
import pytest

from playground import site, world as W
from playground.sim import PlaygroundSim
from wetlabsim import robot_api as RA, scene as WS, sonic as SO
from wetlabsim.sim import HandArm, Humanoid, RobotError

from test_playground_grip import _go, _step

pytest.importorskip("onnxruntime")


def _lab(item=None, side="left", kind="wetlab"):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("g1", (0, 0), 0.0, kind, starter=False)
    st = sim.station(uid)
    if item:   # 22 cm past the table's near edge, in front of one hand
        x, y, _ = st.to_world(-st.footprint()[0] / 2 + 0.22, 0.12 if side == "left" else -0.12)
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
    assert m.actuator_gainprm[m.actuator("st1/left_knee_joint").id, 0] == pytest.approx(SO.KP[3])   # SONIC's
    assert m.actuator_gainprm[m.actuator("st1/left_elbow_joint").id, 0] == pytest.approx(80)       # LeRobot's
    st = g.state()
    assert set(st["body"]) >= {"imu", "joint_positions", "movement", "moving", "arms_free", "fallen"}
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
    assert np.linalg.norm(p[:2] - p0[:2]) < 0.08          # settles a few cm as it starts balancing
    assert p[2] == pytest.approx(WS.G1_STANDING_HEIGHT, abs=0.02)
    for a in g.sides.values():                             # arms hold the ready pose
        assert np.max(np.abs(sim.d.qpos[a.arm_qadr] - a.ready_q)) < 0.02
    own = g.bodies
    for c in sim.d.contact[:sim.d.ncon]:                   # only the feet touch anything
        b1, b2 = sim.m.geom_bodyid[c.geom1], sim.m.geom_bodyid[c.geom2]
        for b in (b1, b2):
            if b in own:
                assert "ankle_roll" in sim.m.body(b).name, sim.m.body(b).name


def test_walks_turns_kneels_and_crawls():
    sim, g = _lab()
    _step(sim, 1.0)
    p0 = sim.d.xpos[g.base_body].copy()
    _go(sim, g.move("walk", direction=np.pi, seconds=2.0))     # backwards, away from the table
    assert sim.d.xpos[g.base_body][0] - p0[0] < -0.4
    assert g.state()["body"]["movement"] == "stand"            # it stops when the time is up
    _go(sim, g.move("walk", turn=np.pi / 2, seconds=2.0))      # turn left a quarter, walk that way
    w, x, y, z = g.state()["body"]["imu"]["quaternion"]
    assert 2 * np.arctan2(z, w) > 0.9
    _go(sim, g.pose("kneel", height=0.5))
    assert sim.d.xpos[g.base_body][2] < 0.55 and g.state()["body"]["arms_free"]
    _go(sim, g.move("crawl", seconds=2.0))
    body = g.state()["body"]
    assert body["movement"] == "crawl" and not body["arms_free"] and not body["moving"]
    with pytest.raises(RobotError, match="crawl movement"):     # the hands are on the floor
        g.sides["left"].move_j(g.sides["left"].ready_q)
    with pytest.raises(RobotError, match="kneel or squat first"):
        g.pose("stand")
    _go(sim, g.pose("kneel"))
    _go(sim, g.pose("stand"))
    _step(sim, 1.0)
    assert sim.d.xpos[g.base_body][2] == pytest.approx(WS.G1_STANDING_HEIGHT, abs=0.03)
    assert g.mode == "running" and not g.fallen
    assert g.state()["body"]["arms_free"]
    for a in g.sides.values():                     # an arm command takes the arms back from SONIC
        _go(sim, a.move_j(a.ready_q))
    _step(sim, 1.0)
    for a in g.sides.values():
        assert np.max(np.abs(sim.d.qpos[a.arm_qadr] - a.ready_q)) < 0.03
    assert g.mode == "running" and not g.fallen
    with pytest.raises(RobotError, match="within 1.5 to 3.0"):
        g.move("run", speed=5.0)
    with pytest.raises(RobotError, match="unknown movement"):
        g.move("moonwalk")


def test_runs_and_comes_back_to_stand():
    sim, g = _lab(kind="table")
    _step(sim, 1.0)
    p0 = sim.d.xpos[g.base_body].copy()
    _go(sim, g.move("run", direction=np.pi, speed=2.0, seconds=2.0))
    assert np.linalg.norm(sim.d.xpos[g.base_body][:2] - p0[:2]) > 1.5
    _step(sim, 2.0)
    assert g.mode == "running" and not g.fallen and g.state()["body"]["movement"] == "stand"


def test_sonic_commands_follow_nvidias_keyboard_rules():
    c = SO.Command.make("kneel")
    assert c.mode == 6 and c.height == 0.8 and c.speed == -1 and not c.move.any()
    c = SO.Command.make("run", move=(1, 0, 0), speed=9.0)
    assert c.speed == 3.0 and c.height == -1
    c = SO.Command.make("walk", move=(0, 1, 0))
    assert c.speed == -1 and c.move[1] == 1
    assert len(SO.MODES) == 27


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
        g.move("walk", seconds=1.0)
    with pytest.raises(RobotError):
        g.unlock()


def test_site_sheet_and_robot_api():
    sim, g = _lab()
    text = site.site_sheet([], sim.station("st1"))
    assert "Unitree G1" in text and "pelvis frame" in text and "`head`" in text and "floor" in text
    for path in ("/move", "/pose", "/stand", "/left/hand", "/right/hand"):
        assert RA.allowed("POST", path)
    assert RA.allowed("GET", "/lidar.npz") and RA.allowed("GET", "/camera/head.png")


def test_g1_works_in_a_solid_7m_room():
    """The G1 walks about: its work box is a 7 x 7 m room of solid walls round its table (not
    the table arm's walls just behind it, which its lidar saw as a wall 40 cm back), other
    stations stay out of the room, and the site sheet says so."""
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("g1", (0.0, 0.0), 0.0, "table", starter=False)
    st, g = sim.station(uid), sim.arms[uid]
    assert st.roomy and not st.open
    assert st.work_box()[:2] == (3.5, 3.5)
    walls = [i for i in range(sim.m.ngeom) if sim.m.geom(i).name.startswith(f"{st.prefix}wall")]
    assert len(walls) == 4 and all(sim.m.geom_contype[i] and sim.m.geom_conaffinity[i] for i in walls)
    pts = g.lidar()["points"]
    behind = pts[(pts[:, 0] < -0.15) & (pts[:, 0] > -1.5) & (abs(pts[:, 1]) < 0.6) & (pts[:, 2] > -0.3)]
    assert len(behind) == 0
    assert not sim.station_spot(2.0, 0.0, 0.0)["valid"]           # a table arm inside the room
    assert sim.station_spot(5.0, 0.0, 0.0)["valid"]               # and just outside it
    other = sim.add_station("franka", (-5.5, 0.0), 0.0, "table", starter=False)
    with pytest.raises(RobotError, match="7 × 7 m room"):
        sim.swap_robot(other, "g1")                                 # its room would overlap
    assert "7 x 7 m" in site.site_sheet([], st)
    sim.stop_threads()
