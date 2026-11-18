"""Describe a scene: a person types what they want ("a robot making breakfast in a kitchen"),
a language model on their own key picks the robots and objects from our catalog, the person
checks that list, and the model then writes a layout plan that the server builds on a free
spot of the floor: robots first (each on its own station table), then furniture, then the
objects, every one put down with the same drop check as drag and drop (PlaygroundSim.support).

Models: the owner's own Anthropic or OpenAI key (Settings > General); on a computer of one's
own, ANTHROPIC_API_KEY / OPENAI_API_KEY too. With one company connected its most capable model
is used; with both, the page shows a picker. An OpenAI connection made by ChatGPT sign-in
(Codex's login, not an API key) asks through Codex instead (`codex exec`, where task runs go:
a Modal Sandbox on the hosted site), on the person's ChatGPT plan. Devin and Jev can't do this (Devin is a coding
agent that is slow and costly for one answer; Jev only answers moves for a robot).

WETLAB_SCENEGEN_FAKE=1 answers without any model (tests, screenshots)."""
from __future__ import annotations

import base64
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import accounts as ACCT
from . import catalog
from . import world as W
from wetlabsim import scene as WS

MAX_ROBOTS = 4
MAX_EACH = 6          # copies of one object a scene may ask for
MAX_ITEMS = 40        # objects in one scene, all told
FIX_ROUNDS = 2        # look-and-fix rounds after a v2 scene is built

# The models that can build a scene, by company, most capable first (the default).
SCENE_MODELS = [
    {"id": "claude-fable-5-2", "label": "Claude Fable 5.2", "provider": "anthropic"},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "provider": "anthropic"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "provider": "anthropic"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "provider": "anthropic"},
    {"id": "gpt-6-astra", "label": "GPT-6 Astra", "provider": "openai"},
    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol", "provider": "openai"},
    {"id": "gpt-6.1-terra", "label": "GPT-6.1 Terra", "provider": "openai"},
    {"id": "gpt-6-sol", "label": "GPT-6 Sol", "provider": "openai"},
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "provider": "openai"},
]
# A task run's model (server.MODELS ids) as the scene model it is, for "the last model you used".
FROM_RUN = {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"}
_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
_AGENT = {"anthropic": "claude", "openai": "codex"}


def fake() -> bool:
    return os.environ.get("WETLAB_SCENEGEN_FAKE", "") not in ("", "0")


def _cred(provider: str, public: bool) -> tuple[str, str]:
    """("key", an API key) or ("chatgpt", Codex's login file) for this company, or ("key", "")."""
    try:
        kind, k = ACCT.credential_for(_AGENT[provider])
    except Exception:  # noqa: BLE001      no store reachable: no saved key
        kind, k = "key", ""
    if k:
        return kind, k
    return "key", ("" if public else os.environ.get(_ENV[provider], ""))


def _key(provider: str, public: bool) -> str:
    return _cred(provider, public)[1]


def providers(public: bool) -> list[str]:
    """The companies a scene can be built with here: connected in Settings (or, on one's own
    computer, an API key in the environment)."""
    if fake():
        return ["anthropic", "openai"]
    try:
        conn = ACCT.connected()
    except Exception:  # noqa: BLE001
        conn = set()
    return [p for p in ("anthropic", "openai") if p in conn or (not public and os.environ.get(_ENV[p]))]


def models(public: bool) -> list[dict]:
    have = providers(public)
    out, seen = [], set()
    for m in SCENE_MODELS:
        if m["provider"] in have:
            out.append({**m, "default": m["provider"] not in seen})
            seen.add(m["provider"])
    return out


# ------------------------------------------------------------------ asking a model
class ModelError(RuntimeError):
    pass


USAGE: dict[str, list[int]] = {}      # model -> [input tokens, output tokens], this process (for the test runs)


def _count(model: str, out: dict):
    u = out.get("usage") or {}
    i = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    o = u.get("output_tokens", 0)
    t = USAGE.setdefault(model, [0, 0])
    t[0] += i
    t[1] += o


def _post(url: str, headers: dict, body: dict, timeout: float = 240.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        raise ModelError(f"the model's company said no ({e.code}{': ' + msg[:200] if msg else ''})") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"couldn't reach the model ({e})") from None


def _anthropic(model: str, system: str, user: str, key: str, effort: str, images=()) -> str:
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(b).decode()}} for b in images]
    content.append({"type": "text", "text": user})
    body = {"model": model, "max_tokens": 32000, "system": system,
            "messages": [{"role": "user", "content": content}], "output_config": {"effort": effort}}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        out = _post("https://api.anthropic.com/v1/messages", headers, body)
    except ModelError as e:
        if "(400" not in str(e):
            raise
        body.pop("output_config")          # a model without effort levels
        out = _post("https://api.anthropic.com/v1/messages", headers, body)
    _count(model, out)
    if out.get("stop_reason") == "refusal":
        raise ModelError("the model declined this request")
    return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")


