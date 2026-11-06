"""Builds the bench scene: a robot arm with a parallel gripper, tube racks and tubes.

Two robots are available: a Franka Emika Panda with the Franka Hand (the default) and a
UR5e with a Robotiq 2F-85. Pick one with WETLAB_ROBOT=franka|ur5e. The robot models come
from MuJoCo Menagerie (see wetlabsim/assets/*/LICENSE). Everything else (bench, racks,
tubes, cameras) is defined here.
"""
from __future__ import annotations

import os
import pathlib
import warnings

import mujoco
import numpy as np

ASSETS = pathlib.Path(__file__).parent / "assets"

BENCH_HEIGHT = 0.90          # bench top, world z (m)
ROBOT_BASE = (0.0, 0.0, BENCH_HEIGHT)

# 15 ml conical tube (Falcon style), simplified to a cylinder with a cap.
TUBE_RADIUS = 0.0085
TUBE_HALF_LEN = 0.055
CAP_RADIUS = 0.0095
CAP_HALF_LEN = 0.006

# Tube rack: 2 rows x 4 slots.
RACK_ROWS, RACK_COLS = 2, 4
SLOT = 0.024                 # inner slot width
WALL = 0.006
RACK_WALL_H = 0.045          # wall height above rack floor
RACK_FLOOR = 0.006           # floor thickness
PITCH = SLOT + WALL

# Where the racks sit, in the robot base frame (x forward, y left, z up).
RACKS = {
    "rack_a": (0.45, -0.18),
    "rack_b": (0.45, 0.18),
}
# Starting tubes: (rack, row, col, cap colour name, rgba)
TUBES = [
    ("rack_a", 0, 0, "red", (0.85, 0.15, 0.15, 1)),
    ("rack_a", 0, 2, "blue", (0.15, 0.35, 0.85, 1)),
    ("rack_a", 1, 1, "green", (0.15, 0.7, 0.25, 1)),
]


def slot_center(rack: str, row: int, col: int) -> np.ndarray:
    """Slot centre in robot base frame (x, y), top-of-floor z."""
    rx, ry = RACKS[rack]
    x = rx + (row - (RACK_ROWS - 1) / 2) * PITCH
    y = ry + (col - (RACK_COLS - 1) / 2) * PITCH
    return np.array([x, y, RACK_FLOOR])


def _rack_xml(name: str, x: float, y: float) -> str:
    """A rack is a floor plate plus a grid of thin walls forming slots."""
    w = RACK_ROWS * PITCH + WALL      # extent along x
    l = RACK_COLS * PITCH + WALL      # extent along y
    z0 = BENCH_HEIGHT
    parts = [
        f'<geom name="{name}_floor" type="box" size="{w/2} {l/2} {RACK_FLOOR/2}" '
        f'pos="0 0 {RACK_FLOOR/2}" material="rack"/>'
    ]
    wz = RACK_FLOOR + RACK_WALL_H / 2
    for i in range(RACK_ROWS + 1):     # walls running along y
        px = -w / 2 + WALL / 2 + i * PITCH
        parts.append(f'<geom type="box" size="{WALL/2} {l/2} {RACK_WALL_H/2}" pos="{px} 0 {wz}" material="rack"/>')
    for j in range(RACK_COLS + 1):     # walls running along x
        py = -l / 2 + WALL / 2 + j * PITCH
        parts.append(f'<geom type="box" size="{w/2} {WALL/2} {RACK_WALL_H/2}" pos="0 {py} {wz}" material="rack"/>')
    return f'<body name="{name}" pos="{x} {y} {z0}">' + "".join(parts) + "</body>"


