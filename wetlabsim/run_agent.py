"""Run one agent (Claude Code, Codex or Devin) on a task in the robot cell and record everything.

    python -m wetlabsim.run_agent --agent claude --task "Move the red-capped tube to the empty rack."
    python -m wetlabsim.run_agent --agent codex  --task-file tasks/move_tube.txt
    python -m wetlabsim.run_agent --agent devin  --task-file tasks/move_tube.txt

The robot cell (python -m wetlabsim.server) must already be running. Each run:
1. resets the cell to its starting state and starts a new log,
2. gives the agent a fresh workspace with the robot's documents and the agent plug,
3. runs the agent CLI with your existing login (no API keys needed),
4. saves the transcript, the robot's state log and the final object positions.
"""
from __future__ import annotations

import argparse
import http.client
import json
import re
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from . import devin_auth, launchers, storage, traces

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
MCP_TOOLS = ["mcp__wetlab__look", "mcp__wetlab__robot_state", "mcp__wetlab__emergency_stop"]


def _eval_call(url, token, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method="POST" if data else "GET",
                                 headers={"X-Eval-Token": token, "Content-Type": "application/json"})
    # Over a hosted tunnel a reply now and then arrives cut short: ask again.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except (http.client.IncompleteRead, http.client.RemoteDisconnected, ConnectionResetError):
            if attempt == 3:
                raise
            time.sleep(0.5 * (attempt + 1))


# The agent's wetlabsim package: just the robot client. A `pip install -e` of the full package
# adds an import hook that would still find wetlabsim.scene etc., so it is switched off here.
CLIENT_INIT = '''"""Robot client for the wet lab robot cell. Use: from wetlabsim.robot import Robot"""
import sys as _sys
_sys.meta_path[:] = [f for f in _sys.meta_path
                     if not getattr(f, "__module__", "").startswith("__editable__")]
'''

# Things an agent has no business touching on a real robot: the simulator's own code and
# scene (which says where every object is), and the evaluator's token and ground truth.
PEEK_MARKERS = [str(ROOT), "wetlabsim/scene.py", "wetlabsim/sim.py", "wetlabsim/server.py", "wetlabsim/assets", "wetlabsim.scene",
                "wetlabsim.sim", "wetlabsim.server", ".eval_token", "ground_truth",
                "site-packages/wetlabsim"]


def sim_source_peeks(transcript: pathlib.Path) -> list[dict]:
    """Agent steps that mention the simulator's internals (only what the agent ran or read)."""
    peeks = []
    for st in traces.load(transcript):
        if st.kind not in ("runs", "reads", "writes", "tool"):
            continue
        # Running the cell's Python interpreter by its full path isn't looking at the simulator.
        text = st.text.replace(str(ROOT / ".venv" / "bin" / "python"), "python")
        hits = sorted({m for m in PEEK_MARKERS if m in text})
        if hits:
            peeks.append({"t": st.t, "kind": st.kind, "matched": hits, "text": st.text[:300]})
    return peeks


def transcript_text(run_dir: pathlib.Path) -> str:
    f = run_dir / "transcript.jsonl"
    return f.read_text(errors="ignore") if f.exists() else ""


def workspace_leaks(*dirs: pathlib.Path) -> list[pathlib.Path]:
    """Files the agent can read that name the cell's own folder. From that path an agent could
    import the full package (simulator, scene) instead of only the robot client."""
    root, out = str(ROOT), []
    for base in dirs:
        for f in base.rglob("*"):
            if f.is_file() and f.suffix.lower() not in (".pdf", ".stl", ".obj", ".png", ".jpg"):
                try:
                    if root in f.read_text(errors="ignore"):
                        out.append(f)
                except OSError:
                    pass
    return out


DOCS_LEVELS = ("standard", "assisted")


