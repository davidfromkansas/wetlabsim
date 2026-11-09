"""Where an agent's CLI runs. run_agent prepares the agent's workspace and command, then asks
a launcher to start it; the launcher returns a process-like handle (stdout lines, wait,
send_signal, terminate, kill, returncode).

local: a child process on this machine, in the workspace folder (the original setup).
A remote launcher (a cloud sandbox holding only the workspace) implements the same handle.
"""
from __future__ import annotations

import subprocess


class LocalLauncher:
    name = "local"

    def start(self, cmd: list[str], workspace, env: dict):
        return subprocess.Popen(cmd, cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, bufsize=1)


LAUNCHERS = {"local": LocalLauncher}


def get(name: str):
    try:
        return LAUNCHERS[name]()
    except KeyError:
        raise SystemExit(f"unknown launcher {name!r}; choose from {', '.join(LAUNCHERS)}") from None
