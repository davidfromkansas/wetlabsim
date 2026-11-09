"""The MuJoCo Playground: a local web page to build a scene and let an AI drive the robot.

    python -m playground.server            # then open http://localhost:8780

It serves the robot cell's own endpoints (so wetlabsim.robot.Robot, the MCP tools and
wetlabsim.run_agent work unchanged) plus the playground's page and its /pg/ endpoints:
the main view, the object library, placing and moving things, play and pause, and
starting a run with Claude Code or Codex on the user's own login.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer

from wetlabsim.server import Handler, RunBoard
from wetlabsim.sim import RobotError, RobotView

from . import catalog
from . import libero as LB
from . import site
from .bench import Bench
from . import wetlab as WL
from wetlabsim import tasks as WT
from .sim import PlaygroundSim

HERE = pathlib.Path(__file__).parent
PAGE = HERE / "static" / "index.html"
TIME_LIMIT = 180.0     # seconds: a LIBERO test run that hasn't finished by then is stopped
FREE_TIME_LIMIT = 0.0  # free play: no limit, the run goes until the AI finishes or you stop it

# Every model the agent runner can drive, by the CLI that runs it (for Devin, Cognition's own
# models; Devin's Claude and GPT models are here through Claude Code and Codex). The ids "claude" and "codex"
# are kept from the first two entries so earlier results stay on the scoreboards.
MODELS = [
    {"id": "claude", "label": "Claude Opus 5.5", "via": "Claude Code", "agent": "claude", "model": "opus",
     "provider": "anthropic"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1", "via": "Claude Code", "agent": "claude",
     "model": "claude-fable-5-1", "provider": "anthropic"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "via": "Claude Code", "agent": "claude",
     "model": "claude-sonnet-5-5", "provider": "anthropic"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "via": "Claude Code", "agent": "claude",
     "model": "claude-haiku-5-5", "provider": "anthropic"},
    {"id": "codex", "label": "GPT-6 Astra", "via": "Codex CLI", "agent": "codex", "model": "gpt-6-astra",
     "provider": "openai"},
    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol", "via": "Codex CLI", "agent": "codex", "model": "gpt-6.1-sol",
     "provider": "openai"},
    {"id": "gpt-6.1-terra", "label": "GPT-6.1 Terra", "via": "Codex CLI", "agent": "codex", "model": "gpt-6.1-terra",
     "provider": "openai"},
    {"id": "gpt-6-sol", "label": "GPT-6 Sol", "via": "Codex CLI", "agent": "codex", "model": "gpt-6-sol",
     "provider": "openai"},
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "via": "Codex CLI", "agent": "codex", "model": "gpt-6-luna",
     "provider": "openai"},
    {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol", "via": "Codex CLI", "agent": "codex", "model": "gpt-5.6-sol",
     "provider": "openai"},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "via": "Codex CLI", "agent": "codex", "model": "gpt-5.6-terra",
     "provider": "openai"},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "via": "Codex CLI", "agent": "codex", "model": "gpt-5.6-luna",
     "provider": "openai"},
    {"id": "swe-2-max", "label": "SWE-2 Max", "via": "Devin", "agent": "devin", "model": "swe-2-max",
     "provider": "cognition"},
    {"id": "swe-2-high", "label": "SWE-2 High", "via": "Devin", "agent": "devin", "model": "swe-2-high",
     "provider": "cognition"},
    {"id": "swe-2-medium", "label": "SWE-2 Medium", "via": "Devin", "agent": "devin", "model": "swe-2-medium",
     "provider": "cognition"},
    {"id": "swe-2-max-lightning", "label": "SWE-2 Max Lightning", "via": "Devin", "agent": "devin", "model": "swe-2-max-lightning",
     "provider": "cognition"},
    {"id": "swe-2-high-lightning", "label": "SWE-2 High Lightning", "via": "Devin", "agent": "devin", "model": "swe-2-high-lightning",
     "provider": "cognition"},
    {"id": "swe-2-medium-lightning", "label": "SWE-2 Medium Lightning", "via": "Devin", "agent": "devin", "model": "swe-2-medium-lightning",
     "provider": "cognition"},
    {"id": "swe-2-flash-max", "label": "SWE-2 Flash Max", "via": "Devin", "agent": "devin", "model": "swe-2-flash-max",
     "provider": "cognition"},
    {"id": "swe-2-flash-high", "label": "SWE-2 Flash High", "via": "Devin", "agent": "devin", "model": "swe-2-flash-high",
     "provider": "cognition"},
    {"id": "swe-2-flash-medium", "label": "SWE-2 Flash Medium", "via": "Devin", "agent": "devin", "model": "swe-2-flash-medium",
     "provider": "cognition"},
    {"id": "swe-1-7", "label": "SWE-1.7 Max", "via": "Devin", "agent": "devin", "model": "swe-1-7",
     "provider": "cognition"},
    {"id": "swe-1-7-medium", "label": "SWE-1.7 Medium", "via": "Devin", "agent": "devin", "model": "swe-1-7-medium",
     "provider": "cognition"},
    {"id": "swe-1-6", "label": "SWE-1.6", "via": "Devin", "agent": "devin", "model": "swe-1-6",
     "provider": "cognition"},
    {"id": "swe-1-6-slow", "label": "SWE-1.6 Slow", "via": "Devin", "agent": "devin", "model": "swe-1-6-slow",
     "provider": "cognition"},
    {"id": "adaptive", "label": "Adaptive", "via": "Devin", "agent": "devin", "model": "adaptive",
     "provider": "cognition"},
]


class Runner:
    """One agent run at a time on one robot: wetlabsim.run_agent in its own process, against
    this server (url: that robot's API)."""

    def __init__(self, url: str, runs: pathlib.Path, docs: str = "standard"):
        self.url, self.runs, self.docs = url, runs, docs
        self.board = RunBoard()
        self.proc: subprocess.Popen | None = None
        self.info: dict = {}
        self.lock = threading.Lock()

    def active(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, task: str, model_id: str, site_text: str | None, time_limit: float = TIME_LIMIT,
              extra: list[str] | None = None) -> dict:
        with self.lock:
            if self.active():
                raise RobotError("a run is already going; stop it first")
            mdl = next((m for m in MODELS if m["id"] == model_id), None)
            if mdl is None:
                raise RobotError(f"unknown model {model_id!r}")
            cmd = [sys.executable, "-m", "wetlabsim.run_agent", "--agent", mdl["agent"], "--task", task,
                   "--url", self.url, "--runs", str(self.runs), "--time-limit", str(time_limit),
                   "--docs", self.docs, *(extra or [])]
            if site_text is not None:     # None: the bench's own site sheet (Wet Lab mode)
                sitef = pathlib.Path(tempfile.mkdtemp(prefix="playground-site-")) / "SITE.md"
                sitef.write_text(site_text)
                cmd += ["--site-file", str(sitef)]
            if mdl["model"]:
                cmd += ["--model", mdl["model"]]
            self.runs.mkdir(parents=True, exist_ok=True)
            log = open(self.runs / "playground-runner.log", "a")
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         start_new_session=True, cwd=str(HERE.parent))
            self.info = {"model": mdl, "task": task, "started": time.time(), "time_limit": time_limit,
                         "status": "starting"}
            return self.status()

    def stop(self):
        with self.lock:
            if self.active():
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                self.info["status"] = "stopped"

    def status(self) -> dict:
        if not self.info:
            return {"active": False}
        out = {k: v for k, v in self.info.items()}
        out["active"] = self.active()
        out["elapsed"] = round(time.time() - self.info["started"], 1)
        if not out["active"] and self.proc is not None and out["status"] not in ("stopped",):
            # The runner exits cleanly even when the agent itself failed (it couldn't reach its
            # API, say); the run's own status says so.
            rs = (getattr(self, "board", None) and self.board.run.get("status")) or ""
            out["status"] = ("error" if self.proc.returncode != 0 or rs == "agent_error"
                             else "time_limit" if rs == "time_limit" else "finished")
            out["exit_code"] = self.proc.returncode
        return out


