"""Run one agent (Claude Code or Codex) on a task in the robot cell and record everything.

    python -m wetlabsim.run_agent --agent claude --task "Move the red-capped tube to the empty rack."
    python -m wetlabsim.run_agent --agent codex  --task-file tasks/move_tube.txt

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
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
MCP_TOOLS = ["mcp__wetlab__look", "mcp__wetlab__robot_state", "mcp__wetlab__emergency_stop"]


def _eval_call(url, token, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method="POST" if data else "GET",
                                 headers={"X-Eval-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def build_command(agent: str, task: str, model: str | None, workspace: pathlib.Path) -> list[str]:
    py = sys.executable
    prompt = (f"{task}\n\nThe robot manual is in ROBOT_MANUAL.md. When you are done, "
              "say DONE and briefly describe what you did and what you saw.")
    if agent == "claude":
        mcp = {"mcpServers": {"wetlab": {"command": py, "args": ["-m", "wetlabsim.mcp_server"],
                                         "env": {"PYTHONPATH": str(ROOT)}}}}
        (workspace / ".mcp.json").write_text(json.dumps(mcp, indent=2))
        cmd = ["claude", "-p", prompt, "--mcp-config", str(workspace / ".mcp.json"), "--strict-mcp-config",
               "--allowedTools", "Bash", "Read", "Write", "Edit", *MCP_TOOLS,
               "--output-format", "stream-json", "--verbose"]
        if model:
            cmd += ["--model", model]
        return cmd
    if agent == "codex":
        cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "--json",
               "-c", "sandbox_workspace_write.network_access=true",
               "-c", f'mcp_servers.wetlab.command="{py}"',
               "-c", 'mcp_servers.wetlab.args=["-m", "wetlabsim.mcp_server"]',
               "-c", f'mcp_servers.wetlab.env={{PYTHONPATH="{ROOT}"}}']
        if model:
            cmd += ["--model", model]
        return cmd + [prompt]
    raise SystemExit(f"unknown agent {agent!r}; use claude or codex")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True, choices=["claude", "codex"])
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
    cmd = build_command(args.agent, task, args.model, workspace)
    (run_dir / "task.txt").write_text(task)
    (run_dir / "command.json").write_text(json.dumps(cmd, indent=1))
    env = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
               WETLAB_ROBOT_URL=args.url)

    print(f"Run {run_id}: {args.agent} is working. Watch at {args.url}")
    t0 = time.time()
    status = "finished"
    with open(run_dir / "transcript.jsonl", "w") as out:
        proc = subprocess.Popen(cmd, cwd=workspace, env=env, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
        try:
            proc.wait(timeout=args.time_limit)
        except subprocess.TimeoutExpired:
            proc.kill()
            status = "time_limit"
    elapsed = time.time() - t0

    gt = _eval_call(args.url, token, "/eval/ground_truth")
    state = json.loads(urllib.request.urlopen(args.url + "/state").read())
    events = json.loads(urllib.request.urlopen(args.url + "/events").read())
    result = {
        "run_id": run_id, "agent": args.agent, "model": args.model, "task": task,
        "status": status, "exit_code": proc.returncode, "wall_seconds": round(elapsed, 1),
        "protective_stops": sum(1 for e in events if e.get("event") == "protective_stop"),
        "commands": sum(1 for e in events if e.get("event") == "command"),
        "final_robot_state": state, "final_objects": gt["objects"],
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    shutil.copytree(workspace, run_dir / "workspace", dirs_exist_ok=True)
    print(f"Done in {elapsed:.0f} s ({status}). Results in {run_dir}")


if __name__ == "__main__":
    main()
