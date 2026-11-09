"""Builds the playground scene: a graph-paper floor, NVIDIA's packing table, the Franka on
it, and whatever the user has dropped in.

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

TABLE_UID = "table"
# The Franka stands on the table, near one long edge, facing across it (+x).
ROBOT_XY = (-0.42, 0.0)

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
    <map znear="0.01" zfar="50" fogstart="0.8" fogend="2.2"/>
    <rgba fog="0 0 0 1"/>
  </visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" mark="edge" rgb1="0.975 0.975 0.965"
             rgb2="0.975 0.975 0.965" markrgb="0.80 0.83 0.87" width="100" height="100"/>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.99 0.99 0.985" rgb2="0.93 0.94 0.95"
             width="256" height="1536"/>
    <material name="grid" texture="grid" texrepeat="10 10" texuniform="true" reflectance="0"/>
    <!-- the main view's floor in free play (sim.py swaps it in there only): Tron's glowing grid -->
    <texture name="tron" type="2d" builtin="checker" mark="edge" rgb1="0.015 0.025 0.05"
             rgb2="0.015 0.025 0.05" markrgb="0.15 0.85 1.0" width="64" height="64"/>
    <material name="tron" texture="tron" texrepeat="10 10" texuniform="true" reflectance="0.12"/>
  </asset>
  <worldbody>
    <light pos="0.5 -1.0 4" dir="-0.1 0.25 -1" diffuse="0.5 0.5 0.5" specular="0.1 0.1 0.1" castshadow="true"/>
    <light pos="-2 2 3" dir="0.5 -0.5 -1" diffuse="0.2 0.2 0.2" castshadow="false"/>
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


def build(placed: list[Placed], robot: str = "franka") -> mujoco.MjModel:
    """Compile the scene: the fixed table (placed[0]), the robot on it, and every item."""
    world = mujoco.MjSpec.from_string(_world_xml())
    cache: set = set()
    tmeta = catalog.meta(catalog.DEFAULT_TABLE)
    top = table_top(tmeta)
    for p in placed:
        it = catalog.item(p.item)
        _add_item(world, p, catalog.meta(p.item), it["fixed"], cache)
    # Robot mount on the table top, and the robot's cameras.
    rx, ry = ROBOT_XY
    world.worldbody.add_site(name="robot_mount", pos=[rx, ry, top], quat=[1, 0, 0, 0])
    over = (rx + 0.75, ry, top + 1.0)
    cam = world.worldbody.add_camera(name="overhead", pos=list(over), fovy=55)
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [float(v) for v in S._look_at_axes(over, (rx + 0.42, ry, top), up=(-1, 0, 0)).split()]
    side = (rx + 1.75, ry - 1.3, top + 0.8)
    cam = world.worldbody.add_camera(name="side", pos=list(side), fovy=45)
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [float(v) for v in S._look_at_axes(side, (rx + 0.4, ry, top + 0.1)).split()]
    ft_site = S._franka(world) if robot == "franka" else S._ur5e(world)
    world.add_sensor(name="ft_force", type=mujoco.mjtSensor.mjSENS_FORCE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    world.add_sensor(name="ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()


def default_scene() -> list[Placed]:
    return [Placed(TABLE_UID, catalog.DEFAULT_TABLE, (0.0, 0.0, 0.0))]