def _tube_xml(i: int, rack: str, row: int, col: int, colour: str, rgba) -> str:
    c = slot_center(rack, row, col)
    z = BENCH_HEIGHT + RACK_FLOOR + TUBE_HALF_LEN + 0.0005
    r = " ".join(str(v) for v in rgba)
    return (
        f'<body name="tube_{colour}" pos="{c[0]} {c[1]} {z}">'
        f'<freejoint name="tube_{colour}_joint"/>'
        f'<geom name="tube_{colour}_body" type="cylinder" size="{TUBE_RADIUS} {TUBE_HALF_LEN}" '
        f'material="tube" mass="0.02" condim="4" friction="1 0.01 0.001"/>'
        f'<geom name="tube_{colour}_cap" type="cylinder" size="{CAP_RADIUS} {CAP_HALF_LEN}" '
        f'pos="0 0 {TUBE_HALF_LEN - CAP_HALF_LEN + 0.004}" rgba="{r}" mass="0.004" condim="4" friction="1 0.01 0.001"/>'
        f'<geom type="cylinder" size="{TUBE_RADIUS*0.8} {TUBE_HALF_LEN*0.5}" pos="0 0 {-TUBE_HALF_LEN*0.45}" '
        f'rgba="0.95 0.85 0.3 0.6" contype="0" conaffinity="0" mass="0"/>'
        f"</body>"
    )


def _look_at_axes(pos, target, up=(0, 0, 1)):
    """xyaxes for a MuJoCo camera at pos looking at target."""
    pos, target, up = map(np.asarray, (pos, target, up))
    f = target - pos
    f = f / np.linalg.norm(f)
    x = np.cross(f, up)
    if np.linalg.norm(x) < 1e-6:
        x = np.array([1.0, 0, 0]) if abs(f[0]) < 0.9 else np.array([0, 1.0, 0])
        x = np.cross(f, np.cross(x, f))
    x = x / np.linalg.norm(x)
    y = np.cross(x, f)
    return " ".join(f"{v:.5f}" for v in (*x, *y))


def _world_xml(mount_quat: str) -> str:
    bh = BENCH_HEIGHT
    racks = "".join(_rack_xml(n, *p) for n, p in RACKS.items())
    tubes = "".join(_tube_xml(i, *t) for i, t in enumerate(TUBES))
    over_pos = (0.75, 0.0, bh + 1.0)
    side_pos = (1.35, -0.95, bh + 0.75)
    return f"""
<mujoco model="wetlab_bench">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.002" integrator="implicitfast" cone="elliptic" impratio="10"/>
  <visual>
    <global offwidth="1280" offheight="960"/>
    <headlight ambient="0.2 0.2 0.2" diffuse="0.25 0.25 0.25" specular="0.05 0.05 0.05"/>
    <quality shadowsize="2048"/>
  </visual>
  <asset>
    <texture name="floor" type="2d" builtin="checker" rgb1="0.55 0.57 0.6" rgb2="0.5 0.52 0.55" width="300" height="300"/>
    <material name="floor" texture="floor" texrepeat="8 8" reflectance="0.05"/>
    <material name="benchtop" rgba="0.72 0.74 0.73 1"/>
    <material name="steel" rgba="0.6 0.62 0.65 1" specular="0.6"/>
    <material name="rack" rgba="0.95 0.95 0.97 1"/>
    <material name="tube" rgba="0.88 0.92 0.95 0.55" specular="0.8"/>
  </asset>
  <worldbody>
    <light pos="0.4 0.3 3" dir="0 -0.1 -1" diffuse="0.45 0.45 0.45" specular="0.1 0.1 0.1" castshadow="true"/>
    <light pos="-1 -1 2.5" dir="0.4 0.4 -1" diffuse="0.25 0.25 0.25" castshadow="false"/>
    <geom name="floor" type="plane" size="4 4 0.1" material="floor"/>
    <body name="bench" pos="0.35 0 0">
      <geom name="benchtop" type="box" size="0.55 0.6 0.02" pos="0 0 {bh-0.02}" material="benchtop"/>
      <geom type="box" size="0.03 0.03 {(bh-0.04)/2}" pos="0.5 0.55 {(bh-0.04)/2}" material="steel"/>
      <geom type="box" size="0.03 0.03 {(bh-0.04)/2}" pos="0.5 -0.55 {(bh-0.04)/2}" material="steel"/>
      <geom type="box" size="0.03 0.03 {(bh-0.04)/2}" pos="-0.5 0.55 {(bh-0.04)/2}" material="steel"/>
      <geom type="box" size="0.03 0.03 {(bh-0.04)/2}" pos="-0.5 -0.55 {(bh-0.04)/2}" material="steel"/>
    </body>
    <site name="robot_mount" pos="{ROBOT_BASE[0]} {ROBOT_BASE[1]} {ROBOT_BASE[2]}" quat="{mount_quat}"/>
    <camera name="overhead" pos="{over_pos[0]} {over_pos[1]} {over_pos[2]}"
            xyaxes="{_look_at_axes(over_pos, (0.42, 0.0, bh), up=(-1, 0, 0))}" fovy="50"/>
    <camera name="side" pos="{side_pos[0]} {side_pos[1]} {side_pos[2]}"
            xyaxes="{_look_at_axes(side_pos, (0.3, 0.0, bh + 0.15))}" fovy="45"/>
    {racks}
    {tubes}
  </worldbody>
</mujoco>
"""