class PGHandler(Handler):
    sim: PlaygroundSim
    runner: Runner              # the scene's one robot (LIBERO, Wet Lab, and the robot cell's own URLs)
    runners: dict = {}          # free play: one per station, by station id
    bench: Bench
    wetbench: WL.WetBench
    base_url = ""

    def _busy(self) -> bool:
        return (self.runner.active() or self.bench.active() or self.wetbench.active()
                or any(r.active() for r in self.runners.values()))

    @classmethod
    def station_runner(cls, uid: str) -> Runner:
        r = cls.runners.get(uid)
        st = cls.sim.station(uid)
        docs = "standard" if st is None or st.robot == "franka" else "assisted"
        if r is None or r.docs != docs and not r.active():
            r = cls.runners[uid] = Runner(f"{cls.base_url}/st/{uid}", cls.runner.runs, docs)
        return r

    def _station_request(self) -> bool:
        """Requests to /st/<station>/...: that station's robot API (and its run), as if it were
        a robot cell of its own."""
        # A kept-alive connection reuses this handler for its next request: drop the last
        # station request's robot so a /pg/ request sees the whole lab again.
        self.__dict__.pop("sim", None)
        self.__dict__.pop("board", None)
        if not self.path.startswith("/st/"):
            return False
        _, _, uid, rest = (self.path.split("/", 3) + [""])[:4]
        sim = PGHandler.sim
        if sim.scene_mode != "free" or uid not in sim.arms:
            self._err("no such station", 404)
            return True
        self.sim = RobotView(sim, sim.arms[uid])
        self.board = self.station_runner(uid).board
        self.path = "/" + rest
        return True

    def _runs_status(self) -> dict:
        return {uid: self.runners[uid].status() for uid in list(self.runners)}

    def _locked(self) -> str:
        if self.sim.scene_mode == "libero":
            return "LIBERO scenes are fixed: switch to Free play to build your own"
        if self.sim.scene_mode == "wetlab":
            return "the wet lab bench is fixed for a fair test: switch to Free play to build your own"
        if self.runner.active() or any(r.active() for r in self.runners.values()):
            return "the scene is locked while an AI is running; stop the run to edit"
        if not self.sim.paused:
            return "the scene is locked while playing; pause to edit"
        return ""

    def do_GET(self):
        if self._station_request():
            if self.path.startswith("/pg/"):
                return self._err("not found", 404)
            return Handler.do_GET(self)
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        p = url.path.rstrip("/") or "/"
        try:
            if p in ("/", "/playground"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if p == "/viewer":
                from wetlabsim.server import VIEWER_PATH
                return self._send(200, VIEWER_PATH.read_bytes(), "text/html; charset=utf-8")
            if p.startswith("/pg/static/"):
                f = HERE / "static" / pathlib.Path(p).name
                if f.is_file():
                    import mimetypes
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                                      {"Cache-Control": "max-age=3600"})
                return self._err("not found", 404)
            if p == "/pg/catalog":
                return self._json({"tabs": catalog.TABS, "items": catalog.available(), "robots": catalog.robots(),
                                   "models": [{k: m[k] for k in ("id", "label", "via", "provider")} for m in MODELS],
                                   "time_limit": TIME_LIMIT})
            if p.startswith("/pg/thumb/"):
                f = catalog.ASSETS / pathlib.Path(p).stem / "thumb.png"
                if f.is_file():
                    return self._send(200, f.read_bytes(), "image/png", {"Cache-Control": "max-age=86400"})
                return self._err("not found", 404)
            if p == "/pg/scene":
                info = self.sim.scene_info()
                runs = self._runs_status() if info["mode"] == "free" else {}
                run = runs.get(info["active"], {"active": False}) if info["mode"] == "free" else self.runner.status()
                return self._json({**info, "run": run, "runs": runs, "locked": self._locked(),
                                   "bench": self.bench.status(), "wetbench": self.wetbench.status()})
            if p == "/pg/wetlab":
                return self._json({"tasks": [{"id": t.id, "title": t.title, "prompt": t.prompt,
                                              "needs_answer": t.needs_answer} for t in WT.TASKS.values()],
                                   "task": self.sim.wetlab_task, "time_limit": WL.TIME_LIMIT,
                                   "scores": self.wetbench.scoreboard()})
            if p == "/pg/libero":
                cur = self.sim.libero_task.id if self.sim.libero_task else None
                suites = [{"id": k, "name": n, "blurb": bl,
                           "tasks": [{"id": t.id, "index": t.index, "language": t.language,
                                      "goal": [list(g) for g in t.goal], "done_when": LB.done_when(t),
                                      "setups": len(t.states)} for t in LB.tasks(k)]}
                          for k, n, bl in LB.SUITES]
                study = qs.get("study", ["1"])[0] != "0"
                return self._json({"suites": suites, "task": cur, "setup": self.sim.setup,
                                   "suite": self.sim.libero_task.suite if self.sim.libero_task else None,
                                   "study_setups": LB.STUDY_SETUPS,
                                   "scores": self.bench.scoreboard(qs.get("task", [cur])[0]),
                                   "suite_board": self.bench.suite_board(study)})
            if p == "/pg/view.mjpg":
                return self._view_stream()
            if p == "/pg/view.jpg":
                _, jpg = self.sim.latest_frame(int(qs.get("after", ["0"])[0]), 2.0)
                return self._send(200, jpg, "image/jpeg")
            return super().do_GET()
        except RobotError as e:
            return self._err(str(e))
        except (BrokenPipeError, ConnectionResetError):
            return None

    def _view_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seq = 0
        try:
            while True:
                seq, jpg = self.sim.latest_frame(seq, 1.0)
                if not jpg:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        if self._station_request():
            if self.path.startswith("/pg/"):
                return self._err("not found", 404)
            return Handler.do_POST(self)
        p = urllib.parse.urlparse(self.path).path.rstrip("/")
        if not p.startswith("/pg/"):
            return super().do_POST()
        try:
            b = self._body()
            s = self.sim
            if p == "/pg/camera":
                s.orbit(float(b.get("azimuth", 0)), float(b.get("elevation", 0)), float(b.get("zoom", 1.0)),
                        tuple(b.get("pan", (0.0, 0.0))))
                if "move" in b:
                    k = 0.05 * s.view.distance       # one step: about a grid square at the usual distance
                    s.move_camera(*(float(v) * k for v in b["move"]))
                if "aspect" in b:
                    s.set_view_aspect(float(b["aspect"]))
                if "preset" in b:
                    self._camera_preset(b["preset"])
                return self._json({"ok": True})
            if p == "/pg/probe":
                lock = self._locked()
                if lock:
                    return self._json({"valid": False, "reason": lock})
                return self._json(s.probe(b["item"], float(b["u"]), float(b["v"]), float(b.get("yaw", 0.0)),
                                          b.get("uid")))
            if p == "/pg/ghost/clear":
                s.clear_ghost()
                return self._json({"ok": True})
            if p == "/pg/pick":
                out = s.pick(float(b["u"]), float(b["v"]))
                s.selected = out.get("uid") if out["kind"] == "object" else None
                if out.get("station") and s.scene_mode == "free" and out["station"] != s.active_station:
                    s.active_station = out["station"]
                    s.frame_station()
                return self._json(out)
            if p == "/pg/select":
                s.selected = b.get("uid") if b.get("uid") not in (None, "robot") else None
                return self._json({"ok": True})
            if p == "/pg/station/select":
                if s.station(b["uid"]) is None:
                    return self._json({"ok": False, "error": "no such station"})
                s.active_station = b["uid"]
                s.selected = None
                if b.get("frame", True):
                    s.frame_station()
                return self._json({"ok": True})
            if p == "/pg/station/probe":
                lock = self._locked()
                if lock:
                    s.clear_ghost()
                    return self._json({"valid": False, "reason": lock})
                return self._json(s.probe_station(float(b["u"]), float(b["v"]), float(b.get("yaw", 0.0)), b.get("uid")))
            lock = self._locked()
            if (p in ("/pg/place", "/pg/move", "/pg/remove", "/pg/rotate", "/pg/clear") or p.startswith("/pg/station/")) and lock:
                if p != "/pg/station/rename":
                    return self._json({"ok": False, "error": lock})
            if p == "/pg/station/add":
                spot = s.probe_station(float(b["u"]), float(b["v"]), float(b.get("yaw", 0.0)))
                s.clear_ghost()
                if not spot.get("valid"):
                    return self._json({"ok": False, "error": spot.get("reason") or "can't go there"})
                uid = s.add_station(b.get("robot", "franka"), spot["pos"], float(b.get("yaw", 0.0)))
                s.frame_station(uid)
                return self._json({"ok": True, "uid": uid})
            if p == "/pg/station/move":
                st = s.station(b["uid"])
                if st is None:
                    return self._json({"ok": False, "error": "no such station"})
                yaw = float(b.get("yaw", st.yaw))
                if "u" in b:
                    spot = s.probe_station(float(b["u"]), float(b["v"]), yaw, st.uid)
                else:
                    spot = s.station_spot(st.pos[0], st.pos[1], yaw, st.uid)
                s.clear_ghost()
                if not spot.get("valid"):
                    return self._json({"ok": False, "error": spot.get("reason") or "can't go there"})
                s.move_station(st.uid, spot["pos"], yaw)
                return self._json({"ok": True})
            if p == "/pg/station/rotate":
                st = s.station(b["uid"])
                if st is None:
                    return self._json({"ok": False, "error": "no such station"})
                import math
                yaw = st.yaw + math.radians(float(b.get("degrees", 90)))
                spot = s.station_spot(st.pos[0], st.pos[1], yaw, st.uid)
                if not spot.get("valid"):
                    return self._json({"ok": False, "error": spot.get("reason") or "no room to turn it"})
                s.move_station(st.uid, st.pos, yaw)
                return self._json({"ok": True})
            if p == "/pg/station/remove":
                s.remove_station(b["uid"])
                self.runners.pop(b["uid"], None)
                return self._json({"ok": True})
            if p == "/pg/station/rename":
                s.rename_station(b["uid"], b.get("name", ""))
                return self._json({"ok": True})
            if p == "/pg/place":
                spot = b.get("spot") or s.probe(b["item"], float(b["u"]), float(b["v"]), float(b.get("yaw", 0.0)))
                s.clear_ghost()
                if not spot.get("valid"):
                    return self._json({"ok": False, "error": spot.get("reason") or "can't go there"})
                uid = s.add(b["item"], spot["pos"], float(b.get("yaw", 0.0)))
                s.selected = uid
                return self._json({"ok": True, "uid": uid, "spot": spot})
            if p == "/pg/move":
                spot = s.probe(s.find(b["uid"]).item, float(b["u"]), float(b["v"]), float(b.get("yaw", 0.0)), b["uid"])
                s.clear_ghost()
                if not spot.get("valid"):
                    return self._json({"ok": False, "error": spot.get("reason") or "can't go there"})
                s.move(b["uid"], spot["pos"], float(b.get("yaw", 0.0)) if "yaw" in b else None)
                return self._json({"ok": True, "spot": spot})
            if p == "/pg/rotate":
                pl = s.find(b["uid"])
                if pl is None:
                    return self._err("no such object", 404)
                import math
                s.move(pl.uid, pl.pos, pl.yaw + math.radians(float(b.get("degrees", 90))))
                return self._json({"ok": True})
            if p == "/pg/remove":
                s.remove(b["uid"])
                return self._json({"ok": True})
            if p == "/pg/clear":
                s.clear()
                return self._json({"ok": True})
            if p == "/pg/mode":
                if self._busy():
                    return self._json({"ok": False, "error": "stop the run first"})
                if b.get("mode") == "libero":
                    s.set_libero(b.get("task") or LB.tasks()[0].id, int(b.get("setup", 0)))
                elif b.get("mode") == "wetlab":
                    s.set_wetlab(b.get("task") or s.wetlab_task or WL.ORDER[0])
                else:
                    s.set_free()
                s._glide = None
                self._camera_preset("home")
                return self._json({"ok": True})
            if p == "/pg/wetlab/task":
                if self._busy():
                    return self._json({"ok": False, "error": "stop the run first"})
                s.set_wetlab(b["task"])
                return self._json({"ok": True})
            if p == "/pg/wetlab/run":
                if s.scene_mode != "wetlab":
                    return self._json({"ok": False, "error": "switch to Wet Lab first"})
                ids = list(WL.ORDER) if b.get("all") else [s.wetlab_task]
                try:
                    self.wetbench.start(b.get("model", "claude"), ids, float(b.get("time_limit", WL.TIME_LIMIT)))
                except RuntimeError as e:
                    return self._json({"ok": False, "error": str(e)})
                return self._json({"ok": True})
            if p == "/pg/wetlab/stop":
                self.wetbench.stop()
                return self._json({"ok": True})
            if p == "/pg/libero/setup":
                if self._busy():
                    return self._json({"ok": False, "error": "stop the run first"})
                s.set_libero(b.get("task") or s.libero_task.id, int(b.get("setup", 0)))
                return self._json({"ok": True})
            if p == "/pg/libero/run":
                if s.scene_mode != "libero":
                    return self._json({"ok": False, "error": "load a LIBERO task first"})
                t = s.libero_task
                if b.get("study"):
                    # The study set: setups 1-5 of every task in the chosen suites (all four by default).
                    chosen = b.get("suites") or [k for k, _, _ in LB.SUITES]
                    jobs = [(x.id, k) for suite in chosen for x in LB.tasks(suite) for k in range(LB.STUDY_SETUPS)]
                elif b.get("all"):
                    jobs = [(t.id, k) for k in range(len(t.states))]
                else:
                    jobs = [(t.id, s.setup)]
                try:
                    self.bench.start(b.get("model", "claude"), jobs, float(b.get("time_limit", TIME_LIMIT)))
                except RuntimeError as e:
                    return self._json({"ok": False, "error": str(e)})
                return self._json({"ok": True})
            if p == "/pg/libero/stop":
                self.bench.stop()
                return self._json({"ok": True})
            if p == "/pg/play":
                task = (b.get("task") or "").strip()
                if s.scene_mode == "libero" and task:
                    return self._json({"ok": False, "error": "in LIBERO mode, use Run this setup"})
                if s.scene_mode == "wetlab" and task:
                    return self._json({"ok": False, "error": "in Wet Lab mode, use Run this task"})
                if task:
                    uid = b.get("station") or s.active_station
                    station = s.station(uid)
                    if station is None:
                        return self._json({"ok": False, "error": "no such station"})
                    runner = self.station_runner(uid)
                    if runner.active():
                        return self._json({"ok": False, "error": f"{station.name} is already running a task"})
                    s.selected = None
                    s.play()
                    st = runner.start(task, b.get("model", "claude"), site.site_sheet(s.placed, station, s.stations),
                                      float(b.get("time_limit", FREE_TIME_LIMIT)))
                    return self._json({"ok": True, "run": st})
                s.play()
                return self._json({"ok": True})
            if p == "/pg/pause":
                s.pause()
                return self._json({"ok": True})
            if p == "/pg/stop":
                if b.get("station"):          # one station's run
                    r = self.runners.get(b["station"])
                    if r:
                        r.stop()
                    return self._json({"ok": True})
                self.bench.stop()
                self.wetbench.stop()
                self.runner.stop()
                for r in self.runners.values():
                    r.stop()
                return self._json({"ok": True})
            if p == "/pg/reset":
                if self._busy():
                    return self._json({"ok": False, "error": "stop the run first"})
                s.reset()
                s.pause()
                return self._json({"ok": True})
            return self._err("not found", 404)
        except RobotError as e:
            return self._json({"ok": False, "error": str(e)})
        except (KeyError, ValueError, TypeError) as e:
            return self._err(f"bad request: {e}")

    def _camera_preset(self, name):
        s = self.sim
        free = s.scene_mode == "free"
        st = s.station() if free else None
        import math
        yaw = math.degrees(st.yaw) if st else 0.0
        if name == "lab" and free:
            return s.frame_lab()
        if name == "top":
            cx, cy = st.pos if st else (0.0, 0.0)
            s._set_view({"lookat": [cx, cy, 0.9], "distance": 2.6, "azimuth": (180.0 + yaw) % 360,
                         "elevation": -89.0}, free)
        elif name == "robot":
            bp = s.d.xpos[s.arm_of(s.active_station if free else None).base_body]
            c, sn = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            s._set_view({"lookat": [bp[0] + 0.35 * c, bp[1] + 0.35 * sn, bp[2] + 0.1], "distance": 1.6,
                         "azimuth": (160.0 + yaw) % 360, "elevation": -30.0}, free)
        elif free:
            s.frame_station()
        else:
            s._set_view({"lookat": [0.0, 0.0, 0.85], "distance": 2.8, "azimuth": 145.0, "elevation": -28.0}, False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="MuJoCo Playground")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--runs", default="runs/playground")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    runs = pathlib.Path(args.runs).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    tok_file = runs / ".eval_token"
    token = tok_file.read_text().strip() if tok_file.exists() else ""
    if not token:
        token = secrets.token_hex(16)
        tok_file.write_text(token)
    os.chmod(tok_file, 0o600)
    from .tools import fetch_libero as fetch_assets
    if fetch_assets.missing():    # LIBERO's objects, one time (~200 MB), while free play loads
        print("Downloading LIBERO's objects in the background (one time, about 200 MB)...")
        threading.Thread(target=lambda: fetch_assets.ensure(), daemon=True).start()
    print("Loading the scene...")
    sim = PlaygroundSim()
    sim.open_log(runs / time.strftime("session-%Y%m%d-%H%M%S"))
    sim.start()
    url = f"http://{args.host}:{args.port}"
    PGHandler.sim, PGHandler.token, PGHandler.runs_dir = sim, token, runs
    PGHandler.runner = Runner(url, runs)
    PGHandler.base_url = url
    PGHandler.board = PGHandler.runner.board
    PGHandler.bench = Bench(sim, PGHandler.runner, PGHandler, runs / "libero_results.jsonl")
    PGHandler.wetbench = WL.WetBench(sim, PGHandler.runner, PGHandler, runs / "wetlab_results.jsonl")
    srv = ThreadingHTTPServer((args.host, args.port), PGHandler)
    srv.daemon_threads = True
    print(f"MuJoCo Playground is running at {url}")
    if not args.no_browser:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PGHandler.runner.stop()
        for r in PGHandler.runners.values():
            r.stop()
        sim.stop_threads()


if __name__ == "__main__":
    main()
