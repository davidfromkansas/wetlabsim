"""Single robot arms from DeepMind's MuJoCo Menagerie, each standing on its table.

Every model is Menagerie's file, unchanged, in wetlabsim/assets/<folder> (each with its own
LICENSE). What we add when the arm is built into a scene, the same way for every arm:

- a gripper where the arm comes without one: Menagerie's Robotiq 2F-85 (as on the UR5e), or
  for Franka's FR3 arms Menagerie's Franka Hand (as on the Panda);
- a tool centre point (site "tcp") between the gripper's fingers: its z axis points out of the
  gripper and the fingers close along its y axis, so a TCP pose of [x, y, z, pi, 0, 0] points
  the gripper straight down with the fingers closing along the base y axis, as on the Franka;
- a wrist camera beside the gripper, looking along the fingers;
- the playground's contact materials (finger contact surfaces rubber, every other colliding
  shape the robot's hard shell) and gravity compensation (a real controller compensates for
  gravity);
- for an arm that reports the external force at its flange, a force/torque site there.

ARMS has one entry per arm: where its model is, which joints and actuators drive it, its
gripper and its limits. Joint speeds are the makers' (agent/<robot>/datasheets/SOURCES.md).
The starting pose (ready_q) points the gripper straight down in front of the base, solved once
on each model (tests/test_menagerie_arms.py checks it).
"""
from __future__ import annotations

import warnings

import mujoco
import numpy as np

D = np.radians

# The 2F-85 as Menagerie models it (assets/robotiq_2f85), as on the UR5e.
ROBOTIQ = {
    "gripper": "Robotiq 2F-85",
    "tcp_site": "gripper/pinch",
    "grip_actuator": "gripper/fingers_actuator", "grip_joint": "gripper/right_driver_joint",
    "grip_open": 0.0, "grip_closed": 0.8,      # driver joint (rad)
    "grip_ctrl_open": 0.0,
    "max_opening_mm": 85,
}
# The Franka Hand as Menagerie models it (assets/franka_emika_panda/hand.xml), as on the Panda.
FRANKA_HAND = {
    "gripper": "Franka Hand",
    "tcp_site": "hand/tcp",
    "grip_actuator": "hand/actuator8", "grip_joint": "hand/finger_joint1",
    "grip_open": 0.04, "grip_ctrl_open": 255.0,
    "max_opening_mm": 80,
    "grip_speed_mm_s": 50.0, "grip_force_n": (30.0, 70.0), "grip_stroke_mm": 80.0,
}

# Franka mounts the hand turned 45 degrees about the flange (as in Menagerie's panda.xml); hand.xml's
# hand body is already turned half a turn, so the mount turns it the other 135 degrees.
HAND_TURN = (0.3826834, 0, 0, 0.9238795)

NO_REFLEX = {"reflex_force": (np.full(3, -1e9), np.full(3, 1e9)),
             "reflex_torque": (np.full(3, -1e9), np.full(3, 1e9))}


def _j(*names):
    return list(names)


