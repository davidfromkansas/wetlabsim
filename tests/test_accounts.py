"""General settings: the time limit and each person's own API keys (playground/accounts.py), the
model proxy adding the owner's key per run (playground/model_proxy.py), and the lab's
/pg/account and model gating (playground/server.py). No company is called: key checks are faked."""
import http.client
import http.server
import json
import os
import stat
import threading
import urllib.request

import pytest

from playground import accounts as ACCT
from playground import model_proxy
from wetlabsim import robot_api as RA


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(ACCT, "_store", ACCT.LocalStore(tmp_path / "account.json"))
    ACCT._cache.clear()
    monkeypatch.setattr(ACCT, "check_key", lambda p, k: None if k.endswith("good") else "Couldn't connect. bad key")
    yield tmp_path / "account.json"
    ACCT._cache.clear()


def test_defaults(local):
    s = ACCT.settings(fresh=True)
    assert s == {"run_minutes": 5, "connections": {}}
    assert ACCT.run_minutes() == 5 and ACCT.connected() == set()


def test_minutes_limits(local):
    assert ACCT.set_minutes(12)["run_minutes"] == 12
    for bad in (0, 31, "x", 2.5):
        with pytest.raises(ValueError):
            ACCT.set_minutes(bad)
    assert ACCT.run_minutes() == 12


def test_connect_checks_then_saves(local):
    assert ACCT.connect("anthropic", "sk-ant-wrong") == "Couldn't connect. bad key"
    assert ACCT.connected() == set()
    assert ACCT.connect("anthropic", "  sk-ant-xyz-good \n") is None
    c = ACCT.settings()["connections"]["anthropic"]
    assert c["last4"] == "good" and c["connected_at"]
    assert ACCT.key_for("claude") == "sk-ant-xyz-good"
    assert ACCT.key_for("codex") == ""
    # Only this user can read the file holding the keys.
    assert stat.S_IMODE(os.stat(local).st_mode) == 0o600
    # The settings never carry the whole key.
    assert "sk-ant-xyz-good" not in json.dumps(ACCT.settings())
    ACCT.disconnect("anthropic")
    assert ACCT.connected() == set() and ACCT.key_for("claude") == ""
    assert ACCT.connect("nobody", "x") == "unknown company"


def test_every_agent_has_a_company():
    from playground.server import MODELS
    assert {m["agent"] for m in MODELS} <= set(ACCT.AGENT_PROVIDER)
    assert {m["provider"] for m in MODELS} <= set(ACCT.PROVIDERS)
    assert all(ACCT.AGENT_PROVIDER[m["agent"]] == m["provider"] for m in MODELS)


def test_check_key_rejects_partial_keys_without_calling():
    assert "whole API key" in ACCT.check_key("openai", "sk-1")
    assert "whole API key" in ACCT.check_key("openai", "sk-proj 1234567890")
    assert "cog_" in ACCT.check_key("cognition", "apk_1234567890abcdef")


def test_check_key_reads_the_answer(monkeypatch):
    codes = {}
    monkeypatch.setattr(ACCT, "_call", lambda url, h, body=None, method="GET": codes[url.split("/")[2]])
    codes["api.openai.com"] = 200
    assert ACCT.check_key("openai", "sk-proj-1234567890") is None
    codes["api.openai.com"] = 401
    assert "isn't valid" in ACCT.check_key("openai", "sk-proj-1234567890")
    codes["api.anthropic.com"] = 0
    assert "Couldn't reach Anthropic" in ACCT.check_key("anthropic", "sk-ant-1234567890")
    codes["api.devin.ai"] = 403          # a real key that can't list organizations
    assert ACCT.check_key("cognition", "cog_1234567890abcdef") is None
    codes["api.devin.ai"] = 401
    assert "isn't valid" in ACCT.check_key("cognition", "cog_1234567890abcdef")
    codes["api.typesafe.ai"] = 400       # the key passed; the empty request didn't
    assert ACCT.check_key("typesafe", "ts_1234567890abcdef") is None
    codes["api.typesafe.ai"] = 403
    assert "isn't valid" in ACCT.check_key("typesafe", "ts_1234567890abcdef")


