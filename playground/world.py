"""Builds the playground's lab: a graph-paper floor, the robot stations on it (each a robot
arm on its own NVIDIA packing table, with its own overhead and side cameras), and whatever
the user has dropped in.

Every library item comes from playground/assets/<id>/ (see tools/convert_simready.py):
visual meshes with their textures, collision meshes, and the mass the asset states.
Physics settings (solver, materials) are the robot cell's own (wetlabsim/scene.py).
"""
from __future__ import annotations

import math
import re
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

# The lab's solver options: the robot cell's own (wetlabsim/scene.py), except three, so that
# soft objects can be springy. MuJoCo 4.0 integrates flex elasticity only under its
# "discrete" integrator ("Numerical integration" in MuJoCo's Computation chapter). Under
# "discrete", MuJoCo's noslip post-processing leaves out tendon and actuator couplings (same
# chapter), and the Franka Hand closes through a tendon: with noslip its grasps slipped and
# dropped things. So noslip is off, and grasps are kept from slipping the way MuJoCo's
# documentation gives for elliptic friction cones instead: a high impratio (frictional-to-
# normal constraint impedance; "XML Reference", option/impratio), 100. Measured in the
# playground (tools: a 20 s full-strength hold of six items, both arms, both benches): every
# grasp holds, creeping 0.06-1.5 mm (a mug held by its rim, 3-19 mm), as with the cell's
# own settings. The robot cell, and with it Wet Lab and LIBERO mode, keeps its own options.
OPTION = {**S.OPTION, "integrator": "discrete", "noslip_iterations": 0, "impratio": 100}


@dataclass
class Placed:
    uid: str
    item: str
    pos: tuple            # world position of the item's bottom centre (m)
    yaw: float = 0.0      # rotation about the vertical (rad)
    quat: tuple | None = None   # full orientation when set (after physics has moved it)
    joints: dict | None = None  # a jointed item's joint positions, by joint name (kept across rebuilds)
    parts: dict | None = None   # a jointed item's loose or welded parts: body name -> (pos, quat)

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
  <option {_xml_attrs(OPTION)}><flag {_xml_attrs(S.FLAGS)}/></option>
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


def _add_materials(world: mujoco.MjSpec, d, prefix: str, meta: dict):
    for k, v in enumerate(meta["visuals"]):
        if v.get("texture"):
            world.add_texture(name=f"{prefix}tex{k}", file=str(d / v["texture"]),
                              type=mujoco.mjtTexture.mjTEXTURE_2D)
            mat = world.add_material(name=f"{prefix}mat{k}", rgba=v["rgba"])
            mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = f"{prefix}tex{k}"
        else:
            world.add_material(name=f"{prefix}mat{k}", rgba=v["rgba"])
        world.material(f"{prefix}mat{k}").specular = 0.3 if v.get("metallic", 0) > 0.5 else 0.15
        world.material(f"{prefix}mat{k}").shininess = max(0.05, 1 - v.get("roughness", 0.6))


def _pose(pos, quat) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = _rot(quat)
    T[:3, 3] = pos
    return T


def _quat_of(T: np.ndarray) -> list:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(T[:3, :3]).ravel())
    return [float(v) for v in q]


def _part_geoms(world, body, name: str, rec: dict, prefix: str, cls, friction, at=None):
    """A part's collision shapes (its stated mass spread over them by volume) and its visuals;
    at: where the part sits in the body, for a part fixed onto another."""
    off = {} if at is None else {"pos": list(at[:3, 3]), "quat": _quat_of(at)}
    total = sum(c["volume"] for c in rec["collision_parts"]) or 1.0
    for k, c in enumerate(rec["collision_parts"]):
        g = body.add_geom(name=f"{name}_col{k}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"{prefix}col{k}",
                          default=cls, group=3, rgba=[0, 0, 0, 0], **off)
        if rec.get("mass"):
            g.mass = rec["mass"] * c["volume"] / total
        if friction:
            g.friction = [friction, g.friction[1], g.friction[2]]
    for k, _ in enumerate(rec["visuals"]):
        body.add_geom(name=f"{name}_vis{k}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"{prefix}vis{k}",
                      material=f"{prefix}mat{k}", contype=0, conaffinity=0, group=1, mass=0, **off)
    if at is None and not rec["collision_parts"]:          # a part with nothing to touch still needs a mass to move
        body.mass, body.inertia, body.explicitinertial = rec.get("mass") or 0.005, [1e-7] * 3, True


# Parts an asset glues on with a fixed joint that stay separate bodies (held by a weld), so they
# could come off later: caps, lids and stoppers. Other glued parts (labels, needles, shelves,
# straps) are fixed in place on their part, and cost nothing.
SEPARATE = re.compile(r"cap|lid|cork|stopper|plug", re.I)


