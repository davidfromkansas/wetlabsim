"""Add LIBERO's objects, fixtures and scene furniture to the playground's library.

Each item is LIBERO's own MuJoCo model of the object (its XML, meshes and textures, at the
LIBERO commit the LIBERO mode was exported from), attached to the playground as it is
(asset.json "mjcf", see world._add_mjcf): LIBERO's shapes, masses, joints, joint ranges,
damping, friction and contact settings, and its sites (a microwave's heating region, a
stove's burner). Only what robosuite does when it loads one of these files is done here too:

- the file's own <compiler> and <size> go (robosuite builds every object under its one
  compiler: angles in radians, limits from ranges);
- a loose object gets a free joint with damping 0.0005, as LIBERO's object classes give it;
- collision shapes (group 0) are drawn only when debugging, as LIBERO draws them;
- an object stands the way LIBERO places it: the turn its object class states
  (`rotation`, `rotation_axis` in libero/libero/envs/objects/*.py), applied as LIBERO's
  placement sampler applies it.

    git clone --filter=blob:none --sparse https://github.com/Lifelong-Robot-Learning/LIBERO
    cd LIBERO && git checkout 8f1084e3132a39270c3a13ebe37270a43ece2a01
    git sparse-checkout set libero/libero/assets
    python -m playground.tools.build_libero_objects <LIBERO checkout> [item ids...]

Writes playground/assets/<id>/ (the XML, the files it uses, asset.json, thumb.png).
"""
from __future__ import annotations

import json
import math
import pathlib
import shutil
import sys
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from .. import catalog

COMMIT = "8f1084e3132a39270c3a13ebe37270a43ece2a01"
ASSET_ROOT = "libero/libero/assets"
LICENSE = "MIT (LIBERO, Lifelong-Robot-Learning/LIBERO); HOPE, Google Scanned Objects and TurboSquid meshes as LIBERO ships them"

H = math.pi / 2
# How LIBERO turns each object when it places it: its object class's `rotation` and
# `rotation_axis` (a range uses its first end), through its placement sampler
# (libero/libero/envs/regions/workspace_region_sampler.py): the sampler builds an (x, y, z, w)
# quaternion and MuJoCo reads it as (w, x, y, z), so a single turn ends up a turn about the
# vertical. LIBERO's own saved starting states have these orientations (checked against
# libero_assets/suites). Fixtures and scene furniture stand as their files lay them out.
ROTATION = {
    # stable_hope_objects (HopeBaseObject: pi/2 about x, unless the class says otherwise)
    "alphabet_soup": ("z", H), "bbq_sauce": ("x", H), "butter": ("x", 0), "chocolate_pudding": ("x", 0),
    "cookies": ("x", H), "cream_cheese": ("x", 0), "ketchup": {"x": H, "z": H},
    "macaroni_and_cheese": {"x": H, "z": H}, "milk": {"x": H, "z": H},
    "new_salad_dressing": {"x": H, "z": H}, "orange_juice": {"x": H, "z": H}, "popcorn": ("x", 0),
    "salad_dressing": {"x": H, "z": H}, "tomato_sauce": ("z", H),
    # stable_scanned_objects (GoogleScannedObject: pi/2 about x; the rack 0)
    "akita_black_bowl": ("x", H), "basket": ("x", H), "chefmate_8_frypan": ("x", H),
    "glazed_rim_porcelain_ramekin": ("x", H), "plate": ("x", H), "red_bowl": ("x", H),
    "simple_rack": ("x", 0), "white_bowl": ("x", H),
    # turbosquid_objects (0 about x or y; mugs -pi/2 about x; books -pi/2 to -pi/4 about x)
    "black_book": ("x", -H), "yellow_book": ("x", -H), "red_coffee_mug": ("x", -H),
    "porcelain_mug": ("x", -H), "white_yellow_mug": ("x", -H), "white_storage_box": ("y", 0),
    **{k: ("x", 0) for k in ("wooden_tray", "wooden_shelf", "wooden_two_layer_shelf", "wine_rack",
                             "wine_bottle", "dining_set_group", "bowl_drainer", "moka_pot", "desk_caddy")},
}


