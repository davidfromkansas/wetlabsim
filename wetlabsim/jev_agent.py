"""Jev (TypeSafe AI's decision model) driving the robot, one move at a time.

Jev doesn't write code or text: it answers typed questions (a Choice, a Score, a Noul, a Box)
about the content it is sent, with a probability for every option and a confidence. So instead of
a coding agent's sandbox, this loop asks Jev, over and over, "here is what you have, what next?",
and carries out the move it picks through the robot client, like any agent's code would.

Each step Jev gets only what the other AIs get: the task, the robot's datasheets, the two
cameras (overhead and wrist) and the robot's own readings. No object positions.

Every answer Jev sends back is printed as a JSON line ({"type": "_jev", ...}) for the run's
transcript and the live chat: the answers with all their probabilities and confidences, the
box it drew, the model that answered, the tokens it read and how long it took.

    python wetlabsim/jev_agent.py <workspace> "<task>" [--model jev-1.14.0]

Needs JEV_API_KEY (or TYPESAFE_API_KEY), WETLAB_ROBOT_URL and WETLAB_ROBOT_TOKEN in the environment.
Run by file path with PYTHONPATH pointing at the agent's robot client (wetlabsim.robot), the only
package it imports from this project.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

import numpy as np

from wetlabsim.robot import Robot, RobotError

API_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
DEFAULT_MODEL = "jev-1.14.0"
PRICE_PER_MTOK = 0.042          # dollars per million input tokens (output is free), Jev 1.14
DOC_CHARS = 80_000               # the datasheets' text, at most: Jev reads at most 32k tokens of state
                                 # plus one question, pictures included
STEP = {"large": 0.05, "small": 0.01}            # metres per move
TURN = math.radians(15)                         # radians per turn
SPEED = 0.15                                    # tool speed, m/s


def emit(kind: str, **kw):
    print(json.dumps({"type": "_jev", "kind": kind, **kw}), flush=True)


# ------------------------------------------------------------------ what Jev reads
def _html_text(path: pathlib.Path) -> str:
    t = path.read_text(errors="ignore")
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", t, flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def _pdf_text(path: pathlib.Path) -> str:
    if not shutil.which("pdftotext"):
        return ""
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", out.stdout)).strip()


def datasheets(workspace: pathlib.Path) -> dict:
    """The robot's documents as text, as they sit in the agent's folder (the same ones the coding
    agents get), shortest first, until DOC_CHARS. Franka's robot manual (about 185,000 characters)
    doesn't fit in Jev's 32k-token window next to the pictures, so it is the one usually left out; what was left out is
    listed in the run's start event."""
    folder = workspace / "datasheets"
    files = sorted(folder.glob("*.html")) + sorted(folder.glob("*.pdf")) if folder.is_dir() else []
    if not files and (workspace / "ROBOT_MANUAL.md").exists():
        files = [workspace / "ROBOT_MANUAL.md"]
    texts = []
    for f in files:
        t = _html_text(f) if f.suffix == ".html" else _pdf_text(f) if f.suffix == ".pdf" else f.read_text()
        if t:
            texts.append((f.name, t))
    texts.sort(key=lambda x: len(x[1]))
    out, used, left = {}, 0, []
    for name, t in texts:
        if used + len(t) <= DOC_CHARS:
            out[name], used = t, used + len(t)
        else:
            left.append(name)
    return {"documents": out, "left_out": left}


def robot_readings(st: dict) -> dict:
    """The robot's own readings, with units, as the controller reports them."""
    p = st["tcp_pose"]
    g = st.get("gripper") or {}
    return {
        "controller_time_s": st["time"],
        "mode": st["mode"] + (f" ({st['protective_stop_reason']})" if st.get("protective_stop_reason") else ""),
        "moving": st["moving"],
        "hand_position_m": {"x_forward": p[0], "y_left": p[1], "z_up": p[2]},
        "hand_rotation_vector_rad": p[3:],
        "joint_angles_rad": st["joint_positions"],
        "wrist_force_N": st["tcp_force"][:3],
        "wrist_torque_Nm": st["tcp_force"][3:],
        "gripper": {"opening_0_open_255_closed": g.get("position"), "moving": g.get("moving"),
                    "holding_something": g.get("object_detected")},
    }


def image_direction(cal: dict, d_base) -> str:
    """Where a base-frame direction points in the overhead picture, in words (from the camera's
    calibration, which the coding agents get as cameras.json)."""
    R = np.array(cal["rotation"])                # base <- camera, OpenCV axes (x right, y down)
    dc = R.T @ np.asarray(d_base, float)
    u, v = dc[0], dc[1]
    if abs(u) < 0.2 * abs(v):
        return "toward the bottom of `overhead`" if v > 0 else "toward the top of `overhead`"
    if abs(v) < 0.2 * abs(u):
        return "toward the right of `overhead`" if u > 0 else "toward the left of `overhead`"
    return ("toward the " + ("bottom" if v > 0 else "top") + "-" + ("right" if u > 0 else "left")
            + " of `overhead`")


