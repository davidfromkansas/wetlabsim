"""LIBERO stations: LIBERO's own rooms, its 40 tasks (Goal, Spatial, Object and Long), its 50
official starting setups per task, and its own success checks, as stations in the playground.

Each task's scene is the one LIBERO builds: we built every task once in LIBERO's own stack
(robosuite 1.4, MuJoCo 2.3) and saved the compiled model (tools/libero_export.py),
then made it loadable in MuJoCo 4 (tools/import_libero.py). Rooms, tables, objects, fixtures, region
markers and placements are LIBERO's, under LIBERO's own names. The robot is our Franka (the
same model, controller and command interface as everywhere else in this repo), mounted
where LIBERO mounts its Panda. Physics settings are the playground's (playground.world.OPTION).

The success checks follow LIBERO's predicate code (libero/libero/envs/predicates and
object_states): On, In, Open, Close, TurnOn and TurnOff, with the same thresholds, which
the export probed from LIBERO's own object classes.
"""
from __future__ import annotations

import functools
import json
import re
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import mujoco
import numpy as np

from .tools import fetch_libero as FA

HERE = pathlib.Path(__file__).parent
ASSETS = HERE / "libero_assets"
FILES = ASSETS / "files"
SUITES_DIR = ASSETS / "suites"

# The four suites Anthropic's study used (LIBERO-40), in the order the app shows them.
SUITES = [
    ("libero_goal", "Goal", "Understands what you ask: one kitchen, the instruction changes."),
    ("libero_spatial", "Spatial", "Picks the right one of two identical bowls from where it is."),
    ("libero_object", "Object", "Recognises and handles different groceries."),
    ("libero_10", "Long", "Chains two steps, like mug into microwave and then close it."),
]
SUITE_NAMES = {k: n for k, n, _ in SUITES}
STUDY_SETUPS = 5          # the study set: setups 1-5 of every task (Anthropic's 200 runs)


@dataclass
class Task:
    id: str
    suite: str
    index: int
    language: str
    goal: list                    # [(predicate, arg1[, arg2]), ...], all must hold
    meta: dict = field(repr=False)
    dir: pathlib.Path = field(repr=False)

    @functools.cached_property
    def states(self) -> np.ndarray:
        return np.load(self.dir / "init_states.npy")

    @property
    def n_setups(self) -> int:
        return int(self.meta.get("n_setups") or len(self.states))


@functools.lru_cache(maxsize=1)
def _all() -> tuple[Task, ...]:
    out = []
    for suite, _, _ in SUITES:
        for d in sorted((SUITES_DIR / suite).glob("*")):
            meta = json.loads((d / "meta.json").read_text())
            goal = [tuple(g) for g in meta["goal"]]
            out.append(Task(meta["name"], suite, meta["index"], meta["language"], goal, meta, d))
    return tuple(out)


def tasks(suite: str | None = None) -> list[Task]:
    return [t for t in _all() if suite is None or t.suite == suite]


def task(task_id: str) -> Task:
    t = next((t for t in _all() if t.id == task_id), None)
    if t is None:
        raise KeyError(task_id)
    return t


# ----------------------------------------------------------------- the room
def room_kind(t: Task) -> str:
    """Which of LIBERO's rooms a task is in, in plain words."""
    for pre, name in (("KITCHEN_", "Kitchen"), ("LIVING_ROOM_", "Living room"), ("STUDY_", "Study")):
        if t.id.startswith(pre):
            return name
    return "Floor" if t.suite == "libero_object" else "Kitchen table"


@functools.lru_cache(maxsize=64)
def room(task_id: str) -> dict:
    """A task's room, in LIBERO's own frame: the floor area its walls enclose (x0, x1, y0, y1),
    its centre and size, and the robot's base pose."""
    t = task(task_id)
    root = ET.parse(t.dir / "scene.xml").getroot()
    xs, ys = [], []
    for g in root.find("worldbody").findall("geom"):
        if not (g.get("name") or "").startswith("wall_") or g.get("size") is None:
            continue
        px, py, _ = (float(v) for v in g.get("pos").split())
        hx = float(g.get("size").split()[0])
        # a wall is a thin box turned upright: its long side is the box's x
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, np.array([float(v) for v in (g.get("quat") or "1 0 0 0").split()]))
        ax = R.reshape(3, 3)[:, 0]
        xs += [px - hx * ax[0], px + hx * ax[0]]
        ys += [py - hx * ax[1], py + hx * ax[1]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "centre": ((x0 + x1) / 2, (y0 + y1) / 2),
            "size": (x1 - x0, y1 - y0), "base": t.meta["robot_base"]}