# Each arm:
#   folder, file: its Menagerie model; name, maker: as the robot picker shows them
#   base_body: the model's root; arm_joints, arm_actuators (None: the model's actuators in order,
#     unnamed in the file, named here by their joint)
#   add: "robotiq" or "franka_hand" for an added gripper, mounted at `mount` (a site of the model,
#     or (body, pos, quat) for a mount we place: on the flange, z out of the arm)
#   hand, tcp: for an arm with its own gripper, the body the fingers ride on and the TCP on it:
#     (pos, z axis, y axis) in that body's frame (z out of the gripper, y the closing direction)
#   grip: its own gripper's actuator and joint, finger joint travel (open, closed) and the
#     actuator's command for open and closed
#   ft: the body/site the arm measures external force at (None: no force sensing)
#   cam: the wrist camera's place in the TCP frame: (back along -x, back along -z) (m)
ARMS = {
    "arx_l5": dict(
        folder="arx_l5", file="arx_l5.xml", name="ARX L5", maker="ARX Robotics",
        base_body="base_link", arm_joints=_j(*[f"joint{i}" for i in range(1, 7)]),
        hand="link6", tcp=((0.135, 0, 0), (1, 0, 0), (0, 1, 0)), camera="wrist_cam",
        grip=dict(gripper="ARX parallel gripper", grip_actuator="gripper", grip_joint="joint7",
                  grip_open=0.044, grip_closed=0.0, grip_ctrl_range=(0.044, 0.0), grip_force_at="actuator",
                  fingers=("link7", "link8"), stiffen=(1000.0, 20.0)),
        reach_mm=620, payload_kg=1.5, joints=6,
        max_opening_mm=88, joint_vmax=np.full(6, 1.5), cart_vmax=0.5, rot_vmax=3.0),
    "crx5ia": dict(
        folder="fanuc_crx5ia", file="crx5ia.xml", name="FANUC CRX-5iA", maker="FANUC",
        base_body="base_link", arm_joints=_j("J1", "J2", "J3", "J4", "J5", "J6"),
        add="robotiq", mount="attachment_site",
        reach_mm=994, payload_kg=5, joints=6,
        joint_vmax=np.full(6, 1.5), cart_vmax=1.0, rot_vmax=2.0),
    "rizon4": dict(
        folder="flexiv_rizon4", file="flexiv_rizon4.xml", name="Flexiv Rizon 4", maker="Flexiv",
        base_body="base", arm_joints=_j(*[f"joint{i}" for i in range(1, 8)]),
        add="robotiq", mount=("link7", (0, 0, 0.081), (1, 0, 0, 0)), ft="flange",
        reach_mm=916, payload_kg=4, joints=7,
        joint_vmax=np.radians([120, 120, 140, 140, 280, 280, 280]), cart_vmax=1.0, rot_vmax=2.0),
    "rizon4s": dict(
        folder="flexiv_rizon4s", file="flexiv_rizon4s.xml", name="Flexiv Rizon 4s", maker="Flexiv",
        base_body="base", arm_joints=_j(*[f"joint{i}" for i in range(1, 8)]),
        add="robotiq", mount=("link7", (0, 0, 0.081), (1, 0, 0, 0)), ft="flange",
        reach_mm=959, payload_kg=4, joints=7,
        joint_vmax=np.radians([120, 120, 140, 140, 280, 280, 280]), cart_vmax=1.0, rot_vmax=2.0),
    "fr3": dict(
        folder="franka_fr3", file="fr3.xml", name="Franka Research 3", maker="Franka Robotics",
        base_body="base", arm_joints=_j(*[f"fr3_joint{i}" for i in range(1, 8)]),
        add="franka_hand", mount=("fr3_link7", (0, 0, 0.107), HAND_TURN), ft="flange",
        reach_mm=855, payload_kg=3, joints=7,
        joint_vmax=np.array([2.62, 2.62, 2.62, 2.62, 5.26, 4.18, 5.26]), cart_vmax=1.7, rot_vmax=2.5),
    "fr3_v2": dict(
        folder="franka_fr3_v2", file="fr3v2.xml", name="Franka Research 3 (v2)", maker="Franka Robotics",
        base_body="base", arm_joints=_j(*[f"fr3v2_joint{i}" for i in range(1, 8)]),
        add="franka_hand", mount=("fr3v2_link7", (0, 0, 0.107), HAND_TURN), ft="flange",
        reach_mm=855, payload_kg=3, joints=7,
        joint_vmax=np.array([2.62, 2.62, 2.62, 2.62, 5.26, 4.18, 5.26]), cart_vmax=1.7, rot_vmax=2.5),
    "yam": dict(
        folder="i2rt_yam", file="yam.xml", name="I2RT YAM", maker="I2RT Robotics",
        base_body="arm", arm_joints=_j(*[f"joint{i}" for i in range(1, 7)]),
        hand="link_6", tcp=((0, 0, 0.12), (0, 0, 1), (1, 0, 0)),
        grip=dict(gripper="YAM parallel gripper", grip_actuator="gripper", grip_joint="left_finger",
                  grip_open=0.038, grip_closed=0.0, grip_ctrl_range=(0.038, 0.0),
                  fingers=("link_left_finger", "lf_rot", "lf_down", "link_right_finger", "rf_rot", "rf_down"),
                  stiffen=(1000.0, 20.0)),
        ready_at=(0.305, 0.0915), reach_mm=807, payload_kg=1.5, joints=6,
        max_opening_mm=75, joint_vmax=np.full(6, 1.5), cart_vmax=0.5, rot_vmax=3.0),
    "gen3": dict(
        folder="kinova_gen3", file="gen3.xml", name="Kinova Gen3 (7 joints)", maker="Kinova",
        base_body="base_link", arm_joints=_j(*[f"joint_{i}" for i in range(1, 8)]),
        add="robotiq", mount="pinch_site", ft="flange", camera="wrist",
        reach_mm=902, payload_kg=4, joints=7,
        joint_vmax=np.array([1.36, 1.36, 1.36, 1.36, 2.62, 2.62, 2.62]), cart_vmax=0.5, rot_vmax=1.75),
    "iiwa14": dict(
        folder="kuka_iiwa_14", file="iiwa14.xml", name="KUKA LBR iiwa 14 R820", maker="KUKA",
        base_body="base", arm_joints=_j(*[f"joint{i}" for i in range(1, 8)]),
        arm_actuators=[f"actuator{i}" for i in range(1, 8)],
        add="robotiq", mount="attachment_site", ft="flange", ready_at=(0.55, 0.2),
        reach_mm=820, payload_kg=14, joints=7,
        joint_vmax=np.radians([85, 85, 100, 75, 130, 135, 135]), cart_vmax=1.0, rot_vmax=2.0),
    "koch": dict(
        folder="low_cost_robot_arm", file="low_cost_robot_arm.xml", name="Low-Cost Robot Arm (Koch)",
        maker="Alexander Koch (open source)",
        base_body="base_link", turn=np.pi, arm_joints=_j("base_rotation", "pitch", "elbow", "wrist_pitch", "wrist_roll"),
        hand="gripper_static_finger", tcp=None,
        grip=dict(gripper="Servo-driven jaw", grip_actuator="gripper", grip_joint="gripper",
                  grip_open=-1.6, grip_closed=0.03, grip_ctrl_range=(-1.6, 0.032), grip_force_at="actuator",
                  fingers=("gripper_static_finger", "gripper_moving_finger")),
        reach_mm=300, payload_kg=0.2, joints=5, cam=(-0.04, -0.04),
        joint_vmax=np.full(5, 1.5), cart_vmax=0.3, rot_vmax=3.0),
    "sawyer": dict(
        folder="rethink_robotics_sawyer", file="sawyer.xml", name="Rethink Robotics Sawyer", maker="Rethink Robotics",
        base_body="base", arm_joints=_j(*[f"right_j{i}" for i in range(7)]),
        arm_actuators=[f"a{i}" for i in range(7)],
        add="robotiq", mount="attachment_site", ft="flange",
        reach_mm=1260, payload_kg=4, joints=7,
        joint_vmax=np.array([1.74, 1.328, 1.957, 1.957, 3.485, 3.485, 4.545]), cart_vmax=1.0, rot_vmax=2.0),
    "omy_3m": dict(
        folder="robotis_omy_3m", file="omy_3m.xml", name="ROBOTIS OMY-3M", maker="ROBOTIS",
        base_body="base_unit", arm_joints=_j(*[f"joint{i}" for i in range(1, 7)]),
        add="robotiq", mount=("link6", (0, -0.103, 0), (0.70710678, 0.70710678, 0, 0)),
        reach_mm=580, payload_kg=3, joints=6,
        joint_vmax=np.full(6, 1.5), cart_vmax=1.0, rot_vmax=2.0),
    "so101": dict(
        folder="robotstudio_so101", file="so101.xml", name="SO-101", maker="TheRobotStudio / Hugging Face",
        base_body="base", arm_joints=_j("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"),
        hand="gripper", tcp=None, camera="wrist_cam",
        grip=dict(gripper="Servo-driven jaw", grip_actuator="gripper", grip_joint="gripper",
                  grip_open=1.745, grip_closed=-0.175, grip_ctrl_range=(1.745, -0.175), grip_force_at="actuator",
                  fingers=("gripper", "moving_jaw_so101_v1")),
        reach_mm=300, payload_kg=0.2, joints=5, cam=(-0.04, -0.04),
        joint_vmax=np.full(5, 1.5), cart_vmax=0.3, rot_vmax=3.0),
    "devarm": dict(
        folder="seeed_rebot_devarm", file="seeed_rebot_devarm.xml", name="Seeed reBot DevArm", maker="Seeed Studio",
        base_body="base_link", arm_joints=_j(*[f"joint{i}" for i in range(1, 7)]),
        hand="link6", tcp=((0, 0, 0.11), (0, 0, 1), (0, 1, 0)),
        grip=dict(gripper="Parallel gripper", grip_actuator="joint_left", grip_also=("joint_right",),
                  grip_joint="joint_left", grip_open=0.05, grip_closed=0.0, grip_ctrl_range=(0.05, 0.0),
                  grip_force_at="actuator", fingers=("gripper_left", "gripper_right")),
        reach_mm=754, payload_kg=2.5, joints=6,
        max_opening_mm=98, joint_vmax=np.full(6, 1.5), cart_vmax=0.5, rot_vmax=3.0),
    "vx300s": dict(
        folder="trossen_vx300s", file="vx300s.xml", name="Trossen ViperX 300 S", maker="Trossen Robotics",
        base_body="base_link",
        arm_joints=_j("waist", "shoulder", "elbow", "forearm_roll", "wrist_angle", "wrist_rotate"),
        hand="gripper_link", tcp=((0.11, 0, 0), (1, 0, 0), (0, 1, 0)),
        grip=dict(gripper="Interbotix parallel gripper", grip_actuator="gripper", grip_joint="left_finger",
                  grip_open=0.057, grip_closed=0.021, grip_ctrl_range=(0.057, 0.021),
                  fingers=("left_finger_link", "right_finger_link")),
        reach_mm=750, payload_kg=0.75, joints=6,
        max_opening_mm=116, joint_vmax=np.array([30, 30, 30, 30, 30, 46]) * 2 * np.pi / 60, cart_vmax=0.5, rot_vmax=3.0),
    "wx250s": dict(
        folder="trossen_wx250s", file="wx250s.xml", name="Trossen WidowX 250 S", maker="Trossen Robotics",
        base_body="wx250s/base_link",
        arm_joints=_j("waist", "shoulder", "elbow", "forearm_roll", "wrist_angle", "wrist_rotate"),
        hand="wx250s/gripper_link", tcp=((0.11, 0, 0), (1, 0, 0), (0, 1, 0)),
        grip=dict(gripper="Interbotix parallel gripper", grip_actuator="gripper", grip_joint="left_finger",
                  grip_open=0.037, grip_closed=0.015, grip_ctrl_range=(0.037, 0.015),
                  fingers=("wx250s/left_finger_link", "wx250s/right_finger_link")),
        reach_mm=650, payload_kg=0.25, joints=6,
        max_opening_mm=74, joint_vmax=np.array([30, 30, 30, 30, 30, 46]) * 2 * np.pi / 60, cart_vmax=0.5, rot_vmax=3.0),
    "wxai": dict(
        folder="trossen_wxai", file="wxai_follower.xml", name="Trossen WidowX AI", maker="Trossen Robotics",
        base_body="base_link", arm_joints=_j(*[f"joint_{i}" for i in range(6)]),
        hand="link_6", tcp=((0.14, 0, 0), (1, 0, 0), (0, 1, 0)), camera="wrist_cam",
        grip=dict(gripper="WidowX AI parallel gripper", grip_actuator="right_carriage_joint",
                  grip_joint="right_carriage_joint", grip_open=0.044, grip_closed=0.0,
                  grip_ctrl_range=(0.044, -0.002),
                  fingers=("carriage_right", "gripper_right", "carriage_left", "gripper_left")),
        reach_mm=769, payload_kg=1.5, joints=6,
        max_opening_mm=80, joint_vmax=np.array([6.2832, 6.2832, 6.2832, 9.4248, 9.4248, 9.4248]), cart_vmax=0.5, rot_vmax=3.0),
    "so100": dict(
        folder="trs_so_arm100", file="so_arm100.xml", name="SO-ARM100", maker="TheRobotStudio",
        base_body="Base", turn=np.pi / 2, arm_joints=_j("Rotation", "Pitch", "Elbow", "Wrist_Pitch", "Wrist_Roll"),
        hand="Fixed_Jaw", tcp=None,
        grip=dict(gripper="Servo-driven jaw", grip_actuator="Jaw", grip_joint="Jaw",
                  grip_open=1.75, grip_closed=-0.174, grip_ctrl_range=(1.75, -0.174), grip_force_at="actuator",
                  fingers=("Fixed_Jaw", "Moving_Jaw")),
        reach_mm=300, payload_kg=0.2, joints=5, cam=(-0.04, -0.04),
        joint_vmax=np.full(5, 1.5), cart_vmax=0.3, rot_vmax=3.0),
    "lite6": dict(
        folder="ufactory_lite6", file="lite6_gripper_wide.xml", name="UFACTORY Lite 6", maker="UFACTORY",
        base_body="link_base", arm_joints=_j(*[f"joint{i}" for i in range(1, 7)]), arm_actuators=None,
        hand="gripper_body", tcp=((0, 0, 0.081), (0, 0, 1), (0, 1, 0)),
        grip=dict(gripper="Lite 6 gripper (wide fingers)", grip_actuator="gripper",
                  grip_joint="gripper_left_finger", grip_open=-0.008, grip_closed=0.0,
                  grip_ctrl_range=(-10.0, 10.0), grip_force_at="actuator",
                  fingers=("gripper_left_finger", "gripper_right_finger")),
        reach_mm=440, payload_kg=0.6, joints=6,
        max_opening_mm=38, joint_vmax=np.full(6, np.pi), cart_vmax=0.5, rot_vmax=3.0),
    "xarm7": dict(
        folder="ufactory_xarm7", file="xarm7.xml", name="UFACTORY xArm 7", maker="UFACTORY",
        base_body="link_base", arm_joints=_j(*[f"joint{i}" for i in range(1, 8)]),
        arm_actuators=[f"act{i}" for i in range(1, 8)],
        # TCP 15 mm back from UFACTORY's own (link_tcp, at the fingertips): its fingers close
        # through a tendon our tip finder doesn't follow
        hand="xarm_gripper_base_link", tcp=((0, 0, 0.157), (0, 0, 1), (0, 1, 0)), tcp_fixed=True,
        grip=dict(gripper="xArm Gripper", grip_actuator="gripper", grip_joint="left_driver_joint",
                  grip_open=0.0, grip_closed=0.85, grip_ctrl_open=0.0,
                  fingers=("left_finger", "right_finger", "left_inner_knuckle", "right_inner_knuckle",
                           "left_outer_knuckle", "right_outer_knuckle")),
        reach_mm=700, payload_kg=3.5, joints=7,
        max_opening_mm=85, joint_vmax=np.full(7, np.pi), cart_vmax=1.0, rot_vmax=3.0),
    "z1": dict(
        folder="unitree_z1", file="z1_gripper.xml", name="Unitree Z1", maker="Unitree Robotics",
        base_body="link00", arm_joints=_j(*[f"joint{i}" for i in range(1, 7)]),
        arm_actuators=[f"motor{i}" for i in range(1, 7)],
        hand="link06", tcp=None,
        grip=dict(gripper="Z1 gripper", grip_actuator="motorGripper", grip_joint="jointGripper",
                  grip_open=-1.518, grip_closed=0.0, grip_ctrl_range=(-1.518, 0.0), grip_force_at="actuator",
                  fingers=("link06", "gripperMover"), stiffen=(100.0, 2.0)),
        reach_mm=740, payload_kg=2, joints=6,
        joint_vmax=np.full(6, np.pi), cart_vmax=0.5, rot_vmax=3.0),
    "ur10e": dict(
        folder="universal_robots_ur10e", file="ur10e.xml", name="Universal Robots UR10e", maker="Universal Robots",
        base_body="base",
        arm_joints=_j("shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
                      "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"),
        arm_actuators=["shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3"],
        add="robotiq", mount="attachment_site", ft="flange",
        reach_mm=1300, payload_kg=12.5, joints=6,
        joint_vmax=np.radians([120, 120, 180, 180, 180, 180]), cart_vmax=1.0, rot_vmax=1.0),
}