def _openai(model: str, system: str, user: str, key: str, effort: str, images=()) -> str:
    inp = user
    if images:
        inp = [{"role": "user", "content": [
            *({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}
              for b in images), {"type": "input_text", "text": user}]}]
    body = {"model": model, "instructions": system, "input": inp, "max_output_tokens": 32000,
            "reasoning": {"effort": effort}}
    headers = {"authorization": f"Bearer {key}"}
    try:
        out = _post("https://api.openai.com/v1/responses", headers, body)
    except ModelError as e:
        if "(400" not in str(e):
            raise
        body.pop("reasoning")
        out = _post("https://api.openai.com/v1/responses", headers, body)
    _count(model, out)
    if out.get("output_text"):
        return out["output_text"]
    return "".join(c.get("text", "") for o in out.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") in ("output_text", "text"))


WHERE = "local"     # where Codex runs for a ChatGPT sign-in: "local", or "modal" (server.RUN_LAUNCHER)
CODEX_TIMEOUT = 300


def _codex_cmd(model: str, effort: str, out: str, jail: bool, images=()) -> list:
    return ["codex", "exec", "--skip-git-repo-check", *(a for p in images for a in ("--image", p)),
            *(["--dangerously-bypass-approvals-and-sandbox"] if jail else ["--sandbox", "read-only"]),
            "--model", model, "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'cli_auth_credentials_store="file"', "-c", 'forced_login_method="chatgpt"',
            "--output-last-message", out]


def _codex(model: str, system: str, user: str, login: str, effort: str, images=()) -> str:
    """One answer from an OpenAI model through Codex, signed in with the person's ChatGPT login
    file (the OpenAI API takes API keys only). Codex may refresh the login's tokens: the new file
    is kept, as after a run."""
    prompt = (system + "\n\n" + user + "\n\nDon't run any commands or change any files: answer with "
              "the JSON only, as your final message.")
    if WHERE == "modal":
        text, new = _codex_modal(model, prompt, login, effort, images)
    else:
        text, new = _codex_local(model, prompt, login, effort, images)
    if new and new.strip() != login.strip():
        try:
            ACCT.update_login("openai", new)
        except Exception as e:  # noqa: BLE001
            print("could not keep Codex's refreshed login:", e)
    if not text.strip():
        raise ModelError("Codex gave no answer (is the ChatGPT sign-in still good? Try signing in again in Settings)")
    return text


def _codex_local(model: str, prompt: str, login: str, effort: str, images=()) -> tuple[str, str]:
    import shutil
    import subprocess
    import tempfile
    home = tempfile.mkdtemp(prefix="wetlab-scene-codex-")
    try:
        os.chmod(home, 0o700)
        auth = os.path.join(home, "auth.json")
        with open(os.open(auth, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(login)
        out = os.path.join(home, "answer.txt")
        pics = []
        for k, b in enumerate(images):          # pictures go in with --image
            pics.append(os.path.join(home, f"picture{k + 1}.jpg"))
            with open(pics[-1], "wb") as f:
                f.write(b)
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL")}
        env.update(CODEX_HOME=home, NO_COLOR="1")
        try:
            p = subprocess.run(_codex_cmd(model, effort, out, jail=False, images=pics) + [prompt], env=env, cwd=home,
                               capture_output=True, text=True, timeout=CODEX_TIMEOUT, stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            raise ModelError("Codex isn't installed on this machine (npm install -g @openai/codex)") from None
        except subprocess.TimeoutExpired:
            raise ModelError("Codex took too long to answer") from None
        text = open(out).read() if os.path.exists(out) else ""
        if p.returncode != 0 and not text:
            tail = " ".join((p.stderr or p.stdout or "").strip().splitlines()[-2:])[:300]
            raise ModelError(f"Codex couldn't answer{': ' + tail if tail else ''}")
        return text, open(auth).read()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _claude_plan(model: str, system: str, user: str, images=()) -> str:
    """One answer from Claude through the Claude Code CLI signed in with a Claude plan, on this
    computer only (WETLAB_SCENE_CLAUDE_PLAN=1, for test rounds): no API key, no API charges."""
    import shutil
    import subprocess
    import tempfile
    home = tempfile.mkdtemp(prefix="wetlab-scene-claude-")
    try:
        pics = []
        for k, b in enumerate(images):
            pics.append(os.path.join(home, f"picture{k + 1}.jpg"))
            with open(pics[-1], "wb") as f:
                f.write(b)
        prompt = user
        if pics:
            prompt = ("First look at these pictures of the scene with the Read tool: "
                      + ", ".join(pics) + "\n\n" + user)
        prompt += "\n\nDon't change any files: answer with the JSON only, as your final message."
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                                                  "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK")}
        # the prompt goes in on stdin (the tool lists take every word after them)
        cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--system-prompt", system,
               "--tools", "Read", "--allowedTools", "Read"]
        try:
            p = subprocess.run(cmd, env=env, cwd=home, capture_output=True, text=True,
                               timeout=CODEX_TIMEOUT, input=prompt)
        except FileNotFoundError:
            raise ModelError("Claude Code isn't installed on this machine") from None
        except subprocess.TimeoutExpired:
            raise ModelError("Claude Code took too long to answer") from None
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            tail = " ".join((p.stderr or p.stdout or "").strip().splitlines()[-2:])[:300]
            raise ModelError(f"Claude Code couldn't answer{': ' + tail if tail else ''}") from None
        if out.get("is_error"):
            raise ModelError(f"Claude Code couldn't answer: {str(out.get('result', ''))[:300]}")
        _count(model + " (Claude plan)", out)
        return str(out.get("result") or "")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _codex_modal(model: str, prompt: str, login: str, effort: str, images=()) -> tuple[str, str]:
    """The same, in a Modal Sandbox with the agents' image, reaching ChatGPT only."""
    import modal

    from wetlabsim.launchers import CHATGPT_HOSTS, ModalSandboxLauncher
    app = modal.App.lookup(ModalSandboxLauncher.APP, create_if_missing=True)
    sb = modal.Sandbox.create("sleep", "infinity", app=app, image=ModalSandboxLauncher.image(),
                              timeout=CODEX_TIMEOUT + 120, cpu=0.5, memory=1024,
                              outbound_domain_allowlist=CHATGPT_HOSTS)
    try:
        sb.exec("mkdir", "-p", "/tmp/codex", "/tmp/w").wait()
        sb.filesystem.write_bytes(login.encode(), "/tmp/codex/auth.json")
        sb.exec("chmod", "600", "/tmp/codex/auth.json").wait()
        pics = []
        for k, b in enumerate(images):
            pics.append(f"/tmp/w/picture{k + 1}.jpg")
            sb.filesystem.write_bytes(b, pics[-1])
        proc = sb.exec(*_codex_cmd(model, effort, "/tmp/w/answer.txt", jail=True, images=pics), prompt, workdir="/tmp/w",
                       env={"CODEX_HOME": "/tmp/codex", "NO_COLOR": "1"}, timeout=CODEX_TIMEOUT)
        # Close Codex's input right away: `codex exec` reads more of the prompt from a piped stdin
        # until it ends, and a Sandbox process's stdin stays open, so Codex sat waiting until it
        # timed out ("Reading additional input from stdin..."). The local path uses DEVNULL.
        proc.stdin.write_eof()
        proc.stdin.drain()
        log = proc.stdout.read() + proc.stderr.read()
        proc.wait()
        try:
            text = sb.filesystem.read_bytes("/tmp/w/answer.txt").decode()
        except Exception:  # noqa: BLE001
            text = ""
        if proc.returncode != 0 and not text:
            tail = " ".join(log.strip().splitlines()[-2:])[:300]
            raise ModelError(f"Codex couldn't answer{': ' + tail if tail else ''}")
        try:
            new = sb.filesystem.read_bytes("/tmp/codex/auth.json").decode()
        except Exception:  # noqa: BLE001
            new = ""
        return text, new
    finally:
        try:
            sb.terminate()
        except Exception:  # noqa: BLE001
            pass


def can_see(model_id: str, public: bool) -> bool:
    """Whether this model can be sent pictures here (by API key, or through Codex's --image)."""
    return any(m["id"] == model_id for m in SCENE_MODELS)


def ask_json(model_id: str, system: str, user: str, public: bool, effort: str = "medium", images=()) -> dict:
    m = next((m for m in SCENE_MODELS if m["id"] == model_id), None)
    if m is None:
        raise ModelError("that model can't build scenes")
    if m["provider"] == "anthropic" and not public and os.environ.get("WETLAB_SCENE_CLAUDE_PLAN"):
        # on one's own computer: through the Claude Code app's own sign-in (a Claude plan)
        return parse_json(_claude_plan(m["id"], system, user, images))
    kind, key = _cred(m["provider"], public)
    if not key:
        label = ACCT.PROVIDERS[m["provider"]]["label"]
        raise ModelError(f"connect your {label} API key in Settings to use {m['label']}")
    if kind == "chatgpt":
        text = _codex(m["id"], system, user, key, effort, images)
        USAGE.setdefault(m["id"] + " (ChatGPT plan)", [0, 0])[0] += 1     # calls: Codex reports no tokens
    else:
        call = _anthropic if m["provider"] == "anthropic" else _openai
        text = call(m["id"], system, user, key, effort, images)
    return parse_json(text)


def _post_stream(url: str, headers: dict, body: dict, timeout: float = 240.0):
    """The events of a streamed answer (server-sent events), as dicts."""
    req = urllib.request.Request(url, data=json.dumps({**body, "stream": True}).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data and data != "[DONE]":
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError:
                            continue
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        raise ModelError(f"the model's company said no ({e.code}{': ' + msg[:200] if msg else ''})") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"couldn't reach the model ({e})") from None


def _anthropic_stream(model: str, system: str, user: str, key: str, effort: str):
    body = {"model": model, "max_tokens": 32000, "system": system,
            "messages": [{"role": "user", "content": user}], "output_config": {"effort": effort}}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    usage = {}
    for ev in _post_stream("https://api.anthropic.com/v1/messages", headers, body):
        t = ev.get("type")
        if t == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
            yield ev["delta"].get("text", "")
        elif t == "message_start":
            usage.update((ev.get("message") or {}).get("usage") or {})
        elif t == "message_delta":
            usage.update(ev.get("usage") or {})
            if (ev.get("delta") or {}).get("stop_reason") == "refusal":
                raise ModelError("the model declined this request")
        elif t == "error":
            raise ModelError(f"the model stopped: {(ev.get('error') or {}).get('message', '')[:200]}")
    _count(model, {"usage": usage})


def _openai_stream(model: str, system: str, user: str, key: str, effort: str):
    body = {"model": model, "instructions": system, "input": user, "max_output_tokens": 32000,
            "reasoning": {"effort": effort}}
    for ev in _post_stream("https://api.openai.com/v1/responses", {"authorization": f"Bearer {key}"}, body):
        t = ev.get("type")
        if t == "response.output_text.delta":
            yield ev.get("delta", "")
        elif t == "response.completed":
            _count(model, ev.get("response") or {})
        elif t in ("error", "response.failed"):
            raise ModelError("the model stopped partway")


def _claude_plan_stream(model: str, system: str, user: str):
    """As _claude_plan, the words as they come (Claude Code's stream-json with partial messages)."""
    import subprocess
    import tempfile
    home = tempfile.mkdtemp(prefix="wetlab-scene-claude-")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                                              "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK")}
    cmd = ["claude", "-p", "--model", model, "--output-format", "stream-json", "--include-partial-messages",
           "--verbose", "--system-prompt", system, "--tools", ""]
    try:
        p = subprocess.Popen(cmd, env=env, cwd=home, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise ModelError("Claude Code isn't installed on this machine") from None
    try:
        p.stdin.write(user + "\n\nAnswer with the JSON only.")
        p.stdin.close()
        t0 = time.time()
        for line in p.stdout:
            if time.time() - t0 > CODEX_TIMEOUT:
                raise ModelError("Claude Code took too long to answer")
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            e = d.get("event") or {}
            if d.get("type") == "stream_event" and e.get("type") == "content_block_delta" \
                    and (e.get("delta") or {}).get("type") == "text_delta":
                yield e["delta"].get("text", "")
            elif d.get("type") == "result":
                if d.get("is_error"):
                    raise ModelError(f"Claude Code couldn't answer: {str(d.get('result', ''))[:300]}")
                _count(model + " (Claude plan)", d)
    finally:
        if p.poll() is None:
            p.kill()
        import shutil
        shutil.rmtree(home, ignore_errors=True)


def ask_stream(model_id: str, system: str, user: str, public: bool, effort: str = "medium"):
    """A model's answer as it is written, piece by piece (all at once where the route can't
    stream: Codex with a ChatGPT sign-in)."""
    m = next((m for m in SCENE_MODELS if m["id"] == model_id), None)
    if m is None:
        raise ModelError("that model can't build scenes")
    if m["provider"] == "anthropic" and not public and os.environ.get("WETLAB_SCENE_CLAUDE_PLAN"):
        yield from _claude_plan_stream(m["id"], system, user)
        return
    kind, key = _cred(m["provider"], public)
    if not key:
        label = ACCT.PROVIDERS[m["provider"]]["label"]
        raise ModelError(f"connect your {label} API key in Settings to use {m['label']}")
    if kind == "chatgpt":
        yield _codex(m["id"], system, user, key, effort)
        USAGE.setdefault(m["id"] + " (ChatGPT plan)", [0, 0])[0] += 1
    elif m["provider"] == "anthropic":
        yield from _anthropic_stream(m["id"], system, user, key, effort)
    else:
        yield from _openai_stream(m["id"], system, user, key, effort)


def stream_items(text: str, key: str) -> tuple[list[dict], bool, bool]:
    """From a JSON answer still being written: the finished entries of its list `key` so far,
    whether that list has started, and whether it is closed."""
    m = re.search(r'"%s"\s*:\s*\[' % re.escape(key), text)
    if not m:
        return [], False, False
    out, depth, start, in_str, esc = [], 0, None, False, False
    for i in range(m.end(), len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    out.append(json.loads(text[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
        elif c == "]" and depth == 0:
            return out, True, True
    return out, True, False


def parse_json(text: str) -> dict:
    """The JSON object in a model's answer (alone, or in a ``` block, or among words)."""
    t = text.strip()
    f = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if f:
        t = f.group(1)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b < a:
        raise ModelError("the model's answer had no plan in it")
    try:
        return json.loads(t[a:b + 1])
    except json.JSONDecodeError:
        raise ModelError("the model's answer wasn't readable") from None


# ------------------------------------------------------------------ what the model is told
def _robots_text() -> str:
    return "\n".join(f"- {r['id']}: {r['label']} by {r['maker']}, {r.get('arms', 1)} arm(s), reach "
                     f"{r['reach_mm']} mm, payload {r['payload_kg']} kg" for r in catalog.robots())


def _catalog_rows() -> list[dict]:
    return [c for c in catalog.available() if c["id"] not in ("table_packing",)]


def _objects_text() -> str:
    rows = []
    for c in _catalog_rows():
        sx, sy, sz = (round(100 * v) for v in c["size"])
        kind = "furniture (stands on the floor)" if c["fixed"] else ("soft" if c["soft"] else "object")
        rows.append(f"- {c['id']}: {c['label']} | {c['tab']} | {sx}x{sy}x{sz} cm | {kind}")
    return "\n".join(rows)


PICK_SYSTEM = """You set up scenes in a robot physics playground. A scene is one or more robots \
plus the objects they need for a task, laid out somewhere: a lab bench, a kitchen, a workshop...

Only these robots exist (id: what it is):
{robots}

Only these objects exist (id: label | group | size | kind):
{objects}

Read the person's request and choose:
- robots: which robots and how many of each, 1 to {max_robots} robots in all. If they name a \
robot or a number, follow it. Otherwise pick what suits the task (one robot unless the task \
clearly needs more; a two-arm robot for two-handed work).
- items: the objects (and furniture) from the list that the scene needs, with how many of each \
(1 to {max_each}). Use only ids from the list. Include what makes the place feel right, but keep \
it to what fits: about 4 to 16 objects in all.
- missing: things the request asks for that the list doesn't have, each with "instead": the id \
of a listed object used in its place, or "" if nothing fits.
- title: a short name for the scene, 2 to 4 words.
- task: one sentence, the task the robot(s) will be given, in plain words.

Answer with JSON only, exactly this shape:
{{"title": "...", "robots": [{{"robot": "franka", "count": 1}}], "items": [{{"id": "mug", "count": 1}}], \
"missing": [{{"name": "bread", "instead": ""}}], "task": "..."}}"""

LAYOUT_SYSTEM = """You lay out a scene in a robot physics playground (MuJoCo, metres, z up). \
Write a short layout plan, then exact positions. You decide anything the person didn't say: \
where things go, which way they face, what goes on which surface.

How the playground works:
- Every robot stands on its own station table, near one long edge, facing across it (+x in \
the station's own frame). A station is "table" (a packing table 1.87 m along x by 1.22 m along \
y, top 0.99 m high, the robot's base at x -0.42, y 0) or "wetlab" (a stainless lab bench 0.70 m \
along x by 1.80 m along y, top 0.85 m high, the robot's base at x -0.20, y 0) or "island" (a \
kitchen island 0.63 m along x by 1.24 m along y, top 0.90 m high, the robot's base at x -0.17, y 0) \
or "counter" (a kitchen counter over cabinets, 0.60 m along x by 2.30 m along y, worktop 0.75 m high, \
the robot's base at x -0.15, y 0). Use "island" or "counter" for kitchens. A Unitree G1 humanoid \
stands on the floor at its station's near edge instead. An ALOHA stands in \
the middle of its station with its two arm bases at y -0.47 and +0.47. The FR3 Duo has two arms on \
one base at x -0.42.
- A station's position is its table's centre on the floor, in the scene's own frame (x, y, \
metres), and yaw is its turn about the vertical in degrees. Keep stations at least 0.5 m apart.
- The room's shape: the robots' tables in the middle; floor furniture round them like the walls \
of a room, behind the robots (their -x side) and along the two sides (their -y and +y sides), \
fronts facing in, 1 to 2.5 m from the tables. Keep the side the robots face (+x, past the far \
edge of their tables) clear of anything taller than the tables: people and the cameras look in \
from there. A tall unit (fridge, cabinet, rack, hood) never stands between a robot and that side.
- A fence or guard needs enough panels to close the cell; with only one or two panels, stand \
them in one line behind the robot, not loose on the floor.
- Small things never go on the bare floor (only bins, buckets, boxes, signs and things made to \
stand there); put them on a table, counter or shelf.
- Furniture (the items marked as furniture) stands on the floor, in the scene's frame: never \
over a station table, and at least 0.3 m from every table and from other furniture, except:
  - Furniture that belongs together stands side by side in one straight run, fronts the same \
way, backs on one line, with "gap": 0.02: a kitchen run (base cabinets, counter, sink, stove, \
dishwasher, fridge), a row of server racks, a conveyor line, a lab bench run. A room should read \
as one fitted place, not pieces dotted about.
  - Furniture the task uses or feeds (a fridge to load, a rack to plug into, a machine to tend, a \
shelf to stock, the sink and dishwasher of a dish line, the conveyor a robot loads, the pallet it stacks) stands right beside the robot's table with "gap": 0.05, its front facing the \
robot, the part the robot works on within 0.8 m of the robot's base, at a\
side end of the table (its -y or +y end), not past its far edge. Better still, use small \
furniture on the table (below) when one fits the request.
- Objects for the robots' task go on their station's table, within reach of the robot: station \
frame x from -0.15 to 0.75 and y from -0.5 to 0.5 (for the wet lab bench x from -0.1 to 0.3 and y \
from -0.8 to 0.8; the island x from -0.05 to 0.25, y from -0.55 to 0.55; the counter x from -0.05 \
to 0.25, y from -1.05 to 1.05), at least 0.25 m from the robot's base. Small things can go in a hollow object \
(an apple in a bowl): give them the same spot. Objects can also go on top of a piece of furniture \
(its index, and dx, dy from its centre) or on the floor (scene frame). Things the request \
says start in a container (parts in a tote, bottles in a crate, fruit in a basket, boxes on a \
shelf) must go in it with "on": "inside" (below), never loose beside it.
- Inside another thing (a mug in a drawer, cans on a shelf's bottom level, parts in a tote or \
an open box): "on": "inside", "object": the index (from 0) in your "objects" list of the cabinet, shelf \
or box (or "furniture": its index in "furniture"), "level": 1 for the lowest space inside it, 2 \
for the next one up, -1 for the highest (a top drawer), and dx, dy from its centre to spread \
several things out. The top surface of something is not "inside": use "furniture" for that, or \
the same spot as the thing for a hollow object.
- Leave space between objects (about their size plus 3 cm) so a gripper can get to each, \
unless the request asks for clutter: then heap them into one patch about 40 by 40 cm, 1 to \
2 cm apart, at different turns, mixing sizes, still each reachable.
- Small furniture (a little cabinet with drawers, a microwave, a short fridge) can stand on a \
station's table like an object: list it under "objects" with "on": "station", its front facing \
the robot. Only these can: {tabletop}.
- Which way things face: instead of a yaw you may give "face": what the thing's front (its door, \
controls, opening) should turn towards: "station 0" (that station's robot), or [x, y] (a point in \
the scene's frame; for an object on a station, in that station's frame). Use it for furniture \
and appliances so their fronts face the robots and the room, not a wall.

The scene's robots (each entry is one station): {robots}
The scene's objects: {items}
Sizes (x by y by z, cm): {sizes}

Before any position, write the layout rationale ("rationale" in the answer): reason the layout out from the task, not from the list of objects. Every position you then give must follow from it; if a position doesn't fit the rationale, change the position.

Answer with JSON only, exactly this shape:
{{"rationale": {{"task_steps": "what the robot does, step by step, and what it must reach or open at each step",
                "in_reach": "each thing the task uses: where it starts and why the arm reaches it there",
                "task_furniture": "each piece of furniture the task uses or feeds: which side of the robot's table it stands at, its front to the arm, and why",
                "room": "where each zone goes relative to the robots and why (what a person there would keep together, what lines the walls, what stays clear)",
                "starts_in": "what starts inside or on top of what, with the level or shelf, as the request says",
                "left_out": "anything left out or swapped for something else, and why (or 'nothing')",
                "checks": "the gaps and overlaps you checked: anything that would collide, block a door or a camera, or sit out of reach, and how you moved it"}},
 "plan": "2 to 4 plain sentences for the person on the layout and the choices you made",
 "stations": [{{"robot": "franka", "kind": "table", "x": 0, "y": 0, "yaw": 0}}],
 "furniture": [{{"item": "refrigerator", "x": 2.0, "y": 1.2, "face": "station 0", "gap": 0.15}}],
 "objects": [{{"item": "mug", "on": "station", "station": 0, "x": 0.3, "y": 0.1, "yaw": 0}},
             {{"item": "kettle", "on": "furniture", "furniture": 0, "dx": 0, "dy": 0, "yaw": 0}},
             {{"item": "waste_bin", "on": "floor", "x": 1.5, "y": -1.0, "yaw": 0}},
             {{"item": "can", "on": "inside", "object": 0, "level": 1, "dx": 0.05, "dy": 0, "yaw": 0}}],
 "task": "the robot's task, one sentence"}}
When the request wants the stations to match ("identical", "the same setup"), share the \
objects out evenly and put each station's set at the same spots in its own frame.
List every station and every object exactly once per copy (an item asked for twice appears \
twice). Put furniture items in "furniture" only."""


def pick_messages(prompt: str) -> tuple[str, str]:
    sys_ = PICK_SYSTEM.format(robots=_robots_text(), objects=_objects_text(), max_robots=MAX_ROBOTS,
                              max_each=MAX_EACH)
    return sys_, f"The person's request:\n{prompt.strip()[:2000]}"


def clean_pick(raw: dict) -> dict:
    """The model's pick, kept to real robots and objects and our limits."""
    rids = {r["id"] for r in catalog.robots()}
    rows = {c["id"]: c for c in _catalog_rows()}
    robots, total = [], 0
    for r in raw.get("robots") or []:
        rid, n = str((r or {}).get("robot", "")), _int((r or {}).get("count"), 1)
        if rid in rids and n > 0 and total < MAX_ROBOTS and rid not in [x["robot"] for x in robots]:
            n = min(n, MAX_ROBOTS - total)
            robots.append({"robot": rid, "count": n})
            total += n
    items, n_items = [], 0
    for it in raw.get("items") or []:
        iid, n = str((it or {}).get("id", "")), _int((it or {}).get("count"), 1)
        if iid in rows and n > 0 and iid not in [x["id"] for x in items] and n_items < MAX_ITEMS:
            n = min(n, MAX_EACH, MAX_ITEMS - n_items)
            items.append({"id": iid, "count": n})
            n_items += n
    missing = []
    for m in raw.get("missing") or []:
        name = str((m or {}).get("name", "")).strip()[:40]
        inst = str((m or {}).get("instead", ""))
        if name:
            missing.append({"name": name, "instead": inst if inst in rows else ""})
    return {"title": (str(raw.get("title") or "").strip() or "New scene")[:40],
            "robots": robots, "items": items, "missing": missing[:8],
            "task": str(raw.get("task") or "").strip()[:600]}


def _int(v, d: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def layout_messages(prompt: str, pick: dict) -> tuple[str, str]:
    robots = [r["robot"] for r in pick["robots"] for _ in range(r["count"])]
    items = [i["id"] for i in pick["items"] for _ in range(i["count"])]
    sizes = {i: "x".join(str(round(100 * v)) for v in catalog.meta(i)["size"]) for i in set(items)}
    furn = [i for i in set(items) if catalog.item(i)["fixed"]]
    from .scenebrief import tabletop
    sys_ = LAYOUT_SYSTEM.format(robots=json.dumps(robots), items=json.dumps(items), sizes=json.dumps(sizes),
                                tabletop=json.dumps(sorted(set(tabletop()) & set(items)) or "none in this scene"))
    from . import scenegrid
    if scenegrid.on():               # place by square on the layout grid (scenegrid.py)
        sys_ = scenegrid.system(robots, items, sorted(set(tabletop()) & set(items)))
    zones = ""
    if pick.get("brief"):            # a v2 pick (scenebrief.py): the room, its zones, each object's slot
        br = pick["brief"]
        roles = {}
        for i, k in (pick.get("slot_of") or {}).items():
            sl = br["slots"][k]
            roles[i] = {"zone": sl["zone"], "role": sl["role"], "what": sl["want"] or sl["node"]}
        zones = (f"Room: {br['room']}\nZones (lay the scene out by these; the 'robot' zone is the robots' own "
                 f"tables): {json.dumps(br['zones'])}\nEach object's zone and role (role task: on the robot's table, "
                 f"within reach; role scene: in its zone, making the place look real): {json.dumps(roles)}\n"
                 "Make it look like a real place of that kind: furniture against the zone's edges with fronts "
                 "facing the room, appliances on counters, things grouped the way people keep them.\n")
        from .scene_notes import note
        ref = note(prompt, br["room"])
        if ref:
            zones += f"How such a place is really laid out (follow this where the objects allow):\n{ref}\n"
    user = (f"The person's request:\n{prompt.strip()[:2000]}\n\nScene name: {pick['title']}\n" + zones +
            f"Furniture among the objects: {json.dumps(furn)}\n"
            + (f"Things we don't have (leave them out): {json.dumps([m['name'] for m in pick['missing']])}\n"
               if pick.get("missing") else "")
            + (f"Task in mind: {pick['task']}\n" if pick.get("task") else ""))
    return sys_, user


# ------------------------------------------------------------------ fake answers (no model)
def fake_pick(prompt: str) -> dict:
    return {"title": "Kitchen breakfast", "robots": [{"robot": "fr3_duo", "count": 1}],
            "items": [{"id": i, "count": 1} for i in ("refrigerator", "workbench", "wash_basin", "toaster",
                                                       "cereal_box", "milk", "bowl", "mug", "kettle", "apple")
                      if i in {c["id"] for c in _catalog_rows()}],
            "missing": [{"name": "bread", "instead": ""}],
            "task": "Pour cereal into the bowl and put the mug next to it."}


def fake_layout(pick: dict) -> dict:
    robots = [r["robot"] for r in pick["robots"] for _ in range(r["count"])]
    items = [i["id"] for i in pick["items"] for _ in range(i["count"])]
    furn = [i for i in items if catalog.item(i)["fixed"]]
    small = [i for i in items if not catalog.item(i)["fixed"]]
    spots = [(0.25, -0.35), (0.25, 0.0), (0.25, 0.35), (0.55, -0.3), (0.55, 0.05), (0.55, 0.35),
             (0.0, -0.45), (0.0, 0.45)]
    return {"plan": "One station in the middle with the breakfast things on its table, the fridge, "
                    "sink and counter along the back.",
            "stations": [{"robot": r, "kind": "table", "x": 0, "y": 2.0 * k, "yaw": 0} for k, r in enumerate(robots)],
            "furniture": [{"item": f, "x": 2.3, "y": -1.6 + 1.6 * k, "yaw": 180} for k, f in enumerate(furn)],
            "objects": [{"item": it, "on": "station", "station": k % max(1, len(robots)),
                         "x": spots[(k // max(1, len(robots))) % len(spots)][0],
                         "y": spots[(k // max(1, len(robots))) % len(spots)][1], "yaw": 0}
                        for k, it in enumerate(small)],
            "task": pick.get("task", "")}


# Ready-made scenes (Add station, no prompt and no model): a layout in the same shape a model
# writes (metres, yaw in degrees), each station with its own task. Furniture faces the robots:
# most assets' fronts face their -y (yaw 0 faces -y); Tripo's (lab fridge, CO2 incubator,
# countertops) face +y. Objects on a station: x, y and yaw in the station's frame (the robot
# faces +x), appliances turned to face the robot.
PRESETS = {
    "kitchen": {
        "title": "Kitchen", "label": "Kitchen",
        "plan": "A kitchen: a counter along the back wall with the espresso machine, an island in the middle "
                "with the toaster, a second counter on the left with the microwave, and a humanoid at a "
                "second island by the fridge.",
        "stations": [
            {"robot": "franka", "kind": "counter", "x": 0.0, "y": 2.0, "yaw": 90,
             "task": "Put the mug under the espresso machine's spout and pull the brew lever."},
            {"robot": "fr3_duo", "kind": "island", "x": 0.0, "y": 0.2, "yaw": 90,
             "task": "Put the slice of toast in the toaster and push the lever down."},
            {"robot": "aloha", "kind": "counter", "x": -2.6, "y": 0.3, "yaw": 180,
             "task": "Open the microwave, put the bowl on the turntable, and close the door."},
            {"robot": "g1", "kind": "island", "x": 2.0, "y": -0.1, "yaw": 90,
             "task": "Put the banana and the orange in the bowl."},
        ],
        "furniture": [
            {"item": "french_door_fridge", "x": 2.05, "y": 2.0, "yaw": 0},
            {"item": "dishwasher", "x": -1.55, "y": 2.0, "yaw": 0},
            {"item": "range_oven", "x": -2.3, "y": 2.0, "yaw": 0},
            {"item": "bar_stool", "x": -0.3, "y": -0.8, "yaw": 0},
            {"item": "bar_stool", "x": 0.3, "y": -0.8, "yaw": 0},
        ],
        "objects": [
            {"item": "espresso_machine", "on": "station", "station": 0, "x": 0.12, "y": 0.5, "yaw": -90},
            {"item": "mug_white", "on": "station", "station": 0, "x": 0.12, "y": 0.2, "yaw": 0},
            {"item": "electric_kettle", "on": "station", "station": 0, "x": 0.12, "y": -0.55, "yaw": -90},
            {"item": "knife_block", "on": "station", "station": 0, "x": 0.15, "y": -0.9, "yaw": -90},
            {"item": "pop_up_toaster", "on": "station", "station": 1, "x": 0.12, "y": -0.3, "yaw": -90},
            {"item": "toast", "on": "station", "station": 1, "x": 0.12, "y": 0.05, "yaw": 0},
            {"item": "plate", "on": "station", "station": 1, "x": 0.12, "y": 0.38, "yaw": 0},
            {"item": "microwave", "on": "station", "station": 2, "x": 0.08, "y": 0.0, "yaw": -90},
            {"item": "bowl", "on": "station", "station": 2, "x": 0.2, "y": -0.3, "yaw": 0},
            {"item": "bowl", "on": "station", "station": 3, "x": 0.1, "y": 0.2, "yaw": 0},
            {"item": "banana", "on": "station", "station": 3, "x": 0.12, "y": -0.2, "yaw": 0},
            {"item": "orange", "on": "station", "station": 3, "x": 0.1, "y": -0.42, "yaw": 0},
            {"item": "milk", "on": "station", "station": 3, "x": 0.12, "y": 0.45, "yaw": 0},
            {"item": "pedal_bin", "on": "floor", "x": 3.1, "y": 0.6, "yaw": 90},
        ],
    },
    "wetlab": {
        "title": "Wet lab", "label": "Wet lab",
        "plan": "A wet lab: four stainless benches in two rows, with a biosafety cabinet, fume hood, CO2 "
                "incubator and lab fridge along the back wall.",
        "stations": [
            {"robot": "ur5e", "kind": "wetlab", "x": 0.0, "y": 0.0, "yaw": 90,
             "task": "Open the centrifuge, put the two 15 ml tubes in opposite slots of the rotor so it is balanced, and close the lid."},
            {"robot": "franka", "kind": "wetlab", "x": 2.4, "y": 0.0, "yaw": 90,
             "task": "Open the plate reader's drawer, put the 96-well plate in it, and close the drawer."},
            {"robot": "fr3_duo", "kind": "wetlab", "x": -2.4, "y": 0.0, "yaw": 90,
             "task": "Hold the jar and unscrew its lid all the way."},
            {"robot": "g1", "kind": "wetlab", "x": 0.0, "y": -2.3, "yaw": 90,
             "task": "Move the four 15 ml tubes into the blue rack."},
        ],
        "furniture": [
            {"item": "biosafety_cabinet", "x": -2.4, "y": 1.95, "yaw": 0},
            {"item": "fume_hood", "x": -0.8, "y": 1.95, "yaw": 0},
            {"item": "co2_incubator", "x": 0.6, "y": 1.95, "yaw": 180},
            {"item": "lab_fridge", "x": 1.75, "y": 1.95, "yaw": 180},
        ],
        "objects": [
            {"item": "centrifuge_5430", "on": "station", "station": 0, "x": 0.12, "y": -0.5, "yaw": -90},
            {"item": "tube_rack", "on": "station", "station": 0, "x": 0.15, "y": 0.2, "yaw": 0},
            {"item": "tube_15ml", "on": "station", "station": 0, "x": 0.1, "y": 0.5, "yaw": 0},
            {"item": "tube_15ml", "on": "station", "station": 0, "x": 0.2, "y": 0.5, "yaw": 0},
            {"item": "plate_reader", "on": "station", "station": 1, "x": 0.12, "y": -0.5, "yaw": -90},
            {"item": "microplate_96", "on": "station", "station": 1, "x": 0.15, "y": 0.1, "yaw": 0},
            {"item": "tip_box", "on": "station", "station": 1, "x": 0.15, "y": 0.4, "yaw": 0},
            {"item": "pipette", "on": "station", "station": 1, "x": 0.18, "y": 0.6, "yaw": 0},
            {"item": "screw_top_jar", "on": "station", "station": 2, "x": 0.12, "y": -0.15, "yaw": 0},
            {"item": "beaker_500", "on": "station", "station": 2, "x": 0.15, "y": -0.5, "yaw": 0},
            {"item": "erlenmeyer", "on": "station", "station": 2, "x": 0.15, "y": 0.25, "yaw": 0},
            {"item": "hot_plate", "on": "station", "station": 2, "x": 0.12, "y": 0.6, "yaw": -90},
            {"item": "rack_compact_blue", "on": "station", "station": 3, "x": 0.12, "y": 0.35, "yaw": 0},
            {"item": "tube_15ml", "on": "station", "station": 3, "x": 0.12, "y": -0.2, "yaw": 0},
            {"item": "tube_15ml", "on": "station", "station": 3, "x": 0.12, "y": -0.3, "yaw": 0},
            {"item": "tube_15ml", "on": "station", "station": 3, "x": 0.2, "y": -0.2, "yaw": 0},
            {"item": "tube_15ml", "on": "station", "station": 3, "x": 0.2, "y": -0.3, "yaw": 0},
            {"item": "sharps_box", "on": "station", "station": 3, "x": 0.15, "y": -0.65, "yaw": 0},
            {"item": "pedal_bin", "on": "floor", "x": 3.9, "y": 0.0, "yaw": 90},
        ],
    },
}

# The factory and the car assembly line hold many parts that rest untouched while one robot
# works: MuJoCo's sleeping ("Sleeping" in its Simulation chapter) leaves resting things out of
# the physics until something touches them. Its tolerance is the speed below which a thing counts
# as resting: 1 cm/s, since tightly fitted parts (a gear on its shaft) tremble at a few mm/s.
SLEEP = {"flag": {"sleep": True}, "option": {"sleep_tolerance": 0.01}}

PRESETS["factory"] = {
    "title": "Factory", "label": "Factory",
    "plan": "An assembly line: a roller conveyor down the middle carrying totes and boxes, six assembly "
            "benches along it, a FANUC arm stacking boxes on a pallet at the end, a wheeled humanoid that "
            "drives around the line, and pallet racks, a forklift and drums around it.",
    "settings": SLEEP,
    "stations": [
        {"robot": "franka", "kind": "table", "x": -3.2, "y": 2.05, "yaw": -90,
         "task": "Take the round pegs out of the peg block and put them in the blue crate."},
        {"robot": "ur5e", "kind": "table", "x": -1.5, "y": 2.05, "yaw": -90,
         "task": "On the assembly task board, pull out the USB plug and plug it back in."},
        {"robot": "fr3_duo", "kind": "table", "x": 0.2, "y": 2.05, "yaw": -90,
         "task": "Hold the gearbox still with one arm and turn its top knob one full turn with the other."},
        {"robot": "aloha", "kind": "table", "x": -3.2, "y": -2.05, "yaw": 90,
         "task": "Open the breaker board's clear door and switch all six breakers the other way."},
        {"robot": "piper", "kind": "table", "x": -1.5, "y": -2.05, "yaw": 90,
         "task": "Pull the USB-C cable out of the port panel and plug the HDMI cable in."},
        {"robot": "g1", "kind": "table", "x": 0.2, "y": -2.05, "yaw": 90,
         "task": "Turn the ball valve's handle a quarter turn to close the valve."},
        {"robot": "crx30ia", "kind": "pallet", "x": 2.8, "y": -1.2, "yaw": -90,
         "task": "Pick the cardboard box up off the roller conveyor with the vacuum tool and set it down on the pallet."},
        # a wheeled humanoid at the head of the line: its cell is open, so it can drive anywhere
        {"robot": "rby1", "kind": "conveyor", "x": -5.07, "y": 0.0, "yaw": 90,
         "task": "Pick up the air ratchet from the conveyor in front of you, drive around the end of the conveyor to the steel drums, and set it down on top of a drum."},
    ],
    "furniture": [
        {"item": "roller_conveyor", "x": -3.03, "y": 0.0, "yaw": 90, "gap": 0},
        {"item": "roller_conveyor", "x": -1.01, "y": 0.0, "yaw": 90, "gap": 0},
        {"item": "roller_conveyor", "x": 1.01, "y": 0.0, "yaw": 90, "gap": 0},
        {"item": "pallet_rack", "x": -3.4, "y": 5.3, "yaw": 0},
        {"item": "pallet_rack", "x": -0.2, "y": 5.3, "yaw": 0},
        {"item": "pallet", "x": 3.0, "y": 2.2, "yaw": 0},
        {"item": "forklift", "x": 3.4, "y": 4.6, "yaw": 0},
        {"item": "steel_drum", "x": -5.4, "y": 1.3, "yaw": 0},
        {"item": "steel_drum", "x": -5.4, "y": 2.15, "yaw": 0},
        {"item": "steel_drum", "x": -5.4, "y": 3.0, "yaw": 0},
        {"item": "safety_fence", "x": 4.5, "y": -0.3, "yaw": 90},
        {"item": "safety_fence", "x": 4.5, "y": -1.7, "yaw": 90},
        {"item": "safety_fence", "x": 3.6, "y": -3.0, "yaw": 0},
        {"item": "safety_fence", "x": 2.2, "y": -3.0, "yaw": 0},
        {"item": "modular_workbench", "x": -5.4, "y": -2.2, "yaw": -90},
        {"item": "shop_cart", "x": 2.3, "y": 3.9, "yaw": 0},
        {"item": "pallet_jack", "x": 4.9, "y": 3.2, "yaw": 0},
    ],
    "objects": [
        # on the conveyor (furniture 0-2: its own long side is its y)
        {"item": "lid_tote", "on": "furniture", "furniture": 0, "dx": 0.0, "dy": 0.45, "yaw": 0},
        {"item": "load_carrier", "on": "furniture", "furniture": 0, "dx": 0.0, "dy": -0.4, "yaw": 0},
        {"item": "lid_tote", "on": "furniture", "furniture": 1, "dx": 0.0, "dy": 0.0, "yaw": 0},
        {"item": "cardboard_box_flat", "on": "furniture", "furniture": 2, "dx": 0.0, "dy": 0.45, "yaw": 0},
        {"item": "cardboard_box", "on": "furniture", "furniture": 2, "dx": 0.0, "dy": -0.5, "yaw": 0},
        # boxes waiting on the spare pallet (furniture 5)
        {"item": "cardboard_box", "on": "furniture", "furniture": 5, "dx": -0.22, "dy": 0.0, "yaw": 90},
        # the benches
        {"item": "peg_kit", "on": "station", "station": 0, "x": 0.15, "y": 0.0, "yaw": 90},
        {"item": "load_carrier", "on": "station", "station": 0, "x": 0.2, "y": -0.42, "yaw": 0},
        {"item": "parts_cabinet", "on": "station", "station": 0, "x": 0.45, "y": 0.42, "yaw": -90},
        {"item": "task_board", "on": "station", "station": 1, "x": 0.2, "y": 0.0, "yaw": 0},
        {"item": "cantilever_toolbox", "on": "station", "station": 1, "x": 0.4, "y": -0.42, "yaw": 0},
        {"item": "planetary_gearbox", "on": "station", "station": 2, "x": 0.2, "y": 0.0, "yaw": 0},
        {"item": "bench_vise", "on": "station", "station": 2, "x": 0.45, "y": 0.4, "yaw": 0},
        {"item": "breaker_board", "on": "station", "station": 3, "x": 0.25, "y": 0.0, "yaw": 0},
        {"item": "connector_pack", "on": "station", "station": 4, "x": 0.1, "y": 0.0, "yaw": 0},
        {"item": "ball_valve", "on": "station", "station": 5, "x": -0.6, "y": 0.0, "yaw": 90},
        {"item": "toolbox", "on": "station", "station": 5, "x": -0.55, "y": -0.42, "yaw": 0},
        {"item": "air_ratchet", "on": "station", "station": 7, "x": -0.25, "y": 0.0, "yaw": 90},
        {"item": "load_carrier", "on": "station", "station": 7, "x": 0.0, "y": -0.6, "yaw": 0},
    ],
}

PRESETS["car"] = {
    "title": "Car assembly", "label": "Car assembly",
    "plan": "A car assembly bay: a car body in the middle with a big Comau arm that lifts the hood and "
            "windscreen onto it, a FANUC arm moving boxed parts, benches for brakes, engine parts, "
            "electrics and tools, a wheeled humanoid that drives to the car, and garage equipment around them.",
    "settings": SLEEP,
    "stations": [
        {"robot": "n220", "kind": "car", "x": 0.0, "y": 0.0, "yaw": 0,
         "task": "Pick the hood up off the pallets with the vacuum tool and lower it onto the front of the car body, over the engine bay."},
        {"robot": "crx30ia", "kind": "pallet", "x": 3.3, "y": 1.6, "yaw": 90,
         "task": "Pick the cardboard box up off the pallet with the vacuum tool and set it down on the cart."},
        {"robot": "fr3_duo", "kind": "table", "x": -3.4, "y": -4.7, "yaw": 90,
         "task": "Put the two brake pads on top of the brake rotor."},
        {"robot": "franka", "kind": "table", "x": -1.7, "y": -4.7, "yaw": 90,
         "task": "Put the oil filter and the air filter in the blue crate."},
        {"robot": "aloha", "kind": "table", "x": 0.0, "y": -4.7, "yaw": 90,
         "task": "Put the headlight bulb and the fuse in the toolbox tray."},
        {"robot": "g1", "kind": "table", "x": 1.7, "y": -4.7, "yaw": 90,
         "task": "Pick up the bottle of engine oil and stand it next to the car battery."},
        {"robot": "ur5e", "kind": "table", "x": 3.4, "y": -4.7, "yaw": 90,
         "task": "Put the four spark plugs in the blue crate."},
        # a wheeled humanoid: its cell is open, so it can drive to the car
        {"robot": "rby1", "kind": "table", "x": 4.9, "y": -0.6, "yaw": 180,
         "task": "Pick up the bottle of engine oil from your table, drive to the front of the car, and put the bottle down on the floor next to the front bumper."},
    ],
    "furniture": [
        {"item": "pallet", "x": -2.6, "y": 3.0, "yaw": 0, "gap": 0},      # 0, 1: the hood's pallets
        {"item": "pallet", "x": -2.6, "y": 3.82, "yaw": 0, "gap": 0},
        {"item": "shop_cart", "x": 4.6, "y": 1.0, "yaw": 0},
        {"item": "engine_crane", "x": -6.1, "y": -1.2, "yaw": 0},
        {"item": "engine_stand", "x": -4.3, "y": -2.7, "yaw": 0},
        {"item": "tire_rack", "x": 2.6, "y": -2.4, "yaw": 0},
        {"item": "wheel_balancer", "x": 4.4, "y": -2.3, "yaw": 0},
        {"item": "air_compressor", "x": 0.4, "y": 4.3, "yaw": 0},
        {"item": "ev_charger", "x": 2.3, "y": 4.3, "yaw": 0},
        {"item": "mechanic_cart", "x": 1.7, "y": -1.6, "yaw": 0},
        {"item": "car_dolly", "x": -2.0, "y": -2.6, "yaw": 0},
    ],
    "objects": [
        {"item": "car_hood", "on": "furniture", "furniture": 0, "dx": 0.0, "dy": 0.3, "yaw": 0, "overhang": True},
        {"item": "windscreen", "on": "floor", "x": -4.1, "y": 1.0, "yaw": 0},
        {"item": "electric_motor", "on": "floor", "x": -4.4, "y": -0.8, "yaw": 0},
        {"item": "cardboard_box_flat", "on": "station", "station": 1, "x": 0.1, "y": 0.0, "yaw": 0},
        {"item": "headlight", "on": "station", "station": 4, "x": 0.5, "y": -0.38, "yaw": 0},
        {"item": "front_bumper", "on": "floor", "x": 1.9, "y": 3.2, "yaw": 90},
        {"item": "car_tire", "on": "floor", "x": 1.5, "y": 0.9, "yaw": 0},
        {"item": "car_tire", "on": "floor", "x": 1.5, "y": -0.2, "yaw": 0},
        {"item": "wheel_rim", "on": "floor", "x": 3.5, "y": -1.6, "yaw": 0},
        {"item": "car_seat", "on": "floor", "x": -1.9, "y": -1.3, "yaw": 90},
        {"item": "floor_jack", "on": "floor", "x": 1.5, "y": -2.6, "yaw": 0},
        {"item": "jack_stand", "on": "floor", "x": -1.3, "y": 2.9, "yaw": 0},
        {"item": "jack_stand", "on": "floor", "x": -1.3, "y": 3.4, "yaw": 0},
        # the benches
        {"item": "brake_rotor", "on": "station", "station": 2, "x": 0.25, "y": 0.0, "yaw": 0},
        {"item": "brake_pad", "on": "station", "station": 2, "x": 0.2, "y": -0.38, "yaw": 0},
        {"item": "brake_pad", "on": "station", "station": 2, "x": 0.35, "y": -0.38, "yaw": 0},
        {"item": "brake_caliper", "on": "station", "station": 2, "x": 0.3, "y": 0.42, "yaw": 0},
        {"item": "wheel_hub", "on": "station", "station": 2, "x": 0.6, "y": 0.3, "yaw": 0},
        {"item": "load_carrier", "on": "station", "station": 3, "x": 0.25, "y": -0.35, "yaw": 0},
        {"item": "oil_filter", "on": "station", "station": 3, "x": 0.2, "y": 0.1, "yaw": 0},
        {"item": "air_filter", "on": "station", "station": 3, "x": 0.2, "y": 0.35, "yaw": 0},
        {"item": "alternator", "on": "station", "station": 3, "x": 0.6, "y": 0.35, "yaw": 0},
        {"item": "toolbox", "on": "station", "station": 4, "x": 0.15, "y": 0.0, "yaw": 0},
        {"item": "bulb_h7", "on": "station", "station": 4, "x": -0.1, "y": 0.12, "yaw": 0},
        {"item": "fuse_mini", "on": "station", "station": 4, "x": -0.1, "y": -0.12, "yaw": 0},
        {"item": "wiper_blades", "on": "station", "station": 4, "x": 0.4, "y": 0.0, "yaw": 0},
        {"item": "car_battery", "on": "station", "station": 5, "x": -0.6, "y": 0.2, "yaw": 0},
        {"item": "engine_oil", "on": "station", "station": 5, "x": -0.6, "y": -0.2, "yaw": 0},
        {"item": "impact_wrench", "on": "station", "station": 5, "x": -0.4, "y": -0.45, "yaw": 0},
        {"item": "load_carrier", "on": "station", "station": 6, "x": 0.25, "y": -0.35, "yaw": 0},
        {"item": "spark_plug", "on": "station", "station": 6, "x": 0.2, "y": 0.05, "yaw": 0},
        {"item": "spark_plug", "on": "station", "station": 6, "x": 0.2, "y": 0.13, "yaw": 0},
        {"item": "spark_plug", "on": "station", "station": 6, "x": 0.2, "y": 0.21, "yaw": 0},
        {"item": "spark_plug", "on": "station", "station": 6, "x": 0.2, "y": 0.29, "yaw": 0},
        {"item": "steering_wheel", "on": "station", "station": 6, "x": 0.6, "y": 0.2, "yaw": 0},
        {"item": "engine_oil", "on": "station", "station": 7, "x": -0.6, "y": 0.0, "yaw": 0},
        {"item": "air_ratchet", "on": "station", "station": 7, "x": -0.55, "y": 0.35, "yaw": 0},
    ],
}


def preset_pick(name: str) -> dict:
    """A ready-made scene's robots and objects, in the shape of a model's pick."""
    pr = PRESETS[name]
    robots: dict[str, int] = {}
    for st in pr["stations"]:
        robots[st["robot"]] = robots.get(st["robot"], 0) + 1
    items: dict[str, int] = {}
    for o in pr["furniture"] + pr["objects"]:
        items[o["item"]] = items.get(o["item"], 0) + 1
    return {"title": pr["title"], "robots": [{"robot": r, "count": n} for r, n in robots.items()],
            "items": [{"id": i, "count": n} for i, n in items.items()], "missing": [], "task": ""}


def pick(prompt: str, model_id: str, public: bool) -> dict:
    if fake():
        time.sleep(0.6)
        return clean_pick(fake_pick(prompt))
    sys_, user = pick_messages(prompt)
    out = clean_pick(ask_json(model_id, sys_, user, public, effort="low"))
    if not out["robots"]:
        raise ModelError("the model didn't choose any robot: try saying which robot you want")
    return out



FIX_SYSTEM = """You check a scene you laid out in a robot physics playground (MuJoCo, metres, z \
up). You get two pictures of it and the list of what's placed where. Compare it with the person's \
request and the plan, and fix what looks wrong:
- Fronts (doors, controls, openings, screens) turned to a wall, away from the robots or the room.
- Things in the wrong zone, scattered oddly, or not grouped the way people keep them.
- The robot's table cluttered so the task objects are hard to reach, or a task object hidden.
- Something that doesn't belong in this place at all (take it out; never a task object).
Leave what is fine alone: only fix real problems, at most 8. Positions are in the scene's \
frame (the pictures' axes). "face" turns an object's front towards "station N" or a point [x, y]; \
or give "yaw" in degrees. Every move is checked: it won't land where something else is.

Answer with JSON only:
{"plan": "one or two plain sentences: what you saw and what you changed (or that it looks right)",
 "fixes": [{"n": 3, "action": "move", "x": 1.2, "y": -0.4, "face": "station 0"},
           {"n": 5, "action": "remove"}]}"""


def snapshot(sim, view: dict, w: int = 1024, h: int = 640, grid: tuple | None = None) -> bytes:
    """A JPEG of the scene from a free camera (lookat, distance, azimuth, elevation). grid
    (x0, y0, x1, y1): the floor's 25 cm squares drawn over that area, each metre numbered."""
    import io
    import mujoco
    from PIL import Image
    with sim.lock:
        m = sim.m
        d = mujoco.MjData(m)
        d.qpos[:] = sim.d.qpos
    mujoco.mj_forward(m, d)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = view["lookat"]
    cam.distance, cam.azimuth, cam.elevation = view["distance"], view["azimuth"], view["elevation"]
    m.vis.global_.offwidth = max(m.vis.global_.offwidth, w)
    m.vis.global_.offheight = max(m.vis.global_.offheight, h)
    r = mujoco.Renderer(m, h, w)
    try:
        r.update_scene(d, camera=cam)
        marks = _grid_lines(mujoco, r.scene, grid) if grid else []
        img = r.render()
        pic = Image.fromarray(img)
        if marks:
            _grid_numbers(pic, r.scene, m.vis.global_.fovy, marks)
    finally:
        r.close()
    buf = io.BytesIO()
    pic.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _grid_lines(mujoco, scn, grid: tuple) -> list:
    """The floor grid as line geoms in a render's scene (25 cm squares, each metre's line
    bolder). Gives back the points to number: (x, y, text)."""
    import numpy as np
    from .scenegrid import FLOOR
    x0, y0 = math.floor(grid[0]) - 1, math.floor(grid[1]) - 1
    x1, y1 = math.ceil(grid[2]) + 1, math.ceil(grid[3]) + 1

    def line(a, b, bold):
        if scn.ngeom >= scn.maxgeom:
            return
        g = scn.geoms[scn.ngeom]
        mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_LINE, np.zeros(3), np.zeros(3), np.zeros(9),
                            np.array([0.1, 0.25, 0.7, 0.9 if bold else 0.35], dtype=np.float32))
        mujoco.mjv_connector(g, mujoco.mjtGeom.mjGEOM_LINE, 3.0 if bold else 1.0,
                             np.array([a[0], a[1], 0.004]), np.array([b[0], b[1], 0.004]))
        scn.ngeom += 1
    for k in range(round((x1 - x0) / FLOOR) + 1):
        x = x0 + k * FLOOR
        line((x, y0), (x, y1), k % 4 == 0)
    for k in range(round((y1 - y0) / FLOOR) + 1):
        y = y0 + k * FLOOR
        line((x0, y), (x1, y), k % 4 == 0)
    return ([(x, y, f"x {x}") for x in range(x0, x1 + 1) for y in (y0, y1)] +
            [(x, y, f"y {y}") for y in range(y0, y1 + 1) for x in (x0, x1)])


def _grid_numbers(pic, scn, fovy: float, marks: list):
    """Writes each metre line's number where it meets the grid's edge, by the render's camera."""
    import numpy as np
    from PIL import ImageDraw
    c0, c1 = scn.camera[0], scn.camera[1]
    pos = (np.array(c0.pos) + np.array(c1.pos)) / 2
    fwd, up = np.array(c0.forward), np.array(c0.up)
    right = np.cross(fwd, up)
    w, h = pic.size
    t = math.tan(math.radians(fovy) / 2)
    dr = ImageDraw.Draw(pic)
    for x, y, text in marks:
        v = np.array([x, y, 0.0]) - pos
        z = float(v @ fwd)
        if z <= 0.05:
            continue
        px = w / 2 + float(v @ right) / (z * t) * h / 2
        py = h / 2 - float(v @ up) / (z * t) * h / 2
        if 0 <= px < w - 24 and 0 <= py < h - 10:
            dr.rectangle([px - 1, py - 1, px + 6 * len(text) + 2, py + 10], fill=(255, 255, 255))
            dr.text((px + 1, py - 1), text, fill=(20, 50, 160))


# ------------------------------------------------------------------ building it
def _rot(x: float, y: float, yaw: float):
    c, s = math.cos(yaw), math.sin(yaw)
    return c * x - s * y, s * x + c * y


def _station_rect(kind: str, robot: str, x: float, y: float, yaw: float):
    st = W.Station("probe", robot, (x, y), yaw, kind=kind)
    sx, sy = st.footprint()
    pts = [st.to_world(fx * sx / 2, fy * sy / 2)[:2] for fx in (-1, 1) for fy in (-1, 1)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _item_rect(item: str, x: float, y: float, yaw: float):
    sx, sy, _ = catalog.meta(item)["size"]
    pts = [_rot(fx * sx / 2, fy * sy / 2, yaw) for fx in (-1, 1) for fy in (-1, 1)]
    return (x + min(p[0] for p in pts), y + min(p[1] for p in pts),
            x + max(p[0] for p in pts), y + max(p[1] for p in pts))


def _hit(a, b, m: float = 0.0) -> bool:
    return a[0] - m < b[2] and b[0] - m < a[2] and a[1] - m < b[3] and b[1] - m < a[3]


class Build:
    """One scene being built: its layout put down step by step in a session's sim (in a thread
    of its own), with progress the page polls, Stop, and Undo."""

    def __init__(self, sim, sess, prompt: str, pck: dict, model_id: str, public: bool, preset: str = ""):
        self.sim, self.sess, self.prompt, self.pick = sim, sess, prompt, pck
        self.preset = preset          # a ready-made scene (PRESETS): its own layout, no model
        self.station_tasks: dict[str, str] = {}
        self.model_id, self.public = model_id, public
        self.id = os.urandom(4).hex()
        self.rationale = {}           # the layout step's own reasons, checked against after the build
        self.phase = "plan"           # plan, robots, furniture, objects, done, stopped, error
        self.plan_text = ""
        self.error = ""
        self.stop = False
        n_items = sum(i["count"] for i in pck["items"])
        n_furn = sum(i["count"] for i in pck["items"] if catalog.item(i["id"])["fixed"])
        self.counts = {"robots": [0, sum(r["count"] for r in pck["robots"])], "furniture": [0, n_furn],
                       "objects": [0, n_items - n_furn]}
        self.stations: list[str] = []
        self.objects: list[str] = []
        self.skipped: list[str] = []
        self.fixes: list[str] = []      # what the look-and-fix step changed ("turned the fridge")
        self.role: dict[str, str] = {}  # each placed object's uid -> "task" or "scene" (v2 picks)
        self.look = bool(pck.get("brief")) and not preset   # check the built scene from pictures
        if self.look:
            self.counts["check"] = [0, FIX_ROUNDS]
        self.task = pck.get("task", "")
        self.zone = None
        self.undone = False
        self.started = time.time()
        self.now = ""                 # what is being put down right now ("the mug")
        rl = {r["id"]: r["label"].replace(" (two arms)", "") for r in catalog.robots()}
        self.names = {"robots": [rl.get(r["robot"], r["robot"]) for r in pck["robots"]],
                      "furniture": [catalog.item(i["id"])["label"] for i in pck["items"] if catalog.item(i["id"])["fixed"]],
                      "objects": [catalog.item(i["id"])["label"] for i in pck["items"] if not catalog.item(i["id"])["fixed"]]}

    def status(self) -> dict:
        return {"id": self.id, "phase": self.phase, "plan": self.plan_text, "error": self.error,
                "counts": self.counts, "title": self.pick["title"], "stations": self.stations,
                "objects": len(self.objects), "skipped": self.skipped, "task": self.task,
                "undone": self.undone, "now": self.now, "names": self.names,
                "model": next((m["label"] for m in SCENE_MODELS if m["id"] == self.model_id), ""),
                "fixes": self.fixes, "active": self.phase in ("plan", "robots", "furniture", "objects", "check")}

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="scene-build").start()

    # -------------------------------------------------- the steps
    def _run(self):
        s = self.sim
        was_playing = not s.paused
        try:
            if self.preset:
                lay = PRESETS[self.preset]
            elif fake():
                time.sleep(0.8)
                lay = fake_layout(self.pick)
            else:
                return self._run_streamed(was_playing)
            self.plan_text = str(lay.get("plan") or "").strip()[:800]
            self.task = str(lay.get("task") or self.task).strip()[:600] or self.task
            if self.stop:
                return self._end("stopped")
            stations, furniture, objects = self._clean_layout(lay)
            self.raw_layout, self.laid = lay, objects      # kept for checking test rounds
            s.pause()
            if self.preset and lay.get("settings"):
                s.merge_settings(lay["settings"])
            off = self._free_spot(stations, furniture, objects)
            if off is None:
                raise ModelError("there's no free floor space big enough for this scene: "
                                 "remove something, or ask for a smaller scene")
            self._show_zone(stations, furniture, objects, off)
            self.phase = "robots"
            for k, st in enumerate(stations):
                if self.stop:
                    return self._end("stopped")
                self._place_station(st, off, k, len(stations))
            self.phase = "furniture"
            fixed_uids = []
            for f in furniture:
                if self.stop:
                    return self._end("stopped")
                self.now = catalog.item(f["item"])["label"]
                fixed_uids.append(self._place_furniture(f, off))
            self.phase = "objects"
            placed = [None] * len(objects)
            # things that go inside other things go down last, once what holds them is there
            for k in sorted(range(len(objects)), key=lambda k: objects[k]["on"] == "inside"):
                o = objects[k]
                if self.stop:
                    return self._end("stopped")
                self.now = catalog.item(o["item"])["label"]
                placed[k] = self._place_object(o, off, fixed_uids, placed)
            self.now = ""
            if self.look and not fake() and can_see(self.model_id, self.public):
                self.phase = "check"
                for k in range(FIX_ROUNDS):
                    if self.stop:
                        return self._end("stopped")
                    self.now = "Looking over the scene"
                    changed = self._look_and_fix(k)
                    self.counts["check"][0] = k + 1
                    if not changed:
                        self.counts["check"][0] = FIX_ROUNDS
                        break
                self.now = ""
            if self.stations and self.task:
                for u in self.stations:
                    self.sess.unsent[u] = {"task": self.task, "model": ""}
            for u, t in self.station_tasks.items():     # a ready-made scene's own task per robot
                self.sess.unsent[u] = {"task": t, "model": ""}
            self._end("done")
        except Exception as e:  # noqa: BLE001
            self.error = str(e) if isinstance(e, (ModelError,)) else f"something went wrong: {e}"
            self._end("error")
        finally:
            s.zone = []
            if was_playing and self.phase != "plan":
                s.play()

    def _run_streamed(self, was_playing: bool):
        """The model's layout, built as it is written: once its robots and furniture are down
        (the start of its objects list), they are placed while it goes on, and each object
        goes down as soon as its line is finished. Then whatever it left out, then the look."""
        s = self.sim
        try:
            sys_, user = layout_messages(self.prompt, self.pick)
            buf, started = "", False
            stations = furniture = None
            off, fixed_uids, placed, inside_wait = None, [], [], []
            plan_seen = False

            def place_new(objs):
                for k in range(len(placed), len(objs)):
                    o = objs[k]
                    placed.append(None)
                    if o["on"] == "inside" and not o.get("in_furniture") and \
                            not (0 <= o["object"] < k and placed[o["object"]]):
                        inside_wait.append(k)        # its holder isn't down yet
                        continue
                    self.now = catalog.item(o["item"])["label"]
                    placed[k] = self._place_object(o, off, fixed_uids, placed)

            for chunk in ask_stream(self.model_id, sys_, user, self.public, effort="high"):
                if self.stop:
                    return self._end("stopped")
                buf += chunk
                if not plan_seen:
                    m = re.search(r'"plan"\s*:\s*"((?:[^"\\]|\\.)*)"', buf)
                    if m:
                        plan_seen = True
                        try:
                            self.plan_text = json.loads('"' + m.group(1) + '"').strip()[:800]
                        except json.JSONDecodeError:
                            pass
                objs_raw, obj_started, _ = stream_items(buf, "objects")
                if not obj_started:
                    continue
                if not started:          # robots and furniture are all written: put them down
                    st_raw, _, st_closed = stream_items(buf, "stations")
                    f_raw, _, _ = stream_items(buf, "furniture")
                    stations, furniture, _ = self._clean_layout(
                        {"stations": st_raw, "furniture": f_raw, "objects": []}, partial=True)
                    s.pause()
                    off = self._free_spot(stations, furniture, [])
                    if off is None:
                        raise ModelError("there's no free floor space big enough for this scene: "
                                         "remove something, or ask for a smaller scene")
                    self._show_zone(stations, furniture, [], off)
                    self.phase = "robots"
                    for k, st in enumerate(stations):
                        if self.stop:
                            return self._end("stopped")
                        self._place_station(st, off, k, len(stations))
                    self.phase = "furniture"
                    for f in furniture:
                        if self.stop:
                            return self._end("stopped")
                        self.now = catalog.item(f["item"])["label"]
                        fixed_uids.append(self._place_furniture(f, off))
                    self.phase = "objects"
                    started = True
                    n_f = len(furniture)
                _, _, objs = self._clean_layout({"stations": stream_items(buf, "stations")[0],
                                                 "furniture": stream_items(buf, "furniture")[0],
                                                 "objects": objs_raw}, partial=True)
                self.counts["furniture"][1] = max(self.counts["furniture"][1], n_f)
                place_new(objs)
            lay = parse_json(buf)
            self.plan_text = str(lay.get("plan") or self.plan_text).strip()[:800]
            self.rationale = lay.get("rationale") if isinstance(lay.get("rationale"), dict) else {}
            self.task = str(lay.get("task") or self.task).strip()[:600] or self.task
            stations2, furniture2, objects = self._clean_layout(lay)
            self.raw_layout, self.laid = lay, objects
            if not started:              # it couldn't stream (or wrote no objects): all at once
                s.pause()
                stations, furniture = stations2, furniture2
                off = self._free_spot(stations, furniture, objects)
                if off is None:
                    raise ModelError("there's no free floor space big enough for this scene: "
                                     "remove something, or ask for a smaller scene")
                self._show_zone(stations, furniture, objects, off)
                self.phase = "robots"
                for k, st in enumerate(stations):
                    self._place_station(st, off, k, len(stations))
                self.phase = "furniture"
            for f in furniture2[len(fixed_uids):]:    # furniture it left out
                self.now = catalog.item(f["item"])["label"]
                fixed_uids.append(self._place_furniture(f, off))
            self.phase = "objects"
            place_new(objects)
            for k in inside_wait:                       # things that go inside others, now all down
                if self.stop:
                    return self._end("stopped")
                self.now = catalog.item(objects[k]["item"])["label"]
                placed[k] = self._place_object(objects[k], off, fixed_uids, placed)
            self.now = ""
            self._finish()
        except Exception as e:  # noqa: BLE001
            self.error = str(e) if isinstance(e, (ModelError,)) else f"something went wrong: {e}"
            self._end("error")
        finally:
            s.zone = []
            if was_playing and self.phase != "plan":
                s.play()

    def _finish(self):
        """The look-and-fix rounds, the task handed to the robots, done."""
        if self.look and not fake() and can_see(self.model_id, self.public):
            self.phase = "check"
            for k in range(FIX_ROUNDS):
                if self.stop:
                    return self._end("stopped")
                self.now = "Looking over the scene"
                changed = self._look_and_fix(k)
                self.counts["check"][0] = k + 1
                if not changed:
                    self.counts["check"][0] = FIX_ROUNDS
                    break
            self.now = ""
        if self.stations and self.task:
            for u in self.stations:
                self.sess.unsent[u] = {"task": self.task, "model": ""}
        for u, t in self.station_tasks.items():     # a ready-made scene's own task per robot
            self.sess.unsent[u] = {"task": t, "model": ""}
        self._end("done")

    def _end(self, phase: str):
        self.phase = phase
        self.sim.zone = []
        if self.stations:
            self.sim.active_station = self.stations[0]
            self.sim.frame_station(self.stations[0])

    def _clean_layout(self, lay: dict, partial: bool = False):
        """The layout kept to what the person checked: the robots and objects on their list
        (anything the model left out goes in a sensible default spot). partial: the layout is
        still being written, so nothing left out is filled in yet (what is there keeps its place
        in the lists as more comes)."""
        from . import scenegrid
        if scenegrid.on() and not self.preset and not fake():      # written in squares: to metres
            lay = scenegrid.to_metres(lay)
        want_r = [r["robot"] for r in self.pick["robots"] for _ in range(r["count"])]
        stations = []
        for st in lay.get("stations") or []:
            rb = str((st or {}).get("robot", ""))
            if rb in want_r:
                want_r.remove(rb)
                kind = st.get("kind") if st.get("kind") in W.KINDS else "table"
                stations.append({"robot": rb, "kind": kind, "x": _f(st.get("x")), "y": _f(st.get("y")),
                                 "yaw": math.radians(_f(st.get("yaw"))), "task": str(st.get("task") or "")})
        for rb in want_r:
            stations.append({"robot": rb, "kind": "table", "x": 0.0, "y": 2.0 * len(stations), "yaw": 0.0})
        items = [i["id"] for i in self.pick["items"] for _ in range(i["count"])]
        from .scenebrief import tabletop
        small = set(tabletop()) if self.pick.get("brief") else set()
        # small furniture the layout puts on a robot's table goes down like an object
        on_table = [str((o or {}).get("item", "")) for o in lay.get("objects") or []
                    if (o or {}).get("on", "station") == "station"]
        want_o = [i for i in items if not catalog.item(i)["fixed"]]
        want_f = []
        for i in items:
            if catalog.item(i)["fixed"]:
                if i in small and i in on_table:
                    on_table.remove(i)
                    want_o.append(i)
                else:
                    want_f.append(i)
        furniture = []
        for f in lay.get("furniture") or []:
            it = str((f or {}).get("item", ""))
            if it in want_f and it in [x for x in want_f]:
                want_f.remove(it)
                furniture.append({"item": it, "x": _f(f.get("x")), "y": _f(f.get("y")),
                                  "yaw": _facing(it, _f(f.get("x")), _f(f.get("y")), f.get("face"), stations,
                                                 math.radians(_f(f.get("yaw")))),
                                  # a ready-made scene may butt pieces together (conveyor sections)
                                  "gap": max(0.0, _f(f.get("gap", 0.15))) if self.preset
                                  else min(0.15, max(0.02, _f(f.get("gap", 0.15))))})
        for it in ([] if partial else want_f):
            furniture.append({"item": it, "x": 2.5, "y": -1.5 + 1.5 * len(furniture), "yaw": math.pi})
        objects, where = [], {}       # where: the model's own index of each object -> ours
        for k_raw, o in enumerate(lay.get("objects") or []):
            it = str((o or {}).get("item", ""))
            if it in want_o:
                where[k_raw] = len(objects)
                want_o.remove(it)
                on = o.get("on") if o.get("on") in ("station", "furniture", "floor", "inside") else "station"
                k_st = max(0, min(len(stations) - 1, _int(o.get("station"), 0)))
                yaw = math.radians(_f(o.get("yaw")))
                if on == "station":       # in the station's frame: its robot sits at robot_xy
                    rx, ry = W.KINDS[stations[k_st]["kind"]].get("robot_xy", (-0.42, 0.0))
                    face = o.get("face")
                    if isinstance(face, str) and face.strip().lower().startswith("station"):
                        face = [rx, ry]
                    yaw = _facing(it, _f(o.get("x")), _f(o.get("y")), face, [], yaw)
                elif on == "floor":
                    yaw = _facing(it, _f(o.get("x")), _f(o.get("y")), o.get("face"), stations, yaw)
                objects.append({"item": it, "on": on,
                                "station": k_st,
                                "furniture": _int(o.get("furniture"), 0),
                                "x": _f(o.get("x")), "y": _f(o.get("y")),
                                "dx": _f(o.get("dx")), "dy": _f(o.get("dy")),
                                "yaw": yaw,
                                # inside: which object (by its place in this list) or furniture
                                "object": _int(o.get("object"), -1) if o.get("object") is not None else -1,
                                "in_furniture": "object" not in o and o.get("furniture") is not None,
                                "level": _int(o.get("level"), 1),
                                # a ready-made scene's big part may hang over its pallet's edges
                                "overhang": bool(self.preset and o.get("overhang"))})
        for o in objects:
            if o["on"] == "inside" and not o["in_furniture"]:
                o["object"] = where.get(o["object"], -1)
        if len(stations) > 1 and MATCHING.search(self.prompt or ""):
            # stations asked to match: each one's things at the spots of the first station's
            if not partial:          # the copies of each thing shared out evenly over the stations
                by_item = {}
                for o in objects:
                    if o["on"] == "station":
                        by_item.setdefault(o["item"], []).append(o)
                for rows in by_item.values():
                    if len(rows) % len(stations) == 0:
                        rows.sort(key=lambda o: o["station"])
                        for j, o in enumerate(rows):
                            o["station"] = j // (len(rows) // len(stations))
            first = {}
            for o in objects:
                if o["on"] == "station" and o["station"] == 0:
                    first.setdefault(o["item"], []).append(o)
            seen = {}
            for o in objects:
                if o["on"] == "station" and o["station"] > 0:
                    k = seen.setdefault((o["station"], o["item"]), 0)
                    seen[(o["station"], o["item"])] += 1
                    src = first.get(o["item"], [])
                    if k < len(src):
                        o["x"], o["y"], o["yaw"] = src[k]["x"], src[k]["y"], src[k]["yaw"]
        to_come = len(want_o)
        for k, it in enumerate([] if partial else want_o):
            objects.append({"item": it, "on": "station", "station": k % max(1, len(stations)),
                            "x": 0.3, "y": 0.0, "dx": 0.0, "dy": 0.0, "yaw": 0.0})
        if not stations:
            raise ModelError("the scene has no robot")
        # the progress counts as laid out (small furniture may have gone on a table as an object)
        self.counts["furniture"][1] = len(furniture)
        self.counts["objects"][1] = len(objects) + (to_come if partial else 0)
        if any(o["on"] == "furniture" for o in objects) and not furniture:
            for o in objects:
                if o["on"] == "furniture":
                    o["on"] = "station"
        if self.pick.get("brief") and not self.preset:
            self._dock_task_furniture(stations, furniture, objects)
            self._arrange_room(stations, furniture)
        return stations, furniture, objects

    def _dock_task_furniture(self, stations, furniture, objects):
        """A floor-standing thing the task itself works (the brief's role "task": an incubator to
        open, a fridge to load) with a door or drawer, or with task things starting inside it:
        stood against its robot's table, front to the robot, its front within the arm's reach.
        The side the model chose if the arm reaches it there, else the nearest side that it does."""
        br = self.pick.get("brief") or {}
        slot_of = self.pick.get("slot_of") or {}
        from .scenegrid import long_y
        hosts = {o["furniture"] for o in objects if o["on"] == "inside" and o.get("in_furniture")}
        for n, f in enumerate(furniture):
            it = f["item"]
            k = slot_of.get(it)
            try:
                role = br["slots"][k]["role"]
            except (KeyError, IndexError, TypeError):
                continue
            meta = catalog.meta(it)
            sx, sy, _ = meta["size"]
            if role != "task" or it in FENCE or max(sx, sy) > 1.5 or \
                    not (n in hosts or len(meta.get("bodies") or []) > 1):
                continue
            lng = long_y(it)
            deep = sx if lng else sy
            best = None
            for st in stations:
                pr = W.Station("probe", st["robot"], (st["x"], st["y"]), st["yaw"], kind=st["kind"])
                if len(pr.bases()) != 1:
                    continue
                bx, by = pr.bases()[0]
                tx, ty = pr.footprint()
                reach = 0.85 * next((r["reach_mm"] for r in catalog.robots() if r["id"] == st["robot"]), 850) / 1000.0
                lx, ly = _rot(f["x"] - st["x"], f["y"] - st["y"], -st["yaw"])
                ax = min(tx / 2 - 0.1, max(bx + 0.3, -tx / 2 + 0.1))       # along the table, just ahead of the base
                # (the front's spot, the way the front points, how far the model's spot is from it)
                # at a side end of the table (across the table its door would open into the table)
                cands = [((ax, ty / 2 + 0.05), -math.pi / 2), ((ax, -ty / 2 - 0.05), math.pi / 2)]
                for (qx, qy), phi in cands:
                    if math.hypot(qx - bx, qy - by) > reach:
                        continue
                    cx, cy = qx - math.cos(phi) * deep / 2, qy - math.sin(phi) * deep / 2
                    d = math.hypot(cx - lx, cy - ly)
                    if best is None or d < best[0]:
                        best = (d, st, cx, cy, phi)
            if best is None:
                continue
            _, st, cx, cy, phi = best
            wx, wy = _rot(cx, cy, st["yaw"])
            turn = phi if lng else (phi - math.pi / 2 if front_sign(it) > 0 else phi + math.pi / 2)
            f["x"], f["y"], f["yaw"], f["gap"] = st["x"] + wx, st["y"] + wy, st["yaw"] + turn, 0.02

    def _arrange_room(self, stations, furniture):
        """Floor furniture that lines a wall in a real room (WALL_KINDS) stood in one run behind
        the robots' tables, backs on a line, fronts facing in, pieces of one zone side by side;
        a long run turns the corner down a side. The model's own spots decide the order; a
        piece it stood right against a table (the task uses it) stays where it is, as does
        everything else (a dining set, a pallet, a cart). The side the robots face stays open."""
        th = stations[0]["yaw"]
        ox, oy = stations[0]["x"], stations[0]["y"]

        def local(x, y):
            return _rot(x - ox, y - oy, -th)

        pts = []
        srects = [_station_rect(st["kind"], st["robot"], st["x"], st["y"], st["yaw"]) for st in stations]
        for r in srects:
            pts += [local(x, y) for x in (r[0], r[2]) for y in (r[1], r[3])]
        for st in stations:          # and the robots themselves (a big one stands beside its table)
            pr = W.Station("probe", st["robot"], (st["x"], st["y"]), st["yaw"], kind=st["kind"])
            for bxy in pr.bases():
                wx, wy = pr.to_world(*bxy)[:2]
                pts += [local(wx + dx, wy + dy) for dx in (-0.45, 0.45) for dy in (-0.45, 0.45)]
        from . import object_tree as T
        tags = T.tags()

        def stays(f):
            """At a table (the task works with it), or not a kind that lines a wall (a dining
            set, a pallet, a cart): where the model put it."""
            r = _item_rect(f["item"], f["x"], f["y"], f["yaw"])
            return any(_hit(r, b, 0.08) for b in srects) or \
                not any(k in pth for pth in tags.get(f["item"], {}).get("paths", []) for k in WALL_KINDS)

        for f in furniture:          # the walls go round the tables and whatever stands at them
            r = _item_rect(f["item"], f["x"], f["y"], f["yaw"])
            if any(_hit(r, b, 0.08) for b in srects):
                pts += [local(x, y) for x in (r[0], r[2]) for y in (r[1], r[3])]
        bx0, bx1 = min(q[0] for q in pts), max(q[0] for q in pts)
        by0, by1 = min(q[1] for q in pts), max(q[1] for q in pts)
        cy = (by0 + by1) / 2
        # a guarded cell: its fence as a ring round the tables and robots, the door mid-back, an
        # opening left mid-front; panels are added to close it. The wall furniture stands outside.
        fence = [f for f in furniture if f["item"] in FENCE]
        if len(fence) >= 3:
            m, wp = 0.9, catalog.meta("safety_fence")["size"][0] + 0.01
            doors = [f for f in fence if f["item"] != "safety_fence"][:1]
            panels = [f for f in fence if f not in doors]
            wd = catalog.meta(doors[0]["item"])["size"][0] + 0.01 if doors else 0.0
            k = math.ceil(max(0.0, by1 - by0 + 2 * m - wd) / (2 * wp)) if doors else \
                math.ceil((by1 - by0 + 2 * m) / wp / 2)
            wide = wd + 2 * k * wp
            ns = math.ceil((bx1 - bx0 + 2 * m) / wp)
            nf = max(0, int((wide / 2 - 0.6) / wp))
            while 2 * k + 2 * ns + 2 * nf > 14 and nf:        # at most 14 panels: the front goes first
                nf -= 1
            while 2 * k + 2 * ns > 14 and ns > 1:
                ns -= 1
            spots = []                                        # (x, y, turn) in the room's frame
            xb = bx0 - m
            for j in range(k):
                spots += [(xb, cy - wide / 2 + (j + 0.5) * wp, math.pi / 2),
                          (xb, cy + wide / 2 - (j + 0.5) * wp, math.pi / 2)]
            for j in range(ns):
                spots += [(xb + 0.14 + (j + 0.5) * wp, cy - wide / 2 - 0.14, 0.0),
                          (xb + 0.14 + (j + 0.5) * wp, cy + wide / 2 + 0.14, 0.0)]
            xf = xb + 0.28 + ns * wp
            for j in range(nf):
                spots += [(xf, cy - wide / 2 + (j + 0.5) * wp, math.pi / 2),
                          (xf, cy + wide / 2 - (j + 0.5) * wp, math.pi / 2)]
            while len(panels) < len(spots):
                panels.append({"item": "safety_fence", "x": 0.0, "y": 0.0, "yaw": 0.0})
                furniture.append(panels[-1])
            for f in panels[len(spots):]:                     # more than the ring takes: left out
                furniture.remove(f)
            for f, (x, y, turn) in zip(panels + doors, spots[:len(panels)] + [(xb, cy, math.pi / 2)]):
                q = _rot(x, y, th)
                f["x"], f["y"], f["yaw"], f["gap"] = q[0] + ox, q[1] + oy, th + turn, 0.0
            bx0, by0, by1 = xb - 0.3, cy - wide / 2 - 0.44, cy + wide / 2 + 0.44
            self.counts["furniture"][1] = len(furniture)
        zone_of = {}
        br = self.pick["brief"]
        for i, k in (self.pick.get("slot_of") or {}).items():
            if 0 <= k < len(br["slots"]):
                zone_of[i] = br["slots"][k]["zone"]
        walls = {"back": [], "right": [], "left": []}
        rows = [(f,) + local(f["x"], f["y"]) for f in furniture if not stays(f)]
        zmean = {}
        for f, lx, ly in rows:
            zmean.setdefault(zone_of.get(f["item"], ""), []).append(ly)
        rows.sort(key=lambda t: (sum(zmean[zone_of.get(t[0]["item"], "")]) / len(zmean[zone_of.get(t[0]["item"], "")]),
                                 zone_of.get(t[0]["item"], ""), t[2]))
        # one run behind the robots; what doesn't fit turns the corner and runs down a side
        room, used = max(5.0, by1 - by0 + 2.0), 0.0
        for k, (f, lx, ly) in enumerate(rows):
            sx, sy, _ = catalog.meta(f["item"])["size"]
            used += max(sx, sy) if sy > 1.25 * sx else sx
            w = "back" if used <= room or not walls["back"] else "left" if used <= room + 3.5 else "right"
            # in the order they stand: the back run by y, a side run by its place in the list
            walls[w].append((f, float(k), ly if w == "back" else float(k)))
        if sum(len(v) for v in walls.values()) < 2:
            return
        clear, gap, zgap = 0.7, 0.03, 0.15
        norm = {"back": (1.0, 0.0), "right": (0.0, 1.0), "left": (0.0, -1.0)}

        def run(wall):
            """The wall's pieces in order, each with its turn and its box about its own centre
            (room frame), and the run's length and deepest piece."""
            along = 1 if wall == "back" else 0
            rows = walls[wall]
            out, length, deep, last = [], 0.0, 0.0, None
            for f, _, _ in rows:
                sx, sy, _ = catalog.meta(f["item"])["size"]
                if sy > 1.25 * sx and front_sign(f["item"]) < 0:   # long front to back as modelled (NVIDIA's counters and
                    yaw = math.atan2(norm[wall][1], norm[wall][0])   # benches): its long side along the wall
                else:
                    yaw = _facing(f["item"], 0.0, 0.0, list(norm[wall]), [], 0.0)
                r = _item_rect(f["item"], 0.0, 0.0, yaw)
                z = zone_of.get(f["item"], "")
                if out:
                    length += gap if z == last else zgap
                out.append((f, yaw, r, length))
                length += r[2 + along] - r[along]
                deep = max(deep, r[3 - along] - r[1 - along])
                last = z
            return out, length, deep

        back, lb, db = run("back")
        for f, yaw, r, at in back:                     # backs on one line, the run centred on the tables
            x = bx0 - clear - db - r[0]
            y = cy - lb / 2 + at - r[1]
            f["x"], f["y"] = (lambda q: (q[0] + ox, q[1] + oy))(_rot(x, y, th))
            f["yaw"], f["gap"] = yaw + th, 0.02
        half = max((by1 - by0) / 2 + clear, lb / 2 + 0.3)
        for wall, sign in (("right", -1), ("left", 1)):
            rows, _, deep = run(wall)
            for f, yaw, r, at in rows:                 # from the back corner towards the front
                x = bx0 - clear + at - r[0]
                y = cy + sign * (half + deep) - (r[3] if sign > 0 else r[1])
                f["x"], f["y"] = (lambda q: (q[0] + ox, q[1] + oy))(_rot(x, y, th))
                f["yaw"], f["gap"] = yaw + th, 0.02

    def _rects(self, stations, furniture, objects, ox=0.0, oy=0.0):
        rs = [_station_rect(st["kind"], st["robot"], st["x"] + ox, st["y"] + oy, st["yaw"]) for st in stations]
        rs += [_item_rect(f["item"], f["x"] + ox, f["y"] + oy, f["yaw"]) for f in furniture]
        rs += [_item_rect(o["item"], o["x"] + ox, o["y"] + oy, o["yaw"]) for o in objects if o["on"] == "floor"]
        return rs

    def _taken(self):
        """What already stands on the floor: every station's table, furniture and loose things."""
        s = self.sim
        out = [_station_rect(st.kind, st.robot, st.pos[0], st.pos[1], st.yaw) for st in s.stations]
        for p in s.placed:
            if any(st.holds(p.pos[0], p.pos[1]) for st in s.stations):
                continue
            out.append(_item_rect(p.item, p.pos[0], p.pos[1], p.yaw))
        return out

    def _free_spot(self, stations, furniture, objects):
        """Where to move the whole scene so it stands clear of everything already there: the
        free spot nearest the middle of what's there (or the middle of the floor)."""
        s = self.sim
        rs = self._rects(stations, furniture, objects)
        x0, y0 = min(r[0] for r in rs), min(r[1] for r in rs)
        x1, y1 = max(r[2] for r in rs), max(r[3] for r in rs)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        taken = self._taken()
        if s.stations:
            mx = sum(st.pos[0] for st in s.stations) / len(s.stations)
            my = sum(st.pos[1] for st in s.stations) / len(s.stations)
        else:
            mx = my = 0.0
        cands = sorted({(round(mx + 0.5 * i, 2), round(my + 0.5 * j, 2)) for i in range(-34, 35)
                        for j in range(-34, 35)}, key=lambda v: (v[0] - mx) ** 2 + (v[1] - my) ** 2)
        lim = 8.3
        for tx, ty in cands:
            ox, oy = tx - cx, ty - cy
            if x0 + ox < -lim or x1 + ox > lim or y0 + oy < -lim or y1 + oy > lim:
                continue
            mine = [(r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy) for r in rs]
            if any(_hit(a, b, 0.4) for a in mine for b in taken):
                continue
            if all(s.station_spot(st["x"] + ox, st["y"] + oy, st["yaw"], kind=st["kind"])["valid"]
                   for st in stations):
                return ox, oy
        return None

    def _show_zone(self, stations, furniture, objects, off):
        rs = self._rects(stations, furniture, objects, *off)
        x0, y0 = min(r[0] for r in rs) - 0.3, min(r[1] for r in rs) - 0.3
        x1, y1 = max(r[2] for r in rs) + 0.3, max(r[3] for r in rs) + 0.3
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.zone = [x0, y0, x1, y1]
        self.sim.zone = [
            {"type": "box", "size": [(x1 - x0) / 2, (y1 - y0) / 2, 0.002], "pos": [cx, cy, 0.003],
             "yaw": 0.0, "rgba": [0.25, 0.55, 1.0, 0.22]},
            {"type": "box", "size": [(x1 - x0) / 2, (y1 - y0) / 2, 0.6], "pos": [cx, cy, 0.6],
             "yaw": 0.0, "rgba": [0.25, 0.55, 1.0, 0.06]},
        ]
        span = max(x1 - x0, y1 - y0, 2.0)
        self.sim._set_view({"lookat": [cx, cy, 0.5], "distance": 1.6 + 1.2 * span, "azimuth": 145.0,
                            "elevation": -35.0}, True)

    def _place_station(self, st, off, k, n):
        s = self.sim
        x, y, yaw = st["x"] + off[0], st["y"] + off[1], st["yaw"]
        spot = None
        for dx, dy in _spiral(0.25, 6):
            spot = s.station_spot(x + dx, y + dy, yaw, kind=st["kind"])
            if spot["valid"]:
                break
        if not spot or not spot["valid"]:
            self.skipped.append(next((r["label"] for r in catalog.robots() if r["id"] == st["robot"]), st["robot"]))
            self.counts["robots"][1] -= 1
            return
        # A humanoid among a scene's other robots: an open cell (its own 7 x 7 m room wouldn't fit).
        uid = s.add_station(st["robot"], spot["pos"], yaw, st["kind"], starter=False,
                            open_cell=bool(WS.ROBOTS[st["robot"]].get("humanoid")))
        if self.preset and st.get("task"):
            self.station_tasks[uid] = st["task"]
        title = self.pick["title"]
        s.rename_station(uid, title if n == 1 else f"{title} {k + 1}")
        self.stations.append(uid)
        self.counts["robots"][0] += 1

    def _place_furniture(self, f, off):
        s = self.sim
        x, y, yaw = f["x"] + off[0], f["y"] + off[1], f["yaw"]
        mine = self._mine_rects()
        for dx, dy in _spiral(0.2, 8):
            r = _item_rect(f["item"], x + dx, y + dy, yaw)
            if any(_hit(r, b, f.get("gap", 0.15)) for b in mine):
                continue
            spot = s.support(f["item"], x + dx, y + dy, yaw)
            if spot["valid"] and spot["surface"] == "the floor":
                uid = s.add(f["item"], spot["pos"], yaw)
                self.objects.append(uid)
                self.counts["furniture"][0] += 1
                return uid
        self._skip(f["item"], "furniture")
        return None

    def _mine_rects(self):
        """Tables and floor things already standing (this scene's and everyone else's)."""
        return self._taken()

    def _place_object(self, o, off, fixed_uids, placed=()):
        sl = (self.pick.get("slot_of") or {}).get(o["item"])
        uid = self._place_object1(o, off, fixed_uids, placed)
        if not uid and sl is not None and self.pick.get("lists") and o["on"] != "inside":
            # it didn't fit: the next object on its slot's short list, in the same spot (a thing
            # that should go inside another stays the thing that was asked for: it goes beside it)
            used = {i["id"] for i in self.pick["items"]}
            for alt in self.pick["lists"][sl]:
                if alt in used or catalog.item(alt)["fixed"] != catalog.item(o["item"])["fixed"]:
                    continue
                uid = self._place_object1({**o, "item": alt}, off, fixed_uids, placed)
                if uid:
                    gone = self.skipped.pop()
                    self.counts["objects"][1] += 1
                    self.fixes.append(f"used the {catalog.item(alt)['label'].lower()} for the {gone.lower()}, which didn't fit")
                    break
                self.skipped.pop()
                self.counts["objects"][1] += 1
        if not uid and o["on"] == "inside":
            # nothing on its list fits inside: the first choice, next to what should hold it
            self.skipped.pop()
            self.counts["objects"][1] += 1
            uid = self._place_object1({**o, "last_try": True}, off, fixed_uids, placed)
        if uid and sl is not None:
            self.role[uid] = self.pick["brief"]["slots"][sl]["role"]
        return uid

    def _place_object1(self, o, off, fixed_uids, placed=()):
        s = self.sim
        it, yaw = o["item"], o["yaw"]
        if o["on"] == "inside":
            k = o.get("object", -1)
            if o.get("in_furniture"):
                k = o.get("furniture", -1)
                host = fixed_uids[k] if 0 <= k < len(fixed_uids) else None
            else:
                host = placed[k] if 0 <= k < len(placed) else None
            if host and s.find(host):
                uid = self._place_inside(it, host, o)
                if not uid:
                    # the model may have pointed at the wrong thing: anything placed it fits inside
                    for other in [u for u in placed if u and u != host and s.find(u)]:
                        uid = self._place_inside(it, other, {**o, "dx": 0.0, "dy": 0.0})
                        if uid:
                            break
                if not uid:          # swap the holder first: the thing itself is what was asked for
                    old = host
                    host, uid = self._swap_host(it, host, o)
                    if host != old and isinstance(placed, list):
                        placed[:] = [host if u == old else u for u in placed]
                        self.role[host] = self.role.pop(old, "scene")
                if uid or not o.get("last_try"):
                    return uid or self._skip(it)     # not inside: the next on its short list may fit
                self.fixes.append(f"the {catalog.item(it)['label'].lower()} didn't fit inside the "
                                  f"{catalog.item(s.find(host).item)['label'].lower()}, so it's next to it")
                st = next((st for st in s.stations if st.holds(*s.find(host).pos[:2])), None)
                hp = s.find(host).pos
                mine = [s.station(u) for u in self.stations]
                if st is not None and st in mine:
                    lx, ly = st.to_local(hp[0], hp[1])[:2]
                    o = {**o, "on": "station", "station": mine.index(st), "x": lx, "y": ly + 0.2}
                else:
                    o = {**o, "on": "floor", "x": hp[0] + 0.4, "y": hp[1]}
            else:
                o = {**o, "on": "station"}
        if o["on"] == "station" and o["station"] < len(self.stations):
            st = s.station(self.stations[o["station"]])
            if st is None:
                return self._skip(it)
            want = f"the table of {st.name}"
            lx, ly = o["x"], o["y"]
            # within the arm's comfortable reach (three quarters of the maker's figure), measured
            # to a big thing's near side: a spot further out is pulled in along its line to the base
            reach = next((r["reach_mm"] for r in catalog.robots() if r["id"] == st.robot), 850) / 1000.0
            sx, sy, _ = catalog.meta(it)["size"]
            far = 0.75 * reach + (max(sx, sy) / 2 if max(sx, sy) > 0.3 else 0.0)
            bx, by = min(st.bases(), key=lambda b: math.hypot(lx - b[0], ly - b[1]))
            d = math.hypot(lx - bx, ly - by)
            if d > far:
                lx, ly = bx + (lx - bx) * far / d, by + (ly - by) * far / d
            for dx, dy in _spiral(0.04, 9):
                x, y, _ = st.to_world(lx + dx, ly + dy)
                if not st.holds(x, y, -0.06) or st.near_base(x, y):
                    continue
                spot = s.support(it, x, y, st.yaw + yaw)
                if spot["valid"] and spot["level"] and spot["surface"] == want:
                    return self._add(it, spot, st.yaw + yaw)
            # nothing near where the model wanted it: anywhere free on that table, in reach
            for lx2 in (0.1, 0.25, 0.4, 0.55, -0.05):
                for ly2 in (0.0, -0.2, 0.2, -0.4, 0.4):
                    x, y, _ = st.to_world(lx2, ly2)
                    if st.near_base(x, y):
                        continue
                    spot = s.support(it, x, y, st.yaw + yaw)
                    if spot["valid"] and spot["level"] and spot["surface"] == want:
                        return self._add(it, spot, st.yaw + yaw)
            return self._skip(it)
        if o["on"] == "furniture" and 0 <= o["furniture"] < len(fixed_uids) and fixed_uids[o["furniture"]]:
            p = s.find(fixed_uids[o["furniture"]])
            if p is None:
                return self._skip(it)
            want = catalog.item(p.item)["label"]
            bx, by = p.pos[0], p.pos[1]
            for dx, dy in _spiral(0.04, 8):
                ddx, ddy = _rot(o["dx"] + dx, o["dy"] + dy, p.yaw)
                spot = s.support(it, bx + ddx, by + ddy, yaw)
                if spot["valid"] and (spot["level"] or o.get("overhang")) and spot["surface"] == want:
                    return self._add(it, spot, yaw)
            return self._skip(it)
        # the floor (or a furniture piece that wasn't placed: next to the scene's first table)
        x, y = o["x"] + off[0], o["y"] + off[1]
        if o["on"] != "floor" and self.stations:
            st = s.station(self.stations[0])
            sx, sy = st.footprint()
            x, y, _ = st.to_world(sx / 2 + 0.4, 0.0)
        mine = self._mine_rects()
        for dx, dy in _spiral(0.1, 8):
            r = _item_rect(it, x + dx, y + dy, yaw)
            if any(_hit(r, b, 0.05) for b in mine):
                continue
            spot = s.support(it, x + dx, y + dy, yaw)
            if spot["valid"] and spot["surface"] == "the floor":
                return self._add(it, spot, yaw)
        return self._skip(it)

    def _levels(self, item, host, x, y, yaw):
        """The spaces inside the object host where item would rest with its middle over (x, y),
        lowest first: each a spot from the drop check, kept only when the item stands level on
        the host itself and fits under whatever is above (a drawer's top, the next shelf)."""
        s = self.sim
        p = s.find(host)
        hz = catalog.meta(p.item)["size"][2]
        h = catalog.meta(item)["size"][2]
        want = catalog.item(p.item)["label"]
        groups = []       # [ceiling (the highest drop start that lands here), spot]
        t = p.pos[2] + hz + 0.02
        while t > p.pos[2] + 0.01:
            spot = s.support(item, x, y, yaw, top=t)
            z = spot["pos"][2]
            if groups and abs(groups[-1][1]["pos"][2] - z) < 0.005:
                pass
            else:
                groups.append([t, spot])
            t -= 0.004
        out = []
        for n, (ceil, spot) in enumerate(groups):
            open_top = n == 0
            if not (spot["valid"] and spot["level"] and spot["surface"] == want):
                continue
            if open_top or ceil - spot["pos"][2] >= h + 0.003:
                out.append((spot, open_top))
        return sorted(out, key=lambda r: r[0]["pos"][2])

    def _swap_host(self, item, host, o):
        """item fits inside nothing here: another cabinet (or shelf, box) from the host's own
        short list that it does fit inside, put down where the host was. (host, uid or None)"""
        s = self.sim
        p = s.find(host)
        sl = (self.pick.get("slot_of") or {}).get(p.item)
        if sl is None or not self.pick.get("lists"):
            return host, None
        pos, yaw0, old = tuple(p.pos), p.yaw, p.item
        for alt in self.pick["lists"][sl]:
            if alt == old or catalog.item(alt)["fixed"] != catalog.item(old)["fixed"]:
                continue
            s.remove(host)
            self.objects.remove(host)
            # turned so its front faces where the first one's front did
            yaw = yaw0 + (math.pi if front_sign(alt) != front_sign(old) else 0.0)
            spot = s.support(alt, pos[0], pos[1], yaw)
            nu = None
            if spot["valid"] and spot["level"]:
                nu = s.add(alt, spot["pos"], yaw)
                self.objects.append(nu)
                uid = self._place_inside(item, nu, o)
                if uid:
                    self.fixes.append(f"used the {catalog.item(alt)['label'].lower()} instead of the "
                                      f"{catalog.item(old)['label'].lower()}, so the "
                                      f"{catalog.item(item)['label'].lower()} fits inside")
                    return nu, uid
                s.remove(nu)
                self.objects.remove(nu)
            spot = s.support(old, pos[0], pos[1], yaw0)     # put the first one back
            host = s.add(old, spot["pos"], yaw0)
            self.objects.append(host)
        return host, None

    def _place_inside(self, item, host, o):
        if not hasattr(self, "_host_levels"):
            self._host_levels = {}
        s = self.sim
        p = s.find(host)
        yaw = p.yaw + (o["yaw"] or 0.0)
        for dx, dy in _spiral(0.03, 6):
            ddx, ddy = _rot(o["dx"] + dx, o["dy"] + dy, p.yaw)
            all_lv = self._levels(item, host, p.pos[0] + ddx, p.pos[1] + ddy, yaw)
            lv = [sp for sp, open_top in all_lv if not open_top]
            if not lv:
                # an open container (tote, bin, basket): its floor, down inside its rim
                top = p.pos[2] + catalog.meta(p.item)["size"][2]
                lv = [sp for sp, open_top in all_lv if open_top and sp["pos"][2] < top - 0.02]
            if not lv:
                continue
            # which level is meant is read off the holder as it first was (empty), so things
            # already on a lower level don't shift the count
            heights = self._host_levels.setdefault(host, [sp["pos"][2] for sp in lv])
            n = o.get("level", 1)
            want = heights[min(max(n - 1, 0), len(heights) - 1)] if n > 0 else heights[max(len(heights) + n, 0)]
            spot = next((sp for sp in lv if abs(sp["pos"][2] - want) < 0.006), None)
            if spot is not None:
                return self._add(item, spot, yaw)
        return None

    def _add(self, item, spot, yaw):
        try:
            uid = self.sim.add(item, spot["pos"], yaw)
        except Exception:  # noqa: BLE001     e.g. the soft-object limit
            return self._skip(item)
        self.objects.append(uid)
        self.counts["objects"][0] += 1
        return uid

    def _skip(self, item, what: str = "objects"):
        self.skipped.append(catalog.item(item)["label"])
        self.counts[what][1] -= 1
        return None


    # -------------------------------------------------- look and fix (v2 picks)
    def views(self) -> list[dict]:
        """Two views of the built scene: from above at a slant, and from the robots' front."""
        rs = []
        s = self.sim
        for st in (s.station(u) for u in self.stations):
            if st is not None:
                rs.append(_station_rect(st.kind, st.robot, st.pos[0], st.pos[1], st.yaw))
        for u in self.objects:
            p = s.find(u)
            if p is not None:
                rs.append(_item_rect(p.item, p.pos[0], p.pos[1], p.yaw))
        if not rs:
            return []
        x0, y0 = min(r[0] for r in rs), min(r[1] for r in rs)
        x1, y1 = max(r[2] for r in rs), max(r[3] for r in rs)
        cx, cy, span = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0, 2.0)
        st = s.station(self.stations[0]) if self.stations else None
        az = (math.degrees(st.yaw) + 180.0) % 360 if st else 145.0     # looking at the robot's face... from behind its table
        return [{"lookat": [cx, cy, 0.4], "distance": 1.3 * span + 1.0, "azimuth": 90.0, "elevation": -70.0,
                 "area": (x0, y0, x1, y1)},
                {"lookat": [cx, cy, 0.7], "distance": 1.0 * span + 1.2, "azimuth": az, "elevation": -25.0}]

    def pictures(self, w: int = 1024, h: int = 640) -> list[bytes]:
        from . import scenegrid
        vs = self.views()
        # with the layout grid on, the picture from above shows the floor's squares and metres
        return [snapshot(self.sim, v, w, h, grid=v.get("area") if scenegrid.on() and k == 0 else None)
                for k, v in enumerate(vs)]

    def _placed_rows(self) -> list[dict]:
        s = self.sim
        rows = []
        for n, u in enumerate(self.objects):
            p = s.find(u)
            if p is None:
                continue
            on = "floor"
            st = next((st for st in s.stations if st.holds(p.pos[0], p.pos[1])), None)
            if st is not None:
                on = f"table of {st.name}"
            elif p.pos[2] > 0.05:
                on = "on furniture"
            rows.append({"n": n, "uid": u, "item": p.item, "label": catalog.item(p.item)["label"],
                         "x": round(p.pos[0], 2), "y": round(p.pos[1], 2), "yaw": round(math.degrees(p.yaw)) % 360,
                         "size_cm": [round(100 * v) for v in catalog.meta(p.item)["size"]],
                         "on": on, "role": self.role.get(u, "furniture" if catalog.item(p.item)["fixed"] else "scene")})
        return rows

    def _look_and_fix(self, round_no: int) -> bool:
        """Show the model the scene it built and let it fix what looks wrong: turn things to
        face the right way, move what's misplaced, take out what doesn't belong. Every move
        goes through the same drop check as drag and drop. True if anything changed."""
        s = self.sim
        rows = self._placed_rows()
        if not rows:
            return False
        imgs = self.pictures()
        stations = [{"name": st.name, "robot": st.robot, "x": round(st.pos[0], 2), "y": round(st.pos[1], 2),
                     "faces_deg": round(math.degrees(st.yaw)) % 360}
                    for st in (s.station(u) for u in self.stations) if st is not None]
        br = self.pick.get("brief") or {}
        user = (f"The person's request:\n{self.prompt.strip()[:2000]}\n\nRoom: {br.get('room', '')}\n"
                f"Zones: {json.dumps(br.get('zones', []))}\nTask: {self.task}\n"
                + (f"Your layout rationale (the scene must match it; fix what doesn't, e.g. something "
                   f"meant to start inside or beside a thing but placed elsewhere): {json.dumps(self.rationale)}\n"
                   if self.rationale else "") +
                f"Robots' stations (x, y in metres; the robot faces faces_deg): {json.dumps(stations)}\n"
                f"Objects placed (n, label, x, y, yaw in degrees, size, what it stands on, role): "
                f"{json.dumps([{k: r[k] for k in ('n', 'label', 'x', 'y', 'yaw', 'size_cm', 'on', 'role')} for r in rows])}\n"
                f"Front sides: an object turned yaw 0 has its front towards -y, except "
                f"{[r['n'] for r in rows if front_sign(r['item']) > 0]} whose front is towards +y at yaw 0. "
                "Picture 1 looks down from above (+x to the right, +y up); picture 2 looks at the robots from the side.")
        from . import scenegrid
        if scenegrid.on():
            user += (" Picture 1 has the floor's grid drawn on it: 25 cm squares, a bold line at each metre "
                     "with its x or y number (metres, the same frame as the positions above). Read positions "
                     "and gaps off it, and give moves on its squares (multiples of 0.25 for furniture).")
        try:
            out = ask_json(self.model_id, FIX_SYSTEM, user, self.public, effort="medium", images=imgs)
        except ModelError:
            return False
        if out.get("plan") and round_no == 0:
            self.plan_text = (self.plan_text + " Check: " + str(out["plan"]).strip())[:900]
        changed = False
        by_n = {r["n"]: r for r in rows}
        with_lock = []
        for f in (out.get("fixes") or [])[:10]:
            r = by_n.get(_int((f or {}).get("n"), -1))
            if r is None:
                continue
            p = s.find(r["uid"])
            if p is None:
                continue
            if f.get("action") == "remove":
                if r["role"] == "task":
                    continue                 # the task needs it
                s.remove(r["uid"])
                self.objects.remove(r["uid"])
                kk = "objects" if not catalog.item(p.item)["fixed"] else "furniture"
                self.counts[kk][0] -= 1
                self.counts[kk][1] -= 1
                self.fixes.append(f"took out the {r['label'].lower()}")
                changed = True
                continue
            x = _f(f.get("x")) if f.get("x") is not None else p.pos[0]
            y = _f(f.get("y")) if f.get("y") is not None else p.pos[1]
            yaw = p.yaw
            if f.get("face") is not None:
                yaw = _facing(p.item, x, y, f.get("face"), [{"x": st["x"], "y": st["y"]} for st in stations], yaw)
            elif f.get("yaw") is not None:
                yaw = math.radians(_f(f.get("yaw")))
            if abs(x - p.pos[0]) < 0.01 and abs(y - p.pos[1]) < 0.01 and abs(yaw - p.yaw) < 0.03:
                continue
            spot = None
            for dx, dy in _spiral(0.04, 5):
                sp = s.support(p.item, x + dx, y + dy, yaw, exclude_uid=r["uid"])
                if sp["valid"] and (sp["level"] or catalog.item(p.item)["fixed"]):
                    if catalog.item(p.item)["fixed"] and sp["surface"] != "the floor":
                        continue
                    if r["role"] == "task":          # a task object stays on a robot's table
                        st = next((st for st in s.stations if st.holds(x + dx, y + dy, -0.06)), None)
                        if st is None or st.near_base(x + dx, y + dy):
                            continue
                    spot = sp
                    break
            if spot is None:
                continue
            s.move(r["uid"], spot["pos"], yaw)
            moved = abs(x - p.pos[0]) > 0.01 or abs(y - p.pos[1]) > 0.01
            self.fixes.append(f"{'moved' if moved else 'turned'} the {r['label'].lower()}")
            changed = True
        return changed

    # -------------------------------------------------- undo
    def undo(self) -> str | None:
        if self.status()["active"]:
            return "the scene is still being built: stop it first"
        if self.undone:
            return None
        s = self.sim
        with s.lock:
            s._sync_placed()
            keep = {u for u in self.objects}
            s.placed = [p for p in s.placed if p.uid not in keep]
        gone = [u for u in self.stations if s.station(u) is not None]
        if gone:
            s.remove_stations(gone)
        else:
            s.rebuild()
        for u in gone:
            self.sess.unsent.pop(u, None)
        self.undone = True
        return None


def front_sign(item: str) -> int:
    """Which way an object's front faces when it isn't turned: -1 for -y (NVIDIA SimReady,
    USDCraft and most sources), +1 for +y (Tripo's models)."""
    if item in OPEN_PLUS_Y:
        return 1
    return 1 if catalog.item(item)["hf"].startswith("tripo:") else -1


# Words that ask for every station to be the same
MATCHING = re.compile(r"\b(identical|same (setup|objects|scene|things|items|layout)|the same \d+ objects|"
                      r"side by side.{0,40}compare|duplicate|copies of)\b", re.I)

# The panels of a robot cell's guard: three or more are stood round the cell (Build._arrange_room)
FENCE = ("safety_fence", "uc_robot_cell_safety_fence_door")

# Furniture that stands against a wall in a real room (by its branch of the object tree): a scene's
# pieces of these kinds are stood in runs round the robots' tables (Build._arrange_room)
WALL_KINDS = ("Counters & cabinets", "Sinks & taps", "Large appliances", "Racks & shelving", "Electrical",
              "Machines", "Plant equipment", "Shelves & storage", "Lab furniture", "Incubators & ovens",
              "Medical equipment", "Office & school > Storage", "Library", "Tool storage", "Workbenches",
              "Retail fixtures", "Laundry", "Boards & presenting")


# LIBERO's shelves are open on +y (measured: rays from +y reach the back panel, from -y they hit it)
OPEN_PLUS_Y = {"libero_wooden_shelf", "libero_wooden_two_layer_shelf"}


def _facing(item: str, x: float, y: float, face, stations: list, yaw: float) -> float:
    """The turn (radians) that points an object's front at what "face" names: "station N" (that
    station's robot) or [x, y]; else the yaw it was given."""
    tx = ty = None
    if isinstance(face, str):
        m = re.search(r"(\d+)", face)
        if face.strip().lower().startswith("station") and stations:
            st = stations[max(0, min(len(stations) - 1, int(m.group(1)) if m else 0))]
            tx, ty = st["x"], st["y"]
    elif isinstance(face, (list, tuple)) and len(face) == 2:
        tx, ty = _f(face[0]), _f(face[1])
    if tx is None or (abs(tx - x) < 1e-6 and abs(ty - y) < 1e-6):
        return yaw
    phi = math.atan2(ty - y, tx - x)
    return phi - math.pi / 2 if front_sign(item) > 0 else phi + math.pi / 2


def _f(v) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _spiral(step: float, rings: int):
    """(0, 0), then rings of points around it, step apart, nearest first."""
    yield 0.0, 0.0
    for r in range(1, rings + 1):
        n = 8 * r
        for k in range(n):
            a = 2 * math.pi * k / n
            yield step * r * math.cos(a), step * r * math.sin(a)
