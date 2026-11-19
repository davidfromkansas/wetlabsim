"""Describe a scene: a person types what they want ("a robot making breakfast in a kitchen"),
a language model on their own key picks the robots and objects from our catalog, the person
checks that list, and the model then writes a layout plan that the server builds on a free
spot of the floor: robots first (each on its own station table), then furniture, then the
objects, every one put down with the same drop check as drag and drop (PlaygroundSim.support).
Library objects always win; anything the scene needs that the library lacks (up to MAX_MADE
things) is made by the same model from simple shapes first, the way a scene from a photo is
(photoscene.py), and each one checked and physics-tested by aimade.py before it is laid out.

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
from . import aimade as AI
from . import catalog
from . import world as W
from wetlabsim import scene as WS

MAX_ROBOTS = 4
MAX_EACH = 6          # copies of one object a scene may ask for
MAX_ITEMS = 40        # objects in one scene, all told
MAX_MADE = 15         # different objects the AI may make for one scene (things the library lacks)

# The models that can build a scene, by company, most capable first (the default).
SCENE_MODELS = [
    {"id": "claude-fable-5-2", "label": "Claude Fable 5.2", "provider": "anthropic"},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "provider": "anthropic"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "provider": "anthropic"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "provider": "anthropic"},
    {"id": "gpt-6.2-astra", "label": "GPT-6.2 Astra", "provider": "openai"},
    {"id": "gpt-6.2-sol", "label": "GPT-6.2 Sol", "provider": "openai"},
    {"id": "gpt-6-astra", "label": "GPT-6 Astra", "provider": "openai"},
    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol", "provider": "openai"},
    {"id": "gpt-6.1-terra", "label": "GPT-6.1 Terra", "provider": "openai"},
    {"id": "gpt-6-sol", "label": "GPT-6 Sol", "provider": "openai"},
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "provider": "openai"},
]
# A task run's model (server.MODELS ids) as the scene model it is, for "the last model you used".
FROM_RUN = {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"}  # (only its company is used now)
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
it to what fits: about 4 to 16 objects in all (with the ones to make).
- make: things the scene needs that are NOT in the list. They will be built for it from simple \
shapes by an AI, so don't settle for a poor stand-in. But the list always wins: before you add \
one here, look through the list again, and if a listed object is that thing (any make, size or \
style of it), put it in items instead. Each entry: name (plain words, e.g. "Loaf of bread"), \
count (1 to {max_each}), kind ("furniture" if it stands on the floor, else "object"), size \
[width, depth, height] in metres (its real size), looks (colours, materials, main parts) and \
moves (its moving parts, e.g. "door hinged on the left", or "none"). At most {max_made} \
different things; leave out the least important ones if there would be more.
- title: a short name for the scene, 2 to 4 words.
- task: one sentence, the task the robot(s) will be given, in plain words.

Answer with JSON only, exactly this shape:
{{"title": "...", "robots": [{{"robot": "franka", "count": 1}}], "items": [{{"id": "mug", "count": 1}}], \
"make": [{{"name": "Loaf of bread", "count": 1, "kind": "object", "size": [0.25, 0.12, 0.10], \
"looks": "golden-brown crust, rounded top", "moves": "none"}}], "task": "..."}}"""

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
- Furniture (the items marked as furniture) stands on the floor, in the scene's frame: never \
over a station table, and at least 0.3 m from every table and from other furniture.
- Objects for the robots' task go on their station's table, within reach of the robot: station \
frame x from -0.15 to 0.75 and y from -0.5 to 0.5 (for the wet lab bench x from -0.1 to 0.3 and y \
from -0.8 to 0.8; the island x from -0.05 to 0.25, y from -0.55 to 0.55; the counter x from -0.05 \
to 0.25, y from -1.05 to 1.05), at least 0.25 m from the robot's base. Small things can go in a hollow object \
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


