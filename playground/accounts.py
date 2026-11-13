"""A person's General settings: how long each AI run may go, and their own AI keys.

On the public site every run uses the lab owner's own key for that company (OpenAI, Anthropic,
Devin or TypeSafe's Jev); a company with no key saved can't be used. The keys live in the
website's database, encrypted there; the lab reaches them through the website with the secret
the two share (LAB_LINK_SECRET), and only ever keeps a key in memory, for the run that needs it.

Run locally (no website), the same settings live in one file on this computer
(~/.wetlab/account.json, readable by this user only), and the agent CLIs' own logins still work
for a company with no key saved.

A key is checked with one small call to its company before it is saved.

OpenAI can instead be connected with a ChatGPT sign-in (kind "chatgpt"): Codex's own device code
sign-in (playground/chatgpt_login.py) leaves Codex's login file (auth.json), kept like a key, and
Codex runs on the person's ChatGPT plan. Codex may refresh the tokens in it during a run; the
new file is kept afterwards (update_login).
"""
from __future__ import annotations

import base64
import datetime
import math
import json
import os
import pathlib
import threading
import urllib.error
import urllib.request

# The companies a person can connect, the agents (wetlabsim.run_agent --agent) each one runs,
# and the provider names the model list uses (MODELS[...]["provider"]).
PROVIDERS = {
    "openai": {"label": "OpenAI", "agents": ["codex"]},
    "anthropic": {"label": "Anthropic", "agents": ["claude"]},
    "cognition": {"label": "Devin", "agents": ["devin"]},
    "typesafe": {"label": "Jev", "agents": ["jev"]},
}
AGENT_PROVIDER = {a: p for p, v in PROVIDERS.items() for a in v["agents"]}
MIN_MINUTES, MAX_MINUTES, DEFAULT_MINUTES = 1, 30, 5
_UA = "wetlab-playground"


