"""Fetch and convert every library item (catalog.ITEMS) into playground/assets/<id>/.

    python -m playground.tools.build_assets [ids ...]
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

from .. import catalog
from .convert_simready import convert
from .fetch_simready import fetch


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--cache", default="build/simready")
    a = ap.parse_args(argv)
    ids = a.ids or [i[0] for i in catalog.ITEMS]
    for id_ in ids:
        it = catalog.item(id_)
        try:
            src = fetch(it["hf"], pathlib.Path(a.cache))
            m = convert(src, catalog.ASSETS / id_, hollow=it["hollow"])
            tdir = src / "simready_usd" / ".thumbs" / "256x256"
            thumbs = sorted(tdir.glob("*_transparent.png")) or sorted(tdir.glob("*.usd*.png"))
            if thumbs:
                shutil.copy(thumbs[0], catalog.ASSETS / id_ / "thumb.png")
            print(f"{id_:20s} mass={m['mass']} size={m['size']} parts={len(m['collision_parts'])}")
        except Exception as e:  # noqa: BLE001
            print(f"{id_:20s} FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