ROOM_WALL_GROUP = 5     # the room's walls: the robot's cameras see them (as in LIBERO); the page's
                        # 3D view, which looks in from outside, leaves them out (world.WALL_GROUP)


def room_spec(t: Task) -> mujoco.MjSpec:
    """The task's room as LIBERO builds it (walls, floor, table or floor area, fixtures and
    objects, under LIBERO's own names), ready to attach into the playground at a station.

    Kept as LIBERO has it, except: its own cameras and sky go (the station has its own cameras,
    the playground its sky); its floor is drawn only (the playground's floor, at the same height,
    holds things up) and cut to the room's walls; its walls are seen by the robot's cameras only;
    its collision shapes are hidden as LIBERO hides them; and the robot's pedestal and mount
    point are added where LIBERO mounts its Panda."""
    if FA.missing():          # LIBERO's meshes and textures: downloaded on first use
        FA.ensure()
    root = ET.fromstring((t.dir / "scene.xml").read_text().replace("{FILES}", str(FILES)))
    for tag in ("visual",):
        for el in root.findall(tag):
            root.remove(el)
    asset = root.find("asset")
    for tx in asset.findall("texture"):
        if tx.get("type") == "skybox":
            asset.remove(tx)
    ET.SubElement(asset, "material", {"name": "pg_mount", "rgba": "0.2 0.2 0.22 1", "specular": "0.3"})
    wb = root.find("worldbody")
    for el in list(wb):
        if el.tag == "camera":
            wb.remove(el)
    r = room(t.id)
    for g in wb.iter("geom"):
        n = g.get("name") or ""
        if n == "floor" and g.get("type") == "plane":
            # drawn only, 1 mm above the playground's floor, over the room's floor area
            g.set("type", "box")
            g.set("size", f"{(r['x1'] - r['x0']) / 2:.4f} {(r['y1'] - r['y0']) / 2:.4f} 0.0005")
            g.set("pos", f"{r['centre'][0]:.4f} {r['centre'][1]:.4f} 0.0005")
            g.set("contype", "0")
            g.set("conaffinity", "0")
        elif n.startswith("wall_"):
            g.set("group", str(ROOM_WALL_GROUP))
    bp = t.meta["robot_base"]["pos"]
    bq = t.meta["robot_base"]["quat"]
    # The Panda's pedestal (LIBERO's Rethink mount), drawn simply; on the floor scenes the
    # robot stands on the floor itself.
    if bp[2] > 0.05:
        ET.SubElement(wb, "geom", {"name": "pg_pedestal", "type": "cylinder", "size": f"0.1 {bp[2] / 2:.4f}",
                                   "pos": f"{bp[0]} {bp[1]} {bp[2] / 2:.4f}", "contype": "0", "conaffinity": "0",
                                   "group": "1", "material": "pg_mount"})
    ET.SubElement(wb, "site", {"name": "robot_mount", "pos": " ".join(map(str, bp)), "quat": " ".join(map(str, bq))})
    spec = mujoco.MjSpec.from_string(ET.tostring(root, encoding="unicode"))
    _hide_collision_shapes(spec)
    return spec


def cameras(t: Task) -> dict:
    """The station's two fixed cameras, in LIBERO's frame: "overhead" is LIBERO's agentview (what
    its policies see), "side" its frontview."""
    av = t.meta["agentview"]
    root = ET.parse(t.dir / "scene.xml").getroot()
    fv = next((c for c in root.find("worldbody").findall("camera") if c.get("name") == "frontview"), None)
    return {"overhead": {"pos": list(av["pos"]), "quat": list(av["quat"]), "fovy": float(av["fovy"])},
            "side": {"pos": [float(v) for v in (fv.get("pos") if fv is not None else "1.0 0.0 1.48").split()],
                     "quat": [float(v) for v in (fv.get("quat") if fv is not None else "0.56 0.43 0.43 0.56").split()],
                     "fovy": 45.0}}