# TCPs of the arms whose gripper is a single jaw swinging against a fixed one: set from the
# fingers' shapes when the model is first built (see _jaw_tcp).
_JAW_TCP: dict[str, tuple] = {}


def _quat_from_axes(z, y):
    z = np.asarray(z, float); z /= np.linalg.norm(z)
    y = np.asarray(y, float); y = y - (y @ z) * z; y /= np.linalg.norm(y)
    x = np.cross(y, z)
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.column_stack([x, y, z]).flatten())
    return q


def _load(robot):
    from .scene import ASSETS
    A = ARMS[robot]
    return mujoco.MjSpec.from_file(str(ASSETS / A["folder"] / A["file"]))


def build(world, robot: str, mount_site: str = "robot_mount", prefix: str = ""):
    """Attach one of ARMS at a mount site, with its gripper, TCP, wrist camera and (where the
    arm senses force) force/torque sensors."""
    from .scene import ASSETS, _match_options, _set_material
    A = ARMS[robot]
    P = profile(robot)
    arm = _load(robot)
    specs = [arm]
    # Name the actuators Menagerie leaves unnamed, by their joint (UFACTORY Lite 6).
    for a in arm.actuators:
        if not a.name:
            a.name = "act_" + a.target
    fingers = set(A.get("grip", {}).get("fingers", ()))
    hand_body = None
    if A.get("add"):
        if isinstance(A["mount"], str):
            site = arm.site(A["mount"])
        else:
            body, pos, quat = A["mount"]
            site = arm.body(body).add_site(name="tool_mount", pos=list(pos), quat=list(quat),
                                           size=[0.004] * 3, group=5)
        if A["add"] == "robotiq":
            grip = mujoco.MjSpec.from_file(str(ASSETS / "robotiq_2f85" / "2f85.xml"))
            m = grip.body("base_mount")
            m.add_site(name="ft_site", pos=[0, 0, 0], size=[0.004] * 3, group=5)
            hand_body, hand_name = grip.body("base"), "gripper/"
            for g in grip.geoms:
                if g.classname.name in ("pad_box1", "pad_box2"):
                    _set_material(g, "rubber_pad")
                elif g.contype or g.conaffinity:
                    _set_material(g, "robot")
            specs.append(grip)
            # The camera beside the gripper, as on the UR5e (unless the arm has its own).
            if not A.get("camera"):
                _camera(hand_body, [-0.085, 0.0, 0.07], [0.0, 0.0, 0.20], (0, -1, 0))
            _match_options(arm, grip, world=world)
            for s in (arm, grip):
                for b in s.bodies:
                    b.gravcomp = 1.0
            names = [b.name for b in grip.bodies if b.name and b.name != "world"]
            site.attach_body(m, "gripper/", "")
            # The flange's own collision shape reaches round the gripper's base on some arms (the
            # OMY's): the gripper's links don't collide with the link it is bolted to.
            for n in names:
                arm.add_exclude(bodyname1=site.parent.name, bodyname2="gripper/" + n)
        else:     # the Franka Hand, as on the Panda
            hand = mujoco.MjSpec.from_file(str(ASSETS / "franka_emika_panda" / "hand.xml"))
            for g in hand.geoms:
                if g.classname.name.startswith("fingertip_pad_collision"):
                    _set_material(g, "rubber_pad")
                elif g.contype or g.conaffinity:
                    _set_material(g, "robot")
            act = hand.actuator("actuator8")
            kp, kv = 3000.0, 150.0
            act.gainprm[0] = 0.04 * kp / 255
            act.biasprm[1], act.biasprm[2] = -kp, -kv
            act.forcerange = [-140, 140]
            h = hand.body("hand")
            h.add_site(name="tcp", pos=[0, 0, 0.1034], size=[0.004] * 3, group=5)
            h.add_site(name="ft_site", pos=[0, 0, 0], size=[0.004] * 3, group=5)
            _camera(h, [-0.075, 0.0, 0.04], [0.0, 0.0, 0.22], (0, -1, 0))
            _match_options(arm, hand, world=world)
            for s in (arm, hand):
                for b in s.bodies:
                    b.gravcomp = 1.0
            site.attach_body(h, "hand/", "")
        for g in arm.geoms:
            if g.contype or g.conaffinity:
                _set_material(g, "robot")
    else:
        hb = arm.body(A["hand"])
        pos, z, y = _jaw_tcp(robot) if A["tcp"] is None else _tip_tcp(robot)
        q = _quat_from_axes(z, y)
        hb.add_site(name="tcp", pos=list(pos), quat=list(q), size=[0.004] * 3, group=5)
        # The camera in the TCP frame: behind the fingers and to the side (-x), looking along them.
        R = np.zeros(9); mujoco.mju_quat2Mat(R, q); R = R.reshape(3, 3)
        bx, bz = A.get("cam", (-0.07, -0.07))
        cpos = np.asarray(pos) + R @ np.array([bx, 0, bz])
        target = np.asarray(pos) + R @ np.array([0, 0, 0.12])
        if not A.get("camera"):
            _camera(hb, cpos, target, -R[:, 1])
        for g in arm.geoms:
            if g.contype or g.conaffinity:
                _set_material(g, "rubber_pad" if g.parent.name in fingers and g.parent.name != A["hand"]
                              or g.parent.name in fingers and A["tcp"] is None else "robot")
        _match_options(arm, world=world)
        for b in arm.bodies:
            b.gravcomp = 1.0
        # A stiffer gripper servo where Menagerie's squeezes too gently to hold anything: the
        # motor's force limit decides the grip (as for the Franka Hand and the PiPER).
        stiff = A["grip"].get("stiffen")
        if stiff:
            a = arm.actuator(A["grip"]["grip_actuator"])
            a.gainprm[0] = stiff[0]
            a.biasprm[1], a.biasprm[2] = -stiff[0], -stiff[1]
    # The base stands on the mount: Menagerie's files for the xArm 7 and UR10e place it in their
    # own scenes (12 cm up; turned half a turn).
    root = arm.body(A["base_body"])
    root.pos, root.quat = [0, 0, 0], [1, 0, 0, 0]
    if A.get("turn"):
        # The arm faces the table from a base turned on its mount; poses stay in a frame whose x
        # points over the table, as for every other arm.
        t = -A["turn"] / 2
        arm.body(A["base_body"]).add_body(name="table_frame", quat=[np.cos(t), 0, 0, np.sin(t)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        world.site(mount_site).attach_body(arm.body(A["base_body"]), prefix, "")
    if P.get("ft_site"):
        world.add_sensor(name=prefix + "ft_force", type=mujoco.mjtSensor.mjSENS_FORCE,
                         objtype=mujoco.mjtObj.mjOBJ_SITE, objname=prefix + P["ft_site"])
        world.add_sensor(name=prefix + "ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE,
                         objtype=mujoco.mjtObj.mjOBJ_SITE, objname=prefix + P["ft_site"])


def _camera(body, cam_pos, target, xaxis):
    """A RealSense-style camera on the gripper, looking at target (body frame), image x along xaxis."""
    cam_pos, target = np.asarray(cam_pos, float), np.asarray(target, float)
    f = target - cam_pos
    f /= np.linalg.norm(f)
    x = np.asarray(xaxis, float)
    x = x - (x @ f) * f
    x /= np.linalg.norm(x)
    y = np.cross(-f, x)       # MuJoCo cameras look along their -z axis
    cam = body.add_camera(name="wrist", pos=cam_pos.tolist(), fovy=70)
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [*x, *y]


def _tip_tcp(robot):
    """A two-finger gripper's TCP: midway between the fingers (the middle of their last 3 cm),
    15 mm back from the fingertips (their farthest point along ARMS's z, fingers closed)."""
    if robot in _JAW_TCP:
        return _JAW_TCP[robot]
    A = ARMS[robot]
    pos, z, y = (np.asarray(v, float) for v in A["tcp"])
    if A.get("tcp_fixed"):
        return pos, z, y
    m = _load(robot).compile()
    d = mujoco.MjData(m)
    if m.nkey:
        d.qpos[:] = m.key_qpos[0]
    g = A["grip"]
    hand = m.body(A["hand"]).id
    _set_gripper(m, d, g["grip_joint"], g["grip_closed"])
    mujoco.mj_kinematics(m, d)
    Hp, HR = d.xpos[hand], d.xmat[hand].reshape(3, 3)
    fingers = {m.body(b).id for b in g["fingers"]} - {hand}
    z = z / np.linalg.norm(z)
    pts = np.vstack([(_geom_points(m, d, gi) - Hp) @ HR for gi in range(m.ngeom)
                     if m.geom_bodyid[gi] in fingers and (m.geom_contype[gi] or m.geom_conaffinity[gi])])
    tip = float(np.max(pts @ z))
    # across the fingers, the middle of their shapes near the tips
    near = pts[pts @ z > tip - 0.03]
    mid = (near.min(0) + near.max(0)) / 2
    pos = mid - (mid @ z) * z + (tip - 0.015) * z
    _JAW_TCP[robot] = (pos, z, y)
    return _JAW_TCP[robot]


def _set_gripper(m, d, joint, q):
    """Put a gripper's joint at q, and the joints coupled to it (joint equalities) where it puts them."""
    known = {m.joint(joint).id}
    d.qpos[m.joint(joint).qposadr[0]] = q
    for _ in range(4):
        for e in range(m.neq):
            if m.eq_type[e] != mujoco.mjtEq.mjEQ_JOINT or m.eq_obj2id[e] < 0:
                continue
            j1, j2 = m.eq_obj1id[e], m.eq_obj2id[e]
            c0, c1 = m.eq_data[e, 0], m.eq_data[e, 1]
            a1, a2 = m.jnt_qposadr[j1], m.jnt_qposadr[j2]
            if j2 in known and j1 not in known:
                d.qpos[a1] = c0 + c1 * d.qpos[a2]
                known.add(j1)
            elif j1 in known and j2 not in known and c1:
                d.qpos[a2] = (d.qpos[a1] - c0) / c1
                known.add(j2)


def _geom_points(m, d, gi):
    """A collision shape's points in world coordinates (a mesh's vertices, a primitive's box corners)."""
    R = d.geom_xmat[gi].reshape(3, 3)
    if m.geom_type[gi] == mujoco.mjtGeom.mjGEOM_MESH:
        mid = m.geom_dataid[gi]
        v = m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid] + m.mesh_vertnum[mid]]
    else:
        e = m.geom_size[gi].copy()
        t = m.geom_type[gi]
        if t == mujoco.mjtGeom.mjGEOM_SPHERE:
            e = np.full(3, e[0])
        elif t in (mujoco.mjtGeom.mjGEOM_CAPSULE, mujoco.mjtGeom.mjGEOM_CYLINDER):
            e = np.array([e[0], e[0], e[1] + (e[0] if t == mujoco.mjtGeom.mjGEOM_CAPSULE else 0)])
        v = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * e
    return d.geom_xpos[gi] + v @ R.T


