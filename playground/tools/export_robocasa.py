"""Export RoboCasa's kitchen objects as RoboCasa itself loads them, one folder per object.

RoboCasa doesn't use its objects' model.xml files as they are: its object class (robocasa
MJCFObject, through robosuite's MujocoXMLObject) scales each object by its category's scale and
gives every shape the category's density, friction, solref and solimp. This script lets
RoboCasa's own code do that, then writes the result as a plain MuJoCo file next to copies of the
files it uses:

    <out>/<id>/model.xml      the object's body (no free joint: the playground adds it, with
                              RoboCasa's damping 0.0005), its assets, file paths made relative
    <out>/<id>/robocasa.json  category, registry, source folder and the settings applied

Run it in its own environment with RoboCasa and robosuite installed (RoboCasa pins its own
versions of MuJoCo and numpy, which differ from the playground's):

    python3 -m venv build/rcvenv && . build/rcvenv/bin/activate
    pip install mujoco==3.3.1 numpy==2.2.5 scipy==1.15.3 numba lxml termcolor tqdm pyyaml pillow \\
        opencv-python-headless h5py imageio gymnasium
    git clone --depth 1 https://github.com/ARISE-Initiative/robosuite build/robosuite
    git clone --depth 1 https://github.com/robocasa/robocasa build/robocasa
    pip install --no-deps -e build/robosuite -e build/robocasa
    python -m robocasa.scripts.download_kitchen_assets      # or unzip its objects into
                                                            # robocasa/models/assets/objects/
    python playground/tools/export_robocasa.py build/robocasa_export

(Run it as a file, not with -m: it must not import the playground.) Its fixtures (appliances such as
fridges, ovens, microwaves, sinks, coffee machines, toasters; not its cabinets) are exported the
same way, at their own size, and stay where they are put. Categories RoboCasa itself
leaves out (its `exclude` lists: slow to load or broken) are left out here too.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import xml.etree.ElementTree as ET

REG = {"aigen_objs": "ag", "objaverse": "ov", "lightwheel": "lw"}


# Fixture folders (RoboCasa's appliance and fixture models, from NVIDIA's
# PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF) left out: cabinets and their handles are
# parts RoboCasa assembles into its cabinets, not things on their own
FIXTURE_SKIP = {"cabinets", "handles", "cabinet_panels"}


def export_one(cat, mjcf_path: str, out: pathlib.Path, info: dict):
    from robocasa.models.objects.objects import MJCFObject
    kw = cat.get_mjcf_kwargs()
    obj = MJCFObject(name="o", mjcf_path=mjcf_path, **kw)
    _write(obj, mjcf_path, out, dict(info, settings={k: v for k, v in kw.items() if v is not None}))


def export_fixture(mjcf_path: str, out: pathlib.Path, info: dict):
    """A fixture as RoboCasa's Fixture class loads it (at its own size: scale 1)."""
    from robocasa.models.fixtures.fixture import Fixture
    fx = Fixture(xml=mjcf_path, name="o", duplicate_collision_geoms=False)
    _write(fx, mjcf_path, out, dict(info, settings={"scale": 1}))


def _link(src, dst):
    """A hard link where the file system allows (the sources are large), else a copy."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _write(obj, mjcf_path: str, out: pathlib.Path, info: dict):
    body = obj.get_obj()
    for j in [e for e in body if e.tag in ("joint", "freejoint")]:    # the playground adds its own
        body.remove(j)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    root = ET.Element("mujoco", {"model": out.name})
    src_dir = pathlib.Path(mjcf_path).parent
    default = obj.root.find("default")
    if default is not None and len(default):
        root.append(default)
    asset = ET.SubElement(root, "asset")
    for el in obj.asset:
        f = el.get("file")
        if f:
            fp = pathlib.Path(f)
            try:
                rel = fp.resolve().relative_to(src_dir.resolve())
            except ValueError:                   # a shared file outside the object's folder
                rel = pathlib.Path("_shared") / fp.name
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                _link(fp, dst)
            el.set("file", rel.as_posix())
        asset.append(el)
    wb = ET.SubElement(root, "worldbody")
    wb.append(body)
    (out / "model.xml").write_text(ET.tostring(root, encoding="unicode"))
    (out / "robocasa.json").write_text(json.dumps(info, indent=1))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    out_root = pathlib.Path(argv[0])
    only = set(argv[1:])
    from robocasa.models.objects.kitchen_object_utils import OBJ_CATEGORIES
    import robocasa
    assets = pathlib.Path(robocasa.__file__).parent / "models" / "assets" / "objects"
    n = bad = 0
    for name, regs in OBJ_CATEGORIES.items():
        for reg, cat in regs.items():
            types = cat.types if isinstance(cat.types, tuple) else (cat.types,)
            for p in cat.mjcf_paths:
                folder = pathlib.Path(p).parent
                id_ = f"rc_{REG[cat.reg_type]}_{folder.name}".lower()
                if only and id_ not in only:
                    continue
                if (out_root / id_ / "robocasa.json").exists():
                    continue
                info = {"id": id_, "category": name, "types": list(types), "registry": cat.reg_type,
                        "folder": folder.relative_to(assets).as_posix()}
                try:
                    export_one(cat, p, out_root / id_, info)
                    n += 1
                except Exception as e:  # noqa: BLE001
                    bad += 1
                    print(f"{id_}: FAILED {e}", file=sys.stderr)
    fx_root = assets.parent / "fixtures"
    for d in sorted(fx_root.iterdir()):
        if not d.is_dir() or d.name in FIXTURE_SKIP:
            continue
        for f in sorted(d.glob("*/model.xml")):
            id_ = f"rc_fx_{f.parent.name}".lower()
            if (only and id_ not in only) or (out_root / id_ / "robocasa.json").exists():
                continue
            info = {"id": id_, "category": d.name.rstrip("s") if not d.name.endswith("ches") else d.name[:-2],
                    "types": ["fixture"], "registry": "fixtures", "folder": f.parent.relative_to(fx_root.parent).as_posix()}
            try:
                export_fixture(str(f), out_root / id_, info)
                n += 1
            except Exception as e:  # noqa: BLE001
                bad += 1
                print(f"{id_}: FAILED {e}", file=sys.stderr)
    print(n, "exported,", bad, "failed")


if __name__ == "__main__":
    main()
