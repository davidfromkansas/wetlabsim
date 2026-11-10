"""Builds the playground's lab: a graph-paper floor, the robot stations on it (each a robot
arm on its own NVIDIA packing table, with its own overhead and side cameras), and whatever
the user has dropped in.

Every library item comes from playground/assets/<id>/ (see tools/convert_simready.py):
visual meshes with their textures, collision meshes, and the mass the asset states.
Physics settings (solver, materials) are the robot cell's own (wetlabsim/scene.py).
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import mujoco
import numpy as np

from wetlabsim import scene as S

from . import catalog

TABLE_UID = "table"     # (older saved scenes) the one table a robot stood on
# A station's robot stands on its table, near one long edge, facing across it (+x).
ROBOT_XY = (-0.42, 0.0)
STATION_TABLE = "table_packing"

# The kinds of station: which table the robot stands on, how that table is turned in the
# station's frame (the robot always faces +x), where the robot stands, and what starts on it.
# The wet lab bench is a stainless lab table, turned so its long side runs beside the arm,
# with lab glassware and instruments laid out within reach (item, x, y, yaw in the
# station's frame, on the table top).
KINDS = {
    "table": {"label": "Table with arm", "table": STATION_TABLE, "turn": 0.0, "robot_xy": ROBOT_XY,
              "layout": []},
    "wetlab": {"label": "Wet lab bench", "table": "lab_bench", "turn": math.pi / 2, "robot_xy": (-0.2, 0.0),
               "layout": [
                   ("sterilising_tray", 0.12, -0.5, 0.0),
                   ("syringe", 0.17, -0.27, 0.0),
                   ("syringe_small", 0.24, -0.2, 0.0),
                   ("forceps", 0.05, -0.24, 0.0),
                   ("thermometer", -0.14, -0.33, math.pi / 2),
                   ("medicine", -0.12, -0.72, 0.0),
                   ("glass_vial", 0.24, -0.06, 0.0),
                   ("glass_vial", 0.24, 0.0, 0.0),
                   ("glass_vial", 0.24, 0.06, 0.0),
                   ("lab_bottle_small", 0.1, 0.2, 0.0),
                   ("lab_bottle_small", 0.1, 0.26, 0.0),
                   ("lab_bottle", 0.2, 0.3, 0.0),
                   ("lab_bottle_m", 0.2, 0.42, 0.0),
                   ("lab_bottle_l", 0.2, 0.56, 0.0),
                   ("lab_bottle_xl", 0.2, 0.72, 0.0),
                   ("glass_jar", -0.05, 0.5, 0.0),
                   ("disinfectant", -0.12, 0.7, 0.0),
                   ("glove_box", 0.0, 0.8, math.pi / 2),
               ]},
}

# Contact properties for library items, as a MuJoCo default class like the cell's
# materials. Sliding friction comes from each asset's own physics material.
PROP = dict(condim=6, friction=(1, 0.005, 0.0001), solref=(0.005, 1))
FURNITURE = dict(condim=3, friction=(1, 0.005, 0.0001), solref=(0.005, 1))


@dataclass
class Placed:
    uid: str
    item: str
    pos: tuple            # world position of the item's bottom centre (m)
    yaw: float = 0.0      # rotation about the vertical (rad)
    quat: tuple | None = None   # full orientation when set (after physics has moved it)

    def as_dict(self):
        return {"uid": self.uid, "item": self.item, "pos": [round(float(v), 4) for v in self.pos],
                "yaw": round(float(self.yaw), 4)}


def yaw_quat(yaw: float):
    return (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))


@dataclass
class Station:
    """A robot arm on its own table: the unit a lab is built from."""
    uid: str              # "st1", "st2", ...: also the prefix of the robot's names ("st1/joint1")
    robot: str            # "franka" or "ur5e"
    pos: tuple            # world (x, y) of the table's centre (m)
    yaw: float = 0.0      # rotation about the vertical (rad)
    name: str = ""        # what the user calls it ("Station 1")
    kind: str = "table"   # a key of KINDS

    @property
    def prefix(self) -> str:
        return self.uid + "/"

    @property
    def spec(self) -> dict:
        return KINDS.get(self.kind, KINDS["table"])

    @property
    def table_item(self) -> str:
        return self.spec["table"]

    @property
    def table_yaw(self) -> float:
        return self.yaw + self.spec["turn"]

    @property
    def robot_xy(self) -> tuple:
        return self.spec["robot_xy"]

    @property
    def top(self) -> float:
        return table_top(catalog.meta(self.table_item))

    def to_world(self, x: float, y: float, z: float = 0.0):
        """A point given in the station's own frame (table centre, robot along -x) in the world."""
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (self.pos[0] + c * x - s * y, self.pos[1] + s * x + c * y, z)

    def to_local(self, x: float, y: float):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        dx, dy = x - self.pos[0], y - self.pos[1]
        return (c * dx + s * dy, -s * dx + c * dy)

    def footprint(self):
        """The table's size along the station's own x and y."""
        sx, sy, _ = catalog.meta(self.table_item)["size"]
        c, s = abs(math.cos(self.spec["turn"])), abs(math.sin(self.spec["turn"]))
        return c * sx + s * sy, s * sx + c * sy

    def holds(self, x: float, y: float, margin: float = 0.0) -> bool:
        """Whether a point is over this station's table."""
        sx, sy = self.footprint()
        lx, ly = self.to_local(x, y)
        return abs(lx) <= sx / 2 + margin and abs(ly) <= sy / 2 + margin

    def as_dict(self):
        from wetlabsim import scene as WS
        P = WS.ROBOTS[self.robot]
        return {"id": self.uid, "robot": self.robot, "name": self.name, "label": P["name"], "kind": self.kind,
                "gripper": P["gripper"], "pos": [round(float(v), 4) for v in self.pos],
                "yaw": round(float(self.yaw), 4)}


