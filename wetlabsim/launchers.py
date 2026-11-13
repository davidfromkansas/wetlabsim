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

    def __init__(self, sb, proc, mark: str, pull: dict | None = None):
        self.sb, self.proc, self.mark = sb, proc, mark   # mark: in the agent's command line
        self.pull = pull or {}     # {file in the sandbox: local path}, copied back before it ends
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
        """Signal the agent's process in the sandbox (the sandbox itself stays up, so its folder can
        still be brought back afterwards)."""
        import signal
        name = signal.Signals(sig).name[3:]
        # The mark is split in two in the script, so this shell's own command line doesn't match it.
        k = len(self.mark) // 2
        script = (f'm="{self.mark[:k]}""{self.mark[k:]}"; for d in /proc/[0-9]*; do p=${{d#/proc/}}; '
                  '[ "$p" = "$$" ] && continue; c=$(tr "\\0" " " < $d/cmdline 2>/dev/null); '
                  f'case "$c" in *"$m"*) kill -{name} $p 2>/dev/null;; esac; done; true')
        try:
            self.sb.exec("sh", "-c", script).wait()
        except Exception:  # noqa: BLE001
            pass

    def terminate(self):
        import signal
        self.send_signal(signal.SIGTERM)

    def kill(self):
        import signal
        self.send_signal(signal.SIGKILL)

    def close(self):
        """Copy back the files asked for, then end the sandbox."""
        import pathlib
        for remote, local in self.pull.items():
            try:
                pathlib.Path(local).write_bytes(self.sb.filesystem.read_bytes(remote))
            except Exception:  # noqa: BLE001  (kept as it was)
                pass
        self.pull = {}
        try:
            self.sb.terminate()
        except Exception:  # noqa: BLE001
            pass

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
            self.close()


# The Devin CLI release the sandbox image installs: its Linux build and published SHA-256
# (from https://static.devin.ai/cli/current/manifest.json).
# The Codex CLI release the sandbox image installs (npm @openai/codex).
CODEX_CLI = "0.167.2"
# What Codex reaches when signed in with ChatGPT: ChatGPT's Codex service and OpenAI's sign-in
# server (to refresh its tokens).
CHATGPT_HOSTS = ["chatgpt.com", "auth.openai.com"]
DEVIN_CLI = ("https://static.devin.ai/cli/3000.12.32/devin-3000.12.32-x86_64-unknown-linux.tar.gz",
             "c4f5a4e277f67190daed2f032515219b1fbfcb2320f46140cf0ce70019d41c58")


