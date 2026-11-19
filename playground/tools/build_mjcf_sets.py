"""Add two sets of ready-made MuJoCo objects to the library, each kept as its source made it:

- Google Scanned Objects, as MuJoCo models (github.com/kevinzakka/mujoco_scanned_objects):
  1,030 3D scans of real household items. Meshes and textures CC BY 4.0 (Google), MJCF MIT
  (Kevin Zakka). The files state no mass: the collision pieces are weighed at the density LIBERO
  and RoboCasa give scanned objects (GSO_DENSITY). Names and toy categories are Google's own.
- RoboCasa's kitchen objects (github.com/robocasa/robocasa, assets CC BY 4.0): as RoboCasa
  loads them (scaled per category, with its density, friction, solref and solimp), exported by
  tools/export_robocasa.py, which runs RoboCasa's own object code.

Each item is the source's own MuJoCo model, attached as it is (asset.json "mjcf", see
world._add_mjcf): its shapes, collision pieces, materials and textures. A loose object gets a free
joint (RoboCasa's damping 0.0005 on its objects). Collision pieces are drawn only when debugging.

    git clone --depth 1 https://github.com/kevinzakka/mujoco_scanned_objects build/gso
    python playground/tools/export_robocasa.py build/robocasa_export      # (its own venv)
    python -m playground.tools.build_mjcf_sets pick  --gso build/gso --robocasa build/robocasa_export
    python -m playground.tools.build_mjcf_sets build --gso build/gso --robocasa build/robocasa_export [--workers 4] [ids]
    python -m playground.tools.check_usdcraft --out build/mjcf_check.json $(ids)     # drop test
    python -m playground.tools.build_mjcf_sets finish        # skip failures, fix big/heavy items
    python -m playground.tools.library push

pick writes playground/mjcf_library.json (catalog.MJCF_SETS).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

OUT = pathlib.Path(__file__).resolve().parents[1] / "mjcf_library.json"
CHECK = pathlib.Path("build/mjcf_check.json")
GSO_COMMIT_URL = "https://github.com/kevinzakka/mujoco_scanned_objects/tree/main/models/"
LICENSE = {
    "gso": "Meshes and textures CC BY 4.0 (Google Scanned Objects, Downs et al. 2022); MJCF MIT (Kevin Zakka, mujoco_scanned_objects)",
    "robocasa": "CC BY 4.0 (RoboCasa, Nasiriany et al. 2024/2026)",
    # RoboCasa's Lightwheel objects and its fixtures come from NVIDIA's dataset
    "lightwheel": "CC BY 4.0 (RoboCasa, Nasiriany et al. 2024/2026; models from NVIDIA "
                  "PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF, by Lightwheel)",
}
# The scans state no mass, so MuJoCo's default density (1000 kg/m3) weighs every shape. The files
# give each scan a look-only mesh (group 2) and its collision pieces (group 3) over the same
# volume, which weighs it twice; MuJoCo's compiler setting inertiagrouprange weighs only the
# collision pieces.
GSO_MASS_FROM_COLLISION = True
# ... at the density LIBERO and RoboCasa give scanned household objects (100 kg/m3: LIBERO's
# Google Scanned Objects, RoboCasa's Objaverse scans). A scan is a closed outer surface, so the
# density of water would weigh a shoe or a box as if solid all the way through.
GSO_DENSITY = 100
# Google's own category of a scan (Gazebo Fuel, owner GoogleResearch) -> it's a toy: library tab
# "Toys & Basics", name starting "Toy" (the scans are true to size; a dollhouse sofa is 21 cm)
GSO_FUEL = "https://fuel.gazebosim.org/1.0/GoogleResearch/models"
GSO_TOY_CATEGORIES = {"Toys", "Action Figures", "Board Games", "Legos", "Stuffed Toys"}
BIG, HEAVY = 0.9, 30.0           # m, kg: bigger or heavier items stay where they're put

# RoboCasa's own words for a few categories, said as people say them
WORDS = {"bagged_food": "Bagged food", "boxed_food": "Boxed food", "canned_food": "Canned food",
         "bottled_drink": "Bottled drink", "bottled_water": "Bottled water", "boxed_drink": "Boxed drink",
         "canned_drink": "Canned drink", "packaged_food": "Packaged food"}


def _gso_label(folder: str) -> str:
    s = re.sub(r"_+", " ", folder).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:60]


def gso_rows(folders: list[str]) -> list[dict]:
    """A library row per scan: Google's own name for it, and toys (by Google's category) in the
    toys tab, named as toys."""
    meta = _gso_meta()
    rows = []
    for f in folders:
        m = meta.get(f, {})
        label = m.get("name") or _gso_label(f)
        if label.isupper():                     # many toy makers' names are in capitals
            label = label.title()
        label = label[:60]
        toy = bool(GSO_TOY_CATEGORIES & set(m.get("categories", []))) or bool(re.search(r"(?i)\b(toys?|dollhouse)\b", label))
        if toy and not re.search(r"(?i)\btoys?\b", label):
            label = ("Toy " + label)[:60]
        rows.append({"id": "gs_" + re.sub(r"[^a-z0-9]+", "_", f.lower()).strip("_"), "source": "gso",
                     "folder": f, "label": label, "tab": "Toys & Basics" if toy else "Scanned Objects",
                     "fixed": False, "category": ", ".join(m.get("categories", []))})
    return rows


def relabel():
    """Re-name and re-tab the scans already listed (gso_rows), keeping each row's fixed/skip."""
    rows = json.loads(OUT.read_text())
    new = {r["id"]: r for r in gso_rows([r["folder"] for r in rows if r["source"] == "gso"])}
    for r in rows:
        if r["id"] in new:
            for k in ("label", "tab", "category"):
                r[k] = new[r["id"]][k]
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    print(sum(r["tab"] == "Toys & Basics" for r in new.values()), "of", len(new), "scans are toys")


