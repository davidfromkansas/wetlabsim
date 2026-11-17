"""Download NVIDIA SimReady assets (USD + MuJoCo payload + textures) from Hugging Face.

    python -m playground.tools.fetch_simready kitchenware_bowl_b01 [more ...] --out build/simready

Only what the converter needs is fetched: the root USD, its payloads and full-size textures,
plus one 256 px thumbnail for the object library.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import urllib.request
import urllib.parse

# Where assets come from: NVIDIA's SimReady set, and Tripo's SimReady assets (the same packaging
# under usd/ instead of simready_usd/, with jointed parts).
REPOS = {"nvidia": "nvidia/simready-assets", "tripo": "VAST-AI/Tripo-Simready-Assets",
         # QUIKTECH's lab equipment (CC BY 4.0, NVIDIA SimReady packaging)
         "quiktech": "quiktech/SimReady-Assets",
         # NVIDIA's USDCraft-10K (Apache 2.0): physx/model.usdc + meta.json per item
         "usdcraft": "nvidia/USDCraft-10K",
         # ForgeCAD's parametric models (CC BY 4.0, NVIDIA SimReady packaging, physics under simready_usd/forgecad/)
         "forgecad": "ForgeCAD/simready-assets",
         # Palatial's NVIDIA-packaged furniture and fixtures (CC BY 4.0, folders D00154, ...)
         "palatial": "PalatialSim/palatial-nv-asset-library",
         # More CC BY 4.0 sets in the same NVIDIA SimReady packaging (Nov 17 scan)
         "projectsim": "projectsim/simready-assets",          # Kaedim's household items, many with caps/lids
         "allsides": "ALLSIDES/simready-scanned-objects",     # 3D scans of real objects, weighed masses
         "ndotlight": "NdotLight/SimReady_Assets",            # factory, tools and safety equipment
         "mxr": "M-XR/marso-simready",                        # Marso Studio objects (usd/ folder)
         "yamato": "YAMATOPROTEC/simready-fire-protection",   # the maker's own fire extinguisher
         "atech": "atechdev/simready-assets"}                 # small electronics modules
REPO = "https://huggingface.co/datasets/" + REPOS["nvidia"]


def _list(folder: str, repo: str = "nvidia") -> list[dict]:
    api = f"https://huggingface.co/api/datasets/{REPOS[repo]}/tree/main/"
    with urllib.request.urlopen(api + folder + "?recursive=true", timeout=60) as r:
        return json.load(r)


def wanted(path: str, repo: str = "nvidia") -> bool:
    if "/source_assets/" in path or "/.metadata/" in path:
        return False
    if repo == "allsides":
        # Allsides ship each scan twice (LOD 0 full scan, LOD 1 reduced, picked by its "LOD" variant)
        # plus a PhysX-only layer; we read LOD 1 and the plain physics layer, and only the albedo
        # texture (the converter uses the base colour only). This keeps a download near 30 MB, not 400.
        name = path.rsplit("/", 1)[-1]
        if "lod00" in name or name.endswith("_physx.usd") or ("/textures/" in path and "_albedo" not in name):
            return False
    if "/.thumbs/" in path:
        return path.endswith(("_transparent.png", ".usd.png", ".usda.png")) and "/256x256/" in path \
            and ("simready_usd/.thumbs" in path or "/usd/.thumbs" in path)
    return "/simready_usd/" in path or "/usd/" in path or "/physx/" in path \
        or path.endswith(("LICENSE.txt", "/meta.json"))


def fetch(folder: str, out: pathlib.Path, repo: str = "nvidia") -> pathlib.Path:
    dest = out / folder
    for f in _list(folder, repo):
        if f.get("type") != "file" or not wanted(f["path"], repo):
            continue
        target = out / f["path"]
        if target.exists() and target.stat().st_size == f.get("size"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"https://huggingface.co/datasets/{REPOS[repo]}/resolve/main/{urllib.parse.quote(f['path'])}", timeout=120) as r:
            target.write_bytes(r.read())
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--out", default="build/simready")
    a = ap.parse_args(argv)
    for name in a.folders:
        print("fetched", fetch(name, pathlib.Path(a.out)))


if __name__ == "__main__":
    main()