def questions(cal: dict | None) -> dict:
    """What Jev is asked each step. Directions are the robot's own (its base frame), with where
    each one points in the overhead picture."""
    where = (lambda d: f" ({image_direction(cal, d)})") if cal else (lambda d: "")
    moves = {
        "forward": f"Move the hand forward, away from the robot's base{where([1, 0, 0])}.",
        "back": f"Move the hand back, toward the robot's base{where([-1, 0, 0])}.",
        "left": f"Move the hand to the robot's left{where([0, 1, 0])}.",
        "right": f"Move the hand to the robot's right{where([0, -1, 0])}.",
        "up": "Move the hand up, away from the table.",
        "down": "Move the hand down, toward the table.",
        "turn_left": "Turn the hand 15 degrees counter-clockwise, seen from above.",
        "turn_right": "Turn the hand 15 degrees clockwise, seen from above.",
        "open_gripper": "Open the fingers fully.",
        "close_gripper": "Close the fingers (they stop on whatever is between them).",
        "clear_protective_stop": "Clear a protective stop so the arm moves again. Only when `robot.mode` says protective_stop.",
        "done": "The task is finished: stop here.",
    }
    return {
        "goal": {"type": "choice",
                 "instructions": "Which part of the task in `task` should the robot be working on right now, "
                                 "judging by `cameras` and `robot`?",
                 "criteria": {
                     "find_object": "Move the hand over the object the task is about.",
                     "line_up": "Line the open fingers up with the object, above it.",
                     "reach_down": "Lower the open fingers around the object.",
                     "grasp": "Close the fingers on the object.",
                     "lift": "Raise the object that is held.",
                     "carry": "Carry the held object to where the task wants it.",
                     "set_down": "Lower the held object onto its place.",
                     "let_go": "Open the fingers to release the object.",
                     "back_away": "Move the hand away after letting go.",
                     "finished": "The task in `task` is complete.",
                 }},
        "move": {"type": "choice",
                 "instructions": "What should the robot do next to carry out `task`, judging by `cameras` "
                                 "and `robot`? `cameras.overhead` looks down on the table from above; "
                                 "`cameras.wrist` looks out from between the fingers.",
                 "criteria": moves},
        "step": {"type": "choice",
                 "instructions": "If the next action moves the hand, how far should it go, judging by `cameras`?",
                 "criteria": {"large": "Far from where it needs to be: a big step (5 cm).",
                              "small": "Close to where it needs to be: a small careful step (1 cm)."}},
        "task_done": {"type": "noul",
                      "instructions": "Is the task in `task` already complete in `cameras.overhead`?"},
        "target": {"type": "box",
                   "instructions": "The object the task in `task` is about, in `cameras.overhead`."},
    }


# ------------------------------------------------------------------ talking to Jev
def ask_jev(key: str, model: str, state: dict, assets: dict, qs: dict, timeout: float = 30) -> tuple[dict, float]:
    body = json.dumps({"model": model, "state": state, "questions": qs, "assets": assets}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "TypeSafe-Danger-Zone-Images": "true", "User-Agent": "wetlabsim-jev"})
    for attempt in range(5):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read()), time.time() - t0
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:800]
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                wait = float(e.headers.get("retry-after") or 0.5 * 2 ** attempt)
                emit("retry", status=e.code, wait_s=wait, error=msg)
                time.sleep(min(wait, 10))
                continue
            raise RuntimeError(f"Jev API error {e.code}: {msg}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise RuntimeError(f"can't reach the Jev API: {e}") from None
    raise RuntimeError("Jev API: too many retries")


# ------------------------------------------------------------------ moving the robot
def _rotvec_to_mat(r):
    r = np.asarray(r, float)
    th = np.linalg.norm(r)
    if th < 1e-12:
        return np.eye(3)
    k = r / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


def _mat_to_rotvec(R):
    c = max(-1.0, min(1.0, (np.trace(R) - 1) / 2))
    th = math.acos(c)
    if th < 1e-9:
        return np.zeros(3)
    if abs(th - math.pi) < 1e-6:
        # 180 degrees: the axis from the diagonal
        k = np.sqrt(np.maximum((np.diag(R) + 1) / 2, 0))
        i = int(np.argmax(k))
        if i == 0:
            k[1], k[2] = np.copysign(k[1], R[0, 1]), np.copysign(k[2], R[0, 2])
        elif i == 1:
            k[0], k[2] = np.copysign(k[0], R[0, 1]), np.copysign(k[2], R[1, 2])
        else:
            k[0], k[1] = np.copysign(k[0], R[0, 2]), np.copysign(k[1], R[1, 2])
        return k / np.linalg.norm(k) * th
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * math.sin(th))
    return w * th