class ModalSandboxLauncher:
    """The agent's CLI in a Modal Sandbox holding only its workspace and the robot client. Its
    only ways out are the robot API (run token) and the model's servers; every other address is
    blocked. Claude Code reaches Anthropic and Codex reaches OpenAI through the model proxy (the
    run token where an API key would go; the proxy adds the lab owner's key). Devin reaches Devin's
    own servers, logged in with the owner's Devin key (DEVIN_API_KEY, handed to run_agent for this
    run only)."""

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
                              "apt-get install -y nodejs", "npm install -g @anthropic-ai/claude-code",
                              f"npm install -g @openai/codex@{CODEX_CLI}")
                # Devin CLI, the release's Linux build, checked against its published checksum
                # (the install script ends with a browser sign-in, which an image build can't do).
                .run_commands(f"curl -fsSL {DEVIN_CLI[0]} -o /tmp/devin.tgz",
                              f"echo '{DEVIN_CLI[1]}  /tmp/devin.tgz' | sha256sum -c -",
                              "mkdir -p /opt/devin && tar -xzf /tmp/devin.tgz -C /opt/devin"
                              " && ln -s /opt/devin/bin/devin /usr/local/bin/devin && rm /tmp/devin.tgz")
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

        from . import devin_auth
        devin = len(cmd) > 1 and cmd[1].endswith("devin_acp.py")
        codex = bool(cmd) and cmd[0] == "codex"
        if not cmd or not (cmd[0] == "claude" or devin or codex):
            raise SystemExit("the modal launcher runs Claude Code, Codex and Devin only")
        if devin and not devin_auth.key():
            raise SystemExit("Devin needs a Devin API key (DEVIN_API_KEY) for this run")
        prompt = cmd[3] if devin else cmd[-1] if codex else cmd[2]
        model = cmd[cmd.index("--model") + 1] if "--model" in cmd else None
        robot_url, token = env["WETLAB_ROBOT_URL"], env.get("WETLAB_ROBOT_TOKEN", "")
        proxy = os.environ.get("WETLAB_MODEL_PROXY_URL", "")
        client = pathlib.Path(env["PYTHONPATH"])
        host = lambda u: urllib.parse.urlparse(u).hostname  # noqa: E731
        # A ChatGPT sign-in (Codex only): Codex's login file, from the playground's Settings. Codex
        # then talks to OpenAI itself (ChatGPT's Codex service), not through the model proxy.
        login_dir = env.get("WETLAB_CODEX_AUTH_DIR", "") if codex else ""
        allow = [host(robot_url)] + (devin_auth.HOSTS if devin else CHATGPT_HOSTS if login_dir else [host(proxy)])

        app = modal.App.lookup(self.APP, create_if_missing=True)
        sb = modal.Sandbox.create("sleep", "infinity", app=app, image=self.image(), timeout=2700,
                                  cpu=1.0, memory=2048, workdir="/workspace", outbound_domain_allowlist=allow)
        # Upload: the workspace, the robot client (plus its tool server) and the tools' config.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            t.add(workspace, arcname="workspace")
            t.add(client, arcname="client")
            t.add(pathlib.Path(__file__).with_name("mcp_server.py"), arcname="client/wetlabsim/mcp_server.py")
            mcp = {"mcpServers": {"wetlab": {"command": "python3", "args": ["-m", "wetlabsim.mcp_server"],
                                             "env": {"PYTHONPATH": "/client", "WETLAB_ROBOT_URL": robot_url,
                                                     "WETLAB_ROBOT_TOKEN": token}}}}
            files = {"tools/mcp.json": json.dumps(mcp).encode()}
            if devin:
                files["tools/devin_acp.py"] = pathlib.Path(__file__).with_name("devin_acp.py").read_bytes()
                files["root/.local/share/devin/credentials.toml"] = devin_auth.credentials(devin_auth.key()).encode()
            if login_dir:
                files["tmp/codex/auth.json"] = (pathlib.Path(login_dir) / "auth.json").read_bytes()
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o600
                t.addfile(info, io.BytesIO(data))
        sb.filesystem.write_bytes(buf.getvalue(), "/tmp/up.tar")
        # (/tmp/codex: Codex's home folder, which Codex won't make itself.)
        sb.exec("sh", "-c", "mkdir -p /workspace /tmp/codex && tar -xf /tmp/up.tar -C / && rm /tmp/up.tar").wait()
        base_env = {"PYTHONPATH": "/client", "WETLAB_ROBOT_URL": robot_url, "WETLAB_ROBOT_TOKEN": token}
        if devin:
            # The same bridge as a local run (streams Devin's steps as JSON lines), with the robot's
            # tools as an MCP server; it refuses anything outside /workspace.
            servers = [{"name": "wetlab", "command": "python3", "args": ["-m", "wetlabsim.mcp_server"],
                        "env": [{"name": k, "value": v} for k, v in base_env.items()]}]
            rcmd = ["python3", "/tools/devin_acp.py", "/workspace", prompt, "--mcp", json.dumps(servers),
                    "--deny", "/tools", "--deny", "/root", "--raw-log", "/tmp/devin_acp_raw.jsonl"]
            if model:
                rcmd += ["--model", model]
            return _SandboxRun(sb, sb.exec(*rcmd, workdir="/workspace", env=base_env), "/tools/devin_acp.py")
        if codex:
            # Codex with an API key, through the model proxy (<proxy>/openai/v1), which adds the
            # lab owner's OpenAI key. The sandbox is its jail, so Codex's own one is off (it can't
            # set one up inside a Modal Sandbox anyway).
            tool_env = "{" + ", ".join(f'{k}="{v}"' for k, v in base_env.items()) + "}"
            rcmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "--json",
                    "-c", 'model_reasoning_summary="detailed"',
                    "-c", 'mcp_servers.wetlab.command="python3"',
                    "-c", 'mcp_servers.wetlab.args=["-m", "wetlabsim.mcp_server"]',
                    "-c", f"mcp_servers.wetlab.env={tool_env}"]
            if model:
                rcmd += ["--model", model]
            if login_dir:
                # Signed in with ChatGPT: Codex uses the login file and the person's ChatGPT plan.
                rcmd += ["-c", 'cli_auth_credentials_store="file"', "-c", 'forced_login_method="chatgpt"', prompt]
                proc = sb.exec(*rcmd, workdir="/workspace", env={**base_env, "CODEX_HOME": "/tmp/codex"})
                return _SandboxRun(sb, proc, "codex exec",
                                   pull={"/tmp/codex/auth.json": str(pathlib.Path(login_dir) / "auth.json")})
            rcmd.append(prompt)
            proc = sb.exec(*rcmd, workdir="/workspace", env={
                **base_env, "OPENAI_BASE_URL": proxy.rstrip("/") + "/openai/v1", "OPENAI_API_KEY": token,
                "CODEX_API_KEY": token, "CODEX_HOME": "/tmp/codex"})
            return _SandboxRun(sb, proc, "codex exec")
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
        return _SandboxRun(sb, proc, "/tools/mcp.json")


LAUNCHERS["modal"] = ModalSandboxLauncher
