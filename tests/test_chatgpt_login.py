"""Sign in with ChatGPT for Codex runs: Codex's login file kept as the OpenAI connection
(playground/accounts.py) and the device code sign-in run (playground/chatgpt_login.py), with a
fake `codex` that prints a link and code like the real one, then writes its login file."""
import base64
import json
import os
import stat
import time

import pytest

from playground import accounts as ACCT
from playground import chatgpt_login as CL


def _login(email="ada@example.com", refresh="r1"):
    claims = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return json.dumps({"OPENAI_API_KEY": None, "tokens": {"id_token": f"h.{claims}.s", "access_token": "a",
                                                          "refresh_token": refresh, "account_id": "acc"},
                       "last_refresh": "2026-11-13T00:00:00Z"})


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(ACCT, "_store", ACCT.LocalStore(tmp_path / "account.json"))
    ACCT._cache.clear()
    yield tmp_path / "account.json"
    ACCT._cache.clear()


def test_login_email_and_check():
    assert ACCT.login_email(_login()) == "ada@example.com"
    assert ACCT.login_email("{}") == "" and ACCT.login_email("nope") == ""
    assert ACCT.check_login(_login()) is None
    assert ACCT.check_login('{"tokens": {}}') and ACCT.check_login("x")


def test_chatgpt_login_is_the_openai_connection(local):
    assert ACCT.connect_chatgpt("not json")
    assert ACCT.connect_chatgpt(_login()) is None
    c = ACCT.settings()["connections"]["openai"]
    assert c["kind"] == "chatgpt" and c["email"] == "ada@example.com" and c["last4"] == ""
    assert ACCT.credential_for("codex") == ("chatgpt", _login())
    assert "refresh_token" not in json.dumps(ACCT.settings())       # the page never sees the tokens
    assert stat.S_IMODE(os.stat(local).st_mode) == 0o600
    # Codex refreshed its tokens during a run: the new file is kept.
    ACCT.update_login("openai", _login(refresh="r2"))
    assert json.loads(ACCT.key_for("codex"))["tokens"]["refresh_token"] == "r2"
    # An API key replaces the sign-in, and a late refresh doesn't bring it back.
    ACCT._store.save_key("openai", "sk-proj-xyz1234")
    ACCT.update_login("openai", _login(refresh="r3"))
    assert ACCT.credential_for("codex") == ("key", "sk-proj-xyz1234")
    ACCT.disconnect("openai")
    assert ACCT.credential_for("codex") == ("key", "")


def test_hosted_lab_without_owner_cant_sign_in(monkeypatch):
    monkeypatch.setattr(ACCT, "_store", ACCT.NoStore())
    with pytest.raises(RuntimeError):
        ACCT.connect_chatgpt(_login())


FAKE_CODEX = """#!/bin/sh
printf 'WARNING: proceeding\\n\\nFollow these steps to sign in with ChatGPT using device code authorization:\\n'
printf '1. Open this link\\n   \\033[94mhttps://auth.openai.com/codex/device\\033[0m\\n'
printf '2. Enter this one-time code \\033[90m(expires in 15 minutes)\\033[0m\\n   \\033[94mGIAU-6AP7X\\033[0m\\n'
sleep 1
[ -n "$FAIL" ] && { echo "Error: device code login is not enabled"; exit 1; }
printf '%s' '__LOGIN__' > "$CODEX_HOME/auth.json"
"""


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    f = b / "codex"
    f.write_text(FAKE_CODEX.replace("__LOGIN__", _login()))
    f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")


def _until(login, states, timeout=10):
    end = time.time() + timeout
    while login.status()["state"] not in states and time.time() < end:
        time.sleep(0.05)
    return login.status()


def test_device_login_shows_the_code_then_gets_the_file(fake_codex):
    login = CL.start("local")
    st = _until(login, ("waiting", "done"))
    assert st["state"] == "waiting", st
    assert st["url"] == "https://auth.openai.com/codex/device" and st["code"] == "GIAU-6AP7X"
    assert 0 < st["expires_in"] <= 900
    assert _until(login, ("done", "failed"))["state"] == "done"
    assert ACCT.login_email(login.login) == "ada@example.com"
    CL.cancel()


def test_device_login_failure_says_why(fake_codex, monkeypatch):
    monkeypatch.setenv("FAIL", "1")
    login = CL.start("local")
    st = _until(login, ("done", "failed"))
    assert st["state"] == "failed" and "not enabled" in st["error"]
    CL.cancel()
