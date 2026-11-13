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

MAX_ROBOTS = 4
MAX_EACH = 6          # copies of one object a scene may ask for
MAX_ITEMS = 40        # objects in one scene, all told

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


def _anthropic(model: str, system: str, user: str, key: str, effort: str) -> str:
    body = {"model": model, "max_tokens": 32000, "system": system,
            "messages": [{"role": "user", "content": user}], "output_config": {"effort": effort}}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        out = _post("https://api.anthropic.com/v1/messages", headers, body)
    except ModelError as e:
        if "(400" not in str(e):
            raise
        body.pop("output_config")          # a model without effort levels
        out = _post("https://api.anthropic.com/v1/messages", headers, body)
    if out.get("stop_reason") == "refusal":
        raise ModelError("the model declined this request")
    return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")


def _openai(model: str, system: str, user: str, key: str, effort: str) -> str:
    body = {"model": model, "instructions": system, "input": user, "max_output_tokens": 32000,
            "reasoning": {"effort": effort}}
    headers = {"authorization": f"Bearer {key}"}
    try:
        out = _post("https://api.openai.com/v1/responses", headers, body)
    except ModelError as e:
        if "(400" not in str(e):
            raise
        body.pop("reasoning")
        out = _post("https://api.openai.com/v1/responses", headers, body)
    if out.get("output_text"):
        return out["output_text"]
    return "".join(c.get("text", "") for o in out.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") in ("output_text", "text"))


WHERE = "local"     # where Codex runs for a ChatGPT sign-in: "local", or "modal" (server.RUN_LAUNCHER)
CODEX_TIMEOUT = 300


def _codex_cmd(model: str, effort: str, out: str, jail: bool) -> list:
    return ["codex", "exec", "--skip-git-repo-check",
            *(["--dangerously-bypass-approvals-and-sandbox"] if jail else ["--sandbox", "read-only"]),
            "--model", model, "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'cli_auth_credentials_store="file"', "-c", 'forced_login_method="chatgpt"',
            "--output-last-message", out]


def _codex(model: str, system: str, user: str, login: str, effort: str) -> str:
    """One answer from an OpenAI model through Codex, signed in with the person's ChatGPT login
    file (the OpenAI API takes API keys only). Codex may refresh the login's tokens: the new file
    is kept, as after a run."""
    prompt = (system + "\n\n" + user + "\n\nDon't run any commands or change any files: answer with "
              "the JSON only, as your final message.")
    if WHERE == "modal":
        text, new = _codex_modal(model, prompt, login, effort)
    else:
        text, new = _codex_local(model, prompt, login, effort)
    if new and new.strip() != login.strip():
        try:
            ACCT.update_login("openai", new)
        except Exception as e:  # noqa: BLE001
            print("could not keep Codex's refreshed login:", e)
    if not text.strip():
        raise ModelError("Codex gave no answer (is the ChatGPT sign-in still good? Try signing in again in Settings)")
    return text


def _codex_local(model: str, prompt: str, login: str, effort: str) -> tuple[str, str]:
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
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL")}
        env.update(CODEX_HOME=home, NO_COLOR="1")
        try:
            p = subprocess.run(_codex_cmd(model, effort, out, jail=False) + [prompt], env=env, cwd=home,
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


def _codex_modal(model: str, prompt: str, login: str, effort: str) -> tuple[str, str]:
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
        proc = sb.exec(*_codex_cmd(model, effort, "/tmp/w/answer.txt", jail=True), prompt, workdir="/tmp/w",
                       env={"CODEX_HOME": "/tmp/codex", "NO_COLOR": "1"}, timeout=CODEX_TIMEOUT)
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


def ask_json(model_id: str, system: str, user: str, public: bool, effort: str = "medium") -> dict:
    m = next((m for m in SCENE_MODELS if m["id"] == model_id), None)
    if m is None:
        raise ModelError("that model can't build scenes")
    kind, key = _cred(m["provider"], public)
    if not key:
        label = ACCT.PROVIDERS[m["provider"]]["label"]
        raise ModelError(f"connect your {label} API key in Settings to use {m['label']}")
    if kind == "chatgpt":
        text = _codex(m["id"], system, user, key, effort)
    else:
        call = _anthropic if m["provider"] == "anthropic" else _openai
        text = call(m["id"], system, user, key, effort)
    return parse_json(text)


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
along x by 1.80 m along y, top 0.85 m high, the robot's base at x -0.20, y 0). An ALOHA stands in \
the middle of a "table" with its two arm bases at y -0.47 and +0.47. The FR3 Duo has two arms on \
one base at x -0.42.
- A station's position is its table's centre on the floor, in the scene's own frame (x, y, \
metres), and yaw is its turn about the vertical in degrees. Keep stations at least 0.5 m apart.
- Furniture (the items marked as furniture) stands on the floor, in the scene's frame: never \
over a station table, and at least 0.3 m from every table and from other furniture.
- Objects for the robots' task go on their station's table, within reach of the robot: station \
frame x from -0.15 to 0.75 and y from -0.5 to 0.5 (for the wet lab bench x from -0.1 to 0.3 and y \
from -0.8 to 0.8), at least 0.25 m from the robot's base. Small things can go in a hollow object \
(an apple in a bowl): give them the same spot. Objects can also go on top of a piece of furniture \
(its index, and dx, dy from its centre) or on the floor (scene frame).
- Leave space between objects (about their size plus 3 cm) so a gripper can get to each.

The scene's robots (each entry is one station): {robots}
The scene's objects: {items}
Sizes (x by y by z, cm): {sizes}

Answer with JSON only, exactly this shape:
{{"plan": "2 to 4 plain sentences on the layout and the choices you made",
 "stations": [{{"robot": "franka", "kind": "table", "x": 0, "y": 0, "yaw": 0}}],
 "furniture": [{{"item": "refrigerator", "x": 2.0, "y": 1.2, "yaw": 180}}],
 "objects": [{{"item": "mug", "on": "station", "station": 0, "x": 0.3, "y": 0.1, "yaw": 0}},
             {{"item": "kettle", "on": "furniture", "furniture": 0, "dx": 0, "dy": 0, "yaw": 0}},
             {{"item": "waste_bin", "on": "floor", "x": 1.5, "y": -1.0, "yaw": 0}}],
 "task": "the robot's task, one sentence"}}
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
    sys_ = LAYOUT_SYSTEM.format(robots=json.dumps(robots), items=json.dumps(items), sizes=json.dumps(sizes))
    user = (f"The person's request:\n{prompt.strip()[:2000]}\n\nScene name: {pick['title']}\n"
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


def pick(prompt: str, model_id: str, public: bool) -> dict:
    if fake():
        time.sleep(0.6)
        return clean_pick(fake_pick(prompt))
    sys_, user = pick_messages(prompt)
    out = clean_pick(ask_json(model_id, sys_, user, public, effort="low"))
    if not out["robots"]:
        raise ModelError("the model didn't choose any robot: try saying which robot you want")
    return out


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

    def __init__(self, sim, sess, prompt: str, pck: dict, model_id: str, public: bool):
        self.sim, self.sess, self.prompt, self.pick = sim, sess, prompt, pck
        self.model_id, self.public = model_id, public
        self.id = os.urandom(4).hex()
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
                "model": next((m["label"] for m in SCENE_MODELS if m["id"] == self.model_id), ""), "active": self.phase in ("plan", "robots", "furniture", "objects")}

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="scene-build").start()

    # -------------------------------------------------- the steps
    def _run(self):
        s = self.sim
        was_playing = not s.paused
        try:
            if fake():
                time.sleep(0.8)
                lay = fake_layout(self.pick)
            else:
                sys_, user = layout_messages(self.prompt, self.pick)
                lay = ask_json(self.model_id, sys_, user, self.public, effort="high")
            self.plan_text = str(lay.get("plan") or "").strip()[:800]
            self.task = str(lay.get("task") or self.task).strip()[:600] or self.task
            if self.stop:
                return self._end("stopped")
            stations, furniture, objects = self._clean_layout(lay)
            s.pause()
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
            for o in objects:
                if self.stop:
                    return self._end("stopped")
                self.now = catalog.item(o["item"])["label"]
                self._place_object(o, off, fixed_uids)
            self.now = ""
            if self.stations and self.task:
                for u in self.stations:
                    self.sess.unsent[u] = {"task": self.task, "model": ""}
            self._end("done")
        except Exception as e:  # noqa: BLE001
            self.error = str(e) if isinstance(e, (ModelError,)) else f"something went wrong: {e}"
            self._end("error")
        finally:
            s.zone = []
            if was_playing and self.phase != "plan":
                s.play()

    def _end(self, phase: str):
        self.phase = phase
        self.sim.zone = []
        if self.stations:
            self.sim.active_station = self.stations[0]
            self.sim.frame_station(self.stations[0])

    def _clean_layout(self, lay: dict):
        """The layout kept to what the person checked: the robots and objects on their list
        (anything the model left out goes in a sensible default spot)."""
        want_r = [r["robot"] for r in self.pick["robots"] for _ in range(r["count"])]
        stations = []
        for st in lay.get("stations") or []:
            rb = str((st or {}).get("robot", ""))
            if rb in want_r:
                want_r.remove(rb)
                kind = st.get("kind") if st.get("kind") in W.KINDS else "table"
                stations.append({"robot": rb, "kind": kind, "x": _f(st.get("x")), "y": _f(st.get("y")),
                                 "yaw": math.radians(_f(st.get("yaw")))})
        for rb in want_r:
            stations.append({"robot": rb, "kind": "table", "x": 0.0, "y": 2.0 * len(stations), "yaw": 0.0})
        items = [i["id"] for i in self.pick["items"] for _ in range(i["count"])]
        want_f = [i for i in items if catalog.item(i)["fixed"]]
        want_o = [i for i in items if not catalog.item(i)["fixed"]]
        furniture = []
        for f in lay.get("furniture") or []:
            it = str((f or {}).get("item", ""))
            if it in want_f:
                want_f.remove(it)
                furniture.append({"item": it, "x": _f(f.get("x")), "y": _f(f.get("y")),
                                  "yaw": math.radians(_f(f.get("yaw")))})
        for it in want_f:
            furniture.append({"item": it, "x": 2.5, "y": -1.5 + 1.5 * len(furniture), "yaw": math.pi})
        objects = []
        for o in lay.get("objects") or []:
            it = str((o or {}).get("item", ""))
            if it in want_o:
                want_o.remove(it)
                on = o.get("on") if o.get("on") in ("station", "furniture", "floor") else "station"
                objects.append({"item": it, "on": on,
                                "station": max(0, min(len(stations) - 1, _int(o.get("station"), 0))),
                                "furniture": _int(o.get("furniture"), 0),
                                "x": _f(o.get("x")), "y": _f(o.get("y")),
                                "dx": _f(o.get("dx")), "dy": _f(o.get("dy")),
                                "yaw": math.radians(_f(o.get("yaw")))})
        for k, it in enumerate(want_o):
            objects.append({"item": it, "on": "station", "station": k % max(1, len(stations)),
                            "x": 0.3, "y": 0.0, "dx": 0.0, "dy": 0.0, "yaw": 0.0})
        if not stations:
            raise ModelError("the scene has no robot")
        if any(o["on"] == "furniture" for o in objects) and not furniture:
            for o in objects:
                if o["on"] == "furniture":
                    o["on"] = "station"
        return stations, furniture, objects

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
        uid = s.add_station(st["robot"], spot["pos"], yaw, st["kind"], starter=False)
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
            if any(_hit(r, b, 0.15) for b in mine):
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

    def _place_object(self, o, off, fixed_uids):
        s = self.sim
        it, yaw = o["item"], o["yaw"]
        if o["on"] == "station" and o["station"] < len(self.stations):
            st = s.station(self.stations[o["station"]])
            if st is None:
                return self._skip(it)
            want = f"the table of {st.name}"
            lx, ly = o["x"], o["y"]
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
                if spot["valid"] and spot["level"] and spot["surface"] == want:
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
