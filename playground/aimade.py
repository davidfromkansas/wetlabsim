"""AI-made objects: things a language model built from simple shapes (a scene made from a photo,
playground/photoscene.py), as small MuJoCo models of their own.

Each one is checked before it goes into a scene:
  clean(xml)     only plain MuJoCo shapes, bodies, hinge and slide joints, masses and colours
                 are kept (no files, meshes, plugins, lights, cameras or actuators), with limits
                 on how many parts it has and how big it is;
  measure(xml)   compiled on its own: its size, its bottom centre (the item's place, as for
                 library items) and its mass;
  shake(...)     a short physics test on a floor: nothing blows up, a loose thing comes to rest
                 where it was put down and doesn't sink.

An object that passes is registered under an id "ai_<hex>" and then works like a library item
(catalog.item / catalog.meta look here first), drawn by the browser from its shapes. Its
definition is saved with the session (Session.layout()["ai_items"]), so a saved or copied
session brings its AI-made objects with it.
"""
from __future__ import annotations

import math
import os
import re
import threading
import warnings
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

PREFIX = "ai_"
TAB = "AI-made"
MAX_BODIES = 40
MAX_GEOMS = 160
MAX_JOINTS = 24
MAX_SIZE = 20.0         # m, along any side (a whole wall of a large room)
MAX_XML = 60_000        # characters

# The picture an AI-made object shows where library objects show their thumbnail.
THUMB_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
             '<rect width="256" height="256" rx="28" fill="#EFF4FF"/><g fill="none" stroke="#2563EB" stroke-width="9" '
             'stroke-linejoin="round"><path d="M128 52l66 36v80l-66 36-66-36V88z"/><path d="M62 88l66 36 66-36M128 124v80"/></g>'
             '<path d="M196 40l5 13 13 5-13 5-5 13-5-13-13-5 13-5z" fill="#2563EB"/></svg>')

_REG: dict[str, dict] = {}
_LOCK = threading.Lock()


class Bad(ValueError):
    """Why an AI-made object can't be used (sent back to the model to fix)."""


# ------------------------------------------------------------------ the registry
def is_ai(id_: str) -> bool:
    return str(id_).startswith(PREFIX)


def get(id_: str) -> dict | None:
    return _REG.get(id_)


def item(id_: str) -> dict:
    d = _REG[id_]
    return {"id": id_, "tab": TAB, "label": d["label"], "hf": "", "hollow": False, "fixed": bool(d["fixed"]),
            "soft": None, "ai": True}


def meta(id_: str) -> dict:
    d = _REG[id_]
    parts, friction = describe(d["xml"])
    return {"mjcf_xml": d["xml"], "size": list(d["size"]), "frame": {"pos": list(d["frame"])},
            "mass": d["mass"], "label": d["label"], "parts": parts, "friction": friction}


# Words for moving parts, found in the names the model gives them ("cab_door_l" -> door);
# a part with no such word is a "hinged part" or "sliding part".
_PART_WORDS = {w: w for w in ("door", "drawer", "lid", "flap", "hatch", "window", "sash", "blind", "shutter",
                              "shelf", "tray", "wheel", "caster", "seat", "screen", "knob", "dial", "handle",
                              "lever", "cap", "valve", "tap", "faucet", "arm", "hood", "cover", "panel", "button",
                              "switch", "chair", "stool", "leg", "rack", "basket", "sliding", "slider")}
_PART_WORDS.update({"castor": "caster", "sliding": "sliding part", "slider": "sliding part"})


