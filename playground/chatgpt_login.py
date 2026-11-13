"""Sign in with ChatGPT for Codex runs: Codex's own device code sign-in, run for the lab's owner.

Settings > General > Connections > OpenAI > Sign in with ChatGPT starts `codex login --device-auth`
(the Codex CLI's documented sign-in for remote and headless machines). Where the agents run in
Modal Sandboxes it runs in one too, with the same image as the agents, able to reach OpenAI only.
Codex prints a link and a one-time code; the page shows both, the person approves the code on
OpenAI's page (after turning on device code sign-in for Codex in their ChatGPT settings), and
Codex writes its login file (auth.json). That file is saved like an API key (accounts.py), and
Codex runs then use the person's ChatGPT plan.

One sign-in at a time per lab; it gives up when the code expires (15 minutes).
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import time

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
URL = re.compile(r"https://auth\.openai\.com/\S+")
CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,8}\b")
EXPIRES_S = 15 * 60
# What Codex's sign-in reaches (OpenAI's sign-in server; Codex may also ask for its own API token).
HOSTS = ["auth.openai.com", "api.openai.com", "chatgpt.com"]
CMD = ["codex", "login", "--device-auth", "-c", 'cli_auth_credentials_store="file"']


class _Local:
    """Codex on this machine, with a login folder of its own (not this user's ~/.codex)."""

    def __init__(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="wetlab-codex-login-"))
        os.chmod(self.home, 0o700)
        self.proc = subprocess.Popen(CMD, env={**os.environ, "CODEX_HOME": str(self.home), "NO_COLOR": "1"},
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     text=True, start_new_session=True)
        self.stdout = self.proc.stdout

    def poll(self):
        return self.proc.poll()

    def login_file(self) -> str:
        return (self.home / "auth.json").read_text()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        shutil.rmtree(self.home, ignore_errors=True)


class _Sandbox:
    """Codex in a Modal Sandbox (the agents' image) that can reach OpenAI's sign-in only."""

    HOME = "/root/codex-login"

    def __init__(self):
        import modal

        from wetlabsim.launchers import ModalSandboxLauncher
        app = modal.App.lookup(ModalSandboxLauncher.APP, create_if_missing=True)
        self.sb = modal.Sandbox.create("sleep", "infinity", app=app, image=ModalSandboxLauncher.image(),
                                       timeout=EXPIRES_S + 300, cpu=0.25, memory=512, outbound_domain_allowlist=HOSTS)
        self.proc = self.sb.exec(*CMD, env={"CODEX_HOME": self.HOME, "NO_COLOR": "1"})
        self.stdout = self.proc.stdout

    def poll(self):
        return self.proc.poll()

    def login_file(self) -> str:
        return self.sb.filesystem.read_bytes(f"{self.HOME}/auth.json").decode()

    def close(self):
        try:
            self.sb.terminate()
        except Exception:  # noqa: BLE001
            pass


class DeviceLogin:
    def __init__(self, where: str):
        self.where, self.out, self.state, self.error, self.login = where, "", "starting", "", ""
        self.started, self.lock = time.time(), threading.Lock()
        self.runner = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.runner = _Sandbox() if self.where == "modal" else _Local()
            reader = threading.Thread(target=self._read, daemon=True)
            reader.start()
            while self.runner.poll() is None and self.state in ("starting", "waiting"):
                if time.time() - self.started > EXPIRES_S + 30:
                    self._fail("The code expired. Start again to get a new one.")
                    return
                time.sleep(1)
            if self.state not in ("starting", "waiting"):
                return       # cancelled
            reader.join(timeout=3)
            if self.runner.poll() == 0:
                self.login = self.runner.login_file()
                self.state = "done"
            else:
                self._fail(self._why())
        except FileNotFoundError:
            self._fail("Codex isn't installed on this machine (npm install -g @openai/codex).")
        except Exception as e:  # noqa: BLE001
            self._fail(f"Couldn't sign in to ChatGPT: {e}")
        finally:
            if self.runner:
                self.runner.close()

    def _read(self):
        for chunk in self.runner.stdout:
            with self.lock:
                self.out += ANSI.sub("", chunk)
                if self.state == "starting" and self.url() and self.code():
                    self.state = "waiting"

    def _why(self) -> str:
        lines = [ln.strip() for ln in self.out.splitlines() if ln.strip() and not ln.startswith("WARNING")]
        tail = " ".join(lines[-2:])[:300]
        return f"Couldn't sign in to ChatGPT. Codex said: {tail}" if tail else "Couldn't sign in to ChatGPT. Try again."

    def _fail(self, msg: str):
        self.state, self.error = "failed", msg

    def url(self) -> str:
        m = URL.search(self.out)
        return m.group(0) if m else ""

    def code(self) -> str:
        m = CODE.search(self.out)
        return m.group(0) if m else ""

    def status(self) -> dict:
        d = {"state": self.state}
        if self.state == "waiting":
            d.update(url=self.url(), code=self.code(),
                     expires_in=max(0, int(EXPIRES_S - (time.time() - self.started))))
        if self.state == "failed":
            d["error"] = self.error
        return d

    def cancel(self):
        if self.state in ("starting", "waiting"):
            self.state = "cancelled"
        if self.runner:
            self.runner.close()


_current: DeviceLogin | None = None
_lock = threading.Lock()


def start(where: str) -> DeviceLogin:
    """A new sign-in (any earlier one still going is cancelled)."""
    global _current
    with _lock:
        if _current:
            _current.cancel()
        _current = DeviceLogin(where)
        return _current


def current() -> DeviceLogin | None:
    return _current


def cancel():
    global _current
    with _lock:
        if _current:
            _current.cancel()
        _current = None
