"""A finished run's video: one robot, from its own cameras (its view of its table, its overhead
camera and its wrist camera, or both wrists on a two-arm robot), with the run's clock.

Made after the run from what the lab already saved for it: the scene it ran in (model.ref) and
the whole lab's positions over the run (replay.npz, 30 a second). So it is an exact replay,
drawn with MuJoCo's own renderer, nothing re-simulated. Runs as its own low-priority process so
the lab's live cameras (what the AIs see) are never slowed.

    python -m playground.runvideo <run dir> --cam <model camera>=<label> ... [--title ...] [--out video.mp4]
"""
from __future__ import annotations

import argparse
import bisect
import json
import pathlib
import subprocess

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
HEAD = 56                 # title bar
GAP = 8
FPS = 10
PART = 3_500_000          # stored in parts: the website takes at most 4.5 MB a request


def _font(size, bold=False):
    for p in (f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
              f"/System/Library/Fonts/Supplemental/Arial{' Bold' if bold else ''}.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def model_of(run_dir: pathlib.Path) -> mujoco.MjModel:
    ref = (run_dir / "model.ref").read_text().strip()
    return mujoco.MjModel.from_binary_path(str(run_dir.parent / "_models" / ref))


def layout(n_small: int):
    """(x, y, w, h) of the big scene view and of each small camera (4:3 each)."""
    bh = H - HEAD - 2 * GAP
    bw = bh * 4 // 3
    big = (GAP, HEAD + GAP, bw - bw % 2, bh - bh % 2)
    cx = big[0] + big[2] + GAP
    cw = W - cx - GAP
    each = (bh - (n_small - 1) * GAP) // n_small
    sh = min(each, cw * 3 // 4)
    sw = sh * 4 // 3
    smalls = [(cx + (cw - sw) // 2, HEAD + GAP + i * (each + GAP) + (each - sh) // 2, sw - sw % 2, sh - sh % 2)
              for i in range(n_small)]
    return big, smalls


def make(run_dir, cams: list[tuple[str, str]], out, title: str = "", fps: int = FPS) -> int:
    """Write the video (H.264 MP4); returns the number of frames. cams: (model camera, label),
    the first one big."""
    run_dir = pathlib.Path(run_dir)
    rec = np.load(run_dir / "replay.npz")
    times, qpos = rec["time"], rec["qpos"]
    if len(times) < 2:
        raise SystemExit("this run has no recording")
    m = model_of(run_dir)
    if qpos.shape[1] != m.nq:
        raise SystemExit("the recording doesn't match the run's scene")
    m.vis.global_.offwidth, m.vis.global_.offheight = max(m.vis.global_.offwidth, W), max(m.vis.global_.offheight, H)
    d = mujoco.MjData(m)
    big, smalls = layout(len(cams) - 1)
    boxes = [big] + smalls
    rend = {}
    for (w, h) in {(b[2], b[3]) for b in boxes}:
        rend[(w, h)] = mujoco.Renderer(m, h, w)
    f_title, f_lab, f_clock = _font(22, True), _font(15, True), _font(22, True)
    t0, t1 = float(times[0]), float(times[-1])
    n = int((t1 - t0) * fps) + 1
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                          stdin=subprocess.PIPE)
    tl = list(times)
    try:
        for k in range(n):
            t = t0 + k / fps
            d.qpos[:] = qpos[max(0, bisect.bisect_right(tl, t) - 1)]
            mujoco.mj_forward(m, d)
            img = Image.new("RGB", (W, H), (243, 244, 246))
            for i, ((cam, label), (x, y, w, h)) in enumerate(zip(cams, boxes)):
                r = rend[(w, h)]
                r.update_scene(d, camera=cam)
                # Software OpenGL draws shadows slowly: the big view keeps them (they show what
                # touches what), the small cameras go without, and no floor reflections.
                r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = i == 0
                r.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
                img.paste(Image.fromarray(r.render()), (x, y))
                dr = ImageDraw.Draw(img)
                tw = dr.textlength(label, font=f_lab)
                dr.rounded_rectangle((x + 8, y + 8, x + 24 + tw, y + 34), 6, fill=(255, 255, 255))
                dr.text((x + 16, y + 12), label, font=f_lab, fill=(17, 24, 39))
            dr = ImageDraw.Draw(img)
            el = t - t0
            clock = f"{int(el // 60)}:{int(el % 60):02d}"
            cw = dr.textlength(clock, font=f_clock)
            text = title
            if dr.textlength(text, font=f_title) > W - cw - 60:
                while text and dr.textlength(text + "…", font=f_title) > W - cw - 60:
                    text = text[:-1]
                text = text.rstrip() + "…"
            dr.text((GAP + 6, 15), text, font=f_title, fill=(17, 24, 39))
            dr.text((W - GAP - 6 - cw, 15), clock, font=f_clock, fill=(17, 24, 39))
            ff.stdin.write(img.tobytes())
    finally:
        ff.stdin.close()
        ff.wait()
        for r in rend.values():
            r.close()
    if ff.returncode != 0:
        raise SystemExit("ffmpeg could not write the video")
    return n


def parts(path) -> tuple[list[bytes], dict]:
    """The video in pieces small enough to upload, and the manifest that puts it back together."""
    data = pathlib.Path(path).read_bytes()
    chunks = [data[i:i + PART] for i in range(0, len(data), PART)]
    return chunks, {"type": "video/mp4", "size": len(data), "parts": [len(c) for c in chunks]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--cam", action="append", required=True, help="<model camera>=<label>; the first is drawn big")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--fps", type=int, default=FPS)
    a = ap.parse_args(argv)
    cams = [tuple(c.split("=", 1)) if "=" in c else (c, c) for c in a.cam]
    out = a.out or str(pathlib.Path(a.run_dir) / "video.mp4")
    tmp = out + ".part.mp4"
    n = make(a.run_dir, cams, tmp, a.title, a.fps)
    pathlib.Path(tmp).replace(out)
    print(json.dumps({"frames": n, "out": out}))


if __name__ == "__main__":
    main()