def part_kind(b: dict, fixed: bool) -> str:
    """How a part of a jointed item is built: "top" (the main body, a loose part, a welded cap),
    "joint" (on its hinge or slide) or "rigid" (fixed in place: its shapes join its parent part's
    body). Fixed too, as they'd only cost speed: free-spinning wheels and casters (unlimited
    hinges) of furniture, which doesn't roll here, and buttons and switches of furniture (and of
    everything, with BUTTONS_MOVE off)."""
    if b.get("root") or b.get("free"):
        return "top"
    if b.get("weld"):
        return "top" if SEPARATE.search(b["name"]) else "rigid"
    if fixed and "range" not in b["joint"]:
        return "rigid"
    if BUTTON.search(b["name"]) and (fixed or not BUTTONS_MOVE):
        return "rigid"
    return "joint"


BUTTON = re.compile(r"switch|button", re.I)
# A cap's weld: as quick as the lab's plastic contacts (wetlabsim.scene.MATERIALS) and nearly
# hard. With MuJoCo's defaults a light cap is pushed 3 mm (1.5 degrees) off its tube when the
# tube lies on it, and flies 10 cm off on impact.
CAP_SOLREF = [0.005, 1.0]
CAP_SOLIMP = [0.99, 0.999, 0.001, 0.5, 2.0]
# Buttons, triggers and switches of hand-sized items move (a robot can press them); furniture's
# are fixed. False: fixed everywhere (each moving part costs a little speed).
BUTTONS_MOVE = True


def _add_jointed(world: mujoco.MjSpec, p: Placed, meta: dict, fixed: bool, mesh_cache: set):
    """An item with moving parts (tools/convert_simready.convert_articulated): its main body, the
    parts on hinge and slide joints nested under it, and its separate parts (a cap held by a weld,
    or loose)."""
    d = catalog.ASSETS / p.item
    bodies = meta["bodies"]
    pre = [f"{p.item}__b{i}_" for i in range(len(bodies))]
    if p.item not in mesh_cache:
        mesh_cache.add(p.item)
        for i, b in enumerate(bodies):
            for k, v in enumerate(b["visuals"]):         # weightless: a flat part (a label) is fine
                world.add_mesh(name=f"{pre[i]}vis{k}", file=str(d / v["mesh"]),
                               inertia=mujoco.mjtMeshInertia.mjMESH_INERTIA_SHELL)
            _add_materials(world, d, pre[i], b)
            for k, c in enumerate(b["collision_parts"]):
                world.add_mesh(name=f"{pre[i]}col{k}", file=str(d / c["mesh"]))
    cls = world.find_default("furniture" if fixed else "prop")
    T0 = _pose(p.pos, p.quat or yaw_quat(p.yaw))
    names = [f"obj_{p.uid}" if b.get("root") else f"obj_{p.uid}__{i}" for i, b in enumerate(bodies)]
    frame = [_pose(b["frame"][:3], b["frame"][3:]) for b in bodies]
    root = next(i for i, b in enumerate(bodies) if b.get("root"))
    kind = [part_kind(b, fixed) for b in bodies]

    host = list(names)        # the MuJoCo body each part's shapes are in

    def add(i, parent=None):
        """parent: (the body to build in, where the parent part's frame sits in it)."""
        b = bodies[i]
        at = None
        if kind[i] == "top":                         # placed in the world
            saved = (p.parts or {}).get(names[i])     # where it lay, relative to the main body
            T = T0 @ frame[i] if b.get("root") or not saved else T0 @ frame[root] @ _pose(*saved)
            body = world.worldbody.add_body(name=names[i], pos=list(T[:3, 3]), quat=_quat_of(T))
            if not (fixed and b.get("root")):
                body.add_freejoint(name=f"{names[i]}_joint")
        elif kind[i] == "rigid":                     # its shapes join its parent's body
            body, pat = parent
            at = pat @ np.linalg.inv(frame[b["parent"]]) @ frame[i]
            host[i] = host[b["parent"]]
        else:
            pbody, pat = parent
            T = pat @ _pose(b["pos"], b["quat"])
            body = pbody.add_body(name=names[i], pos=list(T[:3, 3]), quat=_quat_of(T))
            j = b["joint"]
            jt = body.add_joint(name=f"{names[i]}_{j['name']}", pos=j["pos"], axis=j["axis"],
                                type=mujoco.mjtJoint.mjJNT_HINGE if j["type"] == "hinge" else mujoco.mjtJoint.mjJNT_SLIDE)
            if "range" in j:
                jt.range, jt.limited = j["range"], mujoco.mjtLimited.mjLIMITED_TRUE
            for k in ("frictionloss", "armature"):
                if k in j:
                    setattr(jt, k, j[k])
            for k in ("damping", "stiffness"):     # MuJoCo's linear coefficient
                if k in j:
                    getattr(jt, k)[0] = j[k]
        _part_geoms(world, body, names[i], b, pre[i], cls, meta.get("friction"), at)
        for c, cb in enumerate(bodies):
            if cb.get("parent") == i and kind[c] != "top":
                add(c, (body, np.eye(4) if at is None else at))

    for i in range(len(bodies)):
        if kind[i] == "top":
            add(i)
    for i, b in enumerate(bodies):
        if kind[i] == "rigid":
            continue
        if b.get("parent") is not None and not b.get("collide") and host[b["parent"]] != host[i]:
            world.add_exclude(bodyname1=host[b["parent"]], bodyname2=names[i])   # jointed parts pass through each other
        if b.get("weld"):                            # held to its parent as the asset lays them out
            hp = next(k for k in range(len(bodies)) if names[k] == host[b["parent"]])
            rel = np.linalg.inv(frame[i]) @ frame[hp]
            world.add_equality(type=mujoco.mjtEq.mjEQ_WELD, objtype=mujoco.mjtObj.mjOBJ_BODY,
                               name=f"{names[i]}_weld", name1=names[i], name2=host[b["parent"]],
                               data=[0, 0, 0, *rel[:3, 3], *_quat_of(rel), 1, 0],
                               solref=CAP_SOLREF, solimp=CAP_SOLIMP)


