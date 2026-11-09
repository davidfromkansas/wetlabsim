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

REPO = "https://huggingface.co/datasets/nvidia/simready-assets"
API = "https://huggingface.co/api/datasets/nvidia/simready-assets/tree/main/"


def _list(folder: str) -> list[dict]:
    with urllib.request.urlopen(API + folder + "?recursive=true", timeout=60) as r:
        return json.load(r)


def wanted(path: str) -> bool:
    if "/source_assets/" in path or "/.metadata/" in path:
        return False
    if "/.thumbs/" in path:
        return path.endswith(("_transparent.png", ".usd.png", ".usda.png")) and "/256x256/" in path \
            and "simready_usd/.thumbs" in path
    return "/simready_usd/" in path or path.endswith("LICENSE.txt")


def fetch(folder: str, out: pathlib.Path) -> pathlib.Path:
    dest = out / folder
    for f in _list(folder):
        if f.get("type") != "file" or not wanted(f["path"]):
            continue
        target = out / f["path"]
        if target.exists() and target.stat().st_size == f.get("size"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{REPO}/resolve/main/{f['path']}", timeout=120) as r:
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