MAKE_SYSTEM = """You are a 3D artist and simulation engineer. Build each object you are asked for as a \
SIM-READY MuJoCo model for a robot physics playground: the right size, the right look and colours, and \
it must behave like the real thing. Doors open, drawers slide, lids lift, loose things fall and can be \
picked up. Units are metres; z is up. Keep your written notes short (a few lines before the answer).

For each object (these follow Google DeepMind's MuJoCo asset standards, cut to what this format allows):
1. REAL SIZE. Its overall width, depth and height match the real thing (the size you are given, or a \
real product's); check that the parts add up to it. Units are metres and kilograms.
2. KIND. Each object is either kind="fixed" (furniture, counters, appliances, heavy things: they never move \
as a whole) or kind="loose" (things a hand could pick up or push); you are told which.
3. MASS. Put the mass on the shapes themselves, spread by volume and material (water/food ~1000 kg/m3, wood \
~600, plastic ~950, glass ~2500, steel ~7800, ceramic ~2300; hollow items use their shell, not their whole \
volume), so the total is what the real one weighs and the centre of mass sits where the real one's does \
(a heavy base low down). No hidden extra weights, and no part without mass.
4. SHAPES THAT WORK. Collision shapes are the visible shapes, and they must keep what the object is used for:
   - Containers (cups, bowls, bins, trays, drawers, sinks): a base plus a ring of thin wall boxes, open on \
top, so a small thing dropped in lands on the inside floor. Never fill a hollow with one solid shape.
   - Handles and loops (mug handles, drawer pulls, kettle handles): build them from separate segments \
with a real gap, so a finger fits through.
   - Nothing thinner than 3 mm (walls, shelves, bases, rods), so things dropped on it don't pass through.
   - Wheels and casters that let it roll are their own child bodies on hinges (a caster: a swivel body on \
a vertical hinge, then a wheel body on its axle hinge), not fixed to the frame.
   - Every shape is visible: its alpha (the last number of rgba) is 1, never 0.
5. MOVING PARTS. Give it only the joints the real thing has (doors, drawers, lids, laptop screens, knobs \
that turn): each moving part is a child body with one hinge (turns) or slide (moves in a line) joint whose \
pos and axis sit on the real pivot (a door's hinge edge, a drawer's runners). Each has a limited range \
it can really move without hitting its frame or a neighbour (leave 2-3 mm gaps), damping (0.02-0.5 for \
small lids and hinges, 1-5 for heavy doors and drawers) and armature 0.001-0.01. A part that stays where \
it is put (a laptop screen, an adjustable stand) gets frictionloss a little more than gravity's pull on \
it (about 1.25 x its weight in N, times its lever arm in m for a hinge). A part that springs back (a \
toaster lever, a button) gets stiffness and springref. Doors start closed.
6. CONTACT. Give each shape the friction of its material (0.3 smooth glass or metal to 1.0 rubber). Leave \
condim, solref, solimp, margin and gap out: the playground sets contact physics for every object itself.
7. LOOKS. Build it from simple shapes into a recognisable form: a mug = cylinder walls + base + handle, a \
chair = seat + back + 4 legs, a microwave = hollow box + hinged door with a handle. Use its real colours.

ANSWER FORMAT. After your short notes, write the objects and nothing after them:

<scene title="Objects" objects="N">
<object name="Microwave" kind="fixed" x="0" y="0" z="0" yaw="0">
<mujoco>
  <asset><material name="steel" rgba="0.8 0.8 0.82 1" specular="0.5"/></asset>
  <worldbody>
    <body name="microwave">
      <geom type="box" size="0.25 0.18 0.01" pos="0 0 -0.14" material="steel" mass="2.5"/>
      ...
      <body name="door" pos="-0.25 -0.19 0">
        <joint name="door_hinge" type="hinge" axis="0 0 1" range="-110 0" damping="0.2" armature="0.01"/>
        <geom type="box" size="0.25 0.01 0.14" pos="0.25 0 0" rgba="0.1 0.1 0.1 1" mass="0.8"/>
      </body>
    </body>
  </worldbody>
</mujoco>
</object>
...
</scene>

Rules for every object:
- One <object> per object asked for, in the order asked, with exactly the name and kind given; x, y, z \
and yaw are always 0 (the playground places it).
- Inside <mujoco>, build the object around its own origin with its front facing -y. Angles are in degrees.
- One top <body> per object, named for what it is ("toaster", not "body" or "root"), with no pos or \
rotation of its own. Moving parts are child bodies, each with one hinge or slide <joint> and a plain name \
saying what it is ("door_left", "drawer_top", "lid").
- Allowed: <asset> with <material name rgba specular shininess reflectance> only; <body>, <geom> \
(type box, cylinder, capsule, sphere or ellipsoid), <joint> (type hinge or slide), <inertial>. NOT \
allowed: meshes, textures, files, <include>, <default>, lights, cameras, actuators, <freejoint> (the \
playground adds those itself).
- Every geom has mass= (or density=) and rgba= or material=. At most 40 bodies and 160 geoms per object.
- Parts must not start inside each other where they move, and nothing may stick out below the \
object's bottom. A loose object must stand steady on a flat floor.
"""