def pick(gso: pathlib.Path | None, rc: pathlib.Path | None):
    rows = []
    if gso:
        rows += gso_rows(sorted(d.name for d in (gso / "models").iterdir() if (d / "model.xml").exists()))
    if rc:
        found = sorted(rc.glob("*/robocasa.json"))
        counts: dict[str, int] = {}
        for f in found:
            info = json.loads(f.read_text())
            cat = info["category"]
            counts[cat] = counts.get(cat, 0) + 1
            base = WORDS.get(cat, cat.replace("_", " ").capitalize())
            rows.append({"id": info["id"], "source": "robocasa", "folder": info["folder"],
                         "label": f"{base} {counts[cat]}", "tab": "RoboCasa",
                         "fixed": info["registry"] == "fixtures"})   # RoboCasa mounts its fixtures
    old = {r["id"]: r for r in json.loads(OUT.read_text())} if OUT.exists() else {}
    for r in rows:                       # keep what finish decided
        for k in ("fixed", "skip"):
            if k in old.get(r["id"], {}):
                r[k] = old[r["id"]][k]
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    print(len(rows), "items ->", OUT)


def _gso_weight(root: ET.Element):
    """A scan's <compiler> and <default>: weigh its collision pieces only, at GSO_DENSITY."""
    for tag in ("compiler", "default"):
        for el in root.findall(tag):
            if tag == "compiler" or el.get("class") is None:
                root.remove(el)
    comp = {"angle": "radian", "autolimits": "true"}
    if GSO_MASS_FROM_COLLISION:
        comp["inertiagrouprange"] = "3 3"       # weigh the collision pieces (group 3) only
    root.insert(0, ET.Element("compiler", comp))
    default = ET.Element("default")
    ET.SubElement(default, "geom", {"density": str(GSO_DENSITY)})
    root.insert(1, default)


def _gso_meta() -> dict:
    """Google's name and category for every scan, from Gazebo Fuel (where Google published them)."""
    import urllib.error
    import urllib.request
    out, page = {}, 1
    while True:
        try:
            with urllib.request.urlopen(f"{GSO_FUEL}?per_page=100&page={page}", timeout=60) as r:
                batch = json.load(r)
        except urllib.error.HTTPError:          # past the last page
            break
        if not batch:
            break
        for m in batch:
            out[m["name"]] = {"categories": m.get("categories") or [],
                              "name": (m.get("description") or "").split("\n")[0].strip()}
        page += 1
    return out


