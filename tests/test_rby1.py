"""Rainbow Robotics' RB-Y1 wheeled humanoid in the playground: Menagerie's model on the floor at
its table. Nothing balances it: the AI drives the wheels, torso, head and each arm itself."""
import mujoco
import numpy as np
import pytest

from playground import site, world as W
from playground.sim import PlaygroundSim
from wetlabsim import robot_api as RA, scene as WS
from wetlabsim.sim import Arm, Mobile, RobotError

from test_playground_grip import _go, _step


def _lab(item=None, side="left", kind="wetlab"):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("rby1", (0, 0), 0.0, kind, starter=False)
    st = sim.station(uid)
    if item:   # 18 cm past the table's near edge, in front of one gripper
        x, y, _ = st.to_world(-st.footprint()[0] / 2 + 0.18, 0.2 if side == "left" else -0.2)
        sim.placed = [W.Placed("t1", item, (x, y, st.top + 0.002), 0.0)]
        sim.rebuild()
    return sim, sim.arms[uid]


def test_model_is_menageries():
    m = mujoco.MjModel.from_xml_path(str(WS.ASSETS / "rainbow_robotics_rby1" / "rby1a_1.2.xml"))
    assert m.nu == 26                     # 2 wheels, 6 torso, 2 x 7 arm, 2 head, 2 grippers
    assert m.body_subtreemass[1] == pytest.approx(129, abs=2)        # Rainbow: 131 kg
    for j in ("left_wheel", "torso_5", "right_arm_6", "head_1", "gripper_finger_l1"):
        assert m.joint(j).id >= 0


def test_one_robot_two_arms_three_cameras_and_sensors():
    sim, r = _lab()
    assert isinstance(r, Mobile) and set(r.sides) == {"left", "right"}
    assert all(type(a) is Arm and a.n_arm == 7 and a.has_ft for a in r.sides.values())
    assert set(r.P["cameras"]) == {"head", "left_wrist", "right_wrist", "side"}
    st = r.state()
    assert set(st["body"]) >= {"torso", "head", "wheels", "odometry", "driving"}
    assert len(st["left"]["tcp_force"]) == 6
    cal = r.calibration()
    assert cal["left"]["wrist"]["pose_frame"] == "tcp" and cal["right"]["head"]["pose_frame"] == "base"


@pytest.mark.parametrize("kind", ["wetlab", "table"])
def test_stands_still_at_its_table_in_the_ready_pose(kind):
    sim, r = _lab(kind=kind)
    p0 = sim.d.xpos[r.base_body].copy()
    _step(sim, 3.0)
    assert np.linalg.norm(sim.d.xpos[r.base_body] - p0) < 0.005
    assert r.mode == "running"
    top = sim.station("st1").top
    for a in r.sides.values():
        assert np.max(np.abs(sim.d.qpos[a.arm_qadr] - a.ready_q)) < 0.02
        assert a.state()["tcp_pose"][2] > top + 0.1                # the grippers clear the table
    own = r.bodies
    for c in sim.d.contact[:sim.d.ncon]:                            # only the wheels and casters touch
        for b in (sim.m.geom_bodyid[c.geom1], sim.m.geom_bodyid[c.geom2]):
            if b in own:
                assert sim.m.body(b).name.split("/")[-1] in ("base", "wheel_l", "wheel_r")


def test_drives_turns_and_counts_odometry():
    sim, r = _lab()
    _step(sim, 0.5)
    p0 = sim.d.xpos[r.base_body].copy()
    _go(sim, r.drive(-0.3, 0, 2.0))
    dx = sim.d.xpos[r.base_body][0] - p0[0]
    assert -0.65 < dx < -0.5                                        # ramps up at the wheels' limit
    assert r.odom[0] == pytest.approx(dx, abs=0.02)
    _go(sim, r.drive(0, 0.5, 2.0))
    w, x, y, z = sim.d.xquat[r.base_body]
    assert 0.6 < 2 * np.arctan2(z, w) < 1.05
    with pytest.raises(RobotError, match="too fast"):
        r.drive(1.5, 1.0, 1.0)


def test_torso_and_head_move_within_their_limits():
    sim, r = _lab()
    a = r.sides["left"]
    z0 = a.state()["tcp_pose"][2]
    crouch = np.deg2rad([0, 30, -60, 30, 0, 0])
    _go(sim, r.torso_move(crouch))
    assert np.allclose(sim.d.qpos[r.torso.qadr], crouch, atol=0.02)
    assert a.state()["tcp_pose"][2] < z0 - 0.05                    # the chest went down with the knees
    _go(sim, r.head_move([0.3, 0.6]))
    assert np.allclose(sim.d.qpos[r.head.qadr], [0.3, 0.6], atol=0.02)
    with pytest.raises(RobotError, match="limits"):
        r.head_move([1.0, 0])
    with pytest.raises(RobotError, match="6 joints"):
        r.torso_move([0, 0])


@pytest.mark.parametrize("side,kind", [("left", "wetlab"), ("right", "table")])
def test_picks_up_a_vial(side, kind):
    sim, r = _lab("glass_vial", side, kind)
    A = r.sides[side]
    _step(sim, 1.0)
    b = sim.m.body("obj_t1").id
    p0 = sim.d.xpos[b].copy()
    pb = A.to_base(sim.d.xipos[b])
    P = lambda x, y, z: [x, y, z, 0, -0.5, 0]                       # fingers down, tilted forward
    _go(sim, A.move_j_ik(P(pb[0], pb[1], pb[2] + 0.12), 1.0))
    _go(sim, A.move_l(P(pb[0], pb[1], pb[2]), 0.1))
    A.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    assert A.gripper_status()["object_detected"]
    up = np.array(A.state()["tcp_pose"])
    up[2] += 0.12
    _go(sim, A.move_l(up, 0.1))
    _step(sim, 2.0)
    assert sim.d.xpos[b][2] - p0[2] > 0.1, "dropped"
    assert A.state()["tcp_force"][2] > 0.5                          # the sensor feels its weight
    assert r.mode == "running"


def test_site_sheet_and_robot_api():
    sim, r = _lab()
    text = site.site_sheet([], sim.station("st1"))
    assert "RB-Y1" in text and "base frame" in text and "`head`" in text and "wheels" in text
    for path in ("/drive", "/torso", "/head", "/left/move_l", "/right/gripper"):
        assert RA.allowed("POST", path)