def part_bodies(m: mujoco.MjModel, uid: str) -> list[int]:
    """A jointed item's bodies besides its main one (obj_<uid>__<i>)."""
    pre = f"obj_{uid}__"
    return [b for b in range(m.nbody) if m.body(b).name.startswith(pre)]


def save_parts(m: mujoco.MjModel, d: mujoco.MjData, p: Placed, root: int):
    """Remember a jointed item's joint positions, and where its separate parts lie relative to
    its main body, so a rebuild (or a move of the item) keeps them as they are."""
    parts = part_bodies(m, p.uid)
    if not parts:
        return
    joints, loose = {}, {}
    Tr = _pose(d.xpos[root], d.xquat[root])
    meta = catalog.meta(p.item)
    if m.body_jntnum[root]:          # the item's place is its own frame's, not its main body's
        fr = next(b["frame"] for b in meta["bodies"] if b.get("root"))
        Ta = Tr @ np.linalg.inv(_pose(fr[:3], fr[3:]))
        p.pos, p.quat = tuple(float(v) for v in Ta[:3, 3]), tuple(_quat_of(Ta))
    for b in parts:
        for j in range(m.body_jntadr[b], m.body_jntadr[b] + m.body_jntnum[b]):
            if m.jnt_type[j] in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
                joints[m.joint(j).name] = float(d.qpos[m.jnt_qposadr[j]])
        if m.body_parentid[b] == 0:
            rel = np.linalg.inv(Tr) @ _pose(d.xpos[b], d.xquat[b])
            loose[m.body(b).name] = (tuple(float(v) for v in rel[:3, 3]), tuple(_quat_of(rel)))
    p.joints, p.parts = joints, loose


def restore_joints(m: mujoco.MjModel, d: mujoco.MjData, p: Placed):
    for name, q in (p.joints or {}).items():
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
        if j >= 0:
            d.qpos[m.jnt_qposadr[j]] = q


def _add_item(world: mujoco.MjSpec, p: Placed, meta: dict, fixed: bool, mesh_cache: set):
    if meta.get("bodies"):
        return _add_jointed(world, p, meta, fixed, mesh_cache)
    d = catalog.ASSETS / p.item
    prefix = f"{p.item}__"
    if p.item not in mesh_cache:
        mesh_cache.add(p.item)
        for k, v in enumerate(meta["visuals"]):
            world.add_mesh(name=f"{prefix}vis{k}", file=str(d / v["mesh"]))
        _add_materials(world, d, prefix, meta)
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


def read_obj(path):
    """Our OBJs (tools/convert_simready.write_obj): v, vt with the same indices, triangles."""
    V, UV, F = [], [], []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                V.append(line.split()[1:4])
            elif line.startswith("vt "):
                UV.append(line.split()[1:3])
            elif line.startswith("f "):
                F.append([c.split("/")[0] for c in line.split()[1:4]])
    return (np.array(V, float).reshape(-1, 3), np.array(UV, float) if UV else None,
            np.array(F, int).reshape(-1, 3) - 1)


def _rot(quat):
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(quat, float))
    return R.reshape(3, 3)