def reweigh(ids=None):
    """Re-weigh scans already built (playground/assets/gs_*) after GSO_DENSITY or
    GSO_MASS_FROM_COLLISION change: rewrites their model.xml and asset.json "mass", no rebuild."""
    import mujoco

    from .. import catalog
    n = 0
    for r in json.loads(OUT.read_text()):
        if r["source"] != "gso" or (ids and r["id"] not in ids):
            continue
        d = catalog.ASSETS / r["id"]
        if not (d / "asset.json").exists():
            continue
        root = ET.parse(d / "model.xml").getroot()
        _gso_weight(root)
        (d / "model.xml").write_text(ET.tostring(root, encoding="unicode"))
        sp = mujoco.MjSpec()
        sp.attach(mujoco.MjSpec.from_file(str(d / "model.xml")), frame=sp.worldbody.add_frame(), prefix="o_")
        meta = json.loads((d / "asset.json").read_text())
        meta["mass"] = round(float(sp.compile().body_subtreemass[0]), 5)
        (d / "asset.json").write_text(json.dumps(meta, indent=1))
        n += 1
    print(n, "scans re-weighed")


def _src(row: dict, gso: pathlib.Path, rc: pathlib.Path) -> pathlib.Path:
    if row["source"] == "gso":
        return gso / "models" / row["folder"] / "model.xml"
    return rc / row["id"] / "model.xml"


def build(row: dict, src: pathlib.Path) -> dict:
    import mujoco
    import numpy as np

    from .. import catalog
    from .build_libero_objects import thumb

    id_ = row["id"]
    out = catalog.ASSETS / id_
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    root = ET.parse(src).getroot()
    comp = root.find("compiler")
    meshdir = comp.get("meshdir", "") if comp is not None else ""
    texdir = comp.get("texturedir", "") if comp is not None else ""
    for el in root.iter():
        f = el.get("file")
        if f and el.tag in ("mesh", "texture", "hfield", "skin"):
            base = meshdir if el.tag != "texture" else texdir
            fp = (src.parent / base / f).resolve()
            rel = fp.relative_to(src.parent.resolve())
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            if not (out / rel).exists():        # (a file used twice is linked once)
                try:                            # a hard link: the sources are large
                    os.link(fp, out / rel)
                except OSError:
                    shutil.copy2(fp, out / rel)
            el.set("file", rel.as_posix())
    for tag in ("compiler", "size", "option"):
        for el in root.findall(tag):
            root.remove(el)
    comp = {"angle": "radian", "autolimits": "true"}
    if row["source"] == "gso":
        _gso_weight(root)
    else:
        root.insert(0, ET.Element("compiler", comp))
    (out / "model.xml").write_text(ET.tostring(root, encoding="unicode"))

    sp = mujoco.MjSpec()
    sp.attach(mujoco.MjSpec.from_file(str(out / "model.xml")), frame=sp.worldbody.add_frame(), prefix="o_")
    m = sp.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for g in range(m.ngeom):
        if "reg_" in m.geom(g).name:          # RoboCasa's invisible placement regions
            continue
        R = d.geom_xmat[g].reshape(3, 3)
        if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
            k = m.geom_dataid[g]
            pts = m.mesh_vert[m.mesh_vertadr[k]:m.mesh_vertadr[k] + m.mesh_vertnum[k]]
        else:
            c, h = m.geom_aabb[g][:3], m.geom_aabb[g][3:]
            pts = c + np.array(np.meshgrid([-1, 1], [-1, 1], [-1, 1])).T.reshape(-1, 3) * h
        p = d.geom_xpos[g] + pts @ R.T
        lo, hi = np.minimum(lo, p.min(0)), np.maximum(hi, p.max(0))
    size, mid = hi - lo, (lo + hi) / 2
    col = [g for g in range(m.ngeom) if m.geom_contype[g] or m.geom_conaffinity[g]]
    joints = [m.joint(j).name.removeprefix("o_") for j in range(m.njnt)]
    if row["source"] == "gso":
        where = f"Google Scanned Objects, MuJoCo model by Kevin Zakka: {GSO_COMMIT_URL}{row['folder']}"
    else:
        where = f"RoboCasa objects/{row['folder']} (github.com/robocasa/robocasa), as RoboCasa loads it"
    meta = {
        "source": where,
        "mjcf": "model.xml",
        "frame": {"pos": [round(float(-mid[0]), 6), round(float(-mid[1]), 6), round(float(-lo[2]), 6)], "quat": [1.0, 0.0, 0.0, 0.0]},
        "free_damping": 0.0005 if row["source"] == "robocasa" else None,
        "hide_collision": True,
        "mass": round(float(m.body_subtreemass[0]), 5),
        "friction": round(float(m.geom_friction[col[0]][0]), 3) if col else None,
        "size": [round(float(v), 4) for v in size],
        "collision": f"the source's own convex pieces ({len(col)})" + (f", moving parts ({', '.join(joints)})" if joints else ""),
        "license": LICENSE["lightwheel" if row["folder"].startswith(("lightwheel/", "fixtures/")) else row["source"]],
    }
    if meta["free_damping"] is None:
        del meta["free_damping"]
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    thumb(out, meta)
    return meta