def _hide_collision_shapes(spec: mujoco.MjSpec):
    # LIBERO draws collision shapes (group 0) only when debugging.
    for g in spec.geoms:
        if g.group == 0 and (g.contype or g.conaffinity) and g.name != "floor":
            g.group = 3


# ---------------------------------------------------------- starting setups
def apply_setup(m: mujoco.MjModel, d: mujoco.MjData, t: Task, setup: int, arm_qadr, prefix: str = "",
                origin=(0.0, 0.0, 0.0), yaw: float = 0.0, grip_names=("finger_joint1", "finger_joint2")):
    """Put a station's room in one of LIBERO's official starting states.

    A state is [time, qpos, qvel] of LIBERO's own model. The arm starts at the setup's joint
    angles (robot0_joint1..7); the hand starts open (our gripper's rest). Every other joint
    has the same name in our model (after the station's prefix) and is copied across by name;
    a loose object's place goes from LIBERO's frame to the world's (the room stands at
    `origin`, turned by `yaw`). Returns the arm's joint angles.
    """
    q = t.states[setup][1:1 + t.meta["nq"]]
    arm = np.array([q[j["qposadr"]] for j in t.meta["joints"] if j["name"].startswith("robot0_joint")])
    d.qpos[arm_qadr] = arm
    for n in grip_names:
        d.qpos[m.joint(prefix + n).qposadr[0]] = 0.04
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    qyaw = np.array([np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)])
    width = {0: 7, 1: 4, 2: 1, 3: 1}       # free, ball, slide, hinge
    room_free = []
    for j in t.meta["joints"]:
        if j["name"].startswith(("robot0_", "gripper0_", "mount0_")):
            continue
        a, w = j["qposadr"], width[j["type"]]
        jid = m.joint(prefix + j["name"]).id
        jq, jv = m.jnt_qposadr[jid], m.jnt_dofadr[jid]
        v = np.array(q[a:a + w], float)
        if w == 7:
            v[:3] = R @ v[:3] + np.asarray(origin, float)
            qq = np.zeros(4)
            mujoco.mju_mulQuat(qq, qyaw, v[3:])
            v[3:] = qq
            room_free.append(m.jnt_bodyid[jid])
        d.qpos[jq:jq + w] = v
        d.qvel[jv:jv + {7: 6, 4: 3}.get(w, 1)] = 0
    for k in range(len(arm_qadr)):
        d.qvel[m.jnt_dofadr[np.where(m.jnt_qposadr == arm_qadr[k])[0][0]]] = 0
    _lift_out_of_overlaps(m, d, {int(b) for b in room_free})
    return arm


def _lift_out_of_overlaps(m: mujoco.MjModel, d: mujoco.MjData, bodies: set, tol: float = 0.0005):
    """LIBERO's saved setups leave some objects up to 3 cm inside the table (its MuJoCo 2.3
    box-box test reports half the true overlap, so LIBERO pushes them out gently; MuJoCo 4
    sees the true overlap and they would shoot out). Raise each of the room's loose objects just
    out of whatever it overlaps, keeping its x, y and orientation; it then settles onto its
    support. Only the start pose changes, by at most a few centimetres up."""
    free = {m.jnt_bodyid[j]: m.jnt_qposadr[j] for j in range(m.njnt)
            if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE and m.jnt_bodyid[j] in bodies}
    for _ in range(30):
        mujoco.mj_forward(m, d)
        lift: dict[int, float] = {}
        for i in range(d.ncon):
            c = d.contact[i]
            if c.dist >= -tol:
                continue
            b1, b2 = m.body_rootid[m.geom_bodyid[c.geom1]], m.body_rootid[m.geom_bodyid[c.geom2]]
            # lift the loose object; of two loose objects, the higher one
            cands = [b for b in (b1, b2) if b in free]
            if not cands:
                continue
            b = max(cands, key=lambda x: d.xpos[x][2])
            lift[b] = max(lift.get(b, 0.0), -c.dist + tol)
        if not lift:
            return
        for b, dz in lift.items():
            d.qpos[free[b] + 2] += dz


# ------------------------------------------------------------- the checks
def _within(intervals, q) -> bool:
    return any(lo <= q < hi for lo, hi in intervals)


