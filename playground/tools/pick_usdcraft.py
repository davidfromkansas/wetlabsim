"""Pick one version of each USDCraft-10K kind for the library and write playground/usdcraft_library.json.

    python -m playground.tools.pick_usdcraft --cache build/usdcraft_meta

NVIDIA's USDCraft-10K (Apache 2.0) has 1,000 kinds of objects with 10 versions each. For each kind
this keeps one version: one that stands up on its own (meta.json "tips_over" false), has textures,
has the most kinds of moving joints, and has at most 30 parts. Kinds the library already has (by
name) are left out. The library tab comes from the kind's "scene"; furniture-size and larger
kinds are `fixed`.
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import pathlib
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .. import catalog

REPO = "https://huggingface.co/datasets/nvidia/USDCraft-10K/resolve/main/"
OUT = pathlib.Path(catalog.__file__).parent / "usdcraft_library.json"

TAB = {"kitchen": "Kitchen", "dining": "Kitchen", "restaurant_cafe": "Kitchen",
       "laboratory": "Lab & Medical", "hospital_clinic": "Lab & Medical",
       "factory_floor": "Factory", "warehouse_logistics": "Factory", "utility_energy": "Factory",
       "construction_site": "Factory", "vehicle_transport": "Garage", "laundry_cleaning": "Cleaning",
       "bathroom": "Home", "living_room": "Home", "bedroom": "Home", "home_storage": "Home",
       "personal_wearable": "Home", "kids_nursery": "Toys & Basics", "office": "Office",
       "home_office": "Office", "classroom_library": "Office", "retail_store": "Shops & Hotels",
       "hotel_hospitality": "Shops & Hotels", "music_entertainment": "Sports & Leisure",
       "gym_sports": "Sports & Leisure", "park_playground": "Sports & Leisure",
       "camping_outdoor": "Sports & Leisure", "garden_yard": "Outdoor", "farm": "Outdoor",
       "street_urban": "Outdoor"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def _norm(s: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    return " ".join(w[:-1] if w.endswith("s") and len(w) > 3 and not w.endswith("ss") else w for w in words)


def _label(cat: str) -> str:
    """Sentence case, keeping acronyms (TV, CNC) and model names (3D) as written."""
    return " ".join(w if (w.isupper() and len(w) > 1) or any(c.isdigit() for c in w) or w == "Wi-Fi"
                    else (w[0] + w[1:].lower() if i == 0 else w.lower()) for i, w in enumerate(cat.split()))


def _score(meta: dict, textured: bool) -> int:
    jt = set(meta["joint_types"])
    return (-5 * meta["tips_over"] + 2 * textured + len(jt - {"spherical"}) - 3 * ("spherical" in jt)
            - (meta["part_count"] > 30))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="build/usdcraft_meta")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    cache = pathlib.Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(io.StringIO(_get(REPO + "manifest.csv").decode())))

    def meta(r):
        f = cache / (r["object_id"] + ".json")
        if not f.exists():
            f.write_bytes(_get(REPO + r["path"] + "/meta.json"))
        return r, json.loads(f.read_text())

    with ThreadPoolExecutor(32) as ex:
        metas = list(ex.map(meta, rows))
    by_kind = collections.defaultdict(list)
    for r, m in metas:
        by_kind[m["category_id"]].append((r, m))
    ours = [_norm(i[2]) for i in catalog.ITEMS if not i[0].startswith("uc_")]
    labels = {i[2].lower() for i in catalog.ITEMS if not i[0].startswith("uc_")}
    out = []
    for _, versions in sorted(by_kind.items()):
        r, m = sorted(versions, key=lambda v: (-_score(v[1], v[0]["has_textures"] == "true"), v[1]["object_id"]))[0]
        kind = _norm(m["category"])
        if any(f" {kind} " in f" {n} " or (f" {n} " in f" {kind} " and (len(n.split()) >= 2 or n == kind)
                                           and kind.endswith(n)) for n in ours):
            continue                        # the library has this kind already
        scene = m["scene"]
        tab = ("Tools" if m["size_class"] in ("handheld", "tabletop") else "Garage") if scene == "garage_workshop" else TAB[scene]
        label = _label(m["category"])
        if label.lower() in labels:
            label += " (USDCraft)"
        out.append({"id": "uc_" + re.sub(r"[^a-z0-9]+", "_", m["category"].lower()).strip("_"), "tab": tab,
                    "label": label, "folder": r["path"], "fixed": m["size_class"] in ("furniture", "large")})
    pathlib.Path(a.out).write_text("[\n" + ",\n".join(json.dumps(o) for o in out) + "\n]\n")
    print(len(out), "kinds written to", a.out)


if __name__ == "__main__":
    main()