def _build_one(args):
    row, gso, rc = args
    try:
        m = build(row, _src(row, gso, rc))
        return row["id"], True, f"{m['mass']:.3f} kg {'x'.join(f'{v * 100:.0f}' for v in m['size'])} cm"
    except Exception as e:  # noqa: BLE001
        from .. import catalog
        shutil.rmtree(catalog.ASSETS / row["id"], ignore_errors=True)
        return row["id"], False, str(e)[:300]


def build_all(gso, rc, ids, workers, redo=False):
    from .. import catalog
    rows = json.loads(OUT.read_text())
    todo = [r for r in rows if (not ids or r["id"] in ids)
            and (redo or ids or not (catalog.ASSETS / r["id"] / "asset.json").exists())]
    print(len(todo), "to build", flush=True)
    log = pathlib.Path("build/mjcf_build.jsonl")
    log.parent.mkdir(exist_ok=True)
    with ProcessPoolExecutor(workers) as ex, log.open("a") as lf:
        for k, (i, ok, msg) in enumerate(ex.map(_build_one, [(r, gso, rc) for r in todo], chunksize=4), 1):
            lf.write(json.dumps({"id": i, "ok": ok, "msg": msg}) + "\n")
            print(f"{k}/{len(todo)} {i:44s} {'ok ' if ok else 'FAILED '}{msg}", flush=True)


def finish():
    from .. import catalog
    check = json.loads(CHECK.read_text()) if CHECK.exists() else {}
    rows = json.loads(OUT.read_text())
    skipped = fixed = 0
    for r in rows:
        r.pop("skip", None)
        meta = catalog.ASSETS / r["id"] / "asset.json"
        if not meta.exists():
            r["skip"] = "didn't convert"
        elif r["id"] in check and not check[r["id"]]["ok"]:
            r["skip"] = "drop test: " + check[r["id"]]["why"][:120]
        if "skip" in r:
            skipped += 1
            continue
        a = json.loads(meta.read_text())
        r["fixed"] = r["id"].startswith("rc_fx_") or max(a["size"]) > BIG or a["mass"] > HEAVY
        fixed += r["fixed"]
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    print(len(rows), "items;", skipped, "skipped;", fixed, "fixed in place")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["pick", "build", "finish", "relabel", "reweigh"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--gso", type=pathlib.Path)
    ap.add_argument("--robocasa", type=pathlib.Path)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args(argv)
    if a.step == "pick":
        pick(a.gso, a.robocasa)
    elif a.step == "build":
        build_all(a.gso, a.robocasa, set(a.ids), a.workers, a.redo)
    elif a.step == "relabel":
        relabel()
    elif a.step == "reweigh":
        reweigh(set(a.ids))
    else:
        finish()


if __name__ == "__main__":
    sys.exit(main())
