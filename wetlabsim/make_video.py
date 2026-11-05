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
from . import traces as TR

W, H = 1920, 1080
MAIN_X, MAIN_Y, MAIN_W, MAIN_H = 0, 64, 1024, 768     # room camera
CAM_X, SIDE_W, SIDE_H = 1024, 384, 288                # robot's cameras column
TRACE_X, TRACE_W = 1408, 512                          # agent trace column (far right)
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


def _mono(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/System/Library/Fonts/Menlo.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


KIND_STYLE = {
    "says": ("SAYS", (242, 162, 58), "text"),
    "thinks": ("THINKS", (190, 160, 240), "text"),
    "runs": ("RUNS CODE", (111, 190, 255), "mono"),
    "writes": ("WRITES FILE", (111, 190, 255), "mono"),
    "output": ("OUTPUT", (139, 147, 153), "mono"),
    "looks": ("LOOKS THROUGH", (79, 180, 119), "text"),
    "reads": ("READS", (139, 147, 153), "text"),
    "tool": ("TOOL", (139, 147, 153), "text"),
}


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
    agent_name = {"claude": "Claude Code", "codex": "Codex", "devin": "Devin"}.get(result["agent"], result["agent"])
    title = args.title or f"{agent_name} controlling a UR5e robot arm"
    out = pathlib.Path(args.out or run / "demo.mp4")

    m = S.build_model()
    d = mujoco.MjData(m)
    big = mujoco.Renderer(m, MAIN_H, MAIN_W)
    small = mujoco.Renderer(m, SIDE_H, SIDE_W)
    f_title, f_big, f_med, f_small = _font(26, True), _font(20, True), _font(17), _font(14)

    steps = TR.load_run(run)
    if steps and all(s_.t == 0 for s_ in steps):
        steps = []   # older runs have no timing; leave the panel empty rather than misplace it
    f_mono = _mono(14)

    def draw_trace(dr, shown, agent, t_start):
        x0 = TRACE_X
        dr.rectangle((x0, 0, W, H), fill=(11, 13, 15))
        dr.line((x0, 0, x0, H), fill=(40, 46, 50), width=2)
        dr.text((x0 + 16, 16), f"{agent.upper()} TRACE", font=f_small, fill=amber)
        dr.text((x0 + 16, 36), "what it says, the code it runs, and what comes back", font=f_small, fill=quiet)
        top, bottom, width = 68, H - 16, TRACE_W - 32
        blocks = []
        for st in shown[-40:]:
            label, col, font = KIND_STYLE[st.kind]
            body = st.text
            lines = []
            for raw in body.splitlines() or [""]:
                if font == "mono":
                    lines += [raw[i:i + 58] for i in range(0, max(len(raw), 1), 58)]
                else:
                    lines += wrap(raw, f_small, width, dr) or [""]
            limit = 14 if st.kind in ("runs", "writes") else 6
            if len(lines) > limit:
                lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
            blocks.append((st, label, col, font, lines))
        # Fit from the newest backwards.
        y = bottom
        placed = []
        for st, label, col, font, lines in reversed(blocks):
            h = 22 + len(lines) * 18 + 10
            if y - h < top:
                break
            y -= h
            placed.append((y, st, label, col, font, lines))
        for n, (y, st, label, col, font, lines) in enumerate(placed):
            newest = n == 0
            dr.text((x0 + 16, y), f"{st.t - t_start:4.0f}s  {label}", font=f_small, fill=col if newest else tuple(int(c * 0.7) for c in col))
            yy = y + 22
            if font == "mono":
                dr.rectangle((x0 + 12, yy - 3, W - 12, yy + len(lines) * 18 + 1), fill=(24, 28, 31))
            for ln in lines:
                dr.text((x0 + 18, yy), ln, font=f_mono if font == "mono" else f_small,
                        fill=(225, 228, 230) if newest else (150, 156, 160))
                yy += 18

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
        frame.paste(Image.fromarray(big.render()), (MAIN_X, MAIN_Y))
        dr = ImageDraw.Draw(frame)
        # Title and clock above the room view.
        dr.text((20, 16), title, font=f_title, fill=ink)
        dr.text((MAIN_W - 20, 18), f"{t - t0:5.1f} s", font=f_big, fill=ink, anchor="ra")
        idle = k + 1 < len(timeline) and timeline[k + 1] - t > 1.5 / args.fps
        if idle:
            dr.text((MAIN_W - 120, 21), f"agent thinking  \u25b6\u25b6 {IDLE_SPEEDUP:.0f}x", font=f_small, fill=amber, anchor="ra")
        # Task under the room view.
        y = MAIN_Y + MAIN_H + 16
        dr.text((20, y), "TASK", font=f_small, fill=amber)
        for ln in wrap(task, f_med, MAIN_W - 40, dr)[:3]:
            y += 24
            dr.text((20, y), ln, font=f_med, fill=ink)
        dr.text((20, H - 34), "Room camera for viewers only. The agent sees only the robot's own cameras and sensors.",
                font=f_small, fill=quiet)
        # Robot's cameras column.
        for j, (cam, label) in enumerate([("overhead", "ROBOT'S OVERHEAD CAMERA"), ("gripper/wrist", "ROBOT'S WRIST CAMERA")]):
            small.update_scene(d, camera=cam)
            frame.paste(Image.fromarray(small.render()), (CAM_X, j * SIDE_H))
            dr.text((CAM_X + 8, j * SIDE_H + 6), label, font=f_small, fill=ink, stroke_width=2, stroke_fill=(0, 0, 0))
        # Robot commands under the cameras.
        y0 = 2 * SIDE_H
        dr.rectangle((CAM_X, y0, CAM_X + SIDE_W, H), fill=(19, 23, 26))
        dr.text((CAM_X + 14, y0 + 14), "ROBOT COMMANDS", font=f_small, fill=amber)
        recent = [(ct, c) for ct, c in captions if ct <= t][-9:]
        y = y0 + 42
        for n, (ct, c) in enumerate(reversed(recent)):
            col = ink if n == 0 else quiet
            for ln in wrap(f"{ct - t0:4.0f}s  {c}", f_small, SIDE_W - 28, dr)[:2]:
                if y > H - 22:
                    break
                dr.text((CAM_X + 14, y), ln, font=f_small, fill=col)
                y += 19
            y += 6
        # Agent trace column (far right), newest at the bottom like a terminal.
        draw_trace(dr, [s_ for s_ in steps if s_.t <= t], agent_name, t0)
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
