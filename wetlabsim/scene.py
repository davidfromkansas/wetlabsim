"""Builds the bench scene: a robot arm with a parallel gripper, tube racks and tubes.

Two robots are available: a Franka Emika Panda with the Franka Hand (the default) and a
UR5e with a Robotiq 2F-85. Pick one with WETLAB_ROBOT=franka|ur5e. The robot models come
from MuJoCo Menagerie (see wetlabsim/assets/*/LICENSE). The tubes, racks and other
lab items use AutoBio's meshes (wetlabsim/assets/autobio/NOTICE.md). Everything is laid
out here.
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

# Tubes, racks and the other lab items use meshes from AutoBio (see
# wetlabsim/assets/autobio/NOTICE.md). Collision shapes are simple: a tube is the convex
# hull of its body mesh (so the conical tip is real and a dropped tube falls over). Racks
# use AutoBio's box proxies. Masses are mesh plastic volume x density: polypropylene
# 0.90 g/cm3 for tube bodies, HDPE 0.95 for caps, polystyrene 1.05 for the dishes.
AUTOBIO = ASSETS / "autobio"

# 15 ml conical tube with screw cap: 16.8 mm wide, 122.6 mm tall with the cap.
TUBE_RADIUS = 0.0084
TUBE_HALF_LEN = 0.0613       # body frame is at the tube's middle
CAP_RADIUS = 0.0113
CAP_HEIGHT = 0.0102
TUBE_MASS, CAP_MASS = 0.0045, 0.0019

# Tube rack (AutoBio's 205 x 96 x 60 mm centrifuge-tube rack), long side along the base
# y axis: 15 ml holes in 3 rows x 6 columns on a 36 mm grid, with 2 x 5 bigger 50 ml
# holes between them. Row 0 is nearest the robot, column 0 is on the robot's right.
RACK_ROWS, RACK_COLS = 3, 6
PITCH = 0.036
RACK_HALF_H = 0.030          # rack body frame is at mid height
RACK_FLOOR = 0.006           # top of the bottom plate, above the bench
RACK_TOP = 0.060

# Where things sit, in the robot base frame (x forward, y left, z up). The base frame
# has the same x and y as the world frame; z is BENCH_HEIGHT lower.
RACKS = {
    "rack_a": (0.45, -0.19),
    "rack_b": (0.45, 0.19),
}
# The 15 ml tubes: (cap colour name, rgba). Where they start is set per task (tasks.py);
# by default they stand in rack A at (row, col) (0, 0), (0, 2) and (1, 1).
TUBE_COLOURS = [
    ("red", (0.85, 0.15, 0.15, 1)),
    ("blue", (0.15, 0.35, 0.85, 1)),
    ("green", (0.15, 0.7, 0.25, 1)),
]
TUBES = [
    ("rack_a", 0, 0, "red", TUBE_COLOURS[0][1]),
    ("rack_a", 0, 2, "blue", TUBE_COLOURS[1][1]),
    ("rack_a", 1, 1, "green", TUBE_COLOURS[2][1]),
]

# 60-well rack for 1.5 ml tubes (197 x 72 x 21 mm), long side along y. Wells are named
# like the labels printed on a real one: rows A-E from the far side to the near side,
# columns 1-12 from the robot's left to its right.
PLATE_60 = ("rack_60well", 0.63, -0.24)
FALCON_50 = "tube50"
DISHES = ["petri_dish_1", "petri_dish_2"]
PIPETTE_STAND = (0.62, 0.47)  # fixed to the bench, beam along x
GROUND_FREE = ("tube50", "microtube", "rack_60well", "petri_dish_1", "petri_dish_2", "pipette")


def slot_center(rack: str, row: int, col: int) -> np.ndarray:
    """15 ml slot centre in robot base frame (x, y), top-of-floor z."""
    rx, ry = RACKS[rack]
    x = rx + (row - (RACK_ROWS - 1) / 2) * PITCH
    y = ry + (col - (RACK_COLS - 1) / 2) * PITCH
    return np.array([x, y, RACK_FLOOR])


def hole50_center(rack: str, row: int, col: int) -> np.ndarray:
    """50 ml hole centre (row 0-1 from the robot, col 0-4 from its right)."""
    rx, ry = RACKS[rack]
    return np.array([rx + (row - 0.5) * PITCH, ry + (col - 2) * PITCH, RACK_FLOOR])


def well_center(name: str) -> np.ndarray:
    """Centre of a 60-well rack well, e.g. "B3", for the rack at its starting place."""
    row = "ABCDE".index(name[0].upper())
    col = int(name[1:]) - 1
    _, x, y = PLATE_60
    lx = -0.0873 + 0.0162 * (11 - col)      # column 1 at the robot's left (+y)
    ly = 0.0244 - 0.0132 * (4 - row)        # row A at the far side (+x)
    return np.array([x - ly, y + lx, 0.0])


def _mesh(name: str, file: str, scale=0.001) -> str:
    return f'<mesh name="{name}" file="{AUTOBIO / file}" scale="{scale} {scale} {scale}"/>'


_PIPETTE_VIS = ["body_visual", "tube_visual", "connector_visual", "knob_visual", "pusher_mid_visual",
                "pusher_right1_visual", "pusher_right2_visual", "pusher_right3_visual"]
_PIPETTE_COL = ["body_collision_0", "body_collision_1", "body_collision_2", "body_collision_3",
                "tube_collision_0", "tube_collision_1", "pusher_right1_collision_0",
                "pusher_right2_collision_0", "pusher_right3_collision_0", "pusher_right3_collision_1"]
MESHES = "".join([
    _mesh("tube15_body", "centrifuge_tube_15ml_body.STL"),
    _mesh("tube15_cap", "centrifuge_tube_15ml_cap.STL"),
    _mesh("tube50_body", "centrifuge_tube_50ml_body.STL"),
    _mesh("tube50_cap", "centrifuge_tube_50ml_cap.STL"),
    _mesh("micro_body", "centrifuge_1-5ml_screw_body.STL"),
    _mesh("micro_cap", "centrifuge_1-5ml_screw_cap.STL"),
    _mesh("rack_upper", "rack_upper_plane_visual.obj"),
    _mesh("rack_lower", "rack_lower_plane_visual.obj"),
    _mesh("rack_pillars", "rack_pillars_visual.obj"),
    _mesh("plate60", "rack_plate_60well.obj"),
    _mesh("dish", "cell_dish_100.obj"),
    *[_mesh(f"pip_{n}", f"pipette/{n}.obj", 0.1) for n in _PIPETTE_VIS + _PIPETTE_COL],
    *[_mesh(f"stand_{n}", f"pipette_stand/{n}.obj") for n in
      ("beam_visual", "legs_visual", "beam_collision_0", "leg1_collision_0", "leg2_collision_0")],
])

# Solver options (MuJoCo <option>), chosen on the physics panel.
OPTION = dict(timestep=0.001, integrator="implicitfast", cone="elliptic", impratio=10,
              tolerance=1e-10, noslip_iterations=2)
FLAGS = dict(speculative="enable")

# Contact properties by material, as MuJoCo default classes: every collision shape names
# its material instead of carrying its own numbers, so the same material always behaves the
# same. Unlisted attributes keep MuJoCo's defaults (solimp 0.9 0.95 0.001 0.5 2, solmix 1,
# priority 0, margin 0, gap 0). solref 0.005 s is hard, as MuJoCo's tuning guide advises
# for rigid objects; the rubber fingertip pads keep the softer default and, by priority,
# decide every contact they're in, as a soft pad does against hard plastic.
MATERIALS = {
    "polypropylene": dict(condim=6, friction=(1, 0.005, 0.0001), solref=(0.005, 1)),  # tubes, caps, pipette, racks, stand
    "polystyrene": dict(condim=3, friction=(1, 0.005, 0.0001), solref=(0.005, 1)),    # petri dishes
    "rubber_pad": dict(condim=4, friction=(1, 0.05, 0.001), solref=(0.02, 1), priority=1),  # fingertip pads
    "robot": dict(condim=3, friction=(1, 0.005, 0.0001), solref=(0.005, 1)),          # arm links, hand, finger shells
    "bench": dict(condim=3, friction=(1, 0.005, 0.0001), solref=(0.005, 1)),          # bench top, legs, floor
}
_SOLIMP_DEFAULT = (0.9, 0.95, 0.001, 0.5, 2)
GRIP = 'class="polypropylene"'


def _xml_attrs(d):
    return " ".join(f'{k}="{" ".join(str(x) for x in v) if isinstance(v, tuple) else v}"' for k, v in d.items())


def _defaults_xml():
    return ("<default>" + "".join(f'<default class="{n}"><geom {_xml_attrs(p)}/></default>'
                                  for n, p in MATERIALS.items()) + "</default>")


def _set_material(geom, name):
    """Give a geom of an attached robot model the contact properties of a material."""
    p = MATERIALS[name]
    geom.condim = p["condim"]
    geom.friction = list(p["friction"])
    geom.solref = list(p["solref"])
    geom.solimp = list(p.get("solimp", _SOLIMP_DEFAULT))
    geom.solmix = p.get("solmix", 1.0)
    geom.priority = p.get("priority", 0)


def _box(size, pos, extra=""):
    return (f'<geom type="box" size="{size[0]:.5f} {size[1]:.5f} {size[2]:.5f}" '
            f'pos="{pos[0]:.5f} {pos[1]:.5f} {pos[2]:.5f}" {extra}/>')


# Hole sizes: AutoBio's rack has 17.0 mm holes for 15 ml tubes, 0.1 mm wider than the tube
# on each side, tighter than real racks. The collision boxes are set to a catalogue rack
# instead: Bel-Art (SP Scienceware) Poxygrid 15 mL conical tube rack F18722-0000, "18mm
# square holes", and its 50 mL racks (F18794), "holes 30mm square" (Bel-Art racks catalogue).
# Boekel's PN 120056 rack lists 17 and 28 mm wells. Our 15 ml holes are 18 mm across, 50 ml
# holes 30 mm (as in AutoBio). The meshes still show AutoBio's 17 mm holes.
HOLE15 = 0.018
HOLE50 = 0.030


def _rack_xml(name: str, x: float, y: float) -> str:
    """AutoBio's rack: meshes to look at, boxes to collide with (its proxy layout: floor
    plate, outer walls and short walls between the holes, sized for HOLE15 and HOLE50).
    Turned 90 degrees so the long side runs along y."""
    hide = 'rgba="0 0 0 0" group="3" class="polypropylene"'
    r15 = HOLE15 / 2
    stub = PITCH / 2 - r15                      # half length of a wall between two 15 ml holes
    t50 = PITCH / 2 - HOLE50 / 2                # half thickness of the walls around a 50 ml hole
    parts = [
        _box((0.1025, 0.048, 0.003), (0, 0, -0.027), hide),
        _box((0.1025, (0.048 - PITCH - r15) / 2, 0.03), (0, (0.048 + PITCH + r15) / 2, 0), hide),
        _box((0.1025, (0.048 - PITCH - r15) / 2, 0.03), (0, -(0.048 + PITCH + r15) / 2, 0), hide),
        _box(((0.1025 - 2.5 * PITCH - r15) / 2, 0.048, 0.03), ((0.1025 + 2.5 * PITCH + r15) / 2, 0, 0), hide),
        _box(((0.1025 - 2.5 * PITCH - r15) / 2, 0.048, 0.03), (-(0.1025 + 2.5 * PITCH + r15) / 2, 0, 0), hide),
    ]
    for i in range(2):
        for j in range(6):
            parts.append(_box((t50, stub, 0.03), (-0.09 + PITCH * j, -0.018 + PITCH * i, 0), hide))
    for i in range(3):
        for j in range(5):
            parts.append(_box((stub, t50, 0.03), (-0.072 + PITCH * j, -0.036 + PITCH * i, 0), hide))
    for m in ("rack_upper", "rack_lower", "rack_pillars"):
        parts.append(f'<geom type="mesh" mesh="{m}" material="rack" contype="0" conaffinity="0" group="1"/>')
    return (f'<body name="{name}" pos="{x} {y} {BENCH_HEIGHT + RACK_HALF_H}" quat="0.7071068 0 0 0.7071068">'
            + "".join(parts) + "</body>")


def _tube15_xml(colour: str, rgba) -> str:
    """A 15 ml tube with its screw cap on (the cap doesn't come off)."""
    return _fixed_cap_tube(f"tube_{colour}", rgba, "tube15_body", "tube15_cap", 0.1226, CAP_RADIUS,
                           CAP_HEIGHT, TUBE_MASS, CAP_MASS, TUBE_HALF_LEN)


def _fixed_cap_tube(name, rgba, body_mesh, cap_mesh, top, cap_r, cap_t, body_mass, cap_mass, half,
                    capsule=None):
    """A capped tube whose cap doesn't come off. Body frame at mid height.
    capsule=(radius, length): collide as a capsule instead of the mesh's hull."""
    z0 = -half
    r = " ".join(str(v) for v in rgba)
    if capsule:
        cr, cl = capsule
        body = (f'<geom name="{name}_body" type="capsule" fromto="0 0 {z0 + cr} 0 0 {z0 + cl - cr}" size="{cr}" '
                f'rgba="0 0 0 0" group="3" mass="{body_mass}" {GRIP}/>'
                f'<geom type="mesh" mesh="{body_mesh}" pos="0 0 {z0}" material="tube" contype="0" conaffinity="0" '
                f'mass="0" group="1"/>')
    else:
        body = (f'<geom name="{name}_body" type="mesh" mesh="{body_mesh}" pos="0 0 {z0}" material="tube" '
                f'mass="{body_mass}" {GRIP}/>')
    return (
        f'<body name="{name}"><freejoint name="{name}_joint"/>'
        + body +
        f'<geom name="{name}_capvis" type="mesh" mesh="{cap_mesh}" pos="0 0 {z0 + top}" euler="3.14159265 0 0" '
        f'rgba="{r}" contype="0" conaffinity="0" mass="0" group="1"/>'
        f'<geom name="{name}_cap" type="cylinder" size="{cap_r} {cap_t / 2}" pos="0 0 {z0 + top - cap_t / 2}" '
        f'rgba="0 0 0 0" group="3" mass="{cap_mass}" {GRIP}/>'
        f"</body>"
    )


def _extras_xml() -> str:
    """Every other item on the bench. Starting poses are set per task (tasks.py)."""
    # 60-well rack: estimated 45 g (its mesh is a solid block, so the volume method would
    # overstate it).
    name = PLATE_60[0]
    walls = [((0.0985, 0.001, 0.0105), (0, -0.035, 0)), ((0.0985, 0.003, 0.0105), (0, 0.033, 0)),
             ((0.0028, 0.036, 0.0105), (-0.0957, 0, 0)), ((0.001, 0.036, 0.0105), (0.0975, 0, 0))]
    walls += [((0.0025, 0.032, 0.0105), (-0.0792 + 0.0162 * k, -0.002, 0)) for k in range(11)]
    walls += [((0.0947, 0.001, 0.0105), (0.0018, -0.0218 + 0.0132 * k, 0)) for k in range(4)]
    m = 0.045 / len(walls)
    plate = (f'<body name="{name}"><freejoint name="{name}_joint"/>'
             + "".join(_box(s, p, f'mass="{m:.5f}" rgba="0 0 0 0" group="3" {GRIP}') for s, p in walls)
             + '<geom type="mesh" mesh="plate60" rgba="0.2 0.35 0.75 1" contype="0" conaffinity="0" mass="0" group="1"/>'
             + "</body>")
    # The 1.5 ml tube's mesh hull is 11.4 mm wide (it includes the lip under the thread),
    # wider than the 11.2 mm wells; it collides as a 10.5 mm capsule instead (AutoBio's own
    # body radius; real racks for these tubes have ~10.8 mm holes, per Bel-Art's catalogue).
    micro = _fixed_cap_tube("microtube", (0.95, 0.75, 0.1, 1), "micro_body", "micro_cap",
                            0.04455, 0.0062, 0.0086, 0.00097, 0.00028, 0.0224, capsule=(0.00525, 0.0426))
    falcon = _fixed_cap_tube(FALCON_50, (0.95, 0.45, 0.1, 1), "tube50_body", "tube50_cap",
                             0.11965, 0.0175, 0.0123, 0.0086, 0.0041, 0.0598)
    # 100 mm petri dishes, polystyrene (23 g each with lid). AutoBio's proxy: base disc + 16 wall boxes.
    dishes = ""
    for dname in DISHES:
        ring = "".join(
            _box((0.00868, 0.00098, 0.009),
                 (0.04266 * np.sin(k * np.pi / 8), 0.04266 * np.cos(k * np.pi / 8), 0.011),
                 f'euler="0 0 {-k * np.pi / 8:.5f}" mass="0.0009" rgba="0 0 0 0" group="3" class="polystyrene"')
            for k in range(16))
        dishes += (f'<body name="{dname}"><freejoint name="{dname}_joint"/>'
                   f'<geom type="cylinder" size="0.0445 0.001" pos="0 0 0.001" mass="0.0086" rgba="0 0 0 0" group="3" class="polystyrene"/>'
                   + ring
                   + '<geom type="mesh" mesh="dish" rgba="0.92 0.95 0.97 0.45" contype="0" conaffinity="0" mass="0" group="1"/>'
                   + "</body>")
    # Single-channel pipette (AutoBio's), rigid: its plunger and ejector don't move here.
    # Estimated 100 g. Body frame at the tip end, z along the pipette.
    pm = 0.100 / len(_PIPETTE_COL)
    pipette = (f'<body name="pipette"><freejoint name="pipette_joint"/>'
               + "".join(f'<geom type="mesh" mesh="pip_{n}" rgba="0 0 0 0" group="3" mass="{pm:.4f}" {GRIP}/>'
                         for n in _PIPETTE_COL)
               + "".join(f'<geom type="mesh" mesh="pip_{n}" material="{"pip_button" if "pusher" in n or "knob" in n else "pip_plastic"}" '
                         f'contype="0" conaffinity="0" mass="0" group="1"/>' for n in _PIPETTE_VIS)
               + "</body>")
    # Pipette stand (AutoBio's), fixed to the bench, beam along x.
    sx, sy = PIPETTE_STAND
    stand = (f'<body name="pipette_stand" pos="{sx} {sy} {BENCH_HEIGHT}">'
             + "".join(f'<geom type="mesh" mesh="stand_{n}" rgba="0 0 0 0" group="3" {GRIP}/>'
                       for n in ("beam_collision_0", "leg1_collision_0", "leg2_collision_0"))
             + "".join(f'<geom type="mesh" mesh="stand_{n}" material="rack" contype="0" conaffinity="0" group="1"/>'
                       for n in ("beam_visual", "legs_visual"))
             + "</body>")
    return plate + micro + falcon + dishes + pipette + stand


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
    tubes = "".join(_tube15_xml(c, rgba) for c, rgba in TUBE_COLOURS) + _extras_xml()
    over_pos = (0.75, 0.0, bh + 1.0)
    side_pos = (1.35, -0.95, bh + 0.75)
    return f"""
<mujoco model="wetlab_bench">
  <compiler angle="radian" autolimits="true"/>
  <option {_xml_attrs(OPTION)}><flag {_xml_attrs(FLAGS)}/></option>
  {_defaults_xml()}
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
    <material name="pip_plastic" rgba="0.85 0.85 0.85 1"/>
    <material name="pip_button" rgba="0.5 0.7 0.9 1"/>
    {MESHES}
  </asset>
  <worldbody>
    <light pos="0.4 0.3 3" dir="0 -0.1 -1" diffuse="0.45 0.45 0.45" specular="0.1 0.1 0.1" castshadow="true"/>
    <light pos="-1 -1 2.5" dir="0.4 0.4 -1" diffuse="0.25 0.25 0.25" castshadow="false"/>
    <geom name="floor" type="plane" size="4 4 0.1" material="floor" class="bench"/>
    <body name="bench" pos="0.35 0 0" childclass="bench">
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
        # Limits from Franka's own documents (agent/datasheets/SOURCES.md):
        # joint and Cartesian limits from the FCI "Limits for Franka Emika Robot (FER)" table,
        # sensing and force ranges from the datasheet (product manual p. 34), gripper from the
        # Franka Hand manual (section 5.1).
        "joint_vmax": np.array([2.175, 2.175, 2.175, 2.175, 2.61, 2.61, 2.61]),   # rad/s
        "joint_amax": np.array([15.0, 7.5, 10.0, 12.5, 15.0, 20.0, 20.0]),        # rad/s^2
        "cart_vmax": 1.7, "rot_vmax": 2.5,          # m/s, rad/s
        "ft_noise": (0.035, 0.005),                 # force (N), torque (Nm) noise RMS
        "ft_bias": (0.8, 0.15),                     # relative force (N) / torque (Nm) accuracy
        # Stop when the external wrench leaves the datasheet's nominal force/torque range.
        "reflex_force": (np.array([-125.0, -100.0, -50.0]), np.array([95.0, 100.0, 150.0])),   # N
        "reflex_torque": (np.full(3, -10.0), np.full(3, 10.0)),                                # Nm
        "grip_speed_mm_s": 50.0,                    # per finger
        "grip_force_n": (30.0, 70.0),               # continuous grasping force range
        "grip_stroke_mm": 80.0,
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
        "joint_vmax": np.full(6, 3.14), "joint_amax": np.full(6, 40.0),
        "cart_vmax": 1.0, "rot_vmax": 1.0,
        "ft_noise": (0.3, 0.02), "ft_bias": (0.0, 0.0),
        "reflex_force": (np.full(3, -1e9), np.full(3, 1e9)), "reflex_force_norm": 140.0,
        "reflex_torque": (np.full(3, -1e9), np.full(3, 1e9)),
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
        spec.option.timestep = OPTION["timestep"]
        spec.option.impratio = OPTION["impratio"]
        spec.option.tolerance = OPTION["tolerance"]
        spec.option.noslip_iterations = OPTION["noslip_iterations"]
        spec.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
        spec.option.integrator = getattr(mujoco.mjtIntegrator, "mjINT_" + OPTION["integrator"].upper())
        if FLAGS.get("speculative") == "enable":
            spec.option.enableflags |= mujoco.mjtEnableBit.mjENBL_SPECULATIVE


def _franka(world, mount="robot_mount", prefix=""):
    arm = mujoco.MjSpec.from_file(str(ASSETS / "franka_emika_panda" / "panda.xml"))
    # Fingertip pads are rubber; every other colliding shape is the robot's hard shell.
    for g in arm.geoms:
        if g.classname.name.startswith("fingertip_pad_collision"):
            _set_material(g, "rubber_pad")
        elif g.contype or g.conaffinity:
            _set_material(g, "robot")
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
        world.site(mount).attach_body(arm.body("link0"), prefix, "")
    return prefix + "ft_site"


def _ur5e(world, mount_site="robot_mount", prefix=""):
    arm = mujoco.MjSpec.from_file(str(ASSETS / "universal_robots_ur5e" / "ur5e.xml"))
    grip = mujoco.MjSpec.from_file(str(ASSETS / "robotiq_2f85" / "2f85.xml"))

    # Silicone finger pads are rubber; every other colliding shape is the robot's hard shell.
    for spec in (arm, grip):
        for g in spec.geoms:
            if g.classname.name in ("pad_box1", "pad_box2"):
                _set_material(g, "rubber_pad")
            elif g.contype or g.conaffinity:
                _set_material(g, "robot")

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
        world.site(mount_site).attach_body(arm.body("base"), prefix, "")
    return prefix + "gripper/ft_site"


def add_robot(world, robot: str, mount: str = "robot_mount", prefix: str = ""):
    """Attach a robot (with its wrist camera and wrist force/torque sensor) at a mount site.
    prefix: put in front of every name the robot brings, so several robots fit in one scene."""
    ft_site = _franka(world, mount, prefix) if robot == "franka" else _ur5e(world, mount, prefix)
    # Wrist force/torque sensor (UR5e: built in at the flange; Panda: estimated from joint torques).
    world.add_sensor(name=prefix + "ft_force", type=mujoco.mjtSensor.mjSENS_FORCE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    world.add_sensor(name=prefix + "ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)


def profile_for(robot: str, prefix: str = "", world_cameras: str | None = None) -> dict:
    """A robot's profile with its model names as they are when it was attached with prefix.
    world_cameras: prefix of the fixed (overhead, side) cameras that belong to this robot
    (default: the same prefix)."""
    P = dict(ROBOTS[robot_name(robot)])
    if not prefix and world_cameras is None:
        return P
    wc = prefix if world_cameras is None else world_cameras
    for k in ("arm_joints", "arm_actuators"):
        P[k] = [prefix + n for n in P[k]]
    for k in ("tcp_site", "ft_site", "ft_body", "base_body", "grip_actuator", "grip_joint"):
        P[k] = prefix + P[k]
    P["cameras"] = {k: (prefix + v if k == "wrist" else wc + v) for k, v in P["cameras"].items()}
    P["sensors"] = (prefix + "ft_force", prefix + "ft_torque")
    return P


def build_model(robot: str | None = None) -> mujoco.MjModel:
    robot = robot_name(robot)
    world = mujoco.MjSpec.from_string(_world_xml(ROBOTS[robot]["mount_quat"]))
    add_robot(world, robot)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()
