"""Run one agent (Claude Code, Codex or Devin) on a task in the robot cell and record everything.

    python -m wetlabsim.run_agent --agent claude --task "Move the red-capped tube to the empty rack."
    python -m wetlabsim.run_agent --agent codex  --task-file tasks/move_tube.txt
    python -m wetlabsim.run_agent --agent devin  --task-file tasks/move_tube.txt

The robot cell (python -m wetlabsim.server) must already be running. Each run:
1. resets the cell to its starting state and starts a new log,
2. gives the agent a fresh workspace with the robot manual and the agent plug,
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


def build_command(agent: str, task: str, model: str | None, workspace: pathlib.Path,
                  run_dir: pathlib.Path) -> list[str]:
    py = sys.executable
    prompt = (f"{task}\n\nThe robot manual is in ROBOT_MANUAL.md. When you are done, "
              "say DONE and briefly describe what you did and what you saw.")
    if agent == "claude":
        mcp = {"mcpServers": {"wetlab": {"command": py, "args": ["-m", "wetlabsim.mcp_server"],
                                         "env": {"PYTHONPATH": str(ROOT)}}}}
        (workspace / ".mcp.json").write_text(json.dumps(mcp, indent=2))
        cmd = ["claude", "-p", prompt, "--mcp-config", str(workspace / ".mcp.json"), "--strict-mcp-config",
               "--allowedTools", "Bash", "Read", "Write", "Edit", *MCP_TOOLS,
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
        # Devin CLI reads AGENTS.md, the MCP config and the permission rules from the workspace.
        # Like Claude's --allowedTools, only the tools it needs are pre-approved: Python, files
        # in its workspace, and the robot's MCP tools. Anything else is refused (no one is there
        # to approve it). Devin has no streaming JSON output, so its full trajectory (ATIF
        # format, with timestamps) is exported to the run folder instead.
        mcp = {"mcpServers": {"wetlab": {"command": py, "args": ["-m", "wetlabsim.mcp_server"],
                                         "env": {"PYTHONPATH": str(ROOT)}}}}
        perms = {"permissions": {"allow": ["Read(./**)", "Write(./**)", "Exec(python)", "Exec(python3)",
                                           "Exec(ls)", "Exec(cat)", "mcp__wetlab__*"]}}
        (workspace / ".devin").mkdir(exist_ok=True)
        (workspace / ".devin" / "mcp_config.json").write_text(json.dumps(mcp, indent=2))
        (workspace / ".devin" / "config.json").write_text(json.dumps(perms, indent=2))
        # Print mode (-p) only prints the final answer, so hooks log each tool call as it
        # happens; the recorder streams that log into the transcript and the live page.
        hook = {"type": "command", "timeout": 10,
                "command": f'"{py}" -m wetlabsim.devin_hook "{run_dir / "devin_hooks.jsonl"}"'}
        hooks = {ev: [{"matcher": "", "hooks": [hook]}] for ev in ("PreToolUse", "PostToolUse")}
        (workspace / ".devin" / "hooks.v1.json").write_text(json.dumps(hooks, indent=2))
        cmd = ["devin", "--respect-workspace-trust", "false",
               "--export", str(run_dir / "devin_trajectory.json")]
        if model:
            cmd += ["--model", model]
        return cmd + ["-p", prompt]
    raise SystemExit(f"unknown agent {agent!r}; use claude, codex or devin")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True, choices=["claude", "codex", "devin"])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task")
    g.add_argument("--task-file")
    ap.add_argument("--model", help="optional model name passed to the CLI")
    ap.add_argument("--time-limit", type=float, default=900, help="seconds before the agent is stopped")
    ap.add_argument("--url", default=os.environ.get("WETLAB_ROBOT_URL", "http://127.0.0.1:8765"))
    ap.add_argument("--runs", default="runs")
    args = ap.parse_args(argv)

    task = args.task or pathlib.Path(args.task_file).read_text().strip()
    runs = pathlib.Path(args.runs).resolve()
    token = (runs / ".eval_token").read_text().strip()
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{args.agent}"
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)

    # Fresh workspace outside the runs folder, with only the manual in it.
    workspace = pathlib.Path(tempfile.mkdtemp(prefix=f"wetlab-{run_id}-"))
    for f in ("ROBOT_MANUAL.md", "CLAUDE.md", "AGENTS.md"):
        shutil.copy(AGENT_DIR / f, workspace / f)

    _eval_call(args.url, token, "/eval/reset", {"run_dir": str(run_dir)})
    wall_reset = time.time()
    sim_reset = json.loads(urllib.request.urlopen(args.url + "/state").read())["time"]
    cmd = build_command(args.agent, task, args.model, workspace, run_dir)
    (run_dir / "task.txt").write_text(task)
    (run_dir / "command.json").write_text(json.dumps(cmd, indent=1))
    env = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
               WETLAB_ROBOT_URL=args.url)

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
        reader.join(timeout=5)
        done.set()
        hooks_reader.join(timeout=5)
    elapsed = time.time() - t0

    gt = _eval_call(args.url, token, "/eval/ground_truth")
    _eval_call(args.url, token, "/eval/save_recording", {"path": str(run_dir / "replay.npz")})
    state = json.loads(urllib.request.urlopen(args.url + "/state").read())
    events = json.loads(urllib.request.urlopen(args.url + "/events?all=1").read())
    (run_dir / "events.json").write_text(json.dumps(events, indent=0))
    result = {
        "run_id": run_id, "agent": args.agent, "model": args.model, "task": task,
        "status": status, "wall_reset": wall_reset, "sim_reset": sim_reset,
        "exit_code": proc.returncode, "wall_seconds": round(elapsed, 1),
        "protective_stops": sum(1 for e in events if e.get("event") == "protective_stop"),
        "commands": sum(1 for e in events if e.get("event") == "command"),
        "final_robot_state": state, "final_objects": gt["objects"],
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    shutil.copytree(workspace, run_dir / "workspace", dirs_exist_ok=True)
    print(f"Done in {elapsed:.0f} s ({status}). Results in {run_dir}")
    print(f"Make a video of it with: python -m wetlabsim.make_video {run_dir}")


if __name__ == "__main__":
    main()
