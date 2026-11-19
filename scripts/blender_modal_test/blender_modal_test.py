"""Blender on Modal test: build the AI-written lab chair (playground/tools/ai_chair.py) in Modal
containers, CPU-only and with two GPUs, and time each step.

    modal run blender_modal_test.py

A separate Modal app ("blender-asset-test"); it does not touch the Playground's app. Each
container: builds the chair in Blender (bpy), writes it in the library's form, renders the
library picture and a photo-style picture with Cycles, then loads it in MuJoCo the way the
Playground does and checks its physics. Results go to ./out/ next to this file.
"""
import json
import pathlib
import time

import modal

HERE = pathlib.Path(__file__).parent
app = modal.App("blender-asset-test")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libxrender1", "libxxf86vm1", "libxfixes3", "libxi6", "libxkbcommon0", "libsm6", "libx11-6",
                 "libgl1", "libegl1", "libegl-mesa0", "libgl1-mesa-dri", "fonts-dejavu-core")
    .pip_install("bpy==5.0.1", "mujoco==4.0.1", "numpy==1.26.4", "trimesh==5.2.1", "pillow", "usd-core", "scipy")
    .env({"MUJOCO_GL": "egl", "EGL_PLATFORM": "surfaceless", "WETLAB_ASSETS_DIR": "/tmp/assets"})
    .add_local_file(HERE / "src.tgz", "/root/src.tgz")
)


def _job(label: str, gpu: bool) -> dict:
    import io
    import os
    import subprocess
    import sys
    import tarfile
    import zipfile

    t_start = time.time()
    os.makedirs("/root/src", exist_ok=True)
    tarfile.open("/root/src.tgz").extractall("/root/src")
    sys.path.insert(0, "/root/src")
    from playground.tools import ai_chair, build_inhouse as B

    res = {"label": label, "cpus": os.cpu_count()}
    try:
        res["gpu_name"] = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                         capture_output=True, text=True).stdout.strip() or None
    except FileNotFoundError:
        res["gpu_name"] = None
    out = pathlib.Path("/tmp/assets/ai_lab_chair")
    t = time.time(); parts = ai_chair.build(); meta = ai_chair.write(out, parts); res["model_and_export_s"] = round(time.time() - t, 2)
    t = time.time(); B.thumb(out, meta); res["thumbnail_s"] = round(time.time() - t, 2)
    hero = pathlib.Path("/tmp/hero.png")
    t = time.time(); ai_chair.hero(out, meta, hero, gpu, samples=256, res=1200); res["photo_render_s"] = round(time.time() - t, 2)

    # physics: load it the way the Playground does
    import mujoco
    import numpy as np
    from playground import catalog, world as W
    catalog.ITEMS.append(("ai_lab_chair", "Furniture", "Lab chair (AI-made test)", "inhouse:ai_lab_chair", False, False))
    t = time.time()
    m = W.build([W.Placed("c", "ai_lab_chair", (0, 0, 0.01))], [])
    d = mujoco.MjData(m)
    root = m.body("obj_c").id
    seat = m.jnt_bodyid[m.joint("obj_c__2_swivel").id]
    ha, qa = m.joint("obj_c__1_height").qposadr[0], m.joint("obj_c__2_swivel").qposadr[0]

    def run(sec, f=None):
        for _ in range(int(sec / m.opt.timestep)):
            if f is not None:
                d.xfrc_applied[f[0]] = f[1]
            mujoco.mj_step(m, d)
        d.xfrc_applied[:] = 0

    run(2.0)
    ph = {"mass_kg": round(float(m.body_subtreemass[root]), 2), "moving_parts": m.njnt - 1,
          "stands_upright": bool(d.xmat[root][8] > 0.99)}
    run(1.0, (seat, [0, 0, 0, 0, 0, 3.0]))
    ph["seat_turned_deg_by_a_light_twist"] = round(float(np.degrees(d.qpos[qa])), 1)
    h0 = d.qpos[ha]
    run(2.0, (seat, [0, 0, -700, 0, 0, 0]))
    ph["seat_sank_mm_with_700N_sitter"] = round(float((h0 - d.qpos[ha]) * 1000), 2)
    p0 = d.xpos[root].copy()
    run(1.0, (root, [10, 0, 0, 0, 0, 0]))
    ph["moved_cm_with_10N_push"] = round(float(np.linalg.norm((d.xpos[root] - p0)[:2]) * 100), 1)
    p0 = d.xpos[root].copy()
    run(1.0, (root, [40, 0, 0, 0, 0, 0]))
    ph["moved_cm_with_40N_push"] = round(float(np.linalg.norm((d.xpos[root] - p0)[:2]) * 100), 1)
    ph["still_upright"] = bool(d.xmat[root][8] > 0.99)
    ph["no_blowups"] = bool(np.isfinite(d.qpos).all())
    res["physics"] = ph
    res["physics_check_s"] = round(time.time() - t, 2)
    pics = {}
    try:
        r = mujoco.Renderer(m, 900, 900)
        cam = mujoco.MjvCamera()
        cam.lookat[:] = d.xpos[root] + [0, 0, 0.5]
        cam.distance, cam.azimuth, cam.elevation = 2.3, -55, -16
        r.update_scene(d, cam)
        from PIL import Image
        buf = io.BytesIO(); Image.fromarray(r.render()).save(buf, "PNG"); pics["mujoco.png"] = buf.getvalue()
    except Exception as e:      # noqa: BLE001
        res["mujoco_picture_error"] = repr(e)
    res["total_s"] = round(time.time() - t_start, 2)
    pics["photo.png"] = hero.read_bytes()
    pics["thumb.png"] = (out / "thumb.png").read_bytes()
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out.iterdir():
            zf.write(f, f"ai_lab_chair/{f.name}")
    pics["ai_lab_chair.zip"] = z.getvalue()
    return {"result": res, "files": pics}


@app.function(image=image, cpu=8.0, memory=8192, timeout=1800)
def cpu8():
    return _job("CPU only, 8 cores", False)


@app.function(image=image, cpu=4.0, memory=8192, gpu="T4", timeout=1800)
def gpu_t4():
    return _job("GPU: NVIDIA T4 (+4 cores)", True)


@app.function(image=image, cpu=4.0, memory=8192, gpu="L4", timeout=1800)
def gpu_l4():
    return _job("GPU: NVIDIA L4 (+4 cores)", True)


@app.local_entrypoint()
def main():
    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    calls = {name: f.spawn() for name, f in (("cpu8", cpu8), ("gpu_t4", gpu_t4), ("gpu_l4", gpu_l4))}
    summary = {}
    for name, c in calls.items():
        t = time.time()
        try:
            r = c.get()
        except Exception as e:      # noqa: BLE001
            summary[name] = {"error": repr(e)}
            print(name, "FAILED", repr(e))
            continue
        for fn, data in r["files"].items():
            (outdir / f"{name}_{fn}").write_bytes(data)
        summary[name] = r["result"]
        print(name, json.dumps(r["result"]))
    (outdir / "results.json").write_text(json.dumps(summary, indent=1))
    print("wrote", outdir)
