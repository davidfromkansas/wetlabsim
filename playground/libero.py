"""LIBERO-Goal test mode: LIBERO's own scene, its ten tasks, its 50 official starting setups
per task, and its own success checks.

The scene is rebuilt in MuJoCo 4 from LIBERO's published files (playground/libero_assets,
see tools/import_libero.py): the 1.0 x 1.2 m table and room of its "tabletop" scene, the
bowl, plate, cream cheese, wine bottle, wooden cabinet, flat stove and wine rack, placed
the way LIBERO places them. The robot is our Franka (the same model, controller and
command interface as everywhere else in this repo), mounted where LIBERO mounts its Panda.

The success checks follow LIBERO's predicate code (libero/libero/envs/predicates and
object_states): On, In, Open and TurnOn, with the same thresholds.
"""
from __future__ import annotations

import math
import pathlib
import re
import warnings
from dataclasses import dataclass

import mujoco
import numpy as np

from wetlabsim import scene as S

HERE = pathlib.Path(__file__).parent
ASSETS = HERE / "libero_assets"

TABLE_TOP = 0.90                       # LIBERO's table_offset z
TABLE_HALF = (0.5, 0.6, 0.025)         # table_full_size (1.0, 1.2, 0.05) / 2
ROBOT_BASE = (-0.16 - 0.5, 0.0, 0.912)  # MountedPanda base_xpos_offset["table"] on its Rethink mount
OBJ_Z_OFFSET = 0.01                    # objects: dropped 1 cm above the table (LIBERO's sampler)
FIXTURE_Z_OFFSET = 0.01 - 0.05         # fixtures: Libero_Tabletop_Manipulation.z_offset

# Every LIBERO-Goal task uses the same objects and fixtures, in this order in the states.
OBJECTS = ["akita_black_bowl_1", "cream_cheese_1", "wine_bottle_1", "plate_1"]
FIXTURES = {   # instance: (model, region x range, region y range, yaw)
    "wooden_cabinet_1": ("wooden_cabinet", (0.02, 0.04), (-0.25, -0.23), math.pi),
    "flat_stove_1": ("flat_stove", (-0.42, -0.40), (0.20, 0.22), 0.0),
    "wine_rack_1": ("wine_rack", (-0.27, -0.25), (-0.27, -0.25), math.pi),
}
LABELS = {"akita_black_bowl_1": "black bowl", "cream_cheese_1": "cream cheese box", "wine_bottle_1": "wine bottle",
          "plate_1": "plate", "wooden_cabinet_1": "wooden cabinet with three drawers",
          "flat_stove_1": "flat stove with a knob", "wine_rack_1": "wine rack"}

# TargetZone sites on the table, from the task files (x0, y0, x1, y1).
TABLE_REGIONS = {
    "main_table_stove_front_region": (-0.09, 0.17, -0.01, 0.25),
}

# Articulation thresholds (libero/libero/envs/objects/articulated_objects.py)
CABINET_OPEN_BELOW = -0.14     # WoodenCabinet.is_open: qpos < max(default_open_ranges)
STOVE_ON_FROM = 0.5            # FlatStove.turn_on: qpos >= min(default_turnon_ranges)


@dataclass
class Task:
    id: str
    language: str
    goal: tuple            # (predicate, arg1[, arg2])
    states: np.ndarray     # the 50 official starting states


def _parse_bddl(path: pathlib.Path):
    text = path.read_text()
    lang = re.search(r"\(:language\s+([^)]*)\)", text).group(1).strip()
    goal = re.search(r"\(:goal\s*\(And\s*\(([^)]*)\)", text).group(1).split()
    return lang, tuple(goal)


def tasks() -> list[Task]:
    out = []
    for bddl in sorted((ASSETS / "tasks").glob("*.bddl")):
        lang, goal = _parse_bddl(bddl)
        states = np.load(bddl.with_suffix(".npz"))["states"]
        out.append(Task(bddl.stem, lang, goal, states))
    return out


