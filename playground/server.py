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
import re
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
from wetlabsim import robot_api as RA
from . import labs as LABS
from . import savestore as SAVE
from . import scene3d as S3

HERE = pathlib.Path(__file__).parent
PAGE = HERE / "static" / "index.html"
ROBOT_API_URL = ""      # set when the robot API listener is running (main)
TIME_LIMIT = 180.0     # seconds: a LIBERO test run that hasn't finished by then is stopped
# The public site (main --public): Claude (and Devin, with an org key) only, free play only,
# every run capped, the AI in a cloud sandbox, a few runs at once with a queue.
PUBLIC = False
FRONT = False               # the public site's front: hands out labs, lists live runs and past runs
MAX_ACTIVE = 4              # runs at once on the public site; more wait in a queue
RUN_LAUNCHER = "local"      # where agents run (wetlabsim.launchers)
AGENT_ROBOT_URL = ""        # the robot API as agents outside this machine reach it ("" = ROBOT_API_URL)
FREE_TIME_LIMIT = 0.0  # free play: no limit, the run goes until the AI finishes or you stop it

# Every model the agent runner can drive, by the CLI that runs it (for Devin, Cognition's own
# models; Devin's Claude and GPT models are here through Claude Code and Codex).
# "needs": a plan this machine's account doesn't have (checked 2026-11-09: Devin Free runs only
# SWE-2 Flash Medium and SWE-1.6 Slow). Devin would quietly run its default model instead, so
# these are shown but can't be started. The ids "claude" and "codex"
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
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-high", "label": "SWE-2 High", "via": "Devin", "agent": "devin", "model": "swe-2-high",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-medium", "label": "SWE-2 Medium", "via": "Devin", "agent": "devin", "model": "swe-2-medium",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-max-lightning", "label": "SWE-2 Max Lightning", "via": "Devin", "agent": "devin", "model": "swe-2-max-lightning",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-high-lightning", "label": "SWE-2 High Lightning", "via": "Devin", "agent": "devin", "model": "swe-2-high-lightning",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-medium-lightning", "label": "SWE-2 Medium Lightning", "via": "Devin", "agent": "devin", "model": "swe-2-medium-lightning",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-flash-max", "label": "SWE-2 Flash Max", "via": "Devin", "agent": "devin", "model": "swe-2-flash-max",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-flash-high", "label": "SWE-2 Flash High", "via": "Devin", "agent": "devin", "model": "swe-2-flash-high",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-2-flash-medium", "label": "SWE-2 Flash Medium", "via": "Devin", "agent": "devin", "model": "swe-2-flash-medium",
     "provider": "cognition"},
    {"id": "swe-1-7", "label": "SWE-1.7 Max", "via": "Devin", "agent": "devin", "model": "swe-1-7",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-1-7-medium", "label": "SWE-1.7 Medium", "via": "Devin", "agent": "devin", "model": "swe-1-7-medium",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-1-6", "label": "SWE-1.6", "via": "Devin", "agent": "devin", "model": "swe-1-6",
     "provider": "cognition",
     "needs": "Devin Pro"},
    {"id": "swe-1-6-slow", "label": "SWE-1.6 Slow", "via": "Devin", "agent": "devin", "model": "swe-1-6-slow",
     "provider": "cognition"},
    {"id": "adaptive", "label": "Adaptive", "via": "Devin", "agent": "devin", "model": "adaptive",
     "provider": "cognition",
     "needs": "Devin Pro"},
]
# A Devin organization's API key (a service user's, in DEVIN_API_KEY) runs every Devin model.
# Without one, Devin runs as this machine's own login, with that plan's limits ("needs").
DEVIN_ORG = bool(os.environ.get("DEVIN_API_KEY"))


def _needs(m: dict) -> str:
    return "" if m["agent"] == "devin" and DEVIN_ORG else m.get("needs", "")


def _site_agents() -> set:
    """The agents the public site runs: Claude, and Devin once its organization key is set."""
    return {"claude"} | ({"devin"} if DEVIN_ORG else set())


class Runner:
    """One agent run at a time on one robot: wetlabsim.run_agent in its own process, against
    this server (url: that robot's API)."""

    def __init__(self, url: str, runs: pathlib.Path, docs: str = "standard"):
        self.url, self.runs, self.docs = url, runs, docs
        self.board = RunBoard()
        self.proc: subprocess.Popen | None = None
        self.info: dict = {}
        self.lock = threading.Lock()
        self.on_done = None        # called with this runner once a run's process has ended

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
            if _needs(mdl):
                raise RobotError(f"{mdl['label']} needs {_needs(mdl)} on this machine's account")
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
            self.log_from = log.tell()          # this run's part of the shared log starts here
            env = dict(os.environ)
            if ROBOT_API_URL:
                # The agent gets the robot API and a token for this robot, for this run only.
                self.token = RA.TOKENS.issue(urllib.parse.urlparse(self.url).path, run=task[:60])
                env["WETLAB_ROBOT_TOKEN"] = self.token
                cmd += ["--robot-url", AGENT_ROBOT_URL or ROBOT_API_URL, "--launcher", RUN_LAUNCHER]
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         start_new_session=True, cwd=str(HERE.parent), env=env)
            proc, tok = self.proc, getattr(self, "token", None)
            slot = getattr(self, "slot", None)
            def _ended():
                proc.wait()
                RA.TOKENS.revoke(tok)
                LABS.free_slot(slot)
                if self.on_done:
                    try:
                        self.on_done(self)
                    except Exception as e:  # noqa: BLE001
                        print("could not record the run:", e)
            threading.Thread(target=_ended, daemon=True).start()
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
            RA.TOKENS.revoke(getattr(self, "token", None))

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
            if out["status"] == "error":
                out["error_text"] = self.error_text()
        return out

    def error_text(self) -> str:
        """Why a run failed, in the runner's or the agent's own words: the agent's last error
        message if it reported one, else the end of what the runner printed."""
        run_id = self.board.run.get("run_id") if getattr(self, "board", None) else None
        tr = self.runs / run_id / "transcript.jsonl" if run_id else None
        if tr and tr.exists():
            for line in reversed(tr.read_text(errors="ignore").splitlines()[-200:]):
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = (o.get("is_error") and o.get("result")) or (o.get("type") == "error" and o.get("message")) \
                    or (isinstance(o.get("error"), str) and o["error"]) \
                    or (isinstance(o.get("error"), dict) and o["error"].get("message"))
                if msg:
                    return str(msg)[:600]
        try:
            with open(self.runs / "playground-runner.log", errors="ignore") as f:
                f.seek(getattr(self, "log_from", 0))
                lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        except OSError:
            return ""
        lines = [l for l in lines if not l.startswith(("Make a video", "Run ", "Done in "))]
        return "\n".join(lines[-6:])[:600]