# ------------------------------------------------------------------ checking a key
def _call(url: str, headers: dict, body: bytes | None = None, method: str = "GET") -> int:
    """The HTTP status of one call (0: the company couldn't be reached)."""
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": _UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def check_key(provider: str, key: str) -> str | None:
    """None if the company accepts this key, else why not, in plain words."""
    label = PROVIDERS[provider]["label"]
    key = key.strip()
    if len(key) < 12 or any(c.isspace() for c in key):
        return "That doesn't look like a whole API key. Check it was copied in full."
    if provider == "anthropic":
        code = _call("https://api.anthropic.com/v1/models?limit=1",
                     {"x-api-key": key, "anthropic-version": "2023-06-01"})
        ok = code == 200
    elif provider == "openai":
        code = _call("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
        ok = code == 200
    elif provider == "cognition":
        if not key.startswith("cog_"):
            return "Devin keys start with cog_. Make one for a service user in Devin's settings."
        # No call that only checks a key: a wrong key gets 401, a real one anything else (403/404
        # for an organization it can't see).
        code = _call("https://api.devin.ai/v3/organizations", {"Authorization": f"Bearer {key}"})
        ok = code not in (0, 401)
    else:  # typesafe
        # An empty request: a wrong key gets 401/403, a real one a complaint about the request.
        from wetlabsim.jev_agent import API_URL
        code = _call(API_URL, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                     b"{}", "POST")
        ok = code not in (0, 401, 403)
    if ok:
        return None
    if code == 0:
        return f"Couldn't reach {label} to check the key. Try again in a moment."
    if code in (401, 403):
        return f"Couldn't connect. {label} said the key isn't valid. Check it was copied in full."
    if code == 429:
        return f"{label} is busy (too many requests). Try again in a moment."
    return f"Couldn't connect. {label} answered with error {code}."


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _minutes(n) -> int:
    try:
        f = float(n)
    except (TypeError, ValueError):
        f = float("nan")
    if isinstance(n, bool) or not math.isfinite(f) or f != int(f):
        raise ValueError("the time limit is a whole number of minutes")
    n = int(f)
    if not MIN_MINUTES <= n <= MAX_MINUTES:
        raise ValueError(f"the time limit is {MIN_MINUTES} to {MAX_MINUTES} minutes")
    return n


# ------------------------------------------------------------------ where they are kept
class LocalStore:
    """This computer's own settings: one JSON file, readable by this user only."""

    def __init__(self, path: pathlib.Path):
        self.path, self.lock = path, threading.Lock()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, d: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.touch(mode=0o600)
        os.chmod(tmp, 0o600)
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(self.path)

    def settings(self) -> dict:
        d = self._read()
        return {"run_minutes": d.get("run_minutes", DEFAULT_MINUTES),
                "connections": {p: {"kind": v.get("kind", "key"), "last4": v["last4"], "connected_at": v["connected_at"],
                                    **({"email": v["email"]} if v.get("email") else {})}
                                for p, v in (d.get("keys") or {}).items() if p in PROVIDERS}}

    def set_minutes(self, n: int):
        with self.lock:
            d = self._read()
            d["run_minutes"] = n
            self._write(d)

    def save_key(self, provider: str, key: str):
        with self.lock:
            d = self._read()
            d.setdefault("keys", {})[provider] = {"key": key, "last4": key[-4:], "connected_at": _now()}
            self._write(d)

    def save_login(self, provider: str, login: str, email: str):
        with self.lock:
            d = self._read()
            d.setdefault("keys", {})[provider] = {"key": login, "kind": "chatgpt", "last4": "", "email": email,
                                                  "connected_at": _now()}
            self._write(d)

    def update_login(self, provider: str, login: str):
        with self.lock:
            d = self._read()
            v = (d.get("keys") or {}).get(provider)
            if v and v.get("kind") == "chatgpt":
                v["key"] = login
                self._write(d)

    def remove_key(self, provider: str):
        with self.lock:
            d = self._read()
            (d.get("keys") or {}).pop(provider, None)
            self._write(d)

    def credential(self, provider: str) -> tuple[str, str]:
        v = (self._read().get("keys") or {}).get(provider) or {}
        return v.get("kind", "key"), v.get("key", "")

    def key(self, provider: str) -> str:
        return self.credential(provider)[1]


class WebsiteStore:
    """The signed-in owner's settings, in the website's database (keys encrypted there)."""

    def __init__(self, website: str, secret: str, user: str):
        self.url, self.secret, self.user = website.rstrip("/") + "/api/internal/account", secret, user

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps({"user": self.user, **body}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Link-Secret": self.secret,
                                              "User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error")
            except ValueError:
                msg = None
            raise RuntimeError(msg or f"the website answered {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"couldn't reach the website ({e})") from None

    def settings(self) -> dict:
        r = self._post({"action": "get"})
        return {"run_minutes": r.get("run_minutes", DEFAULT_MINUTES), "connections": r.get("connections") or {}}

    def set_minutes(self, n: int):
        self._post({"action": "set_minutes", "minutes": n})

    def save_key(self, provider: str, key: str):
        self._post({"action": "save_key", "provider": provider, "key": key})

    def save_login(self, provider: str, login: str, email: str):
        self._post({"action": "save_login", "provider": provider, "login": login, "email": email})

    def update_login(self, provider: str, login: str):
        self._post({"action": "update_login", "provider": provider, "login": login})

    def remove_key(self, provider: str):
        self._post({"action": "remove_key", "provider": provider})

    def credential(self, provider: str) -> tuple[str, str]:
        r = self._post({"action": "key", "provider": provider})
        return r.get("kind") or "key", r.get("key") or ""

    def key(self, provider: str) -> str:
        return self.credential(provider)[1]


class NoStore:
    """A hosted lab nobody signed in for: no keys, the default time limit."""

    def settings(self) -> dict:
        return {"run_minutes": DEFAULT_MINUTES, "connections": {}}

    def _no(self, *a):
        raise RuntimeError("sign in on the website to change your settings")

    set_minutes = save_key = save_login = update_login = remove_key = _no

    def credential(self, provider: str) -> tuple[str, str]:
        return "key", ""

    def key(self, provider: str) -> str:
        return ""


_store = None


def store():
    """The website's store for a signed-in owner's lab, else this computer's file."""
    global _store
    if _store is None:
        site, secret = os.environ.get("WETLAB_WEBSITE_URL", ""), os.environ.get("LAB_LINK_SECRET", "")
        user = os.environ.get("WETLAB_OWNER_USER", "")
        if site and secret and user:
            _store = WebsiteStore(site, secret, user)
        elif os.environ.get("WETLAB_LAB_ID"):
            _store = NoStore()          # a hosted lab with no signed-in owner: nowhere safe to keep keys
        else:
            _store = LocalStore(pathlib.Path(os.environ.get("WETLAB_ACCOUNT_FILE")
                                             or pathlib.Path.home() / ".wetlab" / "account.json"))
    return _store


# ------------------------------------------------------------------ what the server calls
_cache: dict = {}


def settings(fresh: bool = False) -> dict:
    """{"run_minutes", "connections": {provider: {"last4", "connected_at", "spent_usd"?}}}."""
    if fresh or "s" not in _cache:
        _cache["s"] = store().settings()
    return _cache["s"]


def connected() -> set[str]:
    try:
        return set(settings()["connections"])
    except RuntimeError:
        return set()


def run_minutes() -> int:
    try:
        return int(settings()["run_minutes"])
    except (RuntimeError, ValueError, TypeError):
        return DEFAULT_MINUTES


def set_minutes(n) -> dict:
    store().set_minutes(_minutes(n))
    return settings(fresh=True)


def connect(provider: str, key: str) -> str | None:
    """Check the key with its company, then save it. None if saved, else why not."""
    if provider not in PROVIDERS:
        return "unknown company"
    key = (key or "").strip()
    err = check_key(provider, key)
    if err:
        return err
    store().save_key(provider, key)
    settings(fresh=True)
    return None


def disconnect(provider: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError("unknown company")
    store().remove_key(provider)
    return settings(fresh=True)


def key_for(agent: str) -> str:
    """The owner's key for the company that runs this agent ("" if none is saved)."""
    return credential_for(agent)[1]


def credential_for(agent: str) -> tuple[str, str]:
    """(kind, secret) for the company that runs this agent: ("key", an API key), ("chatgpt",
    Codex's login file) or ("key", "") if nothing is saved."""
    p = AGENT_PROVIDER.get(agent)
    return store().credential(p) if p else ("key", "")


# ------------------------------------------------------------------ ChatGPT sign-in (OpenAI)
def login_email(login: str) -> str:
    """The email in Codex's login file (its ID token's claims), "" if there is none. Only shown
    to its owner; the token is OpenAI's and isn't checked here."""
    try:
        tok = json.loads(login)["tokens"]["id_token"]
        part = tok.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return ""
    email = claims.get("email") or (claims.get("https://api.openai.com/profile") or {}).get("email") or ""
    return str(email)[:200]


def check_login(login: str) -> str | None:
    """None if this looks like Codex's ChatGPT login file, else why not."""
    try:
        d = json.loads(login)
        ok = isinstance(d, dict) and isinstance(d.get("tokens"), dict) and bool(d["tokens"].get("refresh_token"))
    except ValueError:
        ok = False
    if not ok or len(login) > 20000:
        return "Codex didn't finish signing in to ChatGPT. Try again."
    return None


def connect_chatgpt(login: str) -> str | None:
    """Save Codex's ChatGPT login file as the OpenAI connection. None if saved, else why not."""
    err = check_login(login)
    if err:
        return err
    store().save_login("openai", login, login_email(login))
    settings(fresh=True)
    return None


def update_login(provider: str, login: str):
    """Codex refreshed its ChatGPT tokens during a run: keep the new file."""
    if check_login(login) is None:
        store().update_login(provider, login)