MAKE_ASK = """Make these {n} objects for a scene ("{title}", from the request: "{prompt}"):

{wants}"""


def make_messages(prompt: str, title: str, make: list) -> str:
    rows = []
    for k, m in enumerate(make, 1):
        size = (" x ".join(f"{v:.2f}" for v in m["size"]) + " m (width x depth x height)") if m.get("size") else "its real size"
        rows.append(f'{k}. name="{m["name"]}" kind="{"fixed" if m["kind"] == "furniture" else "loose"}": size {size}; '
                    f'looks: {m.get("looks") or "as the real thing"}; moving parts: {m.get("moves") or "none"}')
    return MAKE_ASK.format(n=len(make), title=title.replace('"', "'"), prompt=prompt.strip()[:600].replace('"', "'"),
                           wants="\n".join(rows))


def pick_messages(prompt: str) -> tuple[str, str]:
    sys_ = PICK_SYSTEM.format(robots=_robots_text(), objects=_objects_text(), max_robots=MAX_ROBOTS,
                              max_each=MAX_EACH, max_made=MAX_MADE)
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
    # Things the library lacks, to be made by the AI (photoscene/aimade): the first MAX_MADE kept,
    # the rest left out and said so. A name that is a library object's label is that object.
    labels = {c["label"].strip().lower(): c["id"] for c in rows.values()}
    make, have = [], set()
    for m in raw.get("make") or []:
        if not isinstance(m, dict):
            continue
        name = " ".join(str(m.get("name", "")).split())[:40]
        n = _int(m.get("count"), 1)
        if not name or n <= 0 or name.lower() in have:
            continue
        have.add(name.lower())
        lib = labels.get(name.lower())
        if lib:                                    # the library has it after all
            if lib not in [x["id"] for x in items] and n_items < MAX_ITEMS:
                n = min(n, MAX_EACH, MAX_ITEMS - n_items)
                items.append({"id": lib, "count": n})
                n_items += n
            continue
        if len(make) >= MAX_MADE or n_items >= MAX_ITEMS:
            missing.append({"name": name, "instead": ""})
            continue
        n = min(n, MAX_EACH, MAX_ITEMS - n_items)
        size = m.get("size") if isinstance(m.get("size"), list) else []
        size = [min(20.0, max(0.01, _f(v))) for v in size[:3]] if len(size) >= 3 else []
        make.append({"name": name, "count": n, "kind": "furniture" if m.get("kind") == "furniture" else "object",
                     "size": size, "looks": " ".join(str(m.get("looks", "")).split())[:200],
                     "moves": " ".join(str(m.get("moves", "")).split())[:200]})
        n_items += n
    return {"title": (str(raw.get("title") or "").strip() or "New scene")[:40],
            "robots": robots, "items": items, "make": make, "missing": missing[:8],
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
            + (f"Objects made for this scene (id: what it is): "
               f"{json.dumps({i: catalog.item(i)['label'] for i in set(items) if AI.is_ai(i)})}\n"
               if any(AI.is_ai(i) for i in items) else "")
            + (f"Task in mind: {pick['task']}\n" if pick.get("task") else ""))
    return sys_, user