def _xyzw(axis: str, a: float) -> np.ndarray:
    q = np.zeros(4)
    q["xyz".index(axis)], q[3] = math.sin(a / 2), math.cos(a / 2)
    return q


def _mul_xyzw(q1, q0) -> np.ndarray:            # robosuite.utils.transform_utils.quat_multiply
    x0, y0, z0, w0 = q0
    x1, y1, z1, w1 = q1
    return np.array([x1 * w0 + y1 * z0 - z1 * y0 + w1 * x0, -x1 * z0 + y1 * w0 + z1 * x0 + w1 * y0,
                     x1 * y0 - y1 * x0 + z1 * w0 + w1 * z0, -x1 * x0 - y1 * y0 - z1 * z0 + w1 * w0])


def _quat(name: str) -> list:
    """The orientation LIBERO's sampler gives the object, as MuJoCo applies it (w, x, y, z)."""
    r = ROTATION.get(name)
    if r is None:
        return [1.0, 0.0, 0.0, 0.0]
    if isinstance(r, dict):
        q = np.array([0.0, 0, 0, 1])
        for axis, a in r.items():
            q = _mul_xyzw(_xyzw(axis, a), q)
    else:
        q = _xyzw(*r)
    return [round(float(v), 9) for v in q]       # read as (w, x, y, z), as LIBERO's sim does


def _files(root: ET.Element, src_dir: pathlib.Path):
    comp = root.find("compiler")
    meshdir = comp.get("meshdir", "") if comp is not None else ""
    texdir = comp.get("texturedir", "") if comp is not None else ""
    for el in root.iter():
        f = el.get("file")
        if f and el.tag in ("mesh", "texture", "hfield", "skin"):
            base = meshdir if el.tag in ("mesh", "skin", "hfield") else texdir
            yield el, (src_dir / base / f).resolve()


def build(id_: str, libero: pathlib.Path) -> dict:
    it = catalog.item(id_)
    rel = it["hf"].split(":", 1)[1]
    src = (libero / ASSET_ROOT / rel).resolve()
    name = src.parent.name if src.parent.name not in ("articulated_objects",) else src.stem
    out = catalog.ASSETS / id_
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    root = ET.parse(src).getroot()
    assets_dir = (libero / ASSET_ROOT).resolve()
    for el, f in _files(root, src.parent):
        # keep the file under the same path it has below the XML's folder (or below LIBERO's
        # assets folder, for a file the XML reaches outside its own folder)
        try:
            r = f.relative_to(src.parent)
        except ValueError:
            r = pathlib.Path("_libero") / f.relative_to(assets_dir)
        dst = out / r
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        el.set("file", r.as_posix())
    # robosuite keeps the first of two assets with the same name (LIBERO's flat stove names two
    # textures alike; both its knob materials then use the first)
    asset = root.find("asset")
    seen = set()
    for el in list(asset if asset is not None else []):
        key = (el.tag, el.get("name"))
        if el.get("name") and key in seen:
            asset.remove(el)
        seen.add(key)
    # LIBERO's short fridge (used by none of its tasks) marks a spot with a <region>, which isn't
    # a MuJoCo element and stops the file loading anywhere; it has no shape or physics
    for parent in list(root.iter()):
        for el in list(parent):
            if el.tag == "region":
                parent.remove(el)
    for tag in ("compiler", "size", "option"):
        for el in root.findall(tag):
            root.remove(el)
    root.insert(0, ET.Element("compiler", {"angle": "radian", "autolimits": "true"}))
    xml_name = f"{src.stem}.xml"
    (out / xml_name).write_text(ET.tostring(root, encoding="unicode"))

    quat = _quat(name)
    # LIBERO's model, turned as LIBERO stands it, measured: its bounds, mass and friction
    sp = mujoco.MjSpec()
    child = mujoco.MjSpec.from_file(str(out / xml_name))
    frame = sp.worldbody.add_frame(quat=quat)
    sp.attach(child, frame=frame, prefix="o_")
    m = sp.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for g in range(m.ngeom):
        R = d.geom_xmat[g].reshape(3, 3)
        if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:      # the mesh's own points
            k = m.geom_dataid[g]
            pts = m.mesh_vert[m.mesh_vertadr[k]:m.mesh_vertadr[k] + m.mesh_vertnum[k]]
        else:                                               # a shape's bounding box
            c, h = m.geom_aabb[g][:3], m.geom_aabb[g][3:]
            pts = c + np.array(np.meshgrid([-1, 1], [-1, 1], [-1, 1])).T.reshape(-1, 3) * h
        p = d.geom_xpos[g] + pts @ R.T
        lo, hi = np.minimum(lo, p.min(0)), np.maximum(hi, p.max(0))
    size = hi - lo
    mid = (lo + hi) / 2
    col = [g for g in range(m.ngeom) if m.geom_contype[g] or m.geom_conaffinity[g]]
    joints = [m.joint(j).name.removeprefix("o_") for j in range(m.njnt)]
    meta = {
        "source": f"LIBERO {ASSET_ROOT}/{rel} (github.com/Lifelong-Robot-Learning/LIBERO @ {COMMIT[:7]})",
        "mjcf": xml_name,
        # where LIBERO's model sits in the item: turned upright, its bottom centre at the item's place
        "frame": {"pos": [round(float(-mid[0]), 6), round(float(-mid[1]), 6), round(float(-lo[2]), 6)], "quat": quat},
        "free_damping": 0.0005,
        "hide_collision": True,
        "mass": round(float(m.body_subtreemass[0]), 5),
        "friction": round(float(m.geom_friction[col[0]][0]), 3) if col else None,
        "size": [round(float(v), 4) for v in size],
        "collision": f"LIBERO's own collision shapes ({len(col)})" + (f", moving parts on their joints ({', '.join(joints)})" if joints else ""),
        "license": LICENSE,
    }
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    thumb(out, meta)
    return meta


