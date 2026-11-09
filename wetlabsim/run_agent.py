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
import json
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

from . import traces

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
MCP_TOOLS = ["mcp__wetlab__look", "mcp__wetlab__robot_state", "mcp__wetlab__emergency_stop"]


def _eval_call(url, token, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method="POST" if data else "GET",
                                 headers={"X-Eval-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


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
                  run_dir: pathlib.Path, note: str) -> list[str]:
    py = sys.executable
    prompt = make_prompt(task, note)
    if agent == "claude":
        mcp = {"mcpServers": {"wetlab": {"command": py, "args": ["-m", "wetlabsim.mcp_server"],
                                         "env": {"PYTHONPATH": str(ROOT)}}}}
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
               "-c", f'mcp_servers.wetlab.env={{PYTHONPATH="{ROOT}"}}']
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
                "env": [{"name": "PYTHONPATH", "value": str(ROOT)}]}]
        perms = {"permissions": {"allow": ["Read(./**)", "Write(./**)", "Exec(python)", "Exec(python3)",
                                           "Exec(ls)", "Exec(cat)", "mcp__wetlab__*"],
                                 "deny": [f"Read({ROOT}/**)", f"Write({ROOT}/**)"]}}
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
    ap.add_argument("--time-limit", type=float, default=900, help="seconds before the agent is stopped")
    ap.add_argument("--url", default=os.environ.get("WETLAB_ROBOT_URL", "http://127.0.0.1:8765"))
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
    token = (runs / ".eval_token").read_text().strip()
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{args.agent}" + (f"-{args.task_id}" if args.task_id else "")
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)

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
    cmd = build_command(args.agent, task, args.model, workspace, run_dir, note)
    leaks = workspace_leaks(workspace, client)
    if leaks:
        raise SystemExit(f"setup check failed: these files in the agent's workspace name the cell's "
                         f"folder ({ROOT}): {', '.join(map(str, leaks))}")
    (run_dir / "task.txt").write_text(task)
    (run_dir / "command.json").write_text(json.dumps(cmd, indent=1))
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
    env = dict(os.environ, PYTHONPATH=str(client), WETLAB_ROBOT_URL=args.url)

    print(f"Run {run_id}: {args.agent} is working. Watch at {args.url}")
    t0 = time.time()
    status = "finished"
    parser = traces.Parser()
    lock = threading.Lock()
    done = threading.Event()
    with open(run_dir / "transcript.jsonl", "w") as out:
        proc = subprocess.Popen(cmd, cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, bufsize=1)

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
            proc.wait(timeout=args.time_limit)
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
    (run_dir / "events.json").write_text(json.dumps(events, indent=0))
    run_info.update(meta.info(), status=status, wall_seconds=round(elapsed, 1))
    _eval_call(args.url, token, "/eval/run", run_info)
    (run_dir / "run.json").write_text(json.dumps({k: v for k, v in run_info.items() if k != "workspace"}, indent=1))
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
        (run_dir / "start_objects.json").write_text(json.dumps(gt0))
        run_info.update(task_id=args.task_id, score=sc["score"], passed=sc["passed"], flags=sc["flags"],
                        status=result["status"])
        (run_dir / "run.json").write_text(json.dumps({k: v for k, v in run_info.items() if k != "workspace"}, indent=1))
        _eval_call(args.url, token, "/eval/run", run_info)
        print(f"Score: {sc['score']} ({'PASS' if sc['passed'] else 'FAIL'}) {json.dumps(sc['detail'])[:300]}")
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    shutil.copytree(workspace, run_dir / "workspace", dirs_exist_ok=True)
    print(f"Done in {elapsed:.0f} s ({status}). Results in {run_dir}")
    if peeks:
        print(f"WARNING: the agent looked at the simulator's own code ({len(peeks)} times), "
              "so this run doesn't count as a fair score. See sim_source_peeks in result.json.")
    print(f"Make a video of it with: python -m wetlabsim.make_video {run_dir}")


if __name__ == "__main__":
    main()
