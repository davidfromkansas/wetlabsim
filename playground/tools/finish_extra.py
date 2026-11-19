"""Finish the Nov 17 batch after it is built and drop-tested: mark the items that failed (not built,
or failed the drop test) as `skip`, and big or heavy items as `fixed` in place.

    python -m playground.tools.check_usdcraft --out build/extra_check.json <ids>   # drop test first
    python -m playground.tools.finish_extra

Updates playground/extra_library.json.
"""
from __future__ import annotations

import json
import pathlib

from .. import catalog
from .pick_extra import OUT

BIG = 0.9       # m: anything with a side longer than this stays where it is put
HEAVY = 30.0    # kg


def main(argv=None):
    check = json.loads(pathlib.Path("build/extra_check.json").read_text())
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
        r["fixed"] = max(a.get("size") or [0]) > BIG or (a.get("mass") or 0) > HEAVY
        fixed += r["fixed"]
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    print(len(rows), "items;", skipped, "skipped;", fixed, "fixed in place")


if __name__ == "__main__":
    main()