DIRS = {"forward": (1, 0, 0), "back": (-1, 0, 0), "left": (0, 1, 0), "right": (0, -1, 0),
        "up": (0, 0, 1), "down": (0, 0, -1)}


def carry_out(r: Robot, move: str, step: str, st: dict) -> str:
    """Do the move Jev picked. Returns what happened, in a few words."""
    if move in DIRS:
        p = np.array(st["tcp_pose"], float)
        d = STEP.get(step, STEP["small"])
        p[:3] += np.array(DIRS[move]) * d
        r.move_l(p.tolist(), speed=SPEED)
        return f"moved {move} {d * 100:.0f} cm"
    if move in ("turn_left", "turn_right"):
        p = np.array(st["tcp_pose"], float)
        a = TURN if move == "turn_left" else -TURN
        Rz = _rotvec_to_mat([0, 0, a])
        p[3:] = _mat_to_rotvec(Rz @ _rotvec_to_mat(p[3:]))
        r.move_l(p.tolist(), speed=SPEED)
        return f"turned {'counter-clockwise' if a > 0 else 'clockwise'} 15°"
    if move == "open_gripper":
        g = r.gripper_open()
        return f"opened the fingers (now at {g.get('position')})"
    if move == "close_gripper":
        g = r.gripper_close()
        return "closed the fingers" + (" on something" if g.get("object_detected") else " (nothing between them)")
    if move == "clear_protective_stop":
        r.unlock_protective_stop()
        return "cleared the protective stop"
    return "nothing"


# ------------------------------------------------------------------ the loop
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workspace")
    ap.add_argument("task")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-steps", type=int, default=2000)
    args = ap.parse_args(argv)

    key = os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY") or ""
    if not key:
        emit("error", text="No Jev API key on this server (JEV_API_KEY).")
        return 2
    r = Robot()
    workspace = pathlib.Path(args.workspace)
    docs = datasheets(workspace)
    try:
        cal = r._req("GET", "/info").get("camera_calibration", {}).get("overhead")
    except RobotError:
        cal = None
    qs = questions(cal)
    emit("start", model=args.model, questions=qs, datasheets=list(docs["documents"]),
         datasheets_left_out=docs["left_out"], datasheet_chars=sum(len(t) for t in docs["documents"].values()))

    tokens = 0
    for n in range(1, args.max_steps + 1):
        try:
            st = r.get_state()
            pics = {}
            for cam in ("overhead", "wrist"):
                jpg, _ = r._req("GET", f"/camera/{cam}.jpg", raw=True)
                pics[cam] = jpg
        except RobotError as e:
            emit("error", step=n, text=f"couldn't read the robot: {e}")
            return 1
        refs = {cam: f"{cam}-{uuid.uuid4().hex[:12]}" for cam in pics}
        assets = {refs[c]: {"type": "image", "format": "jpg", "data_base64": base64.b64encode(b).decode()}
                  for c, b in pics.items()}
        state = {"task": args.task,
                 "cameras": {"overhead": refs["overhead"], "wrist": refs["wrist"]},
                 "robot": robot_readings(st),
                 "datasheets": docs["documents"]}
        try:
            resp, secs = ask_jev(key, args.model, state, assets, qs)
        except RuntimeError as e:
            emit("error", step=n, text=str(e))
            return 1
        ans = resp.get("answers", {})
        usage = resp.get("usage", {})
        tokens += usage.get("input_tokens", 0)
        move = (ans.get("move") or {}).get("choice", "")
        step = (ans.get("step") or {}).get("choice", "small")
        if move == "done":
            result = "stopped: Jev says the task is finished"
            ok = True
        else:
            try:
                result, ok = carry_out(r, move, step, st), True
            except RobotError as e:
                result, ok = f"the robot refused: {e}", False
        emit("step", step=n, model=resp.get("model"), seconds=round(secs, 3), answers=ans, usage=usage,
             input_tokens_total=tokens, cost_usd=round(tokens * PRICE_PER_MTOK / 1e6, 6),
             camera_time=st["time"], did=result, ok=ok)
        if move == "done":
            emit("done", steps=n)
            return 0
    emit("done", steps=args.max_steps, text="stopped after the most steps allowed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
