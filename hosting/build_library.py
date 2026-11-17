"""Build library objects on many Modal machines at once (a one-off, not part of the site).

    modal run hosting/build_library.py                     # every EXTRA item not built yet
    modal run hosting/build_library.py --only palatial     # one source

Each item runs tools/build_assets in a container of its own (same converter, same settings as a
local build); its files come back and are written to playground/assets/<id>/. Run by the
"Build library objects" GitHub workflow, which commits the results to the branch.
"""
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import time

import modal

ROOT = pathlib.Path(__file__).resolve().parent.parent
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libegl1", "libgl1", "libegl-mesa0", "libgl1-mesa-dri", "libglvnd0", "libopengl0")
    .pip_install("mujoco>=4.0,<5", "numpy", "pillow", "usd-core", "coacd", "trimesh", "scipy", "shapely",
                 "networkx", "rtree", "manifold3d", "fast_simplification", "pymeshlab", "pyarrow")
    .env({"MUJOCO_GL": "egl", "EGL_PLATFORM": "surfaceless", "PYTHONPATH": "/app", "PYTHONUNBUFFERED": "1"})
    # the code and the library lists only, not the 2 GB of converted objects
    .add_local_dir(str(ROOT / "playground"), "/app/playground", ignore=["assets/**", "libero_assets/files/**",
                                                                         "**/__pycache__", "static/**"])
    .add_local_dir(str(ROOT / "wetlabsim"), "/app/wetlabsim", ignore=["assets/**", "**/__pycache__"])
)
app = modal.App("wetlab-library-build", image=image)


@app.function(cpu=4.0, memory=8192, timeout=3600, retries=1, max_containers=100)
def build(id_: str) -> dict:
    """Build one item; returns its folder as a tar (or the error)."""
    t = time.time()
    (pathlib.Path("/app/playground/assets") / id_).parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, "-m", "playground.tools.build_assets", id_, "--cache", "/tmp/cache",
                        "--by-repo", "--no-credits"], cwd="/app", capture_output=True, text=True, timeout=3300)
    out = pathlib.Path("/app/playground/assets") / id_
    if not (out / "asset.json").exists():
        return {"id": id_, "ok": False, "s": round(time.time() - t),
                "error": (p.stderr.strip().splitlines() or ["no output"])[-1][-300:]}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(out, arcname=id_)
    return {"id": id_, "ok": True, "s": round(time.time() - t), "tar": buf.getvalue()}


@app.local_entrypoint()
def main(only: str = "", limit: int = 0):
    sys.path.insert(0, str(ROOT))
    from playground import catalog
    todo = [u["id"] for u in catalog.EXTRA if (not only or u["source"] == only)
            and not (catalog.ASSETS / u["id"] / "asset.json").exists()]
    if limit:
        todo = todo[:limit]
    print(len(todo), "to build", flush=True)
    log = (ROOT / "build" / "extra_build.jsonl")
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as f:
        for n, r in enumerate(build.map(todo, return_exceptions=True, order_outputs=False), 1):
            if isinstance(r, Exception):
                print(f"{n}/{len(todo)} FAILED {r}", flush=True)
                continue
            tar = r.pop("tar", None)
            if tar:
                with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
                    tf.extractall(catalog.ASSETS, filter="data")
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(f"{n}/{len(todo)} {r['id']} {'ok' if r['ok'] else 'FAILED ' + r['error']} {r['s']}s", flush=True)
