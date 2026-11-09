"""LIBERO test mode: LIBERO's own scenes, its 40 tasks (Goal, Spatial, Object and Long),
its 50 official starting setups per task, and its own success checks.

Each task's scene is the one LIBERO builds: we built every task once in LIBERO's own stack
(robosuite 1.4, MuJoCo 2.3) and saved the compiled model (tools/libero_export.py),
then made it loadable in MuJoCo 4 (tools/import_libero.py). Rooms, tables, objects, fixtures, region
markers and placements are LIBERO's, under LIBERO's own names. The robot is our Franka (the
same model, controller and command interface as everywhere else in this repo), mounted
where LIBERO mounts its Panda. Physics settings are ours (wetlabsim.scene.OPTION).

The success checks follow LIBERO's predicate code (libero/libero/envs/predicates and
object_states): On, In, Open, Close, TurnOn and TurnOff, with the same thresholds, which
the export probed from LIBERO's own object classes.
"""
from __future__ import annotations

import functools
import json
import pathlib
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import mujoco
import numpy as np

from wetlabsim import scene as S

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


# ----------------------------------------------------------------- the scene
def _scene_xml(t: Task) -> str:
    root = ET.fromstring((t.dir / "scene.xml").read_text().replace("{FILES}", str(FILES)))
    # Our physics settings, the robot's material classes, and a big enough render buffer.
    opt = ET.Element("option", {k: str(v) for k, v in S.OPTION.items()})
    ET.SubElement(opt, "flag", {k: str(v) for k, v in S.FLAGS.items()})
    size = ET.Element("size", {"memory": "256M"})
    default = ET.Element("default")
    for n, p in S.MATERIALS.items():
        dc = ET.SubElement(default, "default", {"class": n})
        ET.SubElement(dc, "geom", {k: " ".join(map(str, v)) if isinstance(v, (tuple, list)) else str(v)
                                   for k, v in p.items()})
    for i, el in enumerate((opt, size, default)):
        root.insert(1 + i, el)
    vis = root.find("visual")
    if vis is None:
        vis = ET.SubElement(root, "visual")
    for tag, attrs in (("global", {"offwidth": "1920", "offheight": "1200"}),
                       ("headlight", {"ambient": "0.3 0.3 0.3", "diffuse": "0.3 0.3 0.3", "specular": "0.05 0.05 0.05"}),
                       ("quality", {"shadowsize": "4096"})):
        el = vis.find(tag)
        if el is None:
            el = ET.SubElement(vis, tag)
        el.attrib.update(attrs)
    asset = root.find("asset")
    ET.SubElement(asset, "material", {"name": "pg_mount", "rgba": "0.2 0.2 0.22 1", "specular": "0.3"})
    wb = root.find("worldbody")
    bp = t.meta["robot_base"]["pos"]
    bq = t.meta["robot_base"]["quat"]
    # The Panda's pedestal (LIBERO's Rethink mount), drawn simply; on the floor scenes the
    # robot stands on the floor itself.
    if bp[2] > 0.05:
        ET.SubElement(wb, "geom", {"name": "pg_pedestal", "type": "cylinder", "size": f"0.1 {bp[2] / 2:.4f}",
                                   "pos": f"{bp[0]} {bp[1]} {bp[2] / 2:.4f}", "contype": "0", "conaffinity": "0",
                                   "group": "1", "material": "pg_mount"})
    ET.SubElement(wb, "site", {"name": "robot_mount", "pos": " ".join(map(str, bp)), "quat": " ".join(map(str, bq))})
    # A soft shadow-casting light, as in the Goal scene.
    ET.SubElement(wb, "light", {"diffuse": ".3 .3 .3", "dir": "0.2 0 -1", "pos": "0 0 3", "castshadow": "true"})
    # LIBERO's cameras: agentview is what its policies see; here it is the robot's overhead camera.
    cams = {c.get("name"): c for c in wb.findall("camera")}
    av = t.meta["agentview"]
    ET.SubElement(wb, "camera", {"name": "overhead", "pos": " ".join(map(str, av["pos"])),
                                 "quat": " ".join(map(str, av["quat"])), "fovy": str(av["fovy"])})
    fv = cams.get("frontview")
    ET.SubElement(wb, "camera", {"name": "side", "pos": fv.get("pos") if fv is not None else "1.0 0.0 1.48",
                                 "quat": fv.get("quat") if fv is not None else "0.56 0.43 0.43 0.56", "fovy": "45"})
    return ET.tostring(root, encoding="unicode")


def _hide_collision_shapes(spec: mujoco.MjSpec):
    # LIBERO draws collision shapes (group 0) only when debugging.
    for g in spec.geoms:
        if g.group == 0 and (g.contype or g.conaffinity) and g.name != "floor":
            g.group = 3