def describe(xml: str) -> tuple[str, float | None]:
    """("2 doors and 1 drawer", 0.6): the object's moving parts in words, and its usual friction."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "", None
    names: list[str] = []
    for body in root.iter("body"):
        js = [j for j in body.findall("joint") if j.get("type", "hinge") in ("hinge", "slide")]
        if not js:
            continue
        raw = re.sub(r"[_\-]+", " ", body.get("name") or "").lower()
        word = next((w for w in _PART_WORDS if re.search(rf"\b{w}", raw)), None)
        nm = _PART_WORDS.get(word) if word else ("sliding part" if js[0].get("type") == "slide" else "hinged part")
        names.append(nm)
    counts: dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    words = [f"{k} {n}{'' if k == 1 or n.endswith('s') else 's'}" if k > 1 else f"1 {n}" for n, k in counts.items()]
    parts = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""
    fr = [float(g.get("friction").split()[0]) for g in root.iter("geom")
          if g.get("friction") and g.get("friction").split()[0].replace(".", "", 1).isdigit()]
    friction = round(max(set(fr), key=fr.count), 2) if fr else 1.0      # MuJoCo's default is 1
    return parts, friction


def register(label: str, xml: str, fixed: bool, size, frame, mass: float, id_: str | None = None) -> str:
    id_ = id_ or PREFIX + os.urandom(5).hex()
    with _LOCK:
        _REG[id_] = {"label": str(label)[:60] or "AI-made object", "xml": xml, "fixed": bool(fixed),
                     "size": [float(v) for v in size], "frame": [float(v) for v in frame], "mass": float(mass)}
    return id_


def export(ids) -> dict:
    """The definitions of these AI-made objects, for saving with a session."""
    return {i: dict(_REG[i]) for i in ids if i in _REG}


def load(defs) -> list[str]:
    """AI-made objects saved with a session, registered again (each checked as when it was made)."""
    out = []
    if not isinstance(defs, dict):
        return out
    for id_, d in list(defs.items())[:200]:
        if not (isinstance(d, dict) and re.match(r"^ai_[0-9a-f]{6,20}$", str(id_))):
            continue
        if id_ in _REG:
            out.append(id_)
            continue
        try:
            xml = clean(str(d.get("xml", "")))
            size, frame, mass = measure(xml)
        except Exception as e:  # noqa: BLE001
            print(f"ignoring a saved AI-made object {id_}: {e}")
            continue
        register(str(d.get("label") or ""), xml, bool(d.get("fixed")), size, frame, mass, id_=id_)
        out.append(id_)
    return out


# ------------------------------------------------------------------ cleaning the model's XML
SHAPES = {"box", "sphere", "capsule", "cylinder", "ellipsoid"}
_POSE = {"pos", "quat", "euler", "axisangle", "xyaxes", "zaxis"}
_ALLOWED = {
    "geom": _POSE | {"name", "type", "size", "fromto", "rgba", "material", "mass", "density", "friction",
                     "condim", "solref", "solimp", "margin", "gap", "priority", "contype", "conaffinity"},
    "body": _POSE | {"name"},
    "joint": {"name", "type", "axis", "pos", "range", "limited", "damping", "armature", "stiffness",
              "frictionloss", "springref", "ref"},
    "inertial": {"pos", "quat", "euler", "axisangle", "mass", "diaginertia", "fullinertia"},
    "material": {"name", "rgba", "specular", "shininess", "reflectance", "emission"},
    "site": _POSE | {"name", "type", "size", "rgba", "fromto"},
}
_NAME = re.compile(r"[^\w.-]")


def _num_list(v: str, n_min: int = 1, n_max: int = 12):
    try:
        xs = [float(x) for x in v.split()]
    except ValueError:
        raise Bad(f"'{v[:40]}' isn't a list of numbers") from None
    if not n_min <= len(xs) <= n_max or not all(math.isfinite(x) for x in xs):
        raise Bad(f"'{v[:40]}' isn't a list of numbers")
    return xs


def clean(xml: str) -> str:
    """The model's MJCF for one object, kept to plain shapes, bodies and joints. Raises Bad."""
    xml = (xml or "").strip()
    if not xml:
        raise Bad("the object has no MuJoCo model")
    if len(xml) > MAX_XML:
        raise Bad("the object's model is too long: use fewer, simpler shapes")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", xml, re.I):
        raise Bad("the model may not use DOCTYPE or ENTITY")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise Bad(f"the object's XML isn't valid ({e})") from None
    if root.tag != "mujoco":
        raise Bad("the object's model must be one <mujoco> element")
    out = ET.Element("mujoco", {"model": "ai_object"})
    comp = root.find("compiler")
    angle = (comp.get("angle") if comp is not None else None) or "degree"
    if angle not in ("degree", "radian"):
        raise Bad("compiler angle must be degree or radian")
    ET.SubElement(out, "compiler", {"angle": angle, "autolimits": "true"})
    mats = set()
    asset = root.find("asset")
    if asset is not None:
        a_out = ET.SubElement(out, "asset")
        for m in asset:
            if m.tag != "material":
                continue        # textures and meshes would read files: plain colours only
            attrs = _attrs(m, "material")
            if "name" not in attrs:
                continue
            mats.add(attrs["name"])
            ET.SubElement(a_out, "material", attrs)
    wb = root.find("worldbody")
    if wb is None:
        raise Bad("the object's model has no <worldbody>")
    count = {"body": 0, "geom": 0, "joint": 0}
    w_out = ET.SubElement(out, "worldbody")
    _copy_children(wb, w_out, mats, count, top=True)
    if count["geom"] == 0:
        raise Bad("the object has no shapes (geoms)")
    return ET.tostring(out, encoding="unicode")