# Everything that differs between the two robots. Joint, actuator, site and camera names
# are as they appear in the compiled model.
ROBOTS = {
    "franka": {
        "name": "Franka Emika Panda", "gripper": "Franka Hand",
        "arm_joints": [f"joint{i}" for i in range(1, 8)],
        "arm_actuators": [f"actuator{i}" for i in range(1, 8)],
        "home_q": np.array([0.0, 0.0, 0.0, -1.5708, 0.0, 1.5708, 0.7854]),
        # gripper pointing down over the bench, fingers closing along y
        "ready_q": np.array([0.0, -0.5, 0.0, -2.3, 0.0, 1.8, 0.7854]),
        "tcp_site": "tcp", "ft_site": "ft_site", "ft_body": "hand", "base_body": "link0",
        "grip_actuator": "actuator8", "grip_joint": "finger_joint1",
        "grip_open": 0.04,           # finger joint travel (m) when fully open
        "grip_ctrl_open": 255.0,     # actuator command for fully open (0 is closed)
        "max_opening_mm": 80,
        "cameras": {"overhead": "overhead", "wrist": "wrist", "side": "side"},
        "mount_quat": "1 0 0 0",
    },
    "ur5e": {
        "name": "Universal Robots UR5e", "gripper": "Robotiq 2F-85",
        "arm_joints": ["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
                       "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"],
        "arm_actuators": ["shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3"],
        "home_q": np.array([0.0, -1.5708, 1.5708, -1.5708, -1.5708, 0.0]),
        "ready_q": np.array([0.0, -1.2, 1.6, -1.97, -1.5708, 0.0]),
        "tcp_site": "gripper/pinch", "ft_site": "gripper/ft_site", "ft_body": "gripper/base_mount",
        "base_body": "base",
        "grip_actuator": "gripper/fingers_actuator", "grip_joint": "gripper/right_driver_joint",
        "grip_open": 0.0, "grip_closed": 0.8,   # driver joint (rad)
        "grip_ctrl_open": 0.0,
        "max_opening_mm": 85,
        "cameras": {"overhead": "overhead", "wrist": "gripper/wrist", "side": "side"},
        "mount_quat": "0 0 0 1",
    },
}
DEFAULT_ROBOT = "franka"


def robot_name(robot: str | None = None) -> str:
    robot = robot or os.environ.get("WETLAB_ROBOT", DEFAULT_ROBOT)
    if robot not in ROBOTS:
        raise ValueError(f"unknown robot {robot!r}; choose from {list(ROBOTS)}")
    return robot


def profile(robot: str | None = None) -> dict:
    return ROBOTS[robot_name(robot)]


def _add_wrist_camera(body, cam_pos, target):
    """A RealSense-style camera on the gripper, looking along the fingers."""
    cam_pos, target = np.asarray(cam_pos, float), np.asarray(target, float)
    f = target - cam_pos
    f /= np.linalg.norm(f)
    x = np.array([0.0, -1.0, 0])
    y = np.cross(-f, x)   # MuJoCo cameras look along their -z axis
    cam = body.add_camera(name="wrist", pos=cam_pos.tolist(), fovy=70)
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [*x, *y]