def _jaw_tcp(robot):
    """The TCP of a jaw gripper (one jaw swinging against a fixed one), from the model: on the
    wrist's last (roll) axis, 15 mm back from the fixed jaw's tip; z along that axis, out of the
    gripper; y the way the jaw opens. (On a five-joint arm only a TCP on the roll axis can point
    straight down at any turn of the wrist.)"""
    if robot in _JAW_TCP:
        return _JAW_TCP[robot]
    A = ARMS[robot]
    m = _load(robot).compile()
    d = mujoco.MjData(m)
    if m.nkey:
        d.qpos[:] = m.key_qpos[0]
    g = A["grip"]
    jaw_j = m.joint(g["grip_joint"])
    roll = m.joint(A["arm_joints"][-1])
    hand = m.body(A["hand"]).id

    def pts(b, q):
        d.qpos[jaw_j.qposadr[0]] = q
        mujoco.mj_kinematics(m, d)
        Hp, HR = d.xpos[hand], d.xmat[hand].reshape(3, 3)
        return np.vstack([(_geom_points(m, d, gi) - Hp) @ HR for gi in range(m.ngeom)
                          if m.geom_bodyid[gi] == b and (m.geom_contype[gi] or m.geom_conaffinity[gi])])

    # the roll axis in the hand's frame (the joint sits on the hand body or its parent)
    mujoco.mj_kinematics(m, d)
    HR = d.xmat[hand].reshape(3, 3)
    jb = roll.bodyid[0]
    axis = HR.T @ (d.xmat[jb].reshape(3, 3) @ roll.axis)
    anchor = HR.T @ (d.xpos[jb] + d.xmat[jb].reshape(3, 3) @ roll.pos - d.xpos[hand])
    fixed = pts(hand, g["grip_open"])
    if (fixed - anchor).mean(0) @ axis < 0:
        axis = -axis
    z = axis / np.linalg.norm(axis)
    tip = float(np.max((fixed - anchor) @ z))
    pos = anchor + (tip - 0.015) * z
    y = pts(jaw_j.bodyid[0], g["grip_open"]).mean(0) - pts(jaw_j.bodyid[0], g["grip_closed"]).mean(0)
    y = y - (y @ z) * z
    y /= np.linalg.norm(y)
    _JAW_TCP[robot] = (pos, z, y)
    return _JAW_TCP[robot]