def _runs_page(runs: list[dict], runs_dir: pathlib.Path) -> str:
    """Every finished run, newest first, each opening the replay viewer (chat, files, rewind)."""
    import html
    rows = []
    for r in runs:
        try:
            res = json.loads((runs_dir / r["run_id"] / "result.json").read_text())
        except (OSError, ValueError):
            res = {}
        cost = res.get("cost_usd")
        when = r["run_id"][:8]
        when = f"{when[:4]}-{when[4:6]}-{when[6:8]} {r['run_id'][9:11]}:{r['run_id'][11:13]}"
        rows.append(
            f'<tr><td><a href="/viewer?run={html.escape(r["run_id"])}">{html.escape((r["task"] or "")[:140])}</a></td>'
            f'<td>{html.escape(str(r.get("model") or ""))}</td><td>{html.escape(str(r.get("status") or ""))}</td>'
            f'<td class="n">{r.get("wall_seconds") or "–"}</td><td class="n">{"–" if cost is None else f"${cost:.2f}"}</td>'
            f'<td class="n">{when} UTC</td></tr>')
    body = "".join(rows) or '<tr><td colspan="6" class="empty">No finished runs yet.</td></tr>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Past runs · MuJoCo Playground</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>body{{margin:0;background:#F6F7F9;color:#1F2937;font:14px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}}h1{{font-size:20px;margin:0 0 4px;color:#111827}}