def _attrs(el, tag: str) -> dict:
    keep = {}
    for k, v in el.attrib.items():
        if k not in _ALLOWED[tag]:
            continue
        v = str(v).strip()
        if k in ("name", "material"):
            v = _NAME.sub("_", v)[:60]
            if not v:
                continue
        elif k == "type":
            pass
        elif k in ("limited",):
            if v not in ("true", "false", "auto"):
                continue
        else:
            _num_list(v)
        keep[k] = v
    return keep


def _copy_children(src, dst, mats, count, top=False):
    for el in src:
        tag = el.tag
        if tag in ("freejoint",) or (tag == "joint" and el.get("type") == "free"):
            continue                       # the playground adds its own (loose things)
        if tag not in ("body", "geom", "joint", "inertial", "site"):
            continue                       # lights, cameras, actuators, frames, includes: dropped
        if top and tag in ("joint", "inertial"):
            continue                       # nothing joins the object itself to the world
        attrs = _attrs(el, tag)
        if tag == "geom":
            t = attrs.get("type", "sphere")
            if t not in SHAPES:
                raise Bad(f"geom type '{t}' isn't allowed: use box, cylinder, capsule, sphere or ellipsoid")
            if "size" not in attrs and "fromto" not in attrs:
                raise Bad(f"a {t} geom has no size")
            for v in _num_list(attrs.get("size", "0.01")):
                if v < 0 or v > MAX_SIZE:
                    raise Bad(f"a geom size of {v} m is out of range")
            if attrs.get("material") and attrs["material"] not in mats:
                attrs.pop("material")
            for k in ("mass", "density"):
                if k in attrs and float(attrs[k].split()[0]) < 0:
                    raise Bad("a geom's mass or density is negative")
            count["geom"] += 1
        elif tag == "joint":
            t = attrs.get("type", "hinge")
            if t not in ("hinge", "slide"):
                raise Bad(f"joint type '{t}' isn't allowed: use hinge or slide")
            attrs["type"] = t
            count["joint"] += 1
        elif tag == "body":
            count["body"] += 1
        if count["geom"] > MAX_GEOMS or count["body"] > MAX_BODIES or count["joint"] > MAX_JOINTS:
            raise Bad(f"the object is too detailed (at most {MAX_BODIES} bodies, {MAX_GEOMS} geoms, "
                      f"{MAX_JOINTS} joints)")
        new = ET.SubElement(dst, tag, attrs)
        if tag == "body":
            _copy_children(el, new, mats, count)
    # unique names (the playground keeps joint positions by name)
    if top:
        _name_all(dst)


def _name_all(root):
    used: set = set()
    for tag, pre in (("body", "b"), ("joint", "j"), ("geom", "g"), ("site", "s")):
        k = 0
        for el in root.iter(tag):
            n = el.get("name")
            if not n or n in used:
                while f"{pre}{k}" in used:
                    k += 1
                n = f"{pre}{k}"
                el.set("name", n)
            used.add(n)


# ------------------------------------------------------------------ measuring and testing
def _compile(xml: str) -> mujoco.MjModel:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return mujoco.MjSpec.from_string(xml).compile()
    except Exception as e:  # noqa: BLE001
        raise Bad(f"MuJoCo couldn't load the object: {str(e).splitlines()[0][:300]}") from None