def profile(robot: str) -> dict:
    """The robot's profile (as wetlabsim.scene.ROBOTS has it), names as in the compiled model."""
    A = ARMS[robot]
    n = len(A["arm_joints"])
    P = {
        "name": A["name"], "maker": A["maker"], "menagerie": A["folder"],
        "arm_joints": list(A["arm_joints"]),
        "arm_actuators": list(A.get("arm_actuators") or (
            ["act_" + j for j in A["arm_joints"]] if "arm_actuators" in A else A["arm_joints"])),
        "base_body": A["base_body"],
        # the arm's own wrist camera where its model has one (Kinova's vision module, ARX's, the
        # SO-101's and the WidowX AI's), else ours
        "cameras": {"overhead": "overhead",
                    "wrist": A.get("camera") or {"robotiq": "gripper/wrist", "franka_hand": "hand/wrist"}.get(A.get("add"), "wrist"),
                    "side": "side"},
        "mount_quat": "1 0 0 0" if not A.get("turn") else
                      f"{np.cos(A['turn'] / 2):.8f} 0 0 {np.sin(A['turn'] / 2):.8f}",
        "joint_vmax": np.asarray(A.get("joint_vmax") if A.get("joint_vmax") is not None else np.full(n, 1.0)),
        "joint_amax": np.full(n, A.get("joint_amax", 10.0)),
        "cart_vmax": A["cart_vmax"], "rot_vmax": A["rot_vmax"],
        "home_q": np.asarray(A.get("home_q", np.zeros(n)), float),
        "ready_q": np.asarray(READY.get(robot, np.zeros(n)), float),
    }
    if A.get("turn"):
        P["frame_body"] = "table_frame"
    if A.get("add") == "robotiq":
        P.update(ROBOTIQ)
        flange = ("gripper/ft_site", "gripper/base_mount")
    elif A.get("add") == "franka_hand":
        P.update(FRANKA_HAND)
        flange = ("hand/ft_site", "hand/hand")
    else:
        g = {k: v for k, v in A["grip"].items() if k not in ("fingers", "stiffen")}
        P.update(g)
        P["tcp_site"] = "tcp"
        P["max_opening_mm"] = A.get("max_opening_mm", 0)
        flange = None
    if A.get("ft") and flange:
        P["ft_site"], P["ft_body"] = flange
        P["ft_noise"] = (0.0, 0.0)
        P["ft_bias"] = (0.0, 0.0)
        P.update(NO_REFLEX)
    else:
        P["ft_site"] = None
    return P


