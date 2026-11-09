"""Import LIBERO tasks into the playground.

LIBERO builds each task's scene with robosuite 1.4 on MuJoCo 2.3. To get exactly its rooms,
objects, fixtures, region markers and placements, we build every task once in LIBERO's own
stack and save the compiled model (libero_export.py, run there). This script
takes that export and makes it loadable in MuJoCo 4:

- removes robosuite's Panda, gripper and pedestal (the playground mounts our own Franka
  at the same base pose instead) and their actuators and sensors;
- lists the meshes and textures the scenes use in libero_assets/manifest.json. They are
  too big for this repo (about 200 MB), so the playground downloads them from LIBERO's
  GitHub on first use (fetch_libero.py) into libero_assets/files;
- keeps every object, fixture, geom, joint and site under LIBERO's own names, so the
  success checks and the official starting states map across by name.

    python -m playground.tools.import_libero <export dir>

Writes libero_assets/suites/<suite>/<NN>/{scene.xml, meta.json, init_states.npy}.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import xml.etree.ElementTree as ET


HERE = pathlib.Path(__file__).parent
ASSETS = HERE.parent / "libero_assets"
FILES = ASSETS / "files"
SUITES = ASSETS / "suites"
ROBOT_PREFIXES = ("robot0_", "gripper0_", "mount0_")
MARK = "libero/libero/assets/"
MANIFEST: dict = {}
COMMIT = "8f1084e3132a39270c3a13ebe37270a43ece2a01"   # the LIBERO commit the export was made from


def _copy_asset(path: str) -> str:
    """Copy one LIBERO asset file into FILES (for checking locally) and list it in the
    manifest; return its path relative to FILES (the same as under LIBERO's assets/)."""
    src = pathlib.Path(path).resolve()
    rel = str(src).split(MARK, 1)[1]
    dst = FILES / rel
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    MANIFEST[rel] = {"bytes": dst.stat().st_size, "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()}
    return rel


def _robot(el) -> bool:
    for k in ("name", "joint", "site", "body", "body1", "body2", "geom1", "geom2", "mesh", "material", "texture"):
        v = el.get(k)
        if v and v.startswith(ROBOT_PREFIXES):
            return True
    return False


def convert(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    comp = root.find("compiler")
    if comp is not None:
        comp.attrib.pop("meshdir", None)
        comp.attrib.pop("texturedir", None)
    for tag in ("option", "size", "statistic", "actuator", "sensor"):
        for el in root.findall(tag):
            root.remove(el)
    for sec in ("equality", "tendon", "contact", "keyframe"):
        for parent in root.findall(sec):
            for el in list(parent):
                if _robot(el):
                    parent.remove(el)
    wb = root.find("worldbody")
    for b in list(wb):
        if b.tag == "body" and b.get("name", "").startswith(ROBOT_PREFIXES):
            wb.remove(b)
    asset = root.find("asset")
    for el in list(asset):
        f = el.get("file")
        if _robot(el) or (f and MARK not in str(pathlib.Path(f).resolve())):
            asset.remove(el)
            continue
        if f:
            el.set("file", "{FILES}/" + _copy_asset(f))
    return ET.tostring(root, encoding="unicode")


def main(argv=None):
    export = pathlib.Path((argv or sys.argv[1:])[0])
    for meta_path in sorted(export.glob("*/*/meta.json")):
        src = meta_path.parent
        meta = json.loads(meta_path.read_text())
        out = SUITES / meta["suite"] / src.name
        out.mkdir(parents=True, exist_ok=True)
        (out / "scene.xml").write_text(convert((src / "model.xml").read_text()))
        (out / "meta.json").write_text(json.dumps(meta, indent=1))
        shutil.copy2(src / "init_states.npy", out / "init_states.npy")
        print(meta["suite"], src.name, meta["language"])
    man = ASSETS / "manifest.json"
    old = json.loads(man.read_text())["files"] if man.exists() else {}
    man.write_text(json.dumps({"repo": "Lifelong-Robot-Learning/LIBERO", "commit": COMMIT,
                               "path": MARK, "files": dict(sorted({**old, **MANIFEST}.items()))}, indent=1))


if __name__ == "__main__":
    main()