def table_uid(st: Station) -> str:
    return f"{st.uid}-table"


def _xml_attrs(d):
    return S._xml_attrs(d)


def _world_xml() -> str:
    defaults = ("<default>"
                + "".join(f'<default class="{n}"><geom {_xml_attrs(p)}/></default>' for n, p in S.MATERIALS.items())
                + f'<default class="prop"><geom {_xml_attrs(PROP)}/></default>'
                + f'<default class="furniture"><geom {_xml_attrs(FURNITURE)}/></default>'
                + "</default>")
    return f"""
<mujoco model="playground">
  <compiler angle="radian" autolimits="true"/>
  <size memory="512M"/>
  <option {_xml_attrs(S.OPTION)}><flag {_xml_attrs(S.FLAGS)}/></option>
  {defaults}
  <visual>
    <global offwidth="1920" offheight="1200" azimuth="150" elevation="-25"/>
    <headlight ambient="0.5 0.5 0.5" diffuse="0.3 0.3 0.3" specular="0.05 0.05 0.05"/>
    <quality shadowsize="4096"/>
    <map znear="0.01" zfar="50"/>
  </visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" mark="edge" rgb1="0.975 0.975 0.965"
             rgb2="0.975 0.975 0.965" markrgb="0.80 0.83 0.87" width="100" height="100"/>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.99 0.99 0.985" rgb2="0.93 0.94 0.95"
             width="256" height="1536"/>
    <material name="grid" texture="grid" texrepeat="10 10" texuniform="true" reflectance="0"/>
  </asset>
  <worldbody>
    <light pos="0.5 -1.0 4" dir="-0.1 0.25 -1" diffuse="0.5 0.5 0.5" specular="0.1 0.1 0.1" castshadow="true"/>
    <light type="directional" pos="-2 2 3" dir="0.5 -0.5 -1" diffuse="0.2 0.2 0.2" castshadow="false"/>
    <geom name="floor" type="plane" size="10 10 0.1" material="grid" class="bench"/>
  </worldbody>
</mujoco>
"""