# Starting poses, solved once on each model (playground/tools/solve_menagerie_ready.py): the gripper straight down
# in front of the base.
READY: dict[str, list] = {
    "arx_l5": [0.0, 1.7222, 1.3598, -1.2083, -0.0, 0.0],
    "crx5ia": [0.2647, 0.178, -0.1503, 0.0001, -1.2423, 1.3062],
    "rizon4": [-0.1245, -0.3888, 0.3237, 2.3504, -0.2892, 1.1341, -1.131],
    "rizon4s": [-0.1391, -0.4092, 0.3379, 2.2844, -0.2863, 1.085, -1.1434],
    "fr3": [0.0504, 0.0382, -0.0497, -2.6415, 0.0043, 2.6796, 0.7823],
    "fr3_v2": [0.0504, 0.0382, -0.0497, -2.6415, 0.0043, 2.6796, 0.7823],
    "yam": [-0.0, 1.8701, 1.5346, -1.2353, -0.0001, -0.0002],
    "gen3": [0.1609, 0.5217, 2.9102, -1.7248, 0.1451, -0.9118, 1.4409],
    "iiwa14": [-0.2457, 0.5881, 0.3416, -1.6276, -0.228, 0.9654, -1.3976],
    "koch": [0.0078, -0.4696, -0.5707, -1.6718, 0.0078],
    "sawyer": [-0.018, -1.0719, -0.3868, 1.82, 0.239, 0.8688, 4.3692],
    "omy_3m": [0.4003, -0.2363, 2.1117, -0.3046, 1.5708, -0.4003],
    "so101": [-0.0015, -0.7281, 0.8276, 1.4713, -1.5236],
    "devarm": [0.0001, -2.1084, -1.9671, 1.4292, 0.0004, -0.0001],
    "vx300s": [0.0001, 0.1273, 0.2603, -0.0004, 1.1825, 0.0005],
    "wx250s": [-0.0, 0.1743, 0.201, -0.0, 1.1955, 0.0],
    "wxai": [0.0001, 2.0108, 1.8128, -1.3728, -0.0, 0.0001],
    "so100": [-0.0, -2.3647, 2.4504, 1.485, -1.5708],
    "lite6": [0.0, 0.5753, 0.6835, 0.0, 0.1082, -0.0],
    "xarm7": [-0.0, -0.2135, 0.0, 0.5097, 0.0, 0.7231, -0.0],
    "z1": [0.0, 1.997, -1.71, 1.2838, -0.0, -1.5708],
    "ur10e": [-0.3219, -1.5989, 2.3459, -2.3178, -1.5708, -0.3219],
}


