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


class _SandboxRun:
    """A process-like handle on an agent CLI running in a Modal Sandbox."""

    def __init__(self, sb, proc):
        self.sb, self.proc = sb, proc
        self.stdout = self._lines(proc.stdout)

    @staticmethod
    def _lines(stream):
        """The sandbox's output arrives in chunks of any size: hand it on one whole line at a time,
        as a local process's stdout would."""
        buf = ""
        for chunk in stream:
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                yield line + "\n"
        if buf:
            yield buf

    @property
    def returncode(self):
        return self.proc.poll()

    def poll(self):
        return self.proc.poll()

    def wait(self, timeout=None):
        import subprocess
        import time
        end = None if timeout is None else time.time() + timeout
        while self.proc.poll() is None:
            if end is not None and time.time() > end:
                raise subprocess.TimeoutExpired("agent sandbox", timeout)
            time.sleep(0.5)
        return self.proc.poll()

    def send_signal(self, sig):
        self.terminate()

    def terminate(self):
        try:
            self.sb.terminate()
        except Exception:  # noqa: BLE001
            pass

    kill = terminate

    def sync_workspace(self, local):
        """Copy the sandbox's /workspace back into the local workspace folder, then end it."""
        import io
        import tarfile
        try:
            p = self.sb.exec("tar", "-cf", "/tmp/ws.tar", "-C", "/workspace", ".")
            p.wait()
            data = self.sb.filesystem.read_bytes("/tmp/ws.tar")
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                t.extractall(local, filter="data")
        finally:
            self.terminate()


class ModalSandboxLauncher:
    """The agent's CLI in a Modal Sandbox holding only its workspace and the robot client. Its
    only ways out are the robot API (run token) and the model proxy (the same token, where an
    API key would go); every other address is blocked. Claude Code only, for now."""

    name = "modal"
    APP = "wetlab-playground-agents"
    _image = None

    @classmethod
    def image(cls):
        import modal
        if cls._image is None:
            cls._image = (
                modal.Image.debian_slim(python_version="3.12")
                .apt_install("curl", "ca-certificates", "git")
                .run_commands("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
                              "apt-get install -y nodejs", "npm install -g @anthropic-ai/claude-code")
                .pip_install("numpy", "pillow", "mcp")
            )
        return cls._image

    def start(self, cmd, workspace, env):
        import io
        import json
        import os
        import pathlib
        import tarfile
        import urllib.parse

        import modal

        if not cmd or cmd[0] != "claude":
            raise SystemExit("the modal launcher runs Claude Code only")
        prompt = cmd[2]
        model = cmd[cmd.index("--model") + 1] if "--model" in cmd else None
        robot_url, token = env["WETLAB_ROBOT_URL"], env.get("WETLAB_ROBOT_TOKEN", "")
        proxy = os.environ["WETLAB_MODEL_PROXY_URL"]
        client = pathlib.Path(env["PYTHONPATH"])
        host = lambda u: urllib.parse.urlparse(u).hostname  # noqa: E731

        app = modal.App.lookup(self.APP, create_if_missing=True)
        sb = modal.Sandbox.create("sleep", "infinity", app=app, image=self.image(), timeout=1800,
                                  cpu=1.0, memory=2048, workdir="/workspace",
                                  outbound_domain_allowlist=[host(robot_url), host(proxy)])
        # Upload: the workspace, the robot client (plus its tool server) and the tools' config.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            t.add(workspace, arcname="workspace")
            t.add(client, arcname="client")
            t.add(pathlib.Path(__file__).with_name("mcp_server.py"), arcname="client/wetlabsim/mcp_server.py")
            mcp = {"mcpServers": {"wetlab": {"command": "python3", "args": ["-m", "wetlabsim.mcp_server"],
                                             "env": {"PYTHONPATH": "/client", "WETLAB_ROBOT_URL": robot_url,
                                                     "WETLAB_ROBOT_TOKEN": token}}}}
            data = json.dumps(mcp).encode()
            info = tarfile.TarInfo("tools/mcp.json")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        sb.filesystem.write_bytes(buf.getvalue(), "/tmp/up.tar")
        sb.exec("sh", "-c", "mkdir -p /workspace && tar -xf /tmp/up.tar -C / && rm /tmp/up.tar").wait()
        from .run_agent import MCP_TOOLS
        rcmd = ["claude", "-p", prompt, "--mcp-config", "/tools/mcp.json", "--strict-mcp-config",
                "--allowedTools", "Bash", "Read", "Write", "Edit", *MCP_TOOLS,
                "--output-format", "stream-json", "--verbose", "--thinking-display", "summarized"]
        if model:
            rcmd += ["--model", model]
        proc = sb.exec(*rcmd, workdir="/workspace", env={
            "PYTHONPATH": "/client", "WETLAB_ROBOT_URL": robot_url, "WETLAB_ROBOT_TOKEN": token,
            "ANTHROPIC_BASE_URL": proxy, "ANTHROPIC_API_KEY": token,
            "DISABLE_TELEMETRY": "1", "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        return _SandboxRun(sb, proc)


LAUNCHERS["modal"] = ModalSandboxLauncher
