"""The object library's files (playground/assets/<id>/) live in a Modal Volume, not in git.

    python -m playground.tools.library pull            # download what's missing here (first setup)
    python -m playground.tools.library push            # upload new or changed objects (after a build)
    python -m playground.tools.library push pl_d00033  # just these

The Modal app mounts the Volume at /library (hosting/app.py) and reads objects from it when a scene
uses them, so adding objects needs no deploy. Needs a Modal login (`modal token new`) or the
MODAL_TOKEN_ID / MODAL_TOKEN_SECRET environment variables. Only CREDITS.md stays in git.
A file counts as changed when its size differs (or with --all, always).
"""
from __future__ import annotations

import argparse
import pathlib
from concurrent.futures import ThreadPoolExecutor

from .. import catalog

VOLUME = "wetlab-library"
BATCH = 5000                     # files per upload batch


def volume():
    import modal
    return modal.Volume.from_name(VOLUME, create_if_missing=True, version=2)


def remote_sizes(vol) -> dict[str, int]:
    from modal.volume import FileEntryType
    return {e.path.lstrip("/"): e.size for e in vol.listdir("/", recursive=True) if e.type == FileEntryType.FILE}


def local_files(root: pathlib.Path, ids: list[str]) -> dict[str, pathlib.Path]:
    dirs = [root / i for i in ids] if ids else [d for d in root.iterdir() if d.is_dir()]
    return {str(f.relative_to(root)): f for d in dirs for f in d.rglob("*") if f.is_file()}


def push(ids: list[str], every: bool = False, root: pathlib.Path = catalog.ASSETS):
    vol = volume()
    have = {} if every else remote_sizes(vol)
    todo = [(rel, f) for rel, f in sorted(local_files(root, ids).items()) if have.get(rel) != f.stat().st_size]
    print(len(todo), "files to upload", flush=True)
    for k in range(0, len(todo), BATCH):
        with vol.batch_upload(force=True) as b:
            for rel, f in todo[k:k + BATCH]:
                b.put_file(str(f), "/" + rel)
        print(f"{min(k + BATCH, len(todo))}/{len(todo)}", flush=True)


def pull(ids: list[str], root: pathlib.Path = catalog.ASSETS, workers: int = 16):
    vol = volume()
    todo = [(rel, n) for rel, n in remote_sizes(vol).items()
            if (not ids or rel.split("/")[0] in ids)
            and not ((root / rel).exists() and (root / rel).stat().st_size == n)]
    print(len(todo), "files to download", flush=True)

    def get(rel):
        out = root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".part")
        with tmp.open("wb") as fh:
            vol.read_file_into_fileobj("/" + rel, fh)
        tmp.replace(out)

    with ThreadPoolExecutor(workers) as ex:
        for n, _ in enumerate(ex.map(get, [r for r, _ in todo]), 1):
            if n % 2000 == 0:
                print(f"{n}/{len(todo)}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["push", "pull"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="push: upload every file, changed or not")
    ap.add_argument("--root", default=str(catalog.ASSETS))
    a = ap.parse_args(argv)
    if a.what == "push":
        push(a.ids, a.all, pathlib.Path(a.root))
    else:
        pull(a.ids, pathlib.Path(a.root))


if __name__ == "__main__":
    main()
