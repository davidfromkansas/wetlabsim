"""HTTP server that runs the simulated robot cell.

Start it with:  python -m wetlabsim.server
Then open http://localhost:8765 to watch, and let agents use wetlabsim.robot.Robot.

Robot endpoints mirror what a real robot controller, its gripper and lab
cameras expose. Evaluator endpoints (/eval/...) need the token printed at start
and saved to runs/.eval_token; agents are never given it.
"""
from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import pathlib
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image

from . import traces
from .sim import RobotError, Sim

VIEWER_PATH = pathlib.Path(__file__).parent / "viewer.html"


class Archive:
    """A finished run, read from its folder, so the viewer can replay it."""

    def __init__(self, run_dir: pathlib.Path):
        self.dir = run_dir
        res = json.loads((run_dir / "result.json").read_text()) if (run_dir / "result.json").exists() else {}
        info = json.loads((run_dir / "run.json").read_text()) if (run_dir / "run.json").exists() else {}
        if not info:   # runs from before run.json existed
            meta = traces.RunMeta(res.get("agent", ""), res.get("model"))
            if (run_dir / "transcript.jsonl").exists():
                for line in (run_dir / "transcript.jsonl").read_text().splitlines():
                    try:
                        meta.feed(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            prompt = res.get("prompt", "")
            if not prompt and (run_dir / "command.json").exists():   # the prompt is an argument of the CLI command
                cmd = json.loads((run_dir / "command.json").read_text())
                prompt = next((a for a in cmd if isinstance(a, str) and "When you are done" in a), "")
            info = {"run_id": run_dir.name, "task": res.get("task", ""), "prompt": prompt,
                    "robot": res.get("robot", "ur5e"), "docs": res.get("docs", "assisted"),
                    "time_limit": 900, "sim_start": res.get("sim_reset", 0.0),
                    "status": res.get("status", ""), "wall_seconds": res.get("wall_seconds"), **meta.info()}
        self.info = info
        self.robot = info.get("robot") or res.get("robot", "ur5e")
        self.trace = [{"t": st.t, "kind": st.kind, "text": st.text[:4000]} for st in traces.load_run(run_dir)]
        self.events = json.loads((run_dir / "events.json").read_text()) if (run_dir / "events.json").exists() else []
        self.states = []
        if (run_dir / "states.jsonl").exists():
            for line in (run_dir / "states.jsonl").read_text().splitlines():
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "joint_positions" in o:
                    o.pop("ground_truth", None)   # the evaluator's knowledge stays out of the viewer
                    self.states.append(o)
        rec = np.load(run_dir / "replay.npz") if (run_dir / "replay.npz").exists() else None
        self.rec_t = rec["time"] if rec is not None else np.zeros(0)
        self.rec_q = rec["qpos"] if rec is not None else np.zeros((0, 0))
        self.workspace = run_dir / "workspace"

    def end_time(self) -> float:
        start = self.info.get("sim_start", 0.0)
        if self.info.get("wall_seconds"):
            return start + float(self.info["wall_seconds"])
        ts = [s["time"] for s in self.states] + list(self.rec_t[-1:])
        return max(ts) if ts else start

    def state_at(self, t):
        if not self.states:
            return None
        import bisect
        i = bisect.bisect_right([s["time"] for s in self.states], t) - 1
        return self.states[max(i, 0)]

    def qpos_at(self, t):
        if not len(self.rec_t):
            return None
        return self.rec_q[max(int(np.searchsorted(self.rec_t, t, side="right")) - 1, 0)]


def _encode_png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _encode_jpg(rgb: np.ndarray, q=80) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=q)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    sim: Sim
    token: str
    runs_dir: pathlib.Path
    trace: list = []          # the current run's agent steps, for the live page
    run: dict = {}            # the current run: task, prompt, model, tokens, ... (from run_agent)
    archives: dict = {}       # finished runs opened in the viewer, by run id
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    # ----------------------------------------------------------- helpers
    def _send(self, code, body: bytes, ctype="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if "Cache-Control" not in (headers or {}):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)).encode())

    def _err(self, msg, code=400):
        self._json({"ok": False, "error": msg}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _authed(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Eval-Token", ""), self.token)

    def _wait(self, motion, wait: bool, timeout: float):
        if not wait:
            return {"ok": True, "result": "started"}
        if not motion.done.wait(timeout):
            return {"ok": False, "result": "timeout waiting for motion (still moving)"}
        ok = motion.result == "done"
        return {"ok": ok, "result": motion.result, "state": self.sim.state()}

    # -------------------------------------------------------------- GET
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        p = url.path.rstrip("/") or "/"
        try:
            if p == "/":
                return self._send(200, VIEWER_PATH.read_bytes(), "text/html; charset=utf-8")
            if p == "/state":
                return self._json(self.sim.state())
            if p == "/info":
                return self._json(self.sim_info())
            if p.startswith("/camera/"):
                return self._camera(p[len("/camera/"):], qs)
            if p.startswith("/stream/"):
                return self._stream(p[len("/stream/"):].removesuffix(".mjpg"), qs)
            if p.startswith("/static/"):
                f = (pathlib.Path(__file__).parent / "static" / pathlib.Path(p).name)
                if f.is_file():
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                                      {"Cache-Control": "max-age=86400"})
                return self._err("not found", 404)
            if p == "/runs":
                return self._json(self._list_runs())
            if p.startswith("/runs/"):
                return self._archive_get(p, qs)
            if p == "/run":
                return self._json({k: v for k, v in self.run.items() if k != "workspace"})
            if p == "/run/files":
                return self._json(self._workspace_files(self._workspace()))
            if p == "/run/file":
                return self._workspace_file(self._workspace(), qs.get("path", [""])[0])
            if p == "/history/state":
                st = self.sim.state_at(float(qs.get("t", ["0"])[0]))
                return self._json(st or self.sim.state())
            if p == "/trace":
                since = int(qs.get("since", ["0"])[0])
                return self._json({"total": len(self.trace), "steps": self.trace[since:since + 200]})
            if p == "/events":
                return self._json(self.sim.events if "all" in qs else self.sim.events[-200:])
            if p == "/eval/ground_truth":
                if not self._authed():
                    return self._err("evaluator token required", 403)
                return self._json(self.sim.ground_truth())
            return self._err("not found", 404)
        except RobotError as e:
            return self._err(str(e))
        except (BrokenPipeError, ConnectionResetError):
            return None

    def sim_info(self):
        P = self.sim.P
        return {
            "robot": P["name"], "gripper": P["gripper"], "robot_id": self.sim.robot,
            "cameras": list(P["cameras"]), "joint_names": P["arm_joints"],
            "joint_limits": [self.sim.joint_lo.tolist(), self.sim.joint_hi.tolist()],
            "camera_calibration": self.sim.calibration(),
            "frames": "all poses are in the robot base frame: x forward over the bench, y left, z up (m)",
        }

    # ------------------------------------------------- the agent's workspace
    def _workspace(self) -> pathlib.Path | None:
        w = self.run.get("workspace")
        return pathlib.Path(w) if w and pathlib.Path(w).is_dir() else None

    def _workspace_files(self, root):
        """The agent's folder as a tree: what it was given plus anything it saved."""
        if root is None:
            return {"files": []}

        def walk(d: pathlib.Path, depth: int):
            out = []
            for f in sorted(d.iterdir(), key=lambda f: (f.is_dir(), f.name.lower())):
                if f.name.startswith(".") or f.name == "__pycache__":
                    continue
                rel = str(f.relative_to(root))
                if f.is_dir():
                    kids = walk(f, depth + 1) if depth < 3 else []
                    n = sum(1 for _ in f.iterdir())
                    out.append({"name": f.name, "path": rel, "dir": True, "items": n, "children": kids})
                else:
                    out.append({"name": f.name, "path": rel, "dir": False, "size": f.stat().st_size,
                                "mtime": f.stat().st_mtime})
            return out
        return {"files": walk(root, 0)}

    def _workspace_file(self, root, rel: str):
        if root is None or not root.is_dir():
            return self._err("no run", 404)
        f = (root / rel).resolve()
        if not str(f).startswith(str(root.resolve()) + os.sep) or not f.is_file():
            return self._err("not found", 404)
        ctype = mimetypes.guess_type(f.name)[0] or "text/plain"
        if ctype.startswith("text/") or f.suffix in (".md", ".py", ".json", ".xml", ".txt"):
            ctype = ("application/json" if f.suffix == ".json" else "text/plain") + "; charset=utf-8"
            if f.suffix == ".html":
                ctype = "text/html; charset=utf-8"
        # Files come from the agent's folder, so show them in a sandbox: no scripts, no access to this site.
        return self._send(200, f.read_bytes(), ctype, {"Content-Security-Policy": "sandbox"})

    # ------------------------------------------------------ finished runs
    def _list_runs(self):
        out = []
        for d in sorted(self.runs_dir.iterdir(), reverse=True):
            if not (d / "result.json").exists():
                continue
            try:
                r = json.loads((d / "result.json").read_text())
            except ValueError:
                continue
            out.append({"run_id": d.name, "task": r.get("task", ""), "agent": r.get("agent"),
                        "model": r.get("model_reported") or r.get("model"), "status": r.get("status"),
                        "wall_seconds": r.get("wall_seconds"), "robot": r.get("robot", "ur5e")})
        return out[:200]

    def _archive(self, run_id: str) -> Archive | None:
        d = (self.runs_dir / run_id).resolve()
        if d.parent != self.runs_dir.resolve() or not (d / "result.json").exists():
            return None
        if run_id not in self.archives:
            Handler.archives[run_id] = Archive(d)
        return self.archives[run_id]

    def _archive_get(self, p: str, qs):
        parts = p.split("/", 3)            # "", "runs", <id>, rest
        a = self._archive(parts[2]) if len(parts) > 2 else None
        if a is None:
            return self._err("no such run", 404)
        rest = "/" + (parts[3] if len(parts) > 3 else "")
        t = float(qs.get("t", ["0"])[0])
        if rest == "/run":
            return self._json({**a.info, "end_time": a.end_time()})
        if rest == "/trace":
            since = int(qs.get("since", ["0"])[0])
            return self._json({"total": len(a.trace), "steps": a.trace[since:since + 200]})
        if rest == "/events":
            return self._json(a.events)
        if rest == "/history/state":
            return self._json(a.state_at(t) or {})
        if rest == "/run/files":
            return self._json(self._workspace_files(a.workspace if a.workspace.is_dir() else None))
        if rest == "/run/file":
            return self._workspace_file(a.workspace, qs.get("path", [""])[0])
        if rest.startswith("/camera/"):
            if a.robot != self.sim.robot:
                return self._err(f"this run used the {a.robot}; start the server with --robot {a.robot} to replay it", 409)
            name = rest[len("/camera/"):].partition(".")[0]
            q = a.qpos_at(t)
            if q is None or len(q) != self.sim.m.nq:
                return self._err("no replay for this run", 404)
            fr = self.sim.render(name, priority=5, qpos=q, at_time=t)
            return self._send(200, _encode_jpg(fr["rgb"]), "image/jpeg", {"Cache-Control": "max-age=3600"})
        return self._err("not found", 404)

    def _camera(self, rest: str, qs):
        name, _, kind = rest.partition(".")
        kind = kind or "png"
        if "t" in qs and kind == "jpg":    # the scene as it was at sim time t (viewer rewind)
            q = self.sim.qpos_at(float(qs["t"][0]))
            if q is not None:
                fr = self.sim.render(name, priority=5, qpos=q, at_time=float(qs["t"][0]))
                return self._send(200, _encode_jpg(fr["rgb"]), "image/jpeg", {"Cache-Control": "max-age=3600"})
        want_depth = kind in ("depth.npy", "rgbd.npz")
        # The viewer page polls frames at low priority so it never delays the agent or shows up
        # in the robot's command log.
        viewer = "viewer" in qs
        fr = self.sim.render(name, depth=want_depth, priority=5 if viewer else 0)
        meta = {"time": fr["time"], "intrinsics": fr["intrinsics"], "pose": fr["pose"]}
        hdr = {"X-Frame-Meta": json.dumps(meta)}
        if kind == "png":
            return self._send(200, _encode_png(fr["rgb"]), "image/png", hdr)
        if kind == "jpg":
            return self._send(200, _encode_jpg(fr["rgb"]), "image/jpeg", hdr)
        if kind == "depth.npy":
            buf = io.BytesIO()
            np.save(buf, fr["depth"])
            return self._send(200, buf.getvalue(), "application/octet-stream", hdr)
        if kind == "rgbd.npz":
            buf = io.BytesIO()
            np.savez(buf, rgb=fr["rgb"], depth=fr["depth"])
            return self._send(200, buf.getvalue(), "application/octet-stream", hdr)
        if kind == "json":
            return self._json(meta)
        return self._err("use .png, .jpg, .depth.npy or .json")

    def _stream(self, name: str, qs):
        fps = float(qs.get("fps", ["8"])[0])
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                t = time.time()
                fr = self.sim.render(name, priority=5)   # agents' frames go first
                jpg = _encode_jpg(fr["rgb"], 70)
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                time.sleep(max(0.0, 1.0 / fps - (time.time() - t)))
        except (BrokenPipeError, ConnectionResetError, RobotError):
            return

    # ------------------------------------------------------------- POST
    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path.rstrip("/")
        try:
            b = self._body()
            s = self.sim
            wait = bool(b.get("wait", True))
            timeout = float(b.get("timeout", 60))
            if p == "/move_l":
                mo = s.move_l(b["pose"], b.get("speed", 0.25))
                return self._json(self._wait(mo, wait, timeout))
            if p == "/move_j":
                mo = s.move_j(b["joints"], b.get("speed", 1.0))
                return self._json(self._wait(mo, wait, timeout))
            if p == "/move_j_pose":
                mo = s.move_j_ik(b["pose"], b.get("speed", 1.0))
                return self._json(self._wait(mo, wait, timeout))
            if p == "/stop":
                s.stop()
                return self._json({"ok": True})
            if p == "/unlock_protective_stop":
                s.unlock()
                return self._json({"ok": True})
            if p == "/zero_ft_sensor":
                s.zero_ft()
                return self._json({"ok": True})
            if p == "/gripper":
                s.gripper_move(b["position"], b.get("speed", 255), b.get("force", 150))
                if wait:
                    t0 = time.time()
                    time.sleep(0.05)
                    while s.gripper_status()["moving"] and time.time() - t0 < 5:
                        time.sleep(0.02)
                return self._json({"ok": True, "gripper": s.gripper_status()})
            if p == "/eval/save_recording":
                if not self._authed():
                    return self._err("evaluator token required", 403)
                n = s.save_recording(b["path"])
                return self._json({"ok": True, "frames": n})
            if p == "/eval/close_log":
                # The run is over: later readings go to a fresh session log, not the run's folder.
                if not self._authed():
                    return self._err("evaluator token required", 403)
                s.open_log(self.runs_dir / time.strftime("session-%Y%m%d-%H%M%S"))
                return self._json({"ok": True})
            if p == "/eval/run":
                if not self._authed():
                    return self._err("evaluator token required", 403)
                Handler.run = {**Handler.run, **b}
                return self._json({"ok": True})
            if p == "/eval/trace":
                if not self._authed():
                    return self._err("evaluator token required", 403)
                Handler.trace.extend(b["steps"])
                return self._json({"ok": True})
            if p == "/eval/reset":
                if not self._authed():
                    return self._err("evaluator token required", 403)
                Handler.trace = []
                Handler.run = {}
                s.reset()
                if b.get("run_dir"):
                    s.open_log(b["run_dir"])
                return self._json({"ok": True})
            return self._err("not found", 404)
        except RobotError as e:
            return self._json({"ok": False, "error": str(e)})
        except (KeyError, ValueError, TypeError) as e:
            return self._err(f"bad request: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the simulated wet lab robot cell")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--runs", default="runs", help="where run logs are written")
    ap.add_argument("--robot", choices=["franka", "ur5e"], default=None,
                    help="robot arm (default: $WETLAB_ROBOT or franka)")
    args = ap.parse_args(argv)

    runs = pathlib.Path(args.runs).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    tok_file = runs / ".eval_token"
    tok_file.write_text(token)
    os.chmod(tok_file, 0o600)

    sim = Sim(robot=args.robot)
    sim.open_log(runs / time.strftime("session-%Y%m%d-%H%M%S"))
    sim.start()
    Handler.sim, Handler.token, Handler.runs_dir = sim, token, runs
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"Wet lab robot cell running with a {sim.P['name']}. Watch it at http://{args.host}:{args.port}")
    print(f"Evaluator token saved to {tok_file}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop_threads()


if __name__ == "__main__":
    main()