def thumb(out: pathlib.Path, meta: dict):
    """A 256 px picture for the library, rendered by MuJoCo (collision shapes hidden)."""
    from PIL import Image
    sp = mujoco.MjSpec()
    sp.visual.global_.offwidth = sp.visual.global_.offheight = 512
    child = mujoco.MjSpec.from_file(str(out / meta["mjcf"]))
    frame = sp.worldbody.add_frame(pos=meta["frame"]["pos"], quat=meta["frame"]["quat"])
    sp.attach(child, frame=frame, prefix="o_")
    sp.worldbody.add_light(pos=[0, 0, 3], dir=[0, 0, -1], diffuse=[0.7, 0.7, 0.7])
    sp.worldbody.add_light(pos=[2, -2, 2], dir=[-1, 1, -1], diffuse=[0.4, 0.4, 0.4])
    sp.visual.headlight.ambient = [0.45, 0.45, 0.45]
    m = sp.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    r = mujoco.Renderer(m, 512, 512)
    opt = mujoco.MjvOption()
    opt.geomgroup[0] = 0                     # collision shapes
    opt.sitegroup[:] = 0
    cam = mujoco.MjvCamera()
    sz = meta["size"]
    cam.lookat[:] = [0, 0, sz[2] / 2]
    cam.distance, cam.azimuth, cam.elevation = max(sz) * 1.9, 135, -30
    r.update_scene(d, cam, opt)
    img = r.render()
    bg = (img == img[0, 0]).all(-1)
    img[bg] = [242, 243, 245]
    Image.fromarray(img).resize((256, 256), Image.LANCZOS).save(out / "thumb.png")
    r.close()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    libero = pathlib.Path(argv[0])
    ids = argv[1:] or [i[0] for i in catalog.ITEMS if i[3].startswith("libero:")]
    for id_ in ids:
        meta = build(id_, libero)
        print(f"{id_:32s} {meta['mass']:8.3f} kg  {'x'.join(f'{v * 100:.0f}' for v in meta['size'])} cm  {meta['collision']}")


if __name__ == "__main__":
    main()
