"""Turn a recorded run into an MP4: room view, the robot's two cameras, and the
agent's commands as they happen. Idle stretches (the model thinking while the arm
holds still) are fast-forwarded and labelled.

    python -m wetlabsim.make_video runs/<run-id> [--fps 15] [--out demo.mp4]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import scene as S

W, H = 1280, 720
MAIN_W, MAIN_H = 960, 720
SIDE_W, SIDE_H = 320, 240
IDLE_SPEEDUP = 4.0


def _font(size, bold=False):
    for name in (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]):
        for root in ("/usr/share/fonts/truetype/dejavu/", "/Library/Fonts/", "/System/Library/Fonts/Supplemental/"):
            try:
                return ImageFont.truetype(root + name, size)
            except OSError:
                pass
    try:
        return ImageFont.truetype("Arial Bold.ttf" if bold else "Arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def describe(ev) -> str | None:
    kind = ev.get("kind") or ev.get("event")
    if ev.get("event") == "camera":
        return f"Looks through the {ev['camera']} camera"
    if ev.get("event") == "protective_stop":
        return "PROTECTIVE STOP: " + ev.get("reason", "")
    if kind == "move_l":
        x, y, z = ev["target"][:3]
        return f"Moves hand in a straight line to ({x:.2f}, {y:.2f}, {z:.2f}) m"
    if kind in ("move_j",):
        return "Moves the arm joint by joint"
    if kind == "gripper":
        p = ev["position"]
        return "Closes the gripper" if p >= 250 else "Opens the gripper fully" if p <= 5 else f"Opens the gripper partway ({p:.0f}/255)"
    if kind == "stop":
        return "Stops the arm"
    if kind == "unlock_protective_stop":
        return "Clears the protective stop"
    return None


def wrap(text, font, width, draw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def build_timeline(times, qpos, events, fps):
    """Video frame -> sim time. Fast-forward when nothing is moving and no command is new."""
    moving = np.r_[False, np.max(np.abs(np.diff(qpos, axis=0)), axis=1) > 1e-5]
    ev_t = np.array(sorted(e["t"] for e in events)) if events else np.array([])
    out, t = [], times[0]
    while t <= times[-1]:
        out.append(t)
        i = min(np.searchsorted(times, t), len(times) - 1)
        near_event = len(ev_t) and np.min(np.abs(ev_t - t)) < 0.7
        busy = moving[max(0, i - 15):i + 15].any() or near_event
        t += (1.0 if busy else IDLE_SPEEDUP) / fps
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--out")
    ap.add_argument("--title", default=None)
    args = ap.parse_args(argv)
    run = pathlib.Path(args.run_dir)
    rec = np.load(run / "replay.npz")
    times, qpos = rec["time"], rec["qpos"]
    events = json.loads((run / "events.json").read_text()) if (run / "events.json").exists() else []
    result = json.loads((run / "result.json").read_text())
    task = (run / "task.txt").read_text().strip()
    agent_name = {"claude": "Claude Code", "codex": "Codex"}.get(result["agent"], result["agent"])
    title = args.title or f"{agent_name} controlling a UR5e robot arm"
    out = pathlib.Path(args.out or run / "demo.mp4")

    m = S.build_model()
    d = mujoco.MjData(m)
    big = mujoco.Renderer(m, MAIN_H, MAIN_W)
    small = mujoco.Renderer(m, SIDE_H, SIDE_W)
    f_title, f_big, f_med, f_small = _font(26, True), _font(20, True), _font(17), _font(14)

    captions = [(e["t"], describe(e)) for e in events]
    captions = [(t, c) for t, c in captions if c]
    timeline = build_timeline(times, qpos, events, args.fps)
    t0 = times[0]

    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-", "-c:v", "libx264",
                           "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out)],
                          stdin=subprocess.PIPE)

    def card(lines, secs):
        img = Image.new("RGB", (W, H), (15, 18, 20))
        dr = ImageDraw.Draw(img)
        y = H // 2 - 30 * len(lines)
        for text, font, col in lines:
            for ln in wrap(text, font, W - 240, dr):
                dr.text((W // 2, y), ln, font=font, fill=col, anchor="mm")
                y += font.size + 14
            y += 10
        for _ in range(int(secs * args.fps)):
            ff.stdin.write(img.tobytes())

    amber, ink, quiet = (242, 162, 58), (232, 234, 235), (139, 147, 153)
    card([(title, _font(40, True), ink),
          ("Task: " + task, f_med, quiet),
          ("Real-time MuJoCo simulation. The agent writes Python to move the arm and sees only the robot's cameras and sensors.", f_small, quiet)], 4)

    for k, t in enumerate(timeline):
        i = min(np.searchsorted(times, t), len(times) - 1)
        d.qpos[:] = qpos[i]
        mujoco.mj_forward(m, d)
        big.update_scene(d, camera="side")
        frame = Image.new("RGB", (W, H), (15, 18, 20))
        frame.paste(Image.fromarray(big.render()), (0, 0))
        for j, (cam, label) in enumerate([("overhead", "ROBOT'S OVERHEAD CAMERA"), ("gripper/wrist", "ROBOT'S WRIST CAMERA")]):
            small.update_scene(d, camera=cam)
            frame.paste(Image.fromarray(small.render()), (MAIN_W, j * SIDE_H))
            ImageDraw.Draw(frame).text((MAIN_W + 8, j * SIDE_H + 6), label, font=f_small, fill=ink,
                                       stroke_width=2, stroke_fill=(0, 0, 0))
        dr = ImageDraw.Draw(frame)
        # Title and clock over the main view.
        dr.rectangle((0, 0, MAIN_W, 46), fill=(15, 18, 20))
        dr.text((16, 10), title, font=f_title, fill=ink)
        idle = k + 1 < len(timeline) and timeline[k + 1] - t > 1.5 / args.fps
        clock = f"{t - t0:5.1f} s"
        dr.text((MAIN_W - 16, 12), clock, font=f_big, fill=ink, anchor="ra")
        if idle:
            dr.text((MAIN_W - 110, 14), f"agent thinking  ▶▶ {IDLE_SPEEDUP:.0f}x", font=f_small, fill=amber, anchor="ra")
        # Task banner along the bottom of the main view.
        dr.rectangle((0, MAIN_H - 40, MAIN_W, MAIN_H), fill=(15, 18, 20))
        dr.text((16, MAIN_H - 30), "Task: " + task, font=f_small, fill=quiet)
        # Agent actions panel.
        x0, y0 = MAIN_W, 2 * SIDE_H
        dr.rectangle((x0, y0, W, H), fill=(23, 27, 30))
        dr.text((x0 + 12, y0 + 10), f"WHAT {agent_name.upper()} IS DOING", font=f_small, fill=amber)
        recent = [(ct, c) for ct, c in captions if ct <= t][-5:]
        y = y0 + 36
        for n, (ct, c) in enumerate(reversed(recent)):
            col = ink if n == 0 else quiet
            for ln in wrap(f"{ct - t0:4.0f}s  {c}", f_small, SIDE_W - 24, dr)[:3]:
                if y > H - 18:
                    break
                dr.text((x0 + 12, y), ln, font=f_small, fill=col)
                y += 18
            y += 6
        ff.stdin.write(frame.tobytes())
        if k % 100 == 0:
            print(f"frame {k}/{len(timeline)}", flush=True)

    stops = result.get("protective_stops", 0)
    card([("Run finished", _font(40, True), ink),
          (f"{agent_name} took {result['wall_seconds']:.0f} s, sent {result['commands']} robot commands, "
           f"{stops} protective stop{'s' if stops != 1 else ''}.", f_med, quiet)], 4)
    ff.stdin.close()
    ff.wait()
    print("saved", out)


if __name__ == "__main__":
    main()
