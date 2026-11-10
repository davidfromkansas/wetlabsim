"""Download the meshes and textures LIBERO's scenes use (listed in libero_assets/manifest.json)
from LIBERO's GitHub repository, at the commit the scenes were exported from, into
libero_assets/files. One time, about 200 MB; every file is checked against its SHA-256.

    python -m playground.tools.fetch_libero
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ASSETS = pathlib.Path(__file__).parent.parent / "libero_assets"
FILES = ASSETS / "files"
_lock = threading.Lock()
status = {"state": "idle", "done": 0, "total": 0, "error": None}


def _manifest() -> dict:
    return json.loads((ASSETS / "manifest.json").read_text())


def missing() -> list[str]:
    out = []
    for rel, info in _manifest()["files"].items():
        f = FILES / rel
        if not f.exists() or f.stat().st_size != info["bytes"]:
            out.append(rel)
    return out


def _get(man: dict, rel: str):
    url = f"https://raw.githubusercontent.com/{man['repo']}/{man['commit']}/{man['path']}{rel}"
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != man["files"][rel]["sha256"]:
        raise RuntimeError(f"{rel}: download doesn't match the expected file")
    dst = FILES / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dst)
    with _lock:
        status["done"] += 1


def ensure() -> None:
    """Download whatever is missing. Safe to call from several threads: one download runs."""
    with _lock:
        if status["state"] == "downloading":
            busy = True
        else:
            busy = False
            status.update(state="downloading", done=0, total=0, error=None)
    if busy:
        while status["state"] == "downloading":
            threading.Event().wait(0.5)
        if status["error"]:
            raise RuntimeError(status["error"])
        return
    try:
        todo = missing()
        status["total"] = len(todo)
        if todo:
            man = _manifest()
            with ThreadPoolExecutor(8) as ex:
                list(ex.map(lambda r: _get(man, r), todo))
        status["state"] = "ready"
    except Exception as e:  # noqa: BLE001
        status.update(state="error", error=f"couldn't download LIBERO's objects: {e}")
        raise RuntimeError(status["error"]) from e


if __name__ == "__main__":
    todo = missing()
    mb = sum(_manifest()["files"][r]["bytes"] for r in todo) / 1e6
    print(f"{len(todo)} files to download ({mb:.0f} MB)")
    ensure()
    print("done")
    sys.exit(0)