class Checker:
    """LIBERO's success predicates on our model, for one task."""

    def __init__(self, m: mujoco.MjModel, t: Task, prefix: str = "", origin=(0.0, 0.0, 0.0), yaw: float = 0.0):
        # LIBERO's checks read positions and site frames in LIBERO's own world frame, so a
        # station's room (standing at `origin`, turned by `yaw`) is checked in its own frame.
        self.m, self.t, self.prefix = m, t, prefix
        c, s_ = np.cos(yaw), np.sin(yaw)
        self._Rt = np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]]).T     # world -> room
        self._o = np.asarray(origin, float)
        self.objs = t.meta["objects"]
        self.sites = t.meta["sites"]
        self.body = {n: m.body(prefix + o["root_body"]).id for n, o in self.objs.items()}
        gid = {m.geom(i).name: i for i in range(m.ngeom) if m.geom(i).name.startswith(prefix)}
        self.geoms = {n: {gid[prefix + g] for g in o["contact_geoms"] if prefix + g in gid}
                      for n, o in self.objs.items()}

    def contact(self, d, a: str, b: str) -> bool:
        A, B = self.geoms[a], self.geoms[b]
        for i in range(d.ncon):
            c = d.contact[i]
            if (c.geom1 in A and c.geom2 in B) or (c.geom1 in B and c.geom2 in A):
                return True
        return False

    def pos(self, d, name):
        return self._Rt @ (d.xpos[self.body[name]] - self._o)

    def _site(self, d, name):
        sid = self.m.site(self.prefix + name).id
        return (self._Rt @ (d.site_xpos[sid] - self._o), self._Rt @ d.site_xmat[sid].reshape(3, 3),
                np.asarray(self.sites[name]["size"], float))

    def _joint_q(self, d, joint):
        return float(d.qpos[self.m.joint(self.prefix + joint).qposadr[0]])

    # ObjectState / SiteObjectState
    def ontop(self, d, a: str, b: str) -> bool:        # On(a, b) = b.check_ontop(a)
        if b in self.objs:
            pa, pb = self.pos(d, a), self.pos(d, b)
            return bool(pb[2] <= pa[2] and self.contact(d, b, a) and np.linalg.norm(pb[:2] - pa[:2]) < 0.03)
        s = self.sites[b]
        if not s["under"]:
            return True
        p, R, size = self._site(d, b)
        delta = R @ (self.pos(d, a) - p)
        under = bool(size[2] - 0.005 < delta[2] < size[2] + 0.10 and np.all(np.abs(delta[:2]) < size[:2]))
        if s["parent"] is None or s["parent"] not in self.objs:
            return under
        return under and self.contact(d, s["parent"], a)

    def inside(self, d, a: str, b: str) -> bool:       # In(a, b) = b.check_contact(a) and b.check_contain(a)
        if b not in self.sites:
            raise ValueError(f"In({a}, {b}): LIBERO's object-in-object check isn't used by these tasks")
        p, R, size = self._site(d, b)
        total = np.abs(R @ size)
        ub, lb = p + total, p - total
        lb[2] -= 0.01
        o = self.pos(d, a)
        return bool(np.all(o > lb) and np.all(o < ub))

    def _joints_and_rules(self, x: str):
        if x in self.objs:
            return self.objs[x]["joints"], self.objs[x]["articulation"]
        s = self.sites[x]
        return s["joints"], self.objs[s["parent"]]["articulation"]

    def _any(self, d, x, rule):
        joints, art = self._joints_and_rules(x)
        return any(_within(art[rule], self._joint_q(d, j)) for j in joints)

    def _all(self, d, x, rule):
        joints, art = self._joints_and_rules(x)
        return all(_within(art[rule], self._joint_q(d, j)) for j in joints)

    def check_one(self, d, g: tuple) -> bool:
        p, *args = g
        p = p.lower()
        if p == "on":
            return self.ontop(d, args[0], args[1])
        if p == "in":
            return self.inside(d, args[0], args[1])
        if p == "open":
            return self._any(d, args[0], "is_open")
        if p == "close":
            return self._all(d, args[0], "is_close")
        if p == "turnon":
            return self._any(d, args[0], "turn_on")
        if p == "turnoff":
            return self._all(d, args[0], "turn_off")
        raise ValueError(f"unknown predicate {p}")

    def check(self, d, goal=None) -> bool:
        return all(self.check_one(d, g) for g in (goal or self.t.goal))

    def each(self, d) -> list[bool]:
        """Each of the goal's parts: whether it holds now."""
        return [self.check_one(d, g) for g in self.t.goal]

    def lit_burners(self, d) -> dict[str, bool]:
        """Stoves that are on, so their burner can glow as in LIBERO."""
        return {n: self._any(d, n, "turn_on") for n, o in self.objs.items() if "turn_on" in o["articulation"]}