def task(task_id: str) -> Task:
    t = next((t for t in tasks() if t.id == task_id), None)
    if t is None:
        raise KeyError(task_id)
    return t


# ----------------------------------------------------------------- the scene
def _world_xml() -> str:
    tx, ty, tz = TABLE_HALF
    legs = "".join(
        f'<geom type="cylinder" size="0.025 {(TABLE_TOP - 2 * tz) / 2:.4f}" pos="{sx * (tx - 0.1)} {sy * (ty - 0.1)} '
        f'{-(TABLE_TOP - 2 * tz) / 2 - tz:.4f}" contype="0" conaffinity="0" group="1" material="table_legs"/>'
        for sx in (-1, 1) for sy in (-1, 1))
    tex = ASSETS / "textures"
    defaults = ("<default>" + "".join(f'<default class="{n}"><geom {S._xml_attrs(p)}/></default>'
                                      for n, p in S.MATERIALS.items()) + "</default>")
    return f"""
<mujoco model="libero_goal">
  <compiler angle="radian" autolimits="true"/>
  <size memory="256M"/>
  <option {S._xml_attrs(S.OPTION)}><flag {S._xml_attrs(S.FLAGS)}/></option>
  {defaults}
  <visual>
    <global offwidth="1920" offheight="1200"/>
    <headlight ambient="0.3 0.3 0.3" diffuse="0.3 0.3 0.3" specular="0.05 0.05 0.05"/>
    <quality shadowsize="4096"/>
  </visual>
  <asset>
    <texture builtin="gradient" height="256" rgb1=".9 .9 1." rgb2=".2 .3 .4" type="skybox" width="256"/>
    <texture file="{tex / 'tile_grigia_caldera_porcelain_floor.png'}" type="2d" name="texplane"/>
    <material name="floorplane" reflectance="0.0" shininess="0.0" specular="0.0" texrepeat="3 3" texture="texplane" texuniform="true"/>
    <texture file="{tex / 'martin_novak_wood_table.png'}" type="cube" name="tex-table"/>
    <material name="table_texture" reflectance="0.0" shininess="0.0" specular="0.2" texrepeat="1 1" texture="tex-table"/>
    <material name="table_legs" reflectance="0.8" shininess="0.8" texrepeat="1 1" texture="tex-table"/>
    <texture file="{tex / 'smooth_light_gray_plaster.png'}" type="2d" name="tex-wall"/>
    <material name="walls_mat" reflectance="0.0" shininess="0.1" specular="0.8" texrepeat="3 3" texture="tex-wall" texuniform="true"/>
    <material name="mount" rgba="0.2 0.2 0.22 1" specular="0.3"/>
  </asset>
  <worldbody>
    <geom condim="3" group="1" material="floorplane" name="floor" pos="0 0 0" size="3 3 .125" type="plane"/>
    <geom pos="-1.25 2.25 1.5" quat="0.6532815 0.6532815 0.2705981 0.2705981" size="1.06 1.5 0.01" type="box" conaffinity="0" contype="0" group="1" material="walls_mat"/>
    <geom pos="-1.25 -2.25 1.5" quat="0.6532815 0.6532815 -0.2705981 -0.2705981" size="1.06 1.5 0.01" type="box" conaffinity="0" contype="0" group="1" material="walls_mat"/>
    <geom pos="1.25 3 1.5" quat="0.7071 0.7071 0 0" size="1.75 1.5 0.01" type="box" conaffinity="0" contype="0" group="1" material="walls_mat"/>
    <geom pos="1.25 -3 1.5" quat="0.7071 -0.7071 0 0" size="1.75 1.5 0.01" type="box" conaffinity="0" contype="0" group="1" material="walls_mat"/>
    <geom pos="-2 0 1.5" quat="0.5 0.5 0.5 0.5" size="1.5 1.5 0.01" type="box" conaffinity="0" contype="0" group="1" material="walls_mat"/>
    <body name="table" pos="0 0 {TABLE_TOP - tz}">
      <geom name="table_collision" type="box" size="{tx} {ty} {tz}" group="3" rgba="0 0 0 0" friction="1 0.005 0.0001"/>
      <geom name="table_visual" type="box" size="{tx} {ty} {tz}" contype="0" conaffinity="0" group="1" material="table_texture"/>
      <site name="table_top" pos="0 0 {tz}" size="0.001"/>
      {legs}
    </body>
    <!-- the Panda's pedestal (LIBERO's Rethink mount), drawn simply -->
    <geom type="cylinder" size="0.1 {ROBOT_BASE[2] / 2:.4f}" pos="{ROBOT_BASE[0]} {ROBOT_BASE[1]} {ROBOT_BASE[2] / 2:.4f}" contype="0" conaffinity="0" group="1" material="mount"/>
    <light diffuse=".8 .8 .8" dir="0 -.15 -1" directional="false" pos="1 1 4.0" specular="0.3 0.3 0.3" castshadow="false"/>
    <light diffuse=".8 .8 .8" dir="0 -.15 -1" directional="false" pos="-3. -3. 4.0" specular="0.3 0.3 0.3" castshadow="false"/>
    <light diffuse=".3 .3 .3" dir="0.2 0 -1" pos="0 0 3" castshadow="true"/>
    <!-- LIBERO's cameras: agentview is what its policies see; here it is the robot's overhead camera -->
    <camera name="overhead" pos="0.6586131746834771 0.0 1.6103500240372423" quat="0.6380177736282349 0.3048497438430786 0.3048497438430786 0.6380177736282349" fovy="45"/>
    <camera name="side" pos="1.0 0.0 1.48" quat="0.56 0.43 0.43 0.56" fovy="45"/>
    <site name="robot_mount" pos="{ROBOT_BASE[0]} {ROBOT_BASE[1]} {ROBOT_BASE[2]}" quat="1 0 0 0"/>
  </worldbody>
</mujoco>
"""