p{{margin:0 0 16px;color:#4B5563}}a{{color:#1D4ED8}}.wrap{{overflow-x:auto;background:#fff;border:1px solid #E5E7EB;border-radius:10px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#4B5563;padding:10px 12px;border-bottom:1px solid #E5E7EB}}
td{{padding:9px 12px;border-bottom:1px solid #EEF0F3;vertical-align:top}}td.n,th.n{{text-align:right;white-space:nowrap}}.empty{{color:#4B5563}}</style></head>
<body><main><h1>Past runs</h1><p><a href="/">← Back to the Playground</a> · Every run is public: open one to watch its replay, read the AI's chat and look at its files.</p>
<div class="wrap"><table><thead><tr><th>Task</th><th>Model</th><th>Result</th><th class="n">Seconds</th><th class="n">Cost</th><th class="n">Started</th></tr></thead>
<tbody>{body}</tbody></table></div></main></body></html>"""


# ------------------------------------------------------------------ sessions
# A session is one lab of its own: its own world (PlaygroundSim), stations, runs and chat. One
# server keeps several. Each belongs to the browser that made it (a random id the page keeps in
# localStorage, sent as X-Browser-Id; no sign-in): anyone can watch a session, only its owner
# can change it. On the public site a visitor's sessions all live in their own lab.
MAX_SESSIONS = 12           # worlds this server keeps at once (each is a full simulator)
SID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")


class Session:
    def __init__(self, sid: str, name: str, owner: str, sim: PlaygroundSim, base_url: str, runs: pathlib.Path):
        self.id, self.name, self.owner = sid, name, owner
        self.created = self.used = time.time()
        self.db_id: str | None = None          # its row in the website's database (signed-in owner)
        self.unsent: dict = {}                  # station -> {"task", "model"}: typed but not run yet
        self.sim = sim
        self.base_url, self.runs = base_url, runs
        self.runner = Runner(f"{base_url}/s/{sid}", runs)      # LIBERO, Wet Lab: the scene's one robot
        self.board = self.runner.board
        self.runners: dict[str, Runner] = {}                     # free play: one per station
        self.bench = Bench(sim, self.runner, self, runs / "libero_results.jsonl")
        self.wetbench = WL.WetBench(sim, self.runner, self, runs / "wetlab_results.jsonl")

    def station_runner(self, uid: str) -> Runner:
        r = self.runners.get(uid)
        st = self.sim.station(uid)
        docs = "standard" if st is None or st.robot == "franka" else "assisted"
        if r is None or r.docs != docs and not r.active():
            r = self.runners[uid] = Runner(f"{self.base_url}/s/{self.id}/st/{uid}", self.runs, docs)
            r.on_done = lambda runner, uid=uid: self.record_run(uid, runner)
        return r

    def record_run(self, uid: str, runner: "Runner"):
        """A finished run, into the website's database: its runs row (which robot, starter kit,
        model, task, outcome, cost) and a run_files row per file the agent wrote or changed."""
        if not (SAVE.enabled() and self.db_id):
            return
        run_id = runner.board.run.get("run_id")
        if not run_id:
            return
        run_dir = runner.runs / run_id
        def read(name):
            try:
                return json.loads((run_dir / name).read_text())
            except (OSError, ValueError):
                return {}
        start, result, st, mdl = read("workspace_start.json"), read("result.json"), runner.status(), runner.info.get("model") or {}
        station = self.sim.station(uid)
        files = SAVE.ai_files(run_dir)
        folder = SAVE.upload_run(run_dir, run_id, files)      # into private Blob, through the website
        SAVE.record_run({"run_id": run_id, "session_id": self.db_id, "robot_station_id": uid,
                         "robot_type": start.get("robot_type") or (station.robot if station else None),
                         "robot_kit_version": start.get("robot_kit_version"), "started_by_user_id": SAVE.OWNER_USER,
                         "ai_provider": mdl.get("agent"), "ai_model": mdl.get("model") or mdl.get("id"),
                         "task_prompt": runner.info.get("task"), "run_outcome": st.get("status"),
                         "started_at": runner.info.get("started"), "ended_at": time.time(),
                         "cost_usd": result.get("cost_usd"), "blob_folder_path": folder})
        SAVE.record_files(run_id, files)

    def active(self) -> bool:
        return (self.runner.active() or self.bench.active() or self.wetbench.active()
                or any(r.active() for r in self.runners.values())
                or any(q["session"] == self.id for q in QUEUE))

    def status(self) -> str:
        """working (an AI is running), finished (a run has ended) or empty (nothing run yet)."""
        if self.active():
            return "working"
        if self.runner.info or any(r.info for r in self.runners.values()):
            return "finished"
        return "empty"

    def summary(self) -> dict:
        n = len(self.sim.stations) if self.sim.scene_mode == "free" else 1
        task = next((r.info.get("task", "") for r in self.runners.values() if r.active()), "") or \
            (self.runner.info.get("task", "") if self.runner.active() else "")
        return {"id": self.id, "name": self.name, "stations": n, "used": self.used, "created": self.created,
                "status": self.status(), "mode": self.sim.scene_mode, "task": task[:200]}

    def layout(self) -> dict:
        """The lab as built (stations and objects where they are now), for "Copy to my sessions"."""
        s = self.sim
        with s.lock:
            if s.scene_mode == "free":
                s._sync_placed()
            return {"name": self.name,
                    "stations": [{"uid": st.uid, "robot": st.robot, "pos": list(st.pos), "yaw": st.yaw, "name": st.name}
                                 for st in s.stations],
                    "objects": [{"uid": o.uid, "item": o.item, "pos": list(o.pos), "yaw": o.yaw,
                                 "quat": list(o.quat) if o.quat is not None else None} for o in s.placed]}

    def stop(self):
        with QUEUE_LOCK:
            QUEUE[:] = [q for q in QUEUE if q["session"] != self.id]
        self.bench.stop()
        self.wetbench.stop()
        self.runner.stop()
        for r in self.runners.values():
            r.stop()


SESSIONS: dict[str, Session] = {}
SESSIONS_LOCK = threading.Lock()
ACCOUNT_OWNER = "account-owner"     # a signed-in account's lab: its owner, on any browser
SAVED_AT_START = 4                  # saved sessions a lab opens with; older ones open on request


def _snapshot(sess: Session):
    """What autosave keeps of a session: (db id, name, layout, unsent tasks)."""
    layout = sess.layout()
    layout.pop("name", None)
    return sess.db_id, sess.name, layout, sess.unsent


def open_saved(db_id: str) -> Session | None:
    """A saved session of the owner's, open in this lab (loaded from the database if needed)."""
    for x in list(SESSIONS.values()):
        if x is not None and x.db_id == db_id:
            return x
    row = SAVE.load_session(db_id)
    return _from_row(row) if row else None


def _from_row(row: dict) -> Session:
    sess = new_session(ACCOUNT_OWNER, row["session_name"], layout=row["scene_layout"] or {}, db_id=row["session_id"])
    sess.unsent = row["unsent_tasks"] or {}
    if AUTOSAVE:
        AUTOSAVE.seed(*_snapshot(sess))
    return sess


def _load_saved() -> int:
    """At start: the owner's most recently saved sessions, and autosave from then on."""
    global AUTOSAVE
    AUTOSAVE = SAVE.Autosaver(lambda: [x for x in list(SESSIONS.values()) if x is not None and x.db_id
                                       and x.owner == ACCOUNT_OWNER and x.sim.scene_mode == "free"], _snapshot)
    n = 0
    try:
        for row in SAVE.load_sessions(SAVED_AT_START):
            _from_row(row)
            n += 1
    except Exception as e:  # noqa: BLE001
        print("could not load saved sessions:", e)
    AUTOSAVE.start()
    return n


AUTOSAVE = None


def _world_from_layout(layout: dict | None):
    """Stations and objects from a layout (checked: known robots and objects only)."""
    from wetlabsim import scene as WS
    from . import world as W
    if not layout:
        return [], []
    stations, placed = [], []
    for st in (layout.get("stations") or [])[:12]:
        if st.get("robot") not in WS.ROBOTS or not re.match(r"^st\d{1,3}$", str(st.get("uid", ""))):
            continue
        if any(x.uid == st["uid"] for x in stations):
            continue
        stations.append(W.Station(st["uid"], st["robot"], (float(st["pos"][0]), float(st["pos"][1])),
                                  float(st.get("yaw", 0.0)), str(st.get("name") or "")[:40]))
    known = {i["id"] for i in catalog.available()}
    for o in (layout.get("objects") or [])[:200]:
        if o.get("item") not in known or not re.match(r"^[\w.-]{1,80}$", str(o.get("uid", ""))):
            continue
        q = o.get("quat")
        placed.append(W.Placed(o["uid"], o["item"], tuple(float(v) for v in o["pos"][:3]), float(o.get("yaw", 0.0)),
                               tuple(float(v) for v in q[:4]) if q else None))
    return stations, placed


def new_session(owner: str, name: str | None = None, layout: dict | None = None, default: bool = False,
                db_id: str | None = None) -> Session:
    """A new session for this browser: blank (no stations), the starter lab (default: one Franka),
    or a copy of a layout. Named "Untitled lab", "Untitled lab 2", ... unless named."""
    with SESSIONS_LOCK:
        if len(SESSIONS) >= MAX_SESSIONS:
            raise RobotError(f"this server holds {MAX_SESSIONS} sessions at most; none can be added now")
        mine = {x.name for x in SESSIONS.values() if x.owner == owner}
        if not name:
            name, n = "Untitled lab", 1
            while name in mine:
                n += 1
                name = f"Untitled lab {n}"
        sid = secrets.token_urlsafe(6).replace("_", "x").replace("-", "y")
        SESSIONS[sid] = None      # reserved while its world loads
    try:
        if default:
            sim = PlaygroundSim()
        else:
            stations, placed = _world_from_layout(layout)
            sim = PlaygroundSim(placed=placed, stations=stations)
            nums = [int(m.group(1)) for o in placed for m in [re.search(r"_(\d+)$", o.uid)] if m]
            sim._uid = max(nums, default=0)
        log_root = pathlib.Path(os.environ.get("WETLAB_SESSION_DIR") or PGHandler.runs_dir)
        sim.open_log(log_root / time.strftime(f"session-%Y%m%d-%H%M%S-{sid}"))
        sim.start()
        sim.frame_lab(glide=False)
    except Exception:
        with SESSIONS_LOCK:
            SESSIONS.pop(sid, None)
        raise
    sess = Session(sid, name[:60], owner, sim, PGHandler.base_url, PGHandler.runs_dir)
    if SAVE.enabled():
        import uuid
        sess.db_id = db_id or str(uuid.uuid4())
    with SESSIONS_LOCK:
        SESSIONS[sid] = sess
    return sess


def get_session(sid: str | None) -> Session | None:
    return SESSIONS.get(sid) if sid else None


def first_session() -> Session | None:
    """The oldest session: what a request that names none (an old link, a tool) talks to."""
    live = [x for x in SESSIONS.values() if x is not None]
    return min(live, key=lambda x: x.created) if live else None


QUEUE: list[dict] = []          # free-play runs waiting for a free slot, oldest first
QUEUE_LOCK = threading.Lock()


def _queue_position(sid, uid):
    for i, q in enumerate(QUEUE):
        if q["session"] == sid and q["station"] == uid:
            return i + 1
    return None


def _all_runners():
    return [r for x in list(SESSIONS.values()) if x is not None for r in list(x.runners.values())]


def _start_queued():
    """Start waiting runs while there is room (MAX_ACTIVE on the public site; no limit locally)."""
    with QUEUE_LOCK:
        while QUEUE:
            # Runs at once: across every lab on the shared site, else on this server.
            active = LABS.slots_in_use() if LABS.shared() else sum(1 for r in _all_runners() if r.active())
            if PUBLIC and active >= MAX_ACTIVE:
                return
            job = QUEUE.pop(0)
            sess = get_session(job["session"])
            st = sess.sim.station(job["station"]) if sess else None
            if st is None:
                continue
            slot = LABS.take_slot() if LABS.shared() else None
            try:
                r = sess.station_runner(job["station"])
                r.slot = slot
                r.start(job["task"], job["model"], site.site_sheet(sess.sim.placed, st, sess.sim.stations), job["limit"])
            except Exception as e:  # noqa: BLE001
                LABS.free_slot(slot)
                print("could not start a queued run:", e)


class PGHandler(Handler):
    # Set for each request from its session (_bind_session): that session's world, runs and chat.
    sess: Session
    sim: PlaygroundSim
    runner: Runner              # the scene's one robot (LIBERO, Wet Lab, and the robot cell's own URLs)
    runners: dict               # free play: one per station, by station id
    bench: Bench
    wetbench: WL.WetBench
    base_url = ""

    def _bind_session(self) -> bool:
        """Which session this request is for: /s/<id>/... (the robot API and the page's links),
        else ?s=<id> or X-Session, else the oldest one. False (and an error sent) if it names
        one that doesn't exist."""
        sid = None
        if self.path.startswith("/s/"):
            _, _, sid, rest = (self.path.split("/", 3) + [""])[:4]
            self.path = "/" + rest
        else:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = (q.get("s") or [None])[0] or self.headers.get("X-Session") or None
        sess = get_session(sid) if sid else first_session()
        if sess is None:
            if sid:
                self._err("no such session (it may have closed)", 404)
            else:
                self._err("no session yet", 503)
            return False
        self.sess = sess
        self.sim, self.runner, self.runners = sess.sim, sess.runner, sess.runners
        self.bench, self.wetbench, self.board = sess.bench, sess.wetbench, sess.board
        return True

    def _browser(self) -> str:
        # A lab owned by a signed-in account: its owner is the same person on any browser.
        if LABS.OWNER_USER and LABS.OWNER_KEY and LABS.owner_ok(self.headers):
            return ACCOUNT_OWNER
        b = self.headers.get("X-Browser-Id", "")
        return b if re.match(r"^[A-Za-z0-9_-]{8,64}$", b) else ""

    def _owns(self) -> bool:
        """Whether this request may change its session: the lab's owner key (public site), and
        the session's own browser."""
        if not LABS.owner_ok(self.headers):
            return False
        return bool(self.sess.owner) and secrets.compare_digest(self._browser(), self.sess.owner)

    def _busy(self) -> bool:
        return (self.runner.active() or self.bench.active() or self.wetbench.active()
                or any(r.active() for r in self.runners.values()))

    def station_runner(self, uid: str) -> Runner:
        return self.sess.station_runner(uid)

    def _station_request(self) -> bool:
        """Requests to /st/<station>/...: that station's robot API (and its run), as if it were
        a robot cell of its own."""
        if not self.path.startswith("/st/"):
            return False
        _, _, uid, rest = (self.path.split("/", 3) + [""])[:4]
        sim = self.sess.sim
        if sim.scene_mode != "free" or uid not in sim.arms:
            self._err("no such station", 404)
            return True
        self.sim = RobotView(sim, sim.arms[uid])
        self.board = self.station_runner(uid).board
        self.path = "/" + rest
        return True

    def _pass_in(self):
        """The website's one-time pass into this lab: swap it for the owner's cookie, then the lab."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if not LABS.pass_ok((q.get("pass") or [""])[0]):
            return self._send(403, b"This link has expired or isn't yours. Open your lab from the website again.",
                              "text/plain; charset=utf-8")
        dest = "/"
        want = (q.get("open") or [""])[0]
        if SAVE.enabled() and re.match(r"^[0-9a-f-]{36}$", want):
            try:
                sess = open_saved(want)
                if sess:
                    SAVE.opened(want)
                    dest = f"/?s={sess.id}"
            except Exception as e:  # noqa: BLE001
                print("could not open a saved session:", e)
        self.send_response(303)
        self.send_header("Set-Cookie", f"wl_lab={LABS.OWNER_KEY}; Path=/; Max-Age=43200; HttpOnly; Secure; SameSite=Lax")
        self.send_header("Location", dest)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _lab_for_user(self):
        """The website (signed-in account): start or find that account's lab. Answers {url, lab}
        when it is ready (no key: the website hands the owner a one-time pass instead)."""
        if not LABS.link_ok(self.headers.get("X-Link-Secret", "")):
            return self._err("not found", 404)
        user = str((self._body() or {}).get("user", ""))
        if not re.match(r"^[A-Za-z0-9_-]{1,64}$", user):
            return self._err("bad user", 400)
        try:
            out = LABS.claim_lab("user:" + user, user)
        except Exception as e:  # noqa: BLE001
            return self._err(f"could not start a lab: {e}", 503)
        out.pop("key", None)
        return self._json(out)

    def _claim_lab(self):
        """The visitor's own lab, found by a cookie (no sign-in)."""
        import http.cookies
        c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if "wl_owner" not in c:      # the front page sets it; a request without it starts nothing
            return self._err("open the site's front page first", 400)
        owner = c["wl_owner"].value
        try:
            out = LABS.claim_lab(owner)
        except Exception as e:  # noqa: BLE001
            return self._err(f"could not start a lab: {e}", 503)
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _runs_status(self) -> dict:
        out = {uid: self.runners[uid].status() for uid in list(self.runners)}
        for i, q in enumerate(list(QUEUE)):
            if q["session"] == self.sess.id:
                out[q["station"]] = {"active": False, "queued": i + 1, "task": q["task"], "model": q["model"]}
        return out

    def _sessions(self, starter: bool = False) -> dict:
        """This browser's sessions (asked with starter, a browser with none gets the starter
        lab) and the others that are running now: here, and on the public site in other
        visitors' labs."""
        me = self._browser()
        owner = LABS.owner_ok(self.headers)
        if starter and me and owner and not any(x and x.owner == me for x in SESSIONS.values()):
            free = next((x for x in SESSIONS.values() if x and not x.owner), None)
            if free is not None:
                free.owner = me           # the lab's starter session, not yet anyone's
            elif len(SESSIONS) < MAX_SESSIONS:
                new_session(me, default=True)
        live = [x for x in SESSIONS.values() if x is not None]
        mine = sorted((x.summary() for x in live if me and x.owner == me), key=lambda d: -d["used"])
        others = [{**x.summary(), "url": ""} for x in live if x.owner != me and x.status() == "working"]
        if LABS.shared():
            try:
                for lab, info in LABS.live_labs().items():
                    if lab == LABS.LAB_ID or not info.get("url"):
                        continue
                    for r in info.get("runs", []):
                        if r.get("session"):
                            others.append({"id": r["session"], "name": r.get("session_name") or "A lab",
                                           "stations": r.get("stations") or 1, "used": r.get("started") or 0,
                                           "status": "working", "task": r.get("task", ""), "url": info["url"]})
            except Exception as e:  # noqa: BLE001
                print("could not list other labs:", e)
        seen, uniq = set(), []
        for o in others:
            if (o["url"], o["id"]) not in seen:
                seen.add((o["url"], o["id"]))
                uniq.append(o)
        return {"mine": mine, "live": uniq, "max": MAX_SESSIONS, "owner": owner}

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
        LABS.touch()
        if FRONT:
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/live"):
                # The visitor's cookie is set with the page, so every lab request after it carries
                # it: a repeated or retried request finds the same lab instead of starting another.
                hdr = {} if "wl_owner=" in self.headers.get("Cookie", "") else {
                    "Set-Cookie": f"wl_owner={secrets.token_urlsafe(18)}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax"}
                return self._send(200, (HERE / "static" / "front.html").read_bytes(), "text/html; charset=utf-8", hdr)
            if path == "/api/live":
                return self._json(LABS.live_list())
        elif LABS.OWNER_USER and urllib.parse.urlparse(self.path).path == "/auth":
            return self._pass_in()
        p0 = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if p0 in ("/", "/playground") or p0.startswith("/pg/static/"):
            pass                          # the page itself needs no session
        elif p0 == "/pg/sessions":
            try:
                return self._json(self._sessions("starter=1" in self.path))
            except RobotError as e:
                return self._err(str(e), 503)
        elif not self._bind_session():
            return None
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
            if p == "/pg/layout":
                # Public (anyone may copy a lab they can watch), readable from another lab's page.
                return self._send(200, json.dumps(self.sess.layout()).encode(), "application/json",
                                  {"Access-Control-Allow-Origin": "*"})
            if p == "/pg/runs":
                return self._send(200, _runs_page(self._list_runs(), self.runs_dir).encode(), "text/html; charset=utf-8")
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
                                   "models": [{**{k: m[k] for k in ("id", "label", "via", "provider") if k in m},
                                               **({"needs": _needs(m)} if _needs(m) else {})}
                                              for m in MODELS if not PUBLIC or m["agent"] in _site_agents()],
                                   "time_limit": TIME_LIMIT, "public": PUBLIC,
                                   "free_time_limit": FREE_TIME_LIMIT, "max_active": MAX_ACTIVE if PUBLIC else 0,
                                   "owner": LABS.owner_ok(self.headers), "front": LABS.FRONT_URL,
                                   "lab_url": LABS.LAB_URL})
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
                                   "bench": self.bench.status(), "wetbench": self.wetbench.status(),
                                   "session": {"id": self.sess.id, "name": self.sess.name,
                                               "mine": self._owns()}, "stale": LABS.stale(),
                                   "unsent": self.sess.unsent,
                                   "idle_left": LABS.idle_left()})
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
            # The main view drawn in the browser (scene3d): the scene once, then a pose stream.
            if p == "/pg/scene3d":
                with self.sim.lock:
                    m, ver = self.sim.m, self.sim._model_ver
                out = S3.scene(m, ver)
                out["floorfx"] = self.sim.scene_mode == "free"      # the Tron floor, drawn by the page
                return self._json(out)
            if p.startswith("/pg/mesh/") or p.startswith("/pg/tex/"):
                m = self.sim.m
                i = int(pathlib.Path(p).stem)
                data, ctype = ((S3.mesh_bin(m, i), "application/octet-stream") if p.startswith("/pg/mesh/")
                               else (S3.tex_png(m, i), "image/png"))
                hdr = {"Cache-Control": "max-age=86400"}       # the URL carries the content's hash
                if "gzip" in self.headers.get("Accept-Encoding", "") and ctype != "image/png":
                    import gzip
                    data, hdr["Content-Encoding"] = gzip.compress(data, 5), "gzip"
                return self._send(200, data, ctype, hdr)
            if p == "/pg/poses.sse":
                return self._pose_stream()
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

    def _pose_stream(self):
        """Server-sent events, ~30 a second: every body's pose, the view's overlay shapes and the
        server's camera (for glides and presets). Ends when the browser goes away."""
        s = self.sim
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                t0 = time.time()
                LABS.touch()
                s._glide_step()
                with s.lock:
                    xpos, xquat, ver = s.d.xpos.copy(), s.d.xquat.copy(), s._model_ver
                    c = s.view
                    cam = {"lookat": [round(float(v), 4) for v in c.lookat], "distance": round(float(c.distance), 4),
                           "azimuth": round(float(c.azimuth), 3), "elevation": round(float(c.elevation), 3)}
                shapes = list(s.overlay) + s._selection_overlay()
                frame = S3.poses(xpos, xquat, {"v": str(ver), "t": round(float(s.d.time), 3), "cam": cam,
                                               "shapes": shapes, "paused": s.paused})
                self.wfile.write(b"data: " + frame.encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(max(0.0, 1 / 30 - (time.time() - t0)))
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

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
        LABS.touch()
        if FRONT:
            if urllib.parse.urlparse(self.path).path == "/api/lab-for-user":
                return self._lab_for_user()
            if urllib.parse.urlparse(self.path).path == "/api/lab":
                return self._claim_lab()
            return self._err("not found", 404)      # the front runs no labs of its own
        # Someone else's lab: watch only. Changes need the key the owner's link carries.
        if (urllib.parse.urlparse(self.path).path.startswith("/pg/") and not getattr(self, "robot_api", False)
                and not LABS.owner_ok(self.headers)):
            return self._err("this lab is someone else's: you can watch it, not change it", 403)
        if not getattr(self, "robot_api", False):
            LABS.active()          # the owner did something: the lab is in use
        if re.sub(r"^/s/[^/]+", "", urllib.parse.urlparse(self.path).path).rstrip("/") == "/pg/active":
            self._body()
            return self._json({"ok": True, "idle_left": LABS.idle_left()})
        if urllib.parse.urlparse(self.path).path.rstrip("/") == "/pg/sessions/new":
            return self._new_session()
        if not self._bind_session():
            return None
        # Someone else's session: watch only.
        if (urllib.parse.urlparse(self.path).path.startswith("/pg/") and not getattr(self, "robot_api", False)
                and not self._owns()):
            self._body()
            return self._err("this session is someone else's: you can watch it, not change it", 403)
        if not getattr(self, "robot_api", False):
            self.sess.used = time.time()
        # With a robot API running, robot commands are only taken there, with a run token.
        tail = re.sub(r"^(/s/[^/]+)?(/st/[^/]+)?", "", urllib.parse.urlparse(self.path).path).rstrip("/")
        if ROBOT_API_URL and not getattr(self, "robot_api", False) and tail in RA.ROBOT_COMMANDS:
            return self._err("robot commands go through the robot API, with a run token", 403)
        if urllib.parse.urlparse(self.path).path.endswith("/eval/robot_token/revoke"):
            if not self._authed():
                return self._err("evaluator token required", 403)
            RA.TOKENS.revoke(self._body().get("token"))
            return self._json({"ok": True})
        if urllib.parse.urlparse(self.path).path.endswith("/eval/robot_token"):
            # An orchestrator running elsewhere (with the evaluator's token) asks for a run token
            # for the robot this URL names.
            if not self._authed():
                return self._err("evaluator token required", 403)
            self._body()      # read it all: an unread request body makes the close drop the reply
            prefix = urllib.parse.urlparse(self.path).path[:-len("/eval/robot_token")]
            return self._json({"ok": True, "token": RA.TOKENS.issue(prefix, run="external")})
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
            s.use_camera(b.get("cam"))       # a page drawing its own view picks through its camera
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
            if p == "/pg/station/duplicate":
                uid = s.duplicate_station(b["uid"])
                s.frame_station(uid)
                return self._json({"ok": True, "uid": uid})
            if p == "/pg/station/remove":
                s.remove_station(b["uid"])
                self.runners.pop(b["uid"], None)
                return self._json({"ok": True})
            if p == "/pg/drafts":      # typed-but-unsent tasks and chosen models, kept with the session
                tasks, models = b.get("tasks") or {}, b.get("models") or {}
                self.sess.unsent = {str(k): {"task": str(tasks.get(k, ""))[:8000], "model": str(models.get(k, ""))[:80]}
                                    for k in set(tasks) | set(models) if re.match(r"^st\d{1,3}$", str(k))}
                return self._json({"ok": True})
            if p == "/pg/session/rename":
                name = str(b.get("name", "")).strip()[:60]
                if name:
                    self.sess.name = name
                return self._json({"ok": True, "name": self.sess.name})
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
                if PUBLIC and b.get("mode") in ("libero", "wetlab"):
                    return self._json({"ok": False, "error": "this site runs free play only"})
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
                    if runner.active() or _queue_position(self.sess.id, uid):
                        return self._json({"ok": False, "error": f"{station.name} is already running a task"})
                    model = b.get("model", "claude")
                    if PUBLIC:
                        if not any(m["id"] == model and m["agent"] in _site_agents() for m in MODELS):
                            return self._json({"ok": False, "error": "this site doesn't run that model"})
                        limit = FREE_TIME_LIMIT          # the site's cap, not the page's say
                    else:
                        limit = float(b.get("time_limit", FREE_TIME_LIMIT))
                    s.selected = None
                    s.play()
                    job = {"session": self.sess.id, "station": uid, "task": task[:4000], "model": model,
                           "limit": limit, "queued": time.time()}
                    with QUEUE_LOCK:
                        QUEUE.append(job)
                    _start_queued()
                    pos = _queue_position(self.sess.id, uid)
                    return self._json({"ok": True, "run": self.station_runner(uid).status() if pos is None
                                       else {"active": False, "queued": pos}})
                s.play()
                return self._json({"ok": True})
            if p == "/pg/pause":
                s.pause()
                return self._json({"ok": True})
            if p == "/pg/stop":
                if b.get("station"):          # one station's run
                    with QUEUE_LOCK:
                        QUEUE[:] = [q for q in QUEUE if not (q["session"] == self.sess.id and q["station"] == b["station"])]
                    r = self.runners.get(b["station"])
                    if r:
                        r.stop()
                    return self._json({"ok": True})
                self.sess.stop()
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

    def _new_session(self):
        """A new session for this browser: blank, or a copy of another session's lab (its
        stations and objects; never its tasks or runs)."""
        b = self._body()
        me = self._browser()
        if not me:
            return self._err("no browser id", 400)
        layout = None
        if b.get("from"):
            src = get_session(b["from"])
            if src is None:
                return self._json({"ok": False, "error": "that session has closed"})
            layout = src.layout()
        elif isinstance(b.get("layout"), dict):
            layout = b["layout"]      # copied from a lab elsewhere (its page fetched /pg/layout)
        name = None
        if layout and layout.get("name"):
            name = f"{str(layout['name'])[:48]} (copy)"
        try:
            sess = new_session(me, name, layout)
        except RobotError as e:
            return self._json({"ok": False, "error": str(e)})
        except (KeyError, ValueError, TypeError, IndexError) as e:
            return self._json({"ok": False, "error": f"couldn't copy that lab: {e}"})
        return self._json({"ok": True, "session": sess.summary()})

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


class RobotAPIHandler(RA.RobotAPIMixin, PGHandler):
    """The robot API listener: the robot's commands, readings and the agent's two cameras, for
    the station a run token opens. Shares the app's state (PGHandler's class attributes)."""


def main(argv=None):
    ap = argparse.ArgumentParser(description="MuJoCo Playground")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--public", action="store_true",
                    help="the public site: Claude only, free play only, runs capped at --run-minutes, "
                         "at most --max-active at once, agents in cloud sandboxes (--launcher)")
    ap.add_argument("--front", action="store_true",
                    help="the public site's front: hands each visitor their own lab, lists live and past runs")
    ap.add_argument("--run-minutes", type=float, default=5.0)
    ap.add_argument("--idle-minutes", type=float, default=5.0,
                    help="a hosted lab shuts down after this long with no clicks, typing or scrolling from its owner and nothing running")
    ap.add_argument("--max-active", type=int, default=4)
    ap.add_argument("--launcher", default="local", help="where agents run (wetlabsim.launchers)")
    ap.add_argument("--agent-robot-url", default="",
                    help="the robot API's address as agents elsewhere reach it (a public tunnel)")
    ap.add_argument("--model-proxy-port", type=int, default=0,
                    help="serve the model proxy (agents' Anthropic calls, with run tokens) on this port")
    ap.add_argument("--robot-port", type=int, default=8781,
                    help="the robot API, the only door agents get (0: none; agents then use the app's URL)")
    ap.add_argument("--runs", default="runs/playground")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    global PUBLIC, MAX_ACTIVE, RUN_LAUNCHER, AGENT_ROBOT_URL, FREE_TIME_LIMIT, FRONT
    FRONT = args.front
    PUBLIC, MAX_ACTIVE, RUN_LAUNCHER, AGENT_ROBOT_URL = args.public, args.max_active, args.launcher, args.agent_robot_url
    if PUBLIC:
        FREE_TIME_LIMIT = args.run_minutes * 60
    runs = pathlib.Path(args.runs).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    tok_file = runs / ".eval_token"
    token = os.environ.get("WETLAB_EVAL_TOKEN") or (tok_file.read_text().strip() if tok_file.exists() else "")
    if not token:
        token = secrets.token_hex(16)
        tok_file.write_text(token)
    if tok_file.exists():
        os.chmod(tok_file, 0o600)
    from .tools import fetch_libero as fetch_assets
    if fetch_assets.missing() and not PUBLIC:    # LIBERO's objects, one time (~200 MB), while free play loads
        print("Downloading LIBERO's objects in the background (one time, about 200 MB)...")
        threading.Thread(target=lambda: fetch_assets.ensure(), daemon=True).start()
    print("Loading the scene...")
    url = f"http://{args.host}:{args.port}"
    PGHandler.token, PGHandler.runs_dir = token, runs
    PGHandler.base_url = url
    # The starter session: the first browser to open the page takes it. (The front keeps one
    # too: the replay viewer draws past runs with its renderer. The idle robot log stays off a
    # shared volume; WETLAB_SESSION_DIR points it elsewhere when hosted.)
    if not (_load_saved() if SAVE.enabled() else 0):
        new_session("", "Untitled lab", default=True)
    srv = ThreadingHTTPServer((args.host, args.port), PGHandler)
    srv.daemon_threads = True

    def _queue_loop():               # start waiting runs as running ones finish
        while True:
            time.sleep(2)
            if QUEUE:
                _start_queued()
    threading.Thread(target=_queue_loop, daemon=True, name="run-queue").start()
    if LABS.shared():
        def live_runs():
            out = []
            for sess in [x for x in list(SESSIONS.values()) if x is not None]:
                for uid, r in list(sess.runners.items()):
                    st = r.status()
                    if st.get("active"):
                        out.append({"station": uid, "task": st.get("task", "")[:200],
                                    "model": (st.get("model") or {}).get("label", ""), "started": st.get("started"),
                                    "session": sess.id, "session_name": sess.name,
                                    "stations": len(sess.sim.stations)})
            return out
        LABS.start_reporting(live_runs, args.idle_minutes,
                             lambda: bool(QUEUE) or any(r.active() for r in _all_runners()))
    if args.robot_port:
        global ROBOT_API_URL
        rsrv = ThreadingHTTPServer((args.host, args.robot_port), RobotAPIHandler)
        rsrv.daemon_threads = True
        threading.Thread(target=rsrv.serve_forever, daemon=True, name="robot-api").start()
        ROBOT_API_URL = f"http://{args.host}:{args.robot_port}"
        print(f"Robot API for agents at {ROBOT_API_URL} (run tokens only)")
    if args.model_proxy_port:
        from . import model_proxy
        model_proxy.serve(args.host, args.model_proxy_port)
        print(f"Model proxy for agents on port {args.model_proxy_port} (run tokens only)")
    print(f"MuJoCo Playground is running at {url}")
    if not args.no_browser:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for sess in [x for x in list(SESSIONS.values()) if x is not None]:
            sess.stop()
            sess.sim.stop_threads()


if __name__ == "__main__":
    main()