def prepare_workspace(workspace: pathlib.Path, client: pathlib.Path, robot: str, docs: str,
                      task: str, info: dict, site_file: pathlib.Path | None = None) -> str:
    """Put what the agent gets for this documentation level into its workspace and client
    folder. Returns the note added to the task prompt.

    standard: the task, Franka's own documents unchanged, a site sheet, the camera
              calibration, the robot-only model and a command reference without tips.
    assisted: our hand-written manual with tips and pixel/point helpers (the earlier setup).
    """
    robot_py = (ROOT / "wetlabsim" / "robot.py").read_text()
    if docs == "assisted":
        shutil.copy(AGENT_DIR / f"ROBOT_MANUAL_{robot}.md", workspace / "ROBOT_MANUAL.md")
        for f in ("CLAUDE.md", "AGENTS.md"):
            shutil.copy(AGENT_DIR / f, workspace / f)
        note = "The robot manual is in ROBOT_MANUAL.md."
        if site_file:   # this installation (e.g. a playground station): it overrides the manual's bench
            shutil.copy(site_file, workspace / "SITE.md")
            (workspace / "cameras.json").write_text(json.dumps(info["camera_calibration"], indent=1))
            note += (" SITE.md describes this installation (its table, cameras and what is on it);"
                     " where it differs from the manual's lab bench, SITE.md is right.")
    else:
        if robot != "franka":
            raise SystemExit("the standard docs level exists only for the Franka; use --docs assisted")
        from .datasheets import fetch
        fetch()
        for f in ("AGENTS.md", "CLAUDE.md", "COMMANDS.md", "SITE.md"):
            shutil.copy(AGENT_DIR / "franka" / f, workspace / f)
        if site_file:   # another installation of the same robot (e.g. the playground's table)
            shutil.copy(site_file, workspace / "SITE.md")
        (workspace / "GOAL.md").write_text(task + "\n")
        (workspace / "cameras.json").write_text(json.dumps(info["camera_calibration"], indent=1))
        sheets = workspace / "datasheets"
        sheets.mkdir()
        for s in json.loads((AGENT_DIR / "datasheets" / "sources.json").read_text()):
            shutil.copy(AGENT_DIR / "datasheets" / s["file"], sheets / s["file"])
        shutil.copy(AGENT_DIR / "datasheets" / "sources.json", sheets / "sources.json")
        model = ROOT / "wetlabsim" / "assets" / "franka_emika_panda"
        shutil.copytree(model, workspace / "robot_model", ignore=shutil.ignore_patterns("*.md"))
        # Leave out the pixel/point helpers: at this level agents use the calibration themselves.
        a = robot_py.index("    # --- assisted helpers")
        b = robot_py.index("    # --- end assisted helpers\n") + len("    # --- end assisted helpers\n")
        robot_py = robot_py[:a] + robot_py[b:]
        note = "The task is also in GOAL.md; AGENTS.md lists the documents in this folder."
    (client / "wetlabsim").mkdir()
    (client / "wetlabsim" / "__init__.py").write_text(CLIENT_INIT)
    (client / "wetlabsim" / "robot.py").write_text(robot_py)
    return note


def make_prompt(task: str, note: str) -> str:
    """The whole prompt the agent gets: the task plus a fixed closing note."""
    return f"{task}\n\n{note} When you are done, say DONE and briefly describe what you did and what you saw."


def default_model(agent: str) -> str:
    """The model an agent CLI uses when none is given, where its config says (Codex)."""
    if agent == "codex":
        try:
            for line in (pathlib.Path.home() / ".codex" / "config.toml").read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "model":
                    return v.strip().strip('"')
        except OSError:
            pass
    return ""