# ------------------------------------------------------------------ fake answers (no model)
def fake_pick(prompt: str) -> dict:
    return {"title": "Kitchen breakfast", "robots": [{"robot": "fr3_duo", "count": 1}],
            "items": [{"id": i, "count": 1} for i in ("refrigerator", "workbench", "wash_basin", "toaster",
                                                       "cereal_box", "milk", "bowl", "mug", "kettle", "apple")
                      if i in {c["id"] for c in _catalog_rows()}],
            "make": [{"name": "Loaf of bread", "count": 1, "kind": "object", "size": [0.25, 0.12, 0.1],
                      "looks": "golden-brown crust", "moves": "none"}],
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


def fake_make(text: str) -> str:
    """A pretend model's answer to MAKE_ASK: each object asked for as a plain box of its size."""
    if text.startswith("Your object"):
        return ""
    time.sleep(0.4)
    out = []
    for name, kind, size in re.findall(r'^\d+\. name="([^"]*)" kind="(\w+)": size ([\d. x]*)', text, re.M):
        dims = [float(v) for v in re.findall(r"[\d.]+", size)][:3] or [0.2, 0.2, 0.2]
        w, d, h = (dims + [0.2, 0.2, 0.2])[:3]
        mass = max(0.05, min(80.0, w * d * h * 400))
        out.append(f'<object name="{name}" kind="{kind}" x="0" y="0" z="0" yaw="0"><mujoco><worldbody>'
                   f'<body name="b"><geom type="box" size="{w / 2:.3f} {d / 2:.3f} {h / 2:.3f}" '
                   f'rgba="0.8 0.6 0.3 1" mass="{mass:.3f}"/></body></worldbody></mujoco></object>')
    return f'<scene title="Objects" objects="{len(out)}">' + "".join(out) + "</scene>"


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
        self.phase = "plan"           # plan, robots, furniture, objects, done, stopped, error
        self.plan_text = ""
        self.error = ""
        self.stop = False
        self.counts = {"robots": [0, sum(r["count"] for r in pck["robots"])], "furniture": [0, 0],
                       "objects": [0, 0], "make": [0, 0 if preset else len(pck.get("make") or [])], "retries": 0}
        self.stations: list[str] = []
        self.objects: list[str] = []
        self.skipped: list[str] = []
        self.task = pck.get("task", "")
        self.zone = None
        self.undone = False
        self.started = time.time()
        self.now = ""                 # what is being put down right now ("the mug")
        self.thought = ""             # the model's latest thinking heading, while it makes objects
        self.last_heard = time.time()  # when the model last sent anything (thinking or answer)
        self.answers: list[str] = []
        self.names = {}
        self._recount(bool(self.counts["make"][1]))
        if self.counts["make"][1]:
            self.phase = "make"
            self.names["make"] = [m["name"] for m in pck["make"]]

    def _recount(self, to_make: bool = False):
        """Furniture and object counts and names, from the pick's items (and, before they are
        made, the things still to make)."""
        pck = self.pick
        rl = {r["id"]: r["label"].replace(" (two arms)", "") for r in catalog.robots()}
        fixed = [i for i in pck["items"] if catalog.item(i["id"])["fixed"]]
        loose = [i for i in pck["items"] if not catalog.item(i["id"])["fixed"]]
        later = (pck.get("make") or []) if to_make else []
        self.counts["furniture"][1] = sum(i["count"] for i in fixed) + sum(m["count"] for m in later if m["kind"] == "furniture")
        self.counts["objects"][1] = sum(i["count"] for i in loose) + sum(m["count"] for m in later if m["kind"] != "furniture")
        self.names.update({"robots": [rl.get(r["robot"], r["robot"]) for r in pck["robots"]],
                           "furniture": [catalog.item(i["id"])["label"] for i in fixed]
                           + [m["name"] for m in later if m["kind"] == "furniture"],
                           "objects": [catalog.item(i["id"])["label"] for i in loose]
                           + [m["name"] for m in later if m["kind"] != "furniture"]})

    def status(self) -> dict:
        return {"id": self.id, "phase": self.phase, "plan": self.plan_text, "error": self.error,
                "counts": self.counts, "title": self.pick["title"], "stations": self.stations,
                "objects": len(self.objects), "skipped": self.skipped, "task": self.task,
                "undone": self.undone, "now": self.now, "names": self.names, "thought": self.thought,
                "quiet": round(time.time() - self.last_heard, 1),
                "elapsed": round(time.time() - self.started, 1),
                "model": next((m["label"] for m in SCENE_MODELS if m["id"] == self.model_id), ""),
                "active": self.phase in ("make", "plan", "robots", "furniture", "objects")}

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="scene-build").start()

    # -------------------------------------------------- the steps
    def _run(self):
        s = self.sim
        was_playing = not s.paused
        try:
            if self.phase == "make":
                self._make_missing()
                if self.stop:
                    return self._end("stopped")
                self.phase = "plan"
                self.now = ""
                self._recount()
            if self.preset:
                lay = PRESETS[self.preset]
            elif fake():
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
            for o in objects:
                if self.stop:
                    return self._end("stopped")
                self.now = catalog.item(o["item"])["label"]
                self._place_object(o, off, fixed_uids)
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
            if was_playing and self.phase not in ("make", "plan"):
                s.play()

    # -------------------------------------------------- objects the library lacks, made by the model
    def _make_missing(self):
        """Every thing on the pick's "make" list built by the model in one answer (the photo scene's
        object format), then each one checked and physics-tested (aimade), sent back to the model
        to fix when it fails (photoscene.PhotoBuild._make). What passes joins the pick's items."""
        from . import photoscene as PS
        wants = self.pick["make"]
        self.now = ""
        ans = self._ask(make_messages(self.prompt, self.pick["title"], wants), "high", on_text=self._made_text)
        if self.stop:
            return
        _, objs = PS.parse_scene(ans)
        by_name = {o["name"].strip().lower(): o for o in objs}
        for k, w in enumerate(wants):
            if self.stop:
                return
            o = by_name.get(w["name"].lower()) or (objs[k] if k < len(objs) and objs[k]["name"].lower() not in
                                                   {x["name"].lower() for x in wants} else None)
            self.now = f"Testing the {w['name'].lower()}"
            got = None
            if o and o["xml"]:
                o = {**o, "name": w["name"], "kind": "fixed" if w["kind"] == "furniture" else "loose"}
                got = PS.PhotoBuild._make(self, o)    # the same checks and fixing as a scene from a photo
            elif w["name"] not in self.skipped:
                self.skipped.append(w["name"])
            if got:
                self.pick["items"].append({"id": got["item"], "count": w["count"]})
                self.counts["make"][0] += 1

    def _made_text(self, full: str):
        self.last_heard = time.time()
        names = re.findall(r'<object\b[^>]*\bname="([^"]*)"', full)
        if names:
            self.now = f"Making the {names[-1].lower()}" + (f" ({len(names)} of {self.counts['make'][1]})"
                                                             if self.counts["make"][1] > 1 else "")

    def _think(self, s):
        self.last_heard = time.time()
        if not s:
            return
        heads = re.findall(r"\*\*(.+?)\*\*", s)
        if heads:
            self.thought = heads[-1].strip()[:80]
        elif s.strip() and not self.thought:
            self.thought = s.strip().splitlines()[0][:80]

    def _ask(self, text: str, effort: str, on_text=None) -> str:
        """One streamed answer from the scene's model (photoscene.ask_stream), with MAKE_SYSTEM."""
        from . import photoscene as PS
        if fake():
            ans = fake_make(text)
        else:
            ans = PS.ask_stream(self.model_id, [{"type": "text", "text": text}], self.public, effort, self._think,
                                on_text or (lambda t: None), lambda: self.stop, system=MAKE_SYSTEM)
        self.answers.append(f"===== asked: {text[:200]}\n\n{ans}")
        return ans

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
                                 "yaw": math.radians(_f(st.get("yaw"))), "task": str(st.get("task") or "")})
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
                                  "yaw": math.radians(_f(f.get("yaw"))),
                                  # a ready-made scene may butt pieces together (conveyor sections)
                                  "gap": max(0.0, _f(f.get("gap", 0.15))) if self.preset else 0.15})
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
                                "yaw": math.radians(_f(o.get("yaw"))),
                                # a ready-made scene's big part may hang over its pallet's edges
                                "overhang": bool(self.preset and o.get("overhang"))})
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
        cands = sorted({(round(mx + 0.5 * i, 2), round(my + 0.5 * j, 2)) for i in range(-60, 61)
                        for j in range(-60, 61)}, key=lambda v: (v[0] - mx) ** 2 + (v[1] - my) ** 2)
        lim = W.FLOOR_HALF - 0.2
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
