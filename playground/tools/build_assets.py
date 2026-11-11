"""Fetch and convert every library item (catalog.ITEMS) into playground/assets/<id>/.

    python -m playground.tools.build_assets [ids ...]
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

from .. import catalog
from .convert_simready import convert, usd_dir
from .fetch_simready import fetch


SOURCES = {
    "nvidia": ("NVIDIA SimReady", "https://huggingface.co/datasets/nvidia/simready-assets"),
    "tripo": ("Tripo SimReady", "https://huggingface.co/datasets/VAST-AI/Tripo-Simready-Assets"),
}
AUTOBIO = ("AutoBio", "../../wetlabsim/assets/autobio/NOTICE.md")


def write_credits():
    """playground/assets/CREDITS.md: every library item, its source and licence (CC BY 4.0)."""
    lines = ["# Object library credits", "",
             "Every object in the playground's library is a ready-made asset, used under the",
             "[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) licence",
             "it is published with. We converted each to MuJoCo (`playground/tools/convert_simready.py`)",
             "and changed nothing else. All rights stay with their authors.", ""]
    for key, (name, url) in SOURCES.items():
        lines.append(f"- **{name}** ({key}): {url}")
    lines += ["", "AutoBio's lab models (the tubes, racks, dish, pipette and its stand) are used with credit to",
              "its authors; see `wetlabsim/assets/autobio/NOTICE.md`.", "",
              "| Item | Library tab | Source | Asset |", "| --- | --- | --- | --- |"]
    for i, tab, label, hf, _, _ in catalog.ITEMS:
        repo, _, folder = hf.rpartition(":")
        if repo == "autobio":             # in the repo already (tools/build_autobio.py)
            lines.append(f"| {label} | {tab} | AutoBio (credit in NOTICE.md) | [`{folder}`]({AUTOBIO[1]}) |")
            continue
        name, url = SOURCES[repo or "nvidia"]
        lines.append(f"| {label} | {tab} | {name} | [`{folder}`]({url}/tree/main/{folder}) |")
    (catalog.ASSETS / "CREDITS.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--cache", default="build/simready")
    a = ap.parse_args(argv)
    ids = a.ids or [i[0] for i in catalog.ITEMS if not i[3].startswith("autobio:")]
    for id_ in ids:
        it = catalog.item(id_)
        try:
            repo, _, folder = it["hf"].rpartition(":")
            src = fetch(folder, pathlib.Path(a.cache), repo or "nvidia")
            m = convert(src, catalog.ASSETS / id_, hollow=it["hollow"], solid=id_ in catalog.SOLID)
            tdir = usd_dir(src) / ".thumbs" / "256x256"
            thumbs = sorted(tdir.glob("*_transparent.png")) or sorted(tdir.glob("*.usd*.png"))
            if thumbs:
                shutil.copy(thumbs[0], catalog.ASSETS / id_ / "thumb.png")
            print(f"{id_:20s} mass={m['mass']} size={m['size']} parts={len(m['collision_parts'])} bodies={len(m.get('bodies', []))}")
        except Exception as e:  # noqa: BLE001
            print(f"{id_:20s} FAILED: {e}", file=sys.stderr)
    write_credits()


if __name__ == "__main__":
    main()