def build_command(agent: str, task: str, model: str | None, workspace: pathlib.Path,
                  run_dir: pathlib.Path, note: str, robot_url: str = "", robot_token: str = "") -> list[str]:
    py = sys.executable
    prompt = make_prompt(task, note)
    # The agent's own tools (look, robot_state, emergency_stop) reach the robot the same way its
    # Python does: the robot API's URL and this run's token. Passed to each CLI explicitly,
    # since not every CLI hands its own environment on to tool servers.
    tool_env = {"PYTHONPATH": str(ROOT), "WETLAB_ROBOT_URL": robot_url, "WETLAB_ROBOT_TOKEN": robot_token}
    if agent == "claude":
        mcp = {"mcpServers": {"wetlab": {"command": py, "args": ["-m", "wetlabsim.mcp_server"],
                                         "env": tool_env}}}
        # Kept out of the workspace: it names the cell's own folder and Python, which an agent
        # could otherwise put on its path to import more than the robot client.
        cfg = pathlib.Path(tempfile.mkdtemp(prefix="wetlab-mcp-")) / "mcp.json"
        cfg.write_text(json.dumps(mcp, indent=2))
        cmd = ["claude", "-p", prompt, "--mcp-config", str(cfg), "--strict-mcp-config",
               "--allowedTools", "Bash", "Read", "Write", "Edit", *MCP_TOOLS,
               "--disallowedTools", f"Read(/{ROOT}/**)", f"Edit(/{ROOT}/**)", f"Write(/{ROOT}/**)",
               "--output-format", "stream-json", "--verbose",
               "--thinking-display", "summarized"]   # include summarized thinking in the trace
        if model:
            cmd += ["--model", model]
        return cmd
    if agent == "codex":
        cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "--json",
               "-c", "sandbox_workspace_write.network_access=true",
               "-c", 'model_reasoning_summary="detailed"',   # include reasoning summaries in the trace
               "-c", f'mcp_servers.wetlab.command="{py}"',
               "-c", 'mcp_servers.wetlab.args=["-m", "wetlabsim.mcp_server"]',
               "-c", "mcp_servers.wetlab.env={" + ", ".join(f'{k}="{v}"' for k, v in tool_env.items()) + "}"]
        if model:
            cmd += ["--model", model]
        return cmd + [prompt]
    if agent == "devin":
        # Devin CLI reads AGENTS.md and the permission rules from the workspace. Like Claude's
        # --allowedTools, only the tools it needs are pre-approved: Python, files in its
        # workspace, and the robot's MCP tools. Anything else is refused (no one is there to
        # approve it). Devin runs through its ACP server (devin_acp.py), which streams its
        # thinking, tool calls and replies as they happen; print mode only shows the answer.
        mcp = [{"name": "wetlab", "command": py, "args": ["-m", "wetlabsim.mcp_server"],
                "env": [{"name": k, "value": v} for k, v in tool_env.items()]}]
        perms = {"permissions": {"allow": ["Read(./**)", "Write(./**)", "Exec(python)", "Exec(python3)",
                                           "Exec(ls)", "Exec(cat)", "mcp__wetlab__*"],
                                 # The folder above the cell's, so this file doesn't name the cell's
                                 # own folder (the workspace leak check refuses files that do).
                                 # Not when that is / (the hosted image keeps the cell in /app):
                                 # it would deny the workspace too. The bridge still refuses
                                 # anything outside the workspace.
                                 "deny": [] if ROOT.parent == ROOT.parent.parent else
                                         [f"Read({ROOT.parent}/**)", f"Write({ROOT.parent}/**)"]}}
        (workspace / ".devin").mkdir(exist_ok=True)
        (workspace / ".devin" / "config.json").write_text(json.dumps(perms, indent=2))
        # The bridge runs by file path: the agent's PYTHONPATH only has the robot client.
        # It also refuses any permission request for the repo or outside the workspace.
        cmd = [py, str(ROOT / "wetlabsim" / "devin_acp.py"), str(workspace), prompt,
               "--mcp", json.dumps(mcp), "--deny", str(ROOT), "--raw-log", str(run_dir / "devin_acp_raw.jsonl")]
        if model:
            cmd += ["--model", model]
        return cmd
    raise SystemExit(f"unknown agent {agent!r}; use claude, codex or devin")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True, choices=["claude", "codex", "devin"])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task")
    g.add_argument("--task-file")
    g.add_argument("--task-id", help="a task from the task library (wetlabsim/tasks.py), e.g. T1: "
                                     "sets the prompt, lays out the bench and scores the run")
    ap.add_argument("--model", help="optional model name passed to the CLI")
    ap.add_argument("--batch", help="a name grouping runs for the results page, e.g. opus-group1")
    ap.add_argument("--try", dest="attempt", type=int, help="which try of this task in the batch (1, 2, ...)")
    ap.add_argument("--time-limit", type=float, default=900, help="seconds before the agent is stopped (0: no limit)")
    ap.add_argument("--url", default=os.environ.get("WETLAB_ROBOT_URL", "http://127.0.0.1:8765"),
                    help="the cell's own server (the evaluator, the live page)")
    ap.add_argument("--robot-url", help="the robot API the agent gets, if the cell runs one (with a run "
                                        "token in WETLAB_ROBOT_TOKEN); else the agent uses --url")
    ap.add_argument("--launcher", default="local", help="where the agent's CLI runs (wetlabsim.launchers)")
    ap.add_argument("--store", default="local", help="where the run's record is kept (wetlabsim.storage)")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--site-file", help="a site sheet to give the agent instead of the bench's SITE.md")
    ap.add_argument("--docs", choices=DOCS_LEVELS, default="standard",
                    help="what the agent is given: Franka's documents and a command reference "
                         "(standard), or our manual with tips and helpers (assisted)")
    args = ap.parse_args(argv)

    from . import tasks as T
    if args.task_id and args.task_id not in T.TASKS:
        raise SystemExit(f"unknown task {args.task_id}; choose from {', '.join(T.TASKS)}")
    task = (T.TASKS[args.task_id].prompt if args.task_id
            else args.task or pathlib.Path(args.task_file).read_text().strip())
    runs = pathlib.Path(args.runs).resolve()
    token = os.environ.get("WETLAB_EVAL_TOKEN") or (runs / ".eval_token").read_text().strip()
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{args.agent}" + (f"-{args.task_id}" if args.task_id else "")
    if os.environ.get("WETLAB_RUN_TAG"):       # several labs share one runs folder: keep ids apart
        run_id += "-" + os.environ["WETLAB_RUN_TAG"]
    store = storage.get(args.store, runs)
    run_dir = store.create(run_id)
    launcher = launchers.get(args.launcher)
    # The robot as the agent reaches it: the robot API with this run's token (kept out of the
    # saved command and of the agent's workspace files), or the cell's own URL.
    robot_url = args.robot_url or args.url
    robot_token = os.environ.pop("WETLAB_ROBOT_TOKEN", "")
    own_token = False
    if args.robot_url and not robot_token:
        # Run from outside the cell (a hosted orchestrator): ask the cell for a run token.
        robot_token, own_token = _eval_call(args.url, token, "/eval/robot_token", {})["token"], True

    # Fresh workspace outside the runs folder, with only the documents for this cell's robot.
    # The agent's own Python can import only the robot client (wetlabsim.robot), like a real
    # robot's SDK. That copy comes first on PYTHONPATH, so it also hides an installed copy of
    # the full package, whose scene and simulator code would reveal where everything is.
    info = json.loads(urllib.request.urlopen(args.url + "/info").read())
    robot = info.get("robot_id", "ur5e")
    workspace = pathlib.Path(tempfile.mkdtemp(prefix=f"wetlab-{run_id}-"))
    client = pathlib.Path(tempfile.mkdtemp(prefix=f"wetlab-{run_id}-client-"))
    note = prepare_workspace(workspace, client, robot, args.docs, task, info,
                             pathlib.Path(args.site_file) if args.site_file else None)

    _eval_call(args.url, token, "/eval/reset", {"run_dir": str(run_dir), "task": args.task_id})
    gt0 = _eval_call(args.url, token, "/eval/ground_truth")
    wall_reset = time.time()
    sim_reset = json.loads(urllib.request.urlopen(args.url + "/state").read())["time"]
    cmd = build_command(args.agent, task, args.model, workspace, run_dir, note, robot_url, robot_token)
    leaks = workspace_leaks(workspace, client)
    if leaks:
        raise SystemExit(f"setup check failed: these files in the agent's workspace name the cell's "
                         f"folder ({ROOT}): {', '.join(map(str, leaks))}")
    store.write_text(run_id, "task.txt", task)
    store.write_json(run_id, "command.json", [a.replace(robot_token, "<run token>") if robot_token else a for a in cmd])
    # What the viewer shows about this run; the model, tokens and cost fill in as the agent reports them.
    meta = traces.RunMeta(args.agent, args.model or default_model(args.agent))
    run_info = {
        "run_id": run_id, "task": task, "prompt": make_prompt(task, note), "docs": args.docs,
        "robot": robot, "robot_label": info.get("robot", robot), "gripper_label": info.get("gripper", ""),
        "time_limit": args.time_limit, "sim_start": sim_reset, "status": "running",
        "task_id": args.task_id, "task_title": T.TASKS[args.task_id].title if args.task_id else None,
        "batch": args.batch, "attempt": args.attempt,
        "workspace": str(workspace), **meta.info(),
    }
    _eval_call(args.url, token, "/eval/run", run_info)
    last_meta_post = [0.0]
    env = dict(os.environ, PYTHONPATH=str(client), WETLAB_ROBOT_URL=robot_url, WETLAB_ROBOT_TOKEN=robot_token)
    env.pop("DEVIN_API_KEY", None)
    devin_home = None
    if args.agent == "devin" and devin_auth.key() and launcher.name == "local":
        # Devin logs in with the organization's key (a login of its own for this run, outside
        # the workspace), not this machine's own Devin login. The modal launcher does this in
        # its sandbox.
        devin_home = pathlib.Path(tempfile.mkdtemp(prefix=f"wetlab-{run_id}-devin-"))
        devin_auth.write_login(devin_home, devin_auth.key())
        env["XDG_DATA_HOME"] = str(devin_home)

    print(f"Run {run_id}: {args.agent} is working. Watch at {args.url}")
    t0 = time.time()
    status = "finished"
    parser = traces.Parser()
    lock = threading.Lock()
    done = threading.Event()
    with store.open(run_id, "transcript.jsonl", "w") as out:
        proc = launcher.start(cmd, workspace, env)

        def record(obj):
            # Save to the transcript and send the readable steps to the live page.
            with lock:
                out.write(json.dumps(obj) + "\n")
                out.flush()
                steps = parser.feed(obj)
                changed = meta.feed(obj)
            if changed and time.time() - last_meta_post[0] > 1.0:
                last_meta_post[0] = time.time()
                try:
                    _eval_call(args.url, token, "/eval/run", meta.info())
                except OSError:
                    pass
            if steps:
                try:
                    _eval_call(args.url, token, "/eval/trace",
                               {"steps": [{"t": s.t, "kind": s.kind, "text": s.text[:4000]} for s in steps]})
                except OSError:
                    pass

        def pump():
            # Stamp every transcript line with the robot clock so traces line up with the replay.
            for line in proc.stdout:
                t = round(sim_reset + time.time() - wall_reset, 3)
                try:
                    obj = json.loads(line)
                    obj["_sim_time"] = t
                except json.JSONDecodeError:
                    obj = {"type": "_raw", "text": line.rstrip(), "_sim_time": t}
                record(obj)

        def tail_hooks():
            # Devin's hook log (one JSON line per tool call), read as it grows.
            path, pos = run_dir / "devin_hooks.jsonl", 0
            while True:
                finished = done.is_set()
                if path.exists():
                    with open(path) as f:
                        f.seek(pos)
                        for line in iter(f.readline, ""):
                            if not line.endswith("\n"):
                                break
                            pos += len(line.encode())
                            try:
                                obj = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            obj["type"] = "_devin_hook"
                            obj["_sim_time"] = round(sim_reset + obj.get("_wall", time.time()) - wall_reset, 3)
                            record(obj)
                if finished:
                    return
                time.sleep(0.3)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        hooks_reader = threading.Thread(target=tail_hooks, daemon=True)
        hooks_reader.start()
        try:
            proc.wait(timeout=args.time_limit or None)
        except subprocess.TimeoutExpired:
            # Ask the agent to stop first so it can save its trace (Devin writes its export
            # on exit), then force it after a grace period.
            status = "time_limit"
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if status == "finished" and proc.returncode:
            status = "agent_error"
        reader.join(timeout=5)
        done.set()
        hooks_reader.join(timeout=5)
    elapsed = time.time() - t0

    gt = _eval_call(args.url, token, "/eval/ground_truth")
    _eval_call(args.url, token, "/eval/save_recording", {"path": str(run_dir / "replay.npz")})
    _eval_call(args.url, token, "/eval/close_log", {})
    state = json.loads(urllib.request.urlopen(args.url + "/state").read())
    events = json.loads(urllib.request.urlopen(args.url + "/events?all=1").read())
    store.write_json(run_id, "events.json", events, indent=0)
    run_info.update(meta.info(), status=status, wall_seconds=round(elapsed, 1))
    _eval_call(args.url, token, "/eval/run", run_info)
    store.write_json(run_id, "run.json", {k: v for k, v in run_info.items() if k != "workspace"})
    result = {
        "run_id": run_id, "agent": args.agent, "model": args.model, "robot": robot,
        "docs": args.docs, "task": task, "prompt": run_info["prompt"],
        "model_reported": meta.model, "provider": run_info["provider"],
        "tokens": meta.input_tokens + meta.output_tokens, "input_tokens": meta.input_tokens,
        "output_tokens": meta.output_tokens, "cached_tokens": meta.cached_tokens, "cost_usd": meta.cost_usd,
        "status": status, "wall_reset": wall_reset, "sim_reset": sim_reset,
        "exit_code": proc.returncode, "wall_seconds": round(elapsed, 1),
        "protective_stops": sum(1 for e in events if e.get("event") == "protective_stop"),
        "commands": sum(1 for e in events if e.get("event") == "command"),
        "final_robot_state": state, "final_objects": gt["objects"],
    }
    peeks = sim_source_peeks(run_dir / "transcript.jsonl")
    result["fair"] = not peeks
    result["sim_source_peeks"] = peeks
    result["cost_label"] = "API-equivalent cost (not billed)"
    result["batch"], result["attempt"] = args.batch, args.attempt
    if args.task_id:
        from .scoring import score_run
        sc = score_run(args.task_id, gt0, gt, run_dir, events)
        result.update(sc)
        if sc["flags"]["interrupted"]:
            result["status"] = "interrupted: usage limit"
        store.write_json(run_id, "start_objects.json", gt0, indent=None)
        run_info.update(task_id=args.task_id, score=sc["score"], passed=sc["passed"], flags=sc["flags"],
                        status=result["status"])
        store.write_json(run_id, "run.json", {k: v for k, v in run_info.items() if k != "workspace"})
        _eval_call(args.url, token, "/eval/run", run_info)
        print(f"Score: {sc['score']} ({'PASS' if sc['passed'] else 'FAIL'}) {json.dumps(sc['detail'])[:300]}")
    store.write_json(run_id, "result.json", result, indent=2)
    # Claude Code keeps its own scratchpad outside the workspace (and may use it despite being
    # asked not to): keep a copy of whatever the agent wrote there with the run.
    for pad in sorted(set(re.findall(r"(/(?:private/)?tmp/claude-[^\s'\"]+?/scratchpad)\b", transcript_text(run_dir)))):
        src = pathlib.Path(pad)
        if src.is_dir() and any(src.iterdir()):
            shutil.copytree(src, workspace / "scratchpad (outside the workspace)", dirs_exist_ok=True)
    if hasattr(proc, "sync_workspace"):     # a remote agent: bring its folder back for the record
        proc.sync_workspace(workspace)
    if own_token:
        _eval_call(args.url, token, "/eval/robot_token/revoke", {"token": robot_token})
    store.copy_tree(run_id, "workspace", workspace)
    if devin_home:
        shutil.rmtree(devin_home, ignore_errors=True)
    store.finish(run_id)
    print(f"Done in {elapsed:.0f} s ({status}). Results in {run_dir}")
    if peeks:
        print(f"WARNING: the agent looked at the simulator's own code ({len(peeks)} times), "
              "so this run doesn't count as a fair score. See sim_source_peeks in result.json.")
    print(f"Make a video of it with: python -m wetlabsim.make_video {run_dir}")


if __name__ == "__main__":
    main()