# ------------------------------------------------------------- words
_NICE = {"akita_black_bowl": "black bowl", "glazed_rim_porcelain_ramekin": "ramekin", "flat_stove": "stove",
         "wooden_cabinet": "wooden cabinet", "white_cabinet": "white cabinet", "wine_rack": "wine rack",
         "desk_caddy": "desk caddy", "short_cabinet": "short cabinet", "short_fridge": "small fridge",
         "black_book": "black book", "yellow_book": "yellow book", "white_yellow_mug": "white and yellow mug",
         "red_coffee_mug": "red coffee mug", "porcelain_mug": "white mug", "chefmate_8_frypan": "frying pan",
         "moka_pot": "moka pot", "bbq_sauce": "barbecue sauce", "alphabet_soup": "alphabet soup",
         "cream_cheese": "cream cheese box", "tomato_sauce": "tomato sauce", "salad_dressing": "salad dressing",
         "orange_juice": "orange juice", "chocolate_pudding": "chocolate pudding", "basket": "basket",
         "microwave": "microwave", "plate": "plate", "wine_bottle": "wine bottle", "ketchup": "ketchup",
         "butter": "butter", "milk": "milk", "cookies": "cookie box"}


def label(t: Task, name: str) -> str:
    o = t.meta["objects"].get(name)
    cat = o["category"] if o else name.rsplit("_", 1)[0]
    return _NICE.get(cat, cat.replace("_", " "))


def _site_words(t: Task, s: str) -> str:
    info = t.meta["sites"][s]
    parent = info["parent"]
    if parent and parent in t.meta["objects"]:
        rest = s[len(parent) + 1:]
        what = label(t, parent)
        if rest.endswith("_side") and "top" in rest:
            return f"the top of the {what}"
        if rest in ("top_region", "middle_region", "bottom_region"):
            return f"the {rest.split('_')[0]} drawer of the {what}"
        if rest == "cook_region":
            return f"the {what}'s burner"
        if rest == "heating_region":
            return f"the {what}"
        if "contain_region" in rest:
            part = rest.replace("contain_region", "").strip("_")
            return f"the {part + ' compartment of the ' if part else ''}{what}"
        return f"the {what} ({rest.replace('_', ' ')})"
    return "the marked spot on the table"


def _scene_key(t: Task) -> str:
    """Which of LIBERO's rooms a task is set in: a Long task's own scene (KITCHEN_SCENE3...), else
    its suite's one room."""
    m = re.match(r"^([A-Z_]+_SCENE\d+)_", t.id)
    return m.group(1) if m else t.suite


def room_name(t: Task) -> str:
    """A task's room, named for a free station: "Kitchen 3", "Living room 2", "Kitchen table (Goal)"."""
    m = re.match(r"^[A-Z_]+_SCENE(\d+)_", t.id)
    return f"{room_kind(t)} {m.group(1)}" if m else \
        "Floor" if t.suite == "libero_object" else f"{room_kind(t)} ({SUITE_NAMES[t.suite]})"


@functools.lru_cache(maxsize=1)
def rooms() -> list[dict]:
    """LIBERO's different rooms, each once (for free stations): the first task set in each, with
    what stands in it. A suite whose tasks share one room (Goal, Spatial, Object) gives one room."""
    out, seen = [], set()
    for t in _all():
        k = _scene_key(t)
        if k in seen:
            continue
        seen.add(k)
        things = []
        for name in t.meta["objects"]:
            w = label(t, name)
            if w not in things:
                things.append(w)
        out.append({"id": t.id, "name": room_name(t), "kind": room_kind(t), "things": things})
    return out