def test_website_store_sends_the_link_secret():
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("X-Link-Secret"), body))
            out = {"get": {"run_minutes": 7, "connections": {"openai": {"last4": "abcd", "connected_at": "x", "spent_usd": 1.5}}},
                   "key": {"key": "sk-proj-whole"}}.get(body["action"], {"ok": True})
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    st = ACCT.WebsiteStore(f"http://127.0.0.1:{srv.server_port}", "s3cret", "user_1")
    assert st.settings()["run_minutes"] == 7
    assert st.key("openai") == "sk-proj-whole"
    st.set_minutes(9)
    st.save_key("anthropic", "sk-ant-x")
    st.remove_key("anthropic")
    srv.shutdown()
    assert all(p == "/api/internal/account" and sec == "s3cret" and b["user"] == "user_1" for p, sec, b in seen)
    assert [b["action"] for _, _, b in seen] == ["get", "key", "set_minutes", "save_key", "remove_key"]


def test_hosted_lab_without_owner_keeps_no_keys(monkeypatch):
    monkeypatch.setattr(ACCT, "_store", None)
    for k in ("WETLAB_WEBSITE_URL", "LAB_LINK_SECRET", "WETLAB_OWNER_USER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WETLAB_LAB_ID", "lab1")
    st = ACCT.store()
    assert isinstance(st, ACCT.NoStore) and st.key("openai") == ""
    with pytest.raises(RuntimeError):
        st.save_key("openai", "sk-proj-1234567890")
    monkeypatch.setattr(ACCT, "_store", None)


# ------------------------------------------------------------------ the model proxy
class _FakeUpstream:
    """Stands in for http.client.HTTPSConnection: records where a call went and with what."""
    calls = []

    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, body=None, headers=None):
        _FakeUpstream.calls.append({"host": self.host, "path": path, "headers": headers})

    def getresponse(self):
        class R:
            status = 200
            _chunks = [b'{"ok": true}']

            def getheaders(self):
                return [("Content-Type", "application/json")]

            def read1(self, n):
                return self._chunks.pop(0) if self._chunks else b""
        return R()

    def close(self):
        pass


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(http.client, "HTTPSConnection", _FakeUpstream)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _FakeUpstream.calls.clear()
    srv = model_proxy.serve("127.0.0.1", 0)
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    model_proxy.KEYS.clear()


def _post(url, headers):
    req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_proxy_adds_the_owners_openai_key(proxy):
    tok = RA.TOKENS.issue("/st/st1", run="t")
    model_proxy.KEYS[tok] = {"openai": "sk-proj-OWNER"}
    assert _post(proxy + "/openai/v1/responses", {"Authorization": f"Bearer {tok}"}) == 200
    c = _FakeUpstream.calls[-1]
    assert c["host"] == "api.openai.com" and c["path"] == "/v1/responses"
    assert c["headers"]["Authorization"] == "Bearer sk-proj-OWNER"
    assert tok not in json.dumps(c["headers"])
    # This run has no Anthropic key, and the site has none of its own.
    assert _post(proxy + "/v1/messages", {"x-api-key": tok}) == 503
    RA.TOKENS.revoke(tok)


def test_proxy_adds_the_owners_anthropic_key(proxy):
    tok = RA.TOKENS.issue("/st/st1", run="t")
    model_proxy.KEYS[tok] = {"anthropic": "sk-ant-OWNER"}
    assert _post(proxy + "/v1/messages", {"x-api-key": tok}) == 200
    c = _FakeUpstream.calls[-1]
    assert c["host"] == "api.anthropic.com" and c["headers"]["x-api-key"] == "sk-ant-OWNER"
    # The owner's own key has no dollar cap.
    model_proxy._spent[tok] = 999.0
    assert _post(proxy + "/v1/messages", {"x-api-key": tok}) == 200
    RA.TOKENS.revoke(tok)
    assert _post(proxy + "/v1/messages", {"x-api-key": tok}) == 401
