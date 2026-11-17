"""Build the Nov 17 batch (extra_library.json) several at a time, each item in its own process.

    python -m playground.tools.build_extra --workers 4 [--only palatial] [--timeout 1800]

Each item is fetched into its own cache folder, converted by tools/build_assets, and the cache is
deleted again (the sources are large: a whole batch would not fit on disk). Items already built
(playground/assets/<id>/asset.json) are skipped, so a stopped run picks up where it left off.
Results go to build/extra_build.jsonl: one line per item with "ok", the seconds it took and the
error when it failed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .. import catalog

LOG = pathlib.Path("build/extra_build.jsonl")


def build_one(id_: str, timeout: int) -> dict:
    cache = pathlib.Path("build/cache") / id_
    t = time.time()
    try:
        p = subprocess.run([sys.executable, "-m", "playground.tools.build_assets", id_, "--cache", str(cache),
                            "--by-repo", "--no-credits"], capture_output=True, text=True, timeout=timeout)
        ok = (catalog.ASSETS / id_ / "asset.json").exists()
        err = "" if ok else (p.stderr.strip().splitlines() or ["no output"])[-1][-300:]
    except subprocess.TimeoutExpired:
        ok, err = False, f"took over {timeout} s"
        shutil.rmtree(catalog.ASSETS / id_, ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    return {"id": id_, "ok": ok, "s": round(time.time() - t), "error": err}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--only", help="one source (projectsim, allsides, palatial, ...)")
    ap.add_argument("--shard", default="0/1", help="i/n: build only every n-th item, starting at i (split over machines)")
    a = ap.parse_args(argv)
    done = set()
    if LOG.exists():
        done = {json.loads(line)["id"] for line in LOG.read_text().splitlines() if line.strip()}
    i, n = map(int, a.shard.split("/"))     # by place in the whole list, the same on every machine
    todo = [u["id"] for k, u in enumerate(catalog.EXTRA) if k % n == i and (not a.only or u["source"] == a.only)
            and u["id"] not in done and not (catalog.ASSETS / u["id"] / "asset.json").exists()]
    print(len(todo), "to build", flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex, LOG.open("a") as log:
        for n, r in enumerate(ex.map(lambda i: build_one(i, a.timeout), todo), 1):
            log.write(json.dumps(r) + "\n")
            log.flush()
            print(f"{n}/{len(todo)} {r['id']} {'ok' if r['ok'] else 'FAILED ' + r['error']} {r['s']}s", flush=True)


if __name__ == "__main__":
    main()
