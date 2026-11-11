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

# Where assets come from: NVIDIA's SimReady set, and Tripo's SimReady assets (the same packaging
# under usd/ instead of simready_usd/, with jointed parts).
REPOS = {"nvidia": "nvidia/simready-assets", "tripo": "VAST-AI/Tripo-Simready-Assets"}
REPO = "https://huggingface.co/datasets/" + REPOS["nvidia"]


def _list(folder: str, repo: str = "nvidia") -> list[dict]:
    api = f"https://huggingface.co/api/datasets/{REPOS[repo]}/tree/main/"
    with urllib.request.urlopen(api + folder + "?recursive=true", timeout=60) as r:
        return json.load(r)


def wanted(path: str) -> bool:
    if "/source_assets/" in path or "/.metadata/" in path:
        return False
    if "/.thumbs/" in path:
        return path.endswith(("_transparent.png", ".usd.png", ".usda.png")) and "/256x256/" in path \
            and ("simready_usd/.thumbs" in path or "/usd/.thumbs" in path)
    return "/simready_usd/" in path or "/usd/" in path or path.endswith("LICENSE.txt")


def fetch(folder: str, out: pathlib.Path, repo: str = "nvidia") -> pathlib.Path:
    dest = out / folder
    for f in _list(folder, repo):
        if f.get("type") != "file" or not wanted(f["path"]):
            continue
        target = out / f["path"]
        if target.exists() and target.stat().st_size == f.get("size"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"https://huggingface.co/datasets/{REPOS[repo]}/resolve/main/{f['path']}", timeout=120) as r:
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