def _match_options(*specs):
    for spec in specs:  # match the world's solver options so attaching is silent
        spec.option.impratio = 10
        spec.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
        spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST


def _franka(world):
    arm = mujoco.MjSpec.from_file(str(ASSETS / "franka_emika_panda" / "panda.xml"))
    # Grippy finger pads that resist twisting, like the silicone pads on the UR's gripper.
    for g in arm.geoms:
        if g.classname.name.startswith("fingertip_pad_collision"):
            g.condim = 4
            g.friction = [1.0, 0.05, 0.001]
    # Menagerie's hand servo is soft (100 N/m: about 1 N of squeeze on a tube), too weak to
    # hold or let go of things reliably. Stiffen it so the force limit decides the grip:
    # up to 70 N continuous, as on the real hand (the tendon force splits over both fingers).
    act = arm.actuator("actuator8")
    kp, kv = 3000.0, 150.0
    act.gainprm[0] = 0.04 * kp / 255      # command 0..255 maps to 0..40 mm per finger
    act.biasprm[1], act.biasprm[2] = -kp, -kv
    act.forcerange = [-140, 140]
    hand = arm.body("hand")
    # Tool centre point between the fingertips (Franka's default TCP is 103.4 mm past the flange).
    hand.add_site(name="tcp", pos=[0, 0, 0.1034], size=[0.004] * 3, group=5)
    # The Panda estimates the external wrench at the flange from its joint torque sensors;
    # measure it where the hand bolts on.
    hand.add_site(name="ft_site", pos=[0, 0, 0], size=[0.004] * 3, group=5)
    _add_wrist_camera(hand, [-0.075, 0.0, 0.04], [0.0, 0.0, 0.22])
    for body in arm.bodies:   # Franka's controller compensates for gravity
        body.gravcomp = 1.0
    _match_options(arm)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        world.site("robot_mount").attach_body(arm.body("link0"), "", "")
    return "ft_site"


def _ur5e(world):
    arm = mujoco.MjSpec.from_file(str(ASSETS / "universal_robots_ur5e" / "ur5e.xml"))
    grip = mujoco.MjSpec.from_file(str(ASSETS / "robotiq_2f85" / "2f85.xml"))

    # Silicone finger pads: grippy, with some resistance to twisting (the stock
    # pads let round tubes spin between the fingers).
    for g in grip.geoms:
        if g.classname.name in ("pad_box1", "pad_box2"):
            g.condim = 4
            g.friction = [1.0, 0.05, 0.001]

    # Force/torque sensing site where the gripper bolts onto the wrist flange.
    mount = grip.body("base_mount")
    mount.add_site(name="ft_site", pos=[0, 0, 0], size=[0.004] * 3, group=5)
    _add_wrist_camera(grip.body("base"), [-0.085, 0.0, 0.07], [0.0, 0.0, 0.20])

    # Real UR arms compensate for gravity in their controller; do the same here.
    for spec in (arm, grip):
        for body in spec.bodies:
            body.gravcomp = 1.0
    _match_options(arm, grip)

    arm.site("attachment_site").attach_body(mount, "gripper/", "")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        world.site("robot_mount").attach_body(arm.body("base"), "", "")
    return "gripper/ft_site"


def build_model(robot: str | None = None) -> mujoco.MjModel:
    robot = robot_name(robot)
    world = mujoco.MjSpec.from_string(_world_xml(ROBOTS[robot]["mount_quat"]))
    ft_site = _franka(world) if robot == "franka" else _ur5e(world)
    # Wrist force/torque sensor (UR5e: built in at the flange; Panda: estimated from joint torques).
    world.add_sensor(name="ft_force", type=mujoco.mjtSensor.mjSENS_FORCE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    world.add_sensor(name="ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()