def _load_object(model: str) -> mujoco.MjSpec:
    spec = mujoco.MjSpec.from_file(str(ASSETS / "objects" / model / "model.xml"))
    for g in spec.geoms:
        # Collision shapes (group 0) are drawn in LIBERO only when debugging: hide them.
        if g.group == 0 and (g.contype or g.conaffinity):
            g.group = 3
    return spec


def _bottom(spec: mujoco.MjSpec) -> float:
    for s in spec.sites:
        if s.name == "bottom_site":
            return float(s.pos[2])
    return 0.0


def build(robot: str = "franka") -> mujoco.MjModel:
    world = mujoco.MjSpec.from_string(_world_xml())
    for inst, (model, xr, yr, yaw) in FIXTURES.items():
        spec = _load_object(model)
        z = TABLE_TOP - _bottom(spec) + FIXTURE_Z_OFFSET
        frame = world.worldbody.add_frame(pos=[sum(xr) / 2, sum(yr) / 2, z],
                                          quat=[math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame.attach_body(spec.body("object"), inst + "_", "")
    for inst in OBJECTS:
        spec = _load_object(inst.rsplit("_", 1)[0])
        frame = world.worldbody.add_frame()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            body = frame.attach_body(spec.body("object"), inst + "_", "")
        body.pos = [0, 0, 0]
        body.add_freejoint(name=inst + "_joint")
    ft_site = S._franka(world)
    world.add_sensor(name="ft_force", type=mujoco.mjtSensor.mjSENS_FORCE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    world.add_sensor(name="ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    # Each object's own mesh assets keep their names; textures and meshes don't clash across models.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()


# ---------------------------------------------------------- starting setups
def apply_setup(m: mujoco.MjModel, d: mujoco.MjData, state: np.ndarray, arm_qadr, grip_names=("finger_joint1", "finger_joint2")):
    """Put the scene in one of LIBERO's official starting states.

    A state is [time, qpos, qvel] of LIBERO's own model: the Panda's 7 joints and 2 finger
    joints, then each object's free joint (in OBJECTS order), then the fixtures' joints.
    The arm starts at the setup's joint angles; the hand starts open (our gripper's rest).
    """
    q = state[1:]
    arm = q[0:7]
    d.qpos[arm_qadr] = arm
    for n in grip_names:
        d.qpos[m.joint(n).qposadr[0]] = 0.04
    k = 9
    for inst in OBJECTS:
        adr = m.joint(inst + "_joint").qposadr[0]
        d.qpos[adr:adr + 7] = q[k:k + 7]
        k += 7
    fixture_joints = ["wooden_cabinet_1_top_level", "wooden_cabinet_1_middle_level",
                      "wooden_cabinet_1_bottom_level", "flat_stove_1_button"]
    for name, v in zip(fixture_joints, q[k:k + 4]):
        d.qpos[m.joint(name).qposadr[0]] = v
    d.qvel[:] = 0
    return arm


# ------------------------------------------------------------- the checks
class Checker:
    """LIBERO's success predicates on our model."""

    def __init__(self, m: mujoco.MjModel):
        self.m = m
        self.root = {}
        for inst in OBJECTS + list(FIXTURES):
            self.root[inst] = m.body(inst + "_object").id
        self.sub = {inst: self._subtree(b) for inst, b in self.root.items()}

    def _subtree(self, root):
        m = self.m
        out = set()
        for b in range(m.nbody):
            x = b
            while x > 0:
                if x == root:
                    out.add(b)
                    break
                x = m.body_parentid[x]
        return out

    def contact(self, d, a: str, b: str) -> bool:
        A, B = self.sub[a], self.sub[b]
        gb = self.m.geom_bodyid
        for i in range(d.ncon):
            c = d.contact[i]
            b1, b2 = gb[c.geom1], gb[c.geom2]
            if (b1 in A and b2 in B) or (b1 in B and b2 in A):
                return True
        return False

    def pos(self, d, inst):
        return d.xpos[self.root[inst]]

    def _site(self, d, name):
        sid = self.m.site(name).id
        return sid, d.site_xpos[sid], d.site_xmat[sid].reshape(3, 3), self.m.site_size[sid]

    def on(self, d, a: str, b: str) -> bool:
        if b in self.root:     # ObjectState.check_ontop
            pa, pb = self.pos(d, a), self.pos(d, b)
            return bool(pb[2] <= pa[2] and self.contact(d, b, a) and np.linalg.norm(pa[:2] - pb[:2]) < 0.03)
        if b in TABLE_REGIONS:  # a TargetZone on the table: SiteObject.under, no parent object
            x0, y0, x1, y1 = TABLE_REGIONS[b]
            centre = np.array([(x0 + x1) / 2, (y0 + y1) / 2, TABLE_TOP - TABLE_HALF[2] + 0.02])
            size = np.array([(x1 - x0) / 2, (y1 - y0) / 2, 0.007])
            return self._under(centre, np.eye(3), size, self.pos(d, a))
        _, p, R, size = self._site(d, b)
        parent = next(f for f in FIXTURES if b.startswith(f))
        return self._under(p, R, size, self.pos(d, a)) and self.contact(d, parent, a)

    @staticmethod
    def _under(p, R, size, other, other_height=0.10):
        delta = R @ (other - p)     # as LIBERO writes it (this_mat @ ...)
        return bool(size[2] - 0.005 < delta[2] < size[2] + other_height and np.all(np.abs(delta[:2]) < size[:2]))

    def inside(self, d, a: str, region: str) -> bool:
        _, p, R, size = self._site(d, region)      # SiteObject.in_box
        total = np.abs(R @ size)
        ub, lb = p + total, p - total
        lb[2] -= 0.01
        o = self.pos(d, a)
        return bool(np.all(o > lb) and np.all(o < ub))

    def is_open(self, d, region: str) -> bool:
        level = {"top_region": "top_level", "middle_region": "middle_level", "bottom_region": "bottom_level"}
        inst = next(f for f in FIXTURES if region.startswith(f))
        joint = inst + "_" + level[region[len(inst) + 1:]]
        return bool(d.qpos[self.m.joint(joint).qposadr[0]] < CABINET_OPEN_BELOW)

    def turned_on(self, d, inst: str) -> bool:
        return bool(d.qpos[self.m.joint(inst + "_button").qposadr[0]] >= STOVE_ON_FROM)

    def check(self, d, goal: tuple) -> bool:
        p, *args = goal
        p = p.lower()
        if p == "on":
            return self.on(d, *args)
        if p == "in":
            return self.inside(d, *args)
        if p == "open":
            return self.is_open(d, *args)
        if p == "turnon":
            return self.turned_on(d, *args)
        raise ValueError(f"unknown predicate {p}")


def site_sheet() -> str:
    tx, ty, _ = TABLE_HALF
    bx, by, bz = ROBOT_BASE
    items = "\n".join(f"- {LABELS[i]}" for i in OBJECTS + list(FIXTURES))
    return f"""# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Franka Emika Panda on a pedestal at the end of a 1.0 x 1.2 m table, facing along the
  table. The table top is {TABLE_TOP * 100:.0f} cm above the floor.
- The robot base frame has its origin at the centre of the base flange, {(bz - TABLE_TOP) * 100:.1f} cm above
  the table top. x points forward along the table, y to the robot's left, z up. All
  positions and poses in the command interface are in this frame, in metres.
- The table top is the plane z = {TABLE_TOP - bz:.3f} m. It extends from x = {-tx - bx:.2f} m to
  x = {tx - bx:.2f} m and from y = {-ty - by:.2f} m to y = {ty - by:.2f} m.

## Tool and payload settings

- End effector: Franka Hand (0.73 kg), configured as the end effector in the controller.
- TCP: Franka's default for the Franka Hand: 103.4 mm along the flange z axis, rotated
  -45° about it. It is the centre point between the fingertips.
- Payload: none beyond the hand. The force/torque reading has the hand's weight removed.
- Tool orientation convention: the TCP's z axis points out of the hand, between the
  fingers; the fingers close along the TCP's y axis. A TCP pose of
  `[x, y, z, 3.14159, 0, 0]` points the hand straight down with the fingers closing
  along the base y axis.

## Cameras

Two RGB-D cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`:

- `overhead`: fixed above the far end of the table, looking back at the robot and the
  table. Its pose is given in the robot base frame.
- `wrist`: on the hand. Its pose is given in the TCP frame (hand-eye calibration).

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## What's on the table

{items}

## Start state

At the start of a run the arm is near joint angles `[0, -0.16, 0, -2.44, 0, 2.23, 0.785]`
(rad), hand pointing down, gripper open, not in a protective stop.
"""


_REGION_WORDS = {"wooden_cabinet_1_middle_region": "the middle drawer", "wooden_cabinet_1_top_region": "the top drawer",
                 "main_table_stove_front_region": "the marked area in front of the stove",
                 "flat_stove_1_cook_region": "the stove's burner", "wooden_cabinet_1_top_side": "the top of the cabinet",
                 "wine_rack_1_top_region": "the wine rack"}


def done_when(goal: tuple) -> str:
    """LIBERO's goal check in plain words."""
    pred = goal[0].lower()
    name = lambda a: _REGION_WORDS.get(a) or "the " + LABELS.get(a, a)
    if pred == "open":
        return f"{name(goal[1])[0].upper() + name(goal[1])[1:]} is pulled open."
    if pred == "turnon":
        return "The stove's knob is turned to on (the burner glows)."
    if pred == "in":
        return f"{name(goal[1])[0].upper() + name(goal[1])[1:]} is inside {name(goal[2])}."
    if goal[2] in _REGION_WORDS:
        return f"{name(goal[1])[0].upper() + name(goal[1])[1:]} is sitting on {name(goal[2])}."
    return f"{name(goal[1])[0].upper() + name(goal[1])[1:]} is resting on {name(goal[2])}, touching it."
