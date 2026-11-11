"""A session's scene settings: MuJoCo's own physics options, flags and the lab's material
classes, editable from the page's Scene settings panel.

Only official MuJoCo settings: every one is an attribute of MuJoCo's <option> or <option/flag>
element (MuJoCo's XML reference, "option"), or the condim / friction / solref of a geom
default class. The groups match the Physics section of MuJoCo's own viewer
(live.mujoco.org): solver and integrator, the algorithmic numbers, the physical parameters,
the 28 flags, contact override and actuator groups. Plus the lab's own material classes.

A session keeps only what differs from the lab's defaults (world.OPTION, scene.FLAGS,
the material classes). world.build puts them in the model it compiles.
"""
from __future__ import annotations

import math

import mujoco

DOC = "https://mujoco.readthedocs.io/en/latest/XMLreference.html#"

# (name, plain label, kind, extra). kind: enum (choices), int, real, vec (length), and the
# group it shows in. Order and grouping follow MuJoCo's viewer.
ENUMS = {
    "integrator": ["Euler", "RK4", "implicit", "implicitfast", "discrete"],
    "cone": ["pyramidal", "elliptic"],
    "jacobian": ["dense", "sparse", "auto"],
    "solver": ["PGS", "CG", "Newton"],
}
OPTIONS = [
    # group "solver"
    ("integrator", "Integrator", "enum", None, "solver"),
    ("cone", "Friction cone", "enum", None, "solver"),
    ("jacobian", "Jacobian", "enum", None, "solver"),
    ("solver", "Solver", "enum", None, "solver"),
    # group "accuracy"
    ("timestep", "Time step", "real", (1e-5, 0.05), "accuracy"),
    ("iterations", "Iterations", "int", (1, 10000), "accuracy"),
    ("tolerance", "Tolerance", "real", (0, 1), "accuracy"),
    ("ls_iterations", "Line search tries", "int", (1, 10000), "accuracy"),
    ("ls_tolerance", "Line search tolerance", "real", (0, 1), "accuracy"),
    ("noslip_iterations", "No-slip passes", "int", (0, 10000), "accuracy"),
    ("noslip_tolerance", "No-slip tolerance", "real", (0, 1), "accuracy"),
    ("ccd_iterations", "Collision tries", "int", (1, 10000), "accuracy"),
    ("ccd_tolerance", "Collision tolerance", "real", (0, 1), "accuracy"),
    ("sleep_tolerance", "Sleep tolerance", "real", (0, 100), "accuracy"),
    ("sdf_iterations", "SDF tries", "int", (1, 1000), "accuracy"),
    ("sdf_initpoints", "SDF start points", "int", (1, 1000), "accuracy"),
    # group "world"
    ("gravity", "Gravity", "vec", 3, "world"),
    ("wind", "Wind", "vec", 3, "world"),
    ("magnetic", "Magnetic field", "vec", 3, "world"),
    ("density", "Air density", "real", (0, 1e5), "world"),
    ("viscosity", "Air viscosity", "real", (0, 1e3), "world"),
    ("impratio", "Grip stiffness", "real", (1e-4, 1e4), "world"),
    # group "override"
    ("o_margin", "Margin", "real", (0, 1), "override"),
    ("o_solref", "Softness", "vec", 2, "override"),
    ("o_solimp", "Give", "vec", 5, "override"),
    ("o_friction", "Friction", "vec", 5, "override"),
]
OPTION_NAMES = {o[0] for o in OPTIONS}
# The 28 flags, in MuJoCo's viewer's order: the standard features (on unless disabled) and
# the optional ones (off unless enabled).
DISABLE = ["constraint", "equality", "frictionloss", "limit", "contact", "spring", "damper", "gravity",
           "clampctrl", "warmstart", "filterparent", "actuation", "refsafe", "sensor", "midphase",
           "eulerdamp", "autoreset", "nativeccd", "island", "multiccd"]
ENABLE = ["override", "energy", "fwdinv", "invdiscrete", "sleep", "diagexact", "ipc", "speculative"]
FLAGS = DISABLE + ENABLE
ACT_GROUPS = 6          # actuator groups shown (MuJoCo's viewer shows 0-5)
# The lab's material classes (geom defaults) and what each covers.
MATERIALS = {
    "prop": "Objects",
    "furniture": "Furniture",
    "robot": "Robot",
    "rubber_pad": "Fingertip pads",
}
MAT_FIELDS = {"condim": "int", "friction": 3, "solref": 2}
CONDIMS = (1, 3, 4, 6)


def _bit(flag: str):
    if flag in DISABLE:
        return "disable", int(getattr(mujoco.mjtDisableBit, "mjDSBL_" + flag.upper()))
    return "enable", int(getattr(mujoco.mjtEnableBit, "mjENBL_" + flag.upper()))