def goal_parts(t: Task) -> list[str]:
    """Each part of LIBERO's goal check, in plain words."""
    parts = []
    for p, *a in t.goal:
        p = p.lower()
        nm = lambda x: _site_words(t, x) if x in t.meta["sites"] else "the " + label(t, x)
        if p == "open":
            s = f"{nm(a[0])} is pulled open"
        elif p == "close":
            s = f"{nm(a[0])} is shut"
        elif p == "turnon":
            s = f"{nm(a[0])} is turned on"
        elif p == "turnoff":
            s = f"{nm(a[0])} is turned off"
        elif p == "in":
            s = f"{nm(a[0])} is inside {nm(a[1])}"
        elif a[1] in t.meta["sites"]:
            s = f"{nm(a[0])} is sitting on {nm(a[1])}"
        else:
            s = f"{nm(a[0])} is resting on {nm(a[1])}, touching it"
        parts.append(s[0].upper() + s[1:])
    return parts


def done_when(t: Task) -> str:
    """LIBERO's goal check in plain words."""
    parts = goal_parts(t)
    s = "; and ".join(p[0].lower() + p[1:] for p in parts)
    return s[0].upper() + s[1:] + "."


# ---------------------------------------------------------- the site sheet
def _table(m: mujoco.MjModel, d: mujoco.MjData, base, to_room=None, from_room=None):
    """The surface the robot works on: what a ray straight down meets in front of the robot (MuJoCo's
    mj_ray), skipping anything that moves (objects on it, the arm). Its centre and half-size in
    LIBERO's frame (from the hit geom's bounding box) and its top height. base: the robot base's
    position in LIBERO's frame; to_room / from_room: world <-> LIBERO's frame.
    The biggest fixed box is not it: in the study and living rooms the table is a mesh, and the
    biggest box is part of a wall or shelf."""
    to_room = to_room or (lambda p: p)
    from_room = from_room or (lambda p: p)
    gid = np.zeros(1, np.int32)
    hits = []
    for ahead in (0.5, 0.4, 0.6, 0.3, 0.7):
        p = np.array(from_room((base[0] + ahead, base[1], base[2] + 0.6)), float)
        for _ in range(20):
            dist = mujoco.mj_ray(m, d, p, np.array([0.0, 0.0, -1.0]), None, 1, -1, gid)
            if dist < 0 or dist > 2.0:
                break
            g = int(gid[0])
            if m.body_weldid[m.geom_bodyid[g]] == 0 and m.geom_bodyid[g] != 0:
                hits.append(g)
                break
            p = p + np.array([0.0, 0.0, -(dist + 1e-4)])     # something that moves: look on below it
        if hits:
            break
    if not hits:
        return None
    g = hits[0]
    # The geom's bounding box (MuJoCo's geom_aabb: centre and half-sizes in the geom's frame) in LIBERO's frame.
    ac, ah = m.geom_aabb[g, :3], m.geom_aabb[g, 3:]
    R = d.geom_xmat[g].reshape(3, 3)
    corners = [to_room(d.geom_xpos[g] + R @ (ac + ah * np.array(sg)))
               for sg in np.array(np.meshgrid([-1, 1], [-1, 1], [-1, 1])).T.reshape(-1, 3)]
    corners = np.array(corners, float)
    lo, hi = corners.min(0), corners.max(0)
    top = float(to_room(p + np.array([0.0, 0.0, -dist]))[2])
    return (lo + hi) / 2, (hi - lo) / 2, top


def site_sheet(t: Task, m: mujoco.MjModel | None = None, d: mujoco.MjData | None = None,
               to_room=None, from_room=None) -> str:
    bx, by, bz = t.meta["robot_base"]["pos"]
    table = ""
    if m is not None and d is not None and (tb := _table(m, d, (bx, by, bz), to_room, from_room)) is not None:
        c, s, top = tb
        table = f"""- The robot base frame has its origin at the centre of the base flange, {(bz - top) * 100:.1f} cm above
  the table top. x points forward along the table, y to the robot's left, z up. All
  positions and poses in the command interface are in this frame, in metres.
- The table top is the plane z = {top - bz:.3f} m. It extends from x = {c[0] - s[0] - bx:.2f} m to
  x = {c[0] + s[0] - bx:.2f} m and from y = {c[1] - s[1] - by:.2f} m to y = {c[1] + s[1] - by:.2f} m."""
    return f"""# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Franka Emika Panda on a pedestal at the end of a table, facing along the table.
{table}

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

## Start state

At the start of a run the arm is in the pose it was left in, hand open, not in a
protective stop.
"""