def _bounds(m: mujoco.MjModel, d: mujoco.MjData, bodies=None):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for g in range(m.ngeom):
        if bodies is not None and int(m.geom_bodyid[g]) not in bodies:
            continue
        c, h = m.geom_aabb[g, :3], m.geom_aabb[g, 3:]
        R = d.geom_xmat[g].reshape(3, 3)
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * h + c
        w = corners @ R.T + d.geom_xpos[g]
        lo, hi = np.minimum(lo, w.min(0)), np.maximum(hi, w.max(0))
    return lo, hi


def measure(xml: str):
    """(size [x, y, z], frame [where the model's origin sits from the item's bottom centre], mass)."""
    m = _compile(xml)
    if m.ngeom == 0:
        raise Bad("the object has no shapes")
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    lo, hi = _bounds(m, d)
    size = hi - lo
    if not np.all(np.isfinite(size)) or size.max() > MAX_SIZE:
        raise Bad(f"the object is {size.max():.1f} m across: too big (at most {MAX_SIZE:.0f} m)")
    if size.min() < 0.002:
        size = np.maximum(size, 0.002)
    mass = float(m.body_mass[1:].sum())
    if not math.isfinite(mass) or mass <= 0:
        raise Bad("the object has no mass")
    if mass > 20000:
        raise Bad(f"the object weighs {mass:.0f} kg: check the masses and densities")
    centre = (lo + hi) / 2
    frame = [-float(centre[0]), -float(centre[1]), -float(lo[2])]
    return [round(float(v), 5) for v in size], [round(v, 5) for v in frame], round(mass, 4)


SHAKE_S = 1.5


def shake(id_: str) -> None:
    """The object alone on a floor for a moment of physics, put together as the playground puts
    it into a scene (world._add_mjcf). Raises Bad with what went wrong."""
    from . import settings as ST
    from . import world as W
    d0 = _REG[id_]
    fixed = bool(d0["fixed"])
    spec = mujoco.MjSpec.from_string(
        '<mujoco><compiler angle="radian" autolimits="true"/>'
        f'<option {W._xml_attrs(ST.option_attrs(W.OPTION, {}))}/>'
        '<worldbody><geom name="floor" type="plane" size="5 5 0.1"/></worldbody></mujoco>')
    p = W.Placed("t", id_, (0.0, 0.0, 0.001), 0.0)
    W._add_mjcf(spec, p, meta(id_), fixed)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = spec.compile()
    except Exception as e:  # noqa: BLE001
        raise Bad(f"MuJoCo couldn't load the object: {str(e).splitlines()[0][:300]}") from None
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    root = m.body("obj_t").id
    start = d.xpos[root].copy()
    n = int(SHAKE_S / m.opt.timestep)
    for _ in range(n):
        mujoco.mj_step(m, d)
        if not (np.all(np.isfinite(d.qpos)) and np.all(np.isfinite(d.qvel))):
            raise Bad("the physics blew up (numbers went to infinity): check masses, joint limits and "
                      "parts that start inside each other")
    if d.warning[int(mujoco.mjtWarning.mjWARN_BADQACC)].number:
        raise Bad("the physics became unstable: check that every moving part has some mass and damping")
    speed = float(np.abs(d.qvel).max()) if m.nv else 0.0
    if speed > 20:
        raise Bad(f"parts are still flying around after {SHAKE_S} s (speed {speed:.0f}): check joint "
                  "limits, damping and parts that start inside each other")
    bodies = {b for b in range(m.nbody) if b == root or m.body(b).name.startswith("obj_t__")}
    lo, _ = _bounds(m, d, bodies)
    if lo[2] < -0.03:
        raise Bad("the object sinks into the floor: check its collision shapes")
    if not fixed:
        moved = float(np.linalg.norm(d.xpos[root][:2] - start[:2]))
        if moved > 0.25:
            raise Bad(f"the object doesn't stay put on a flat floor (it moved {100 * moved:.0f} cm): "
                      "check its shape is stable and its parts' masses")