def read_model(m: mujoco.MjModel) -> dict:
    """Every setting as a compiled model has it: options, flags, disabled actuator groups."""
    o = m.opt
    opts = {}
    for name, _, kind, _, _ in OPTIONS:
        v = getattr(o, name)
        if kind == "enum":
            opts[name] = ENUMS[name][int(v)]
        elif kind == "int":
            opts[name] = int(v)
        elif kind == "vec":
            opts[name] = [float(x) for x in v]
        else:
            opts[name] = float(v)
    flags = {}
    for f in FLAGS:
        side, bit = _bit(f)
        flags[f] = not (o.disableflags & bit) if side == "disable" else bool(o.enableflags & bit)
    groups = [g for g in range(31) if o.disableactuator & (1 << g)]
    return {"option": opts, "flag": flags, "actuatorgroupdisable": groups}


_MJ_DEFAULTS = None


def mujoco_defaults() -> dict:
    """MuJoCo's own defaults (an empty model), for the panel's notes."""
    global _MJ_DEFAULTS
    if _MJ_DEFAULTS is None:
        _MJ_DEFAULTS = read_model(mujoco.MjModel.from_xml_string("<mujoco/>"))
    return _MJ_DEFAULTS


def _num(v, kind, rng, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(x):
        raise ValueError(f"{name} must be a finite number")
    if kind == "int":
        if x != int(x):
            raise ValueError(f"{name} must be a whole number")
        x = int(x)
    if rng and not (rng[0] <= x <= rng[1]):
        raise ValueError(f"{name} must be between {rng[0]:g} and {rng[1]:g}")
    return x


def clean(raw: dict | None) -> dict:
    """A session's settings from the page or a saved layout, checked: known names, right types
    and ranges. Raises ValueError with the setting's name on a bad one."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    opts = {}
    spec = {o[0]: o for o in OPTIONS}
    for name, v in (raw.get("option") or {}).items():
        if name not in spec:
            raise ValueError(f"unknown option {name!r}")
        _, label, kind, extra, _ = spec[name]
        if kind == "enum":
            if v not in ENUMS[name]:
                raise ValueError(f"{name} must be one of {', '.join(ENUMS[name])}")
            opts[name] = v
        elif kind == "vec":
            if not isinstance(v, (list, tuple)) or len(v) != extra:
                raise ValueError(f"{name} takes {extra} numbers")
            opts[name] = [_num(x, "real", None, name) for x in v]
        else:
            opts[name] = _num(v, kind, extra, name)
    if opts:
        out["option"] = opts
    flags = {}
    for name, v in (raw.get("flag") or {}).items():
        if name not in FLAGS:
            raise ValueError(f"unknown flag {name!r}")
        flags[name] = bool(v)
    if flags:
        out["flag"] = flags
    if raw.get("actuatorgroupdisable") is not None:
        g = raw["actuatorgroupdisable"]
        if not isinstance(g, list) or any(not isinstance(x, int) or not 0 <= x <= 30 for x in g):
            raise ValueError("actuator groups are whole numbers from 0 to 30")
        out["actuatorgroupdisable"] = sorted(set(g))
    mats = {}
    for cls, vals in (raw.get("materials") or {}).items():
        if cls not in MATERIALS or not isinstance(vals, dict):
            raise ValueError(f"unknown material {cls!r}")
        mv = {}
        for k, v in vals.items():
            if k == "condim":
                if v not in CONDIMS:
                    raise ValueError("condim must be 1, 3, 4 or 6")
                mv[k] = int(v)
            elif k in ("friction", "solref"):
                n = MAT_FIELDS[k]
                if not isinstance(v, (list, tuple)) or len(v) != n:
                    raise ValueError(f"{MATERIALS[cls]} {k} takes {n} numbers")
                mv[k] = tuple(_num(x, "real", (-1e3, 1e3) if k == "solref" else (0, 100), k) for x in v)
            else:
                raise ValueError(f"unknown material setting {k!r}")
        if mv:
            mats[cls] = mv
    if mats:
        out["materials"] = mats
    return out


def jsonable(settings: dict) -> dict:
    """Settings as JSON (tuples to lists)."""
    out = dict(settings)
    if "materials" in out:
        out["materials"] = {c: {k: list(v) if isinstance(v, tuple) else v for k, v in d.items()}
                            for c, d in out["materials"].items()}
    return out


def option_attrs(base: dict, settings: dict) -> dict:
    """The <option> element's attributes: the lab's own, with this session's changes."""
    out = dict(base)
    for k, v in (settings.get("option") or {}).items():
        out[k] = tuple(v) if isinstance(v, list) else v
    g = settings.get("actuatorgroupdisable")
    if g:
        out["actuatorgroupdisable"] = tuple(g)
    return out


def flag_attrs(base: dict, settings: dict) -> dict:
    """The <flag> element's attributes: the lab's own, with this session's changes."""
    out = dict(base)
    for k, v in (settings.get("flag") or {}).items():
        out[k] = "enable" if v else "disable"
    return out


def material(base: dict, cls: str, settings: dict) -> dict:
    """A material class's geom defaults, with this session's changes."""
    out = dict(base)
    out.update((settings.get("materials") or {}).get(cls, {}))
    return out