def _add_item(world: mujoco.MjSpec, p: Placed, meta: dict, fixed: bool, mesh_cache: set):
    d = catalog.ASSETS / p.item
    prefix = f"{p.item}__"
    if p.item not in mesh_cache:
        mesh_cache.add(p.item)
        for k, v in enumerate(meta["visuals"]):
            world.add_mesh(name=f"{prefix}vis{k}", file=str(d / v["mesh"]))
            if v.get("texture"):
                world.add_texture(name=f"{prefix}tex{k}", file=str(d / v["texture"]),
                                  type=mujoco.mjtTexture.mjTEXTURE_2D)
                mat = world.add_material(name=f"{prefix}mat{k}", rgba=v["rgba"])
                mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = f"{prefix}tex{k}"
            else:
                world.add_material(name=f"{prefix}mat{k}", rgba=v["rgba"])
            world.material(f"{prefix}mat{k}").specular = 0.3 if v.get("metallic", 0) > 0.5 else 0.15
            world.material(f"{prefix}mat{k}").shininess = max(0.05, 1 - v.get("roughness", 0.6))
        for k, c in enumerate(meta["collision_parts"]):
            world.add_mesh(name=f"{prefix}col{k}", file=str(d / c["mesh"]))
    quat = p.quat or yaw_quat(p.yaw)
    body = world.worldbody.add_body(name=f"obj_{p.uid}", pos=list(p.pos), quat=list(quat))
    if not fixed:
        body.add_freejoint(name=f"obj_{p.uid}_joint")
    cls = world.find_default("furniture" if fixed else "prop")
    total_vol = sum(c["volume"] for c in meta["collision_parts"]) or 1.0
    mass = meta.get("mass") or 0.1
    for k, c in enumerate(meta["collision_parts"]):
        g = body.add_geom(name=f"obj_{p.uid}_col{k}", type=mujoco.mjtGeom.mjGEOM_MESH,
                          meshname=f"{prefix}col{k}", default=cls, group=3, rgba=[0, 0, 0, 0])
        g.mass = mass * c["volume"] / total_vol
        if meta.get("friction"):
            g.friction = [meta["friction"], g.friction[1], g.friction[2]]
    for k, _ in enumerate(meta["visuals"]):
        body.add_geom(name=f"obj_{p.uid}_vis{k}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"{prefix}vis{k}",
                      material=f"{prefix}mat{k}", contype=0, conaffinity=0, group=1, mass=0)


def table_top(meta: dict) -> float:
    return float(meta["size"][2])


def _quat_mul(a, b):
    q = np.zeros(4)
    mujoco.mju_mulQuat(q, np.asarray(a, float), np.asarray(b, float))
    return q


def _camera(world, name, pos, target, fovy, up=(0, 0, 1)):
    cam = world.worldbody.add_camera(name=name, pos=list(pos), fovy=fovy)
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [float(v) for v in S._look_at_axes(pos, target, up=up).split()]


def add_station(world: mujoco.MjSpec, st: Station, cache: set):
    """A station's table, its robot on it, and the robot's overhead and side cameras."""
    tmeta = catalog.meta(st.table_item)
    top = table_top(tmeta)
    _add_item(world, Placed(table_uid(st), st.table_item, (st.pos[0], st.pos[1], 0.0), st.table_yaw),
              tmeta, True, cache)
    rx, ry = st.robot_xy
    mount = _quat_mul(yaw_quat(st.yaw), [float(v) for v in S.ROBOTS[st.robot]["mount_quat"].split()])
    world.worldbody.add_site(name=st.prefix + "robot_mount", pos=list(st.to_world(rx, ry, top)),
                             quat=list(mount))
    c, s_ = math.cos(st.yaw), math.sin(st.yaw)
    _camera(world, st.prefix + "overhead", st.to_world(rx + 0.75, ry, top + 1.0),
            st.to_world(rx + 0.42, ry, top), 55, up=(-c, -s_, 0))
    _camera(world, st.prefix + "side", st.to_world(rx + 1.75, ry - 1.3, top + 0.8),
            st.to_world(rx + 0.4, ry, top + 0.1), 45)
    S.add_robot(world, st.robot, st.prefix + "robot_mount", st.prefix)


def build(placed: list[Placed], stations: list[Station]) -> mujoco.MjModel:
    """Compile the lab: every station (table, robot, cameras) and every placed item."""
    world = mujoco.MjSpec.from_string(_world_xml())
    cache: set = set()
    for st in stations:
        add_station(world, st, cache)
    for p in placed:
        it = catalog.item(p.item)
        _add_item(world, p, catalog.meta(p.item), it["fixed"], cache)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()


def default_scene() -> list[Placed]:
    return []


def default_stations() -> list[Station]:
    return [Station("st1", "franka", (0.0, 0.0), 0.0, "Robot 1")]
