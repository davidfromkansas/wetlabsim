"""HTTP server that runs the simulated robot cell.

Start it with:  python -m wetlabsim.server
Then open http://localhost:8765 to watch, and let agents use wetlabsim.robot.Robot.

Robot endpoints mirror what a real UR5e controller, Robotiq gripper and lab
cameras expose. Evaluator endpoints (/eval/...) need the token printed at start
and saved to runs/.eval_token; agents are never given it.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image

from .sim import RobotError, Sim

VIEWER_HTML = (pathlib.Path(__file__).parent / "viewer.html").read_text()


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
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    # ----------------------------------------------------------- helpers
    def _send(self, code, body: bytes, ctype="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

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
                return self._send(200, VIEWER_HTML.encode(), "text/html; charset=utf-8")
            if p == "/state":
                return self._json(self.sim.state())
            if p == "/info":
                return self._json(self.sim_info())
            if p.startswith("/camera/"):
                return self._camera(p[len("/camera/"):], qs)
            if p.startswith("/stream/"):
                return self._stream(p[len("/stream/"):].removesuffix(".mjpg"), qs)
            if p == "/events":
                return self._json(self.sim.events[-200:])
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
        from . import scene as S
        return {
            "robot": "Universal Robots UR5e", "gripper": "Robotiq 2F-85",
            "cameras": list(S.CAMERAS), "joint_names": S.ARM_JOINTS,
            "joint_limits": [self.sim.joint_lo.tolist(), self.sim.joint_hi.tolist()],
            "frames": "all poses are in the robot base frame: x forward over the bench, y left, z up (m)",
        }

    def _camera(self, rest: str, qs):
        name, _, kind = rest.partition(".")
        kind = kind or "png"
        want_depth = kind in ("depth.npy", "rgbd.npz")
        fr = self.sim.render(name, depth=want_depth, priority=0)
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
            if p == "/eval/reset":
                if not self._authed():
                    return self._err("evaluator token required", 403)
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
    args = ap.parse_args(argv)

    runs = pathlib.Path(args.runs).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    tok_file = runs / ".eval_token"
    tok_file.write_text(token)
    os.chmod(tok_file, 0o600)

    sim = Sim()
    sim.open_log(runs / time.strftime("session-%Y%m%d-%H%M%S"))
    sim.start()
    Handler.sim, Handler.token, Handler.runs_dir = sim, token, runs
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"Wet lab robot cell running. Watch it at http://{args.host}:{args.port}")
    print(f"Evaluator token saved to {tok_file}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop_threads()


if __name__ == "__main__":
    main()