def site_tool(robot: str) -> str:
    """The "Tool settings" lines of the arm's site sheet (agent/<robot>/SITE.md, playground/site.py)."""
    A, P = ARMS[robot], profile(robot)
    lines = [f"- End effector: {P['gripper']}, on the last joint's flange."]
    if A.get("tcp", 0) is None:
        lines.append("- TCP: on the wrist-roll (last joint) axis, 15 mm back from the tip of the fixed jaw.")
    else:
        lines.append("- TCP: the point between the two finger pads, 15 mm back from the fingertips.")
    lines.append("- Tool orientation convention: the TCP's z axis points out of the gripper, between the\n"
                 "  fingers; the fingers close along the TCP's y axis. TCP poses of\n"
                 "  `[x, y, z, 3.14159, 0, 0]` and `[x, y, z, 0, 3.14159, 0]` both point the gripper straight\n"
                 "  down with the fingers closing along the base y axis.")
    if A["joints"] < 6:
        lines.append("- The arm has five joints: it can't point the gripper in every direction at every position.")
    lines.append("- Wrist force/torque reading at the flange." if P.get("ft_site") else "- No force/torque sensing.")
    return "\n".join(lines)


# Each arm's steel stand when it stands off its table (playground/world.py STANDS): the box its
# base covers, as (x, y) of its middle from the mount and its half size along the robot's x and y
# (m), measured on each model's base.
STANDS = {
    "arx_l5": [(0.0, 0.0, 0.06, 0.06)], "crx5ia": [(-0.056, 0.0, 0.13, 0.074)],
    "rizon4": [(0.0, 0.0, 0.082, 0.082)], "rizon4s": [(0.0, 0.0, 0.082, 0.082)],
    "fr3": [(-0.041, 0.0, 0.115, 0.095)], "fr3_v2": [(-0.041, 0.0, 0.115, 0.095)],
    "yam": [(0.0, 0.0, 0.035, 0.1)], "gen3": [(0.0, 0.0, 0.046, 0.046)],
    "iiwa14": [(-0.019, 0.0, 0.141, 0.121)], "koch": [(-0.04, -0.012, 0.041, 0.08)],
    "sawyer": [(0.0, 0.0, 0.105, 0.105)], "omy_3m": [(0.0, 0.0, 0.085, 0.085)],
    "so101": [(0.017, 0.0, 0.048, 0.055)], "devarm": [(0.0, 0.0, 0.072, 0.102)],
    "vx300s": [(-0.048, 0.0, 0.15, 0.102)], "wx250s": [(-0.04, 0.0, 0.117, 0.077)],
    "wxai": [(-0.007, 0.0, 0.044, 0.032)], "so100": [(0.028, 0.0, 0.044, 0.055)],
    "lite6": [(-0.01, 0.0, 0.072, 0.065)], "xarm7": [(-0.015, 0.0, 0.078, 0.063)],
    "z1": [(0.0, 0.0, 0.054, 0.053)], "ur10e": [(0.0, 0.0, 0.095, 0.095)],
}
# Small arms keep less room clear around their base (playground/world.py BASE_CLEARANCE_BY).
SMALL = ("arx_l5", "yam", "gen3", "koch", "so101", "so100", "wxai", "z1", "lite6", "wx250s")