def _add_soft(world: mujoco.MjSpec, p: Placed, meta: dict, mat_cache: set):
    """A soft item (catalog.SOFT): a MuJoCo flex, its own mesh drawn over it as a skin.

    The flex sits in a body "obj_<uid>" at the item's place; its vertices (a solid's 8 corner
    nodes, "obj_<uid>_<ix>_<iy>_<iz>") are bodies "obj_<uid>_<i>" that slide freely. Sheets and
    shells are 2D flexes (tools/build_soft.py's sim.obj), ropes 1D chains; in both the edges
    keep their length (edge equality constraints), so cloth folds but doesn't stretch. Solids
    are 3D flexes with MuJoCo's own elasticity, so they squash and spring back. Contact with everything else uses the
    item's own friction, as rigid items do; the flex doesn't collide with itself."""
    d = catalog.ASSETS / p.item
    soft = meta["soft"]
    quat = yaw_quat(p.yaw)
    R, pos = _rot(quat), np.asarray(p.pos, float)
    simV, _, simF = read_obj(d / soft["sim"])
    pts = " ".join(f"{v:.6f}" for v in simV.ravel())
    if soft["kind"] == "solid":
        lo, hi = simV.min(0), simV.max(0)
        c, size = (lo + hi) / 2, hi - lo
        shape = (f'type="grid" dim="3" count="2 2 2" spacing="{size[0]:.6f} {size[1]:.6f} {size[2]:.6f}" '
                 f'pos="{c[0]:.6f} {c[1]:.6f} {c[2]:.6f}" dof="trilinear"')
    elif soft["kind"] == "rope":
        elems = " ".join(f"{i} {i + 1}" for i in range(len(simV) - 1))
        shape = f'type="direct" dim="1" point="{pts}" element="{elems}"'
    else:
        shape = f'type="direct" dim="2" point="{pts}" element="{" ".join(str(i) for i in simF.ravel())}"'
    mu = meta.get("friction") or PROP["friction"][0]
    material = (f'<elasticity young="{soft["young"]}" poisson="{soft["poisson"]}" damping="{soft["damping"]}"/>'
                if soft["kind"] == "solid" else '<edge equality="true"/>')
    child = mujoco.MjSpec.from_string(f"""<mujoco><worldbody>
      <body name="{p.uid}" pos="{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}" quat="{' '.join(f'{q:.8f}' for q in quat)}">
        <flexcomp name="{p.uid}" {shape} radius="{soft['radius']}" mass="{meta.get('mass') or 0.1}" group="3"
                  rgba="0.6 0.6 0.6 1">
          {material}
          <contact condim="3" friction="{mu} {PROP['friction'][1]} {PROP['friction'][2]}"
                   solref="{PROP['solref'][0]} {PROP['solref'][1]}" selfcollide="none"/>
        </flexcomp>
      </body></worldbody></mujoco>""")
    world.attach(child, frame=world.worldbody.add_frame(), prefix="obj_")
    prefix = f"{p.item}__"
    if p.item not in mat_cache:
        mat_cache.add(p.item)
        _add_materials(world, d, prefix, meta)
    simW = simV @ R.T + pos
    for k, v in enumerate(meta["visuals"]):
        V, UV, F = read_obj(d / v["mesh"])
        b = np.load(d / v["bind"])
        idx, w = b["idx"], b["w"]
        bones = np.unique(idx[w > 1e-6])
        vertid, vertweight = [], []
        for i in bones:
            rows, cols = np.nonzero((idx == i) & (w > 1e-6))
            vertid.append(rows.tolist())
            vertweight.append(w[rows, cols].tolist())
        names = ([f"obj_{p.uid}_{i >> 2}_{(i >> 1) & 1}_{i & 1}" for i in bones] if soft["kind"] == "solid"
                 else [f"obj_{p.uid}_{i}" for i in bones])
        world.add_skin(
            name=f"obj_{p.uid}_skin{k}", material=f"{prefix}mat{k}", group=1,
            vert=(V @ R.T + pos).ravel().tolist(), face=F.ravel().tolist(),
            texcoord=(np.c_[UV[:, 0], 1 - UV[:, 1]].ravel().tolist() if UV is not None else []),
            bodyname=names, bindpos=simW[bones].ravel().tolist(),
            bindquat=np.tile(quat, len(bones)).tolist(), vertid=vertid, vertweight=vertweight)


def soft_count(placed: list[Placed]) -> int:
    return sum(1 for p in placed if catalog.item(p.item)["soft"])


def build(placed: list[Placed], stations: list[Station]) -> mujoco.MjModel:
    """Compile the lab: every station (table, robot, cameras) and every placed item."""
    world = mujoco.MjSpec.from_string(_world_xml())
    cache: set = set()
    for st in stations:
        add_station(world, st, cache)
    for p in placed:
        it = catalog.item(p.item)
        if it["soft"]:
            _add_soft(world, p, catalog.meta(p.item), cache)
        else:
            _add_item(world, p, catalog.meta(p.item), it["fixed"], cache)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()


def default_scene() -> list[Placed]:
    return []


def default_stations() -> list[Station]:
    return [Station("st1", "franka", (0.0, 0.0), 0.0, "Robot 1")]