def build(t: Task, robot: str = "franka") -> mujoco.MjModel:
    if FA.missing():          # LIBERO's meshes and textures: downloaded on first use
        FA.ensure()
    world = mujoco.MjSpec.from_string(_scene_xml(t))
    _hide_collision_shapes(world)
    ft_site = S._franka(world)
    world.add_sensor(name="ft_force", type=mujoco.mjtSensor.mjSENS_FORCE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    world.add_sensor(name="ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE,
                     objtype=mujoco.mjtObj.mjOBJ_SITE, objname=ft_site)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()


# ---------------------------------------------------------- starting setups
def apply_setup(m: mujoco.MjModel, d: mujoco.MjData, t: Task, setup: int, arm_qadr,
                grip_names=("finger_joint1", "finger_joint2")):
    """Put the scene in one of LIBERO's official starting states.

    A state is [time, qpos, qvel] of LIBERO's own model. The arm starts at the setup's joint
    angles (robot0_joint1..7); the hand starts open (our gripper's rest). Every other joint
    has the same name in our model and is copied across by name.
    """
    q = t.states[setup][1:1 + t.meta["nq"]]
    arm = np.array([q[j["qposadr"]] for j in t.meta["joints"] if j["name"].startswith("robot0_joint")])
    d.qpos[arm_qadr] = arm
    for n in grip_names:
        d.qpos[m.joint(n).qposadr[0]] = 0.04
    width = {0: 7, 1: 4, 2: 1, 3: 1}       # free, ball, slide, hinge
    for j in t.meta["joints"]:
        if j["name"].startswith(("robot0_", "gripper0_", "mount0_")):
            continue
        a, w = j["qposadr"], width[j["type"]]
        d.qpos[m.joint(j["name"]).qposadr[0]:][:w] = q[a:a + w]
    d.qvel[:] = 0
    _lift_out_of_overlaps(m, d)
    return arm


def _lift_out_of_overlaps(m: mujoco.MjModel, d: mujoco.MjData, tol: float = 0.0005):
    """LIBERO's saved setups leave some objects up to 3 cm inside the table (its MuJoCo 2.3
    box-box test reports half the true overlap, so LIBERO pushes them out gently; MuJoCo 4
    sees the true overlap and they would shoot out). Raise each loose object just out of
    whatever it overlaps, keeping its x, y and orientation; it then settles onto its support.
    Only the start pose changes, by at most a few centimetres up."""
    free = {m.jnt_bodyid[j]: m.jnt_qposadr[j] for j in range(m.njnt) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE}
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

    def __init__(self, m: mujoco.MjModel, t: Task):
        self.m, self.t = m, t
        self.objs = t.meta["objects"]
        self.sites = t.meta["sites"]
        self.body = {n: m.body(o["root_body"]).id for n, o in self.objs.items()}
        gid = {m.geom(i).name: i for i in range(m.ngeom) if m.geom(i).name}
        self.geoms = {n: {gid[g] for g in o["contact_geoms"] if g in gid} for n, o in self.objs.items()}

    def contact(self, d, a: str, b: str) -> bool:
        A, B = self.geoms[a], self.geoms[b]
        for i in range(d.ncon):
            c = d.contact[i]
            if (c.geom1 in A and c.geom2 in B) or (c.geom1 in B and c.geom2 in A):
                return True
        return False

    def pos(self, d, name):
        return d.xpos[self.body[name]]

    def _site(self, d, name):
        sid = self.m.site(name).id
        return d.site_xpos[sid], d.site_xmat[sid].reshape(3, 3), np.asarray(self.sites[name]["size"], float)

    def _joint_q(self, d, joint):
        return float(d.qpos[self.m.joint(joint).qposadr[0]])

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


def done_when(t: Task) -> str:
    """LIBERO's goal check in plain words."""
    parts = []
    for p, *a in t.goal:
        p = p.lower()
        nm = lambda x: _site_words(t, x) if x in t.meta["sites"] else "the " + label(t, x)
        if p == "open":
            parts.append(f"{nm(a[0])} is pulled open")
        elif p == "close":
            parts.append(f"{nm(a[0])} is shut")
        elif p == "turnon":
            parts.append(f"{nm(a[0])} is turned on")
        elif p == "turnoff":
            parts.append(f"{nm(a[0])} is turned off")
        elif p == "in":
            parts.append(f"{nm(a[0])} is inside {nm(a[1])}")
        elif a[1] in t.meta["sites"]:
            parts.append(f"{nm(a[0])} is sitting on {nm(a[1])}")
        else:
            parts.append(f"{nm(a[0])} is resting on {nm(a[1])}, touching it")
    s = "; and ".join(parts)
    return s[0].upper() + s[1:] + "."


# ---------------------------------------------------------- the site sheet
def _table(m: mujoco.MjModel, d: mujoco.MjData):
    """The biggest fixed box the robot works on: its centre, half-size and top height."""
    best = None
    for g in range(m.ngeom):
        if m.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX or m.body_jntnum[m.geom_bodyid[g]] or m.geom_bodyid[g] == 0:
            continue
        if not (m.geom_contype[g] or m.geom_conaffinity[g]):
            continue
        sx, sy, sz = m.geom_size[g]
        if best is None or sx * sy > best[0]:
            best = (sx * sy, d.geom_xpos[g].copy(), m.geom_size[g].copy())
    if best is None:
        return None
    _, c, s = best
    return c, s, c[2] + s[2]


def site_sheet(t: Task, m: mujoco.MjModel | None = None, d: mujoco.MjData | None = None) -> str:
    bx, by, bz = t.meta["robot_base"]["pos"]
    names = list(t.meta["objects"])
    items = "\n".join(f"- {label(t, n)}" for n in names)
    table = ""
    if m is not None and d is not None and (tb := _table(m, d)) is not None:
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

## What's in the workspace

{items}

## Start state

At the start of a run the arm is in the pose it was left in, hand open, not in a
protective stop.
"""
