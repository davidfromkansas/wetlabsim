"""A scene from a photo: the person drops in a photo of a real place in "Create scene", and a
language model on their own key (or ChatGPT sign-in) rebuilds every object in it from simple
shapes, as small MuJoCo models with real-looking sizes, guessed masses and working doors,
drawers and lids (playground/aimade.py checks each one). The scene is put down on a free spot of
the floor, with no robot: the person adds robots afterwards.

While the model works, its thinking (the summaries the companies stream) is shown live, with the
steps: looking at the photo, measuring, building objects k of n, testing physics, placing.
An object that fails its physics test goes back to the model with what went wrong, up to
MAX_TRIES times in all; one that still fails is left out.

The photo is kept with the session: on this server (runs/playground/photos/) and, on the hosted
site, in private Blob storage through the website (savestore).

WETLAB_SCENEGEN_FAKE=1 answers with a ready-made scene and pretend thinking (tests, screenshots).
"""
from __future__ import annotations

import base64
import json
import math
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.request

from . import aimade as AI
from . import lookcheck as LC
from . import scenegen as SG
from .scenegen import ModelError

MAX_TRIES = 3
FIX_AT_ONCE = 6               # objects tested (and sent back to fix) side by side
MAX_OBJECTS = 46          # up to 40 things + 6 walls
MAX_PHOTO_BYTES = 6_000_000
THINKING_KEEP = 4000          # characters of thinking the page is sent
PHOTO_TIMEOUT = 25 * 60       # s: the longest a model may take over one answer
STEP = None                   # on_think(STEP): a thinking step ended that has no words to show

SYSTEM = """You are a 3D artist and simulation engineer. Rebuild the place in the attached photo as a \
SIM-READY MuJoCo scene: the same objects, the same sizes, the same positions and the same colours, \
and it must behave like the real thing. Doors open, drawers slide, lids lift, loose things fall and \
can be picked up. Units are metres; z is up.

Work it out in five steps. Keep your written notes short (at most 12 lines before the scene):
1. INVENTORY. Every visible object: furniture, appliances, and small loose items. Note colour, material \
(wood, metal, glass, plastic, fabric, ceramic) and what each rests on. Build every wall you can see in \
the photo, each as its own fixed object named "Wall (back)", "Wall (left)" and so on: its real length, \
height and colour, about 0.12 m thick, standing on the floor, with openings where the photo shows a door, \
window or doorway (build the wall from boxes around the opening, and the window or door as its own object). \
A wall behind the camera that the photo doesn't show is not built. Leave out the floor (the playground has \
its own) and the ceiling. Keep things fixed to walls (wall cabinets, shelves, boards) at their real height. \
Ignore any people (and pets) in the photo: don't build them, and build \
what they hide or hold as it would be without them (a chair someone sits on is an empty chair; something \
in a person's hand is left out).
2. SCALE. Pick 2-3 objects whose real size you know well (counter height 0.90 m, table 0.75 m, door \
2.0 x 0.8 m, mug 0.10 m tall, soda can 0.12 m, A4 paper 0.30 x 0.21 m, floor tiles 0.30 or 0.60 m) and say \
which you used. Estimate where the camera stands and its height.
3. MEASURE. For each object: width x depth x height, where it stands, and how it is turned. Room frame: \
origin = the floor point straight below the camera, +x to the right, +y away from the camera into the \
scene, z up. Check that nothing overlaps, everything rests on something, nothing floats, and small items \
fit on their surface.
4. MAKE IT SIM-READY. Each object is either kind="fixed" (furniture, counters, built-in cabinets, \
appliances, heavy things: they never move as a whole) or kind="loose" (things a hand could pick up or push: \
mugs, bottles, fruit, tools, small boxes, chairs). Give every part a realistic mass (from material and size: \
water/food ~1000 kg/m3, wood ~600, plastic ~950, glass ~2500, steel ~7800, ceramic ~2300, a wall ~25 kg per m2 of its face; hollow items use \
their shell, not their whole volume) and friction for its material (0.3 smooth to 1.0 rubber). Anything with \
moving parts gets them, even when the object itself is fixed: microwave, oven and fridge doors, cabinet \
doors, drawers, lids, laptop screens, toilet seats, windows. Each moving part is a child body with a \
hinge (turns) or slide (moves in a line) joint at the right edge, with its axis, a limited range \
(e.g. microwave door 0 to 110 degrees, drawer 0 to 0.40 m), damping 0.05-1 and armature 0.01 so it moves \
calmly. Doors start closed unless open in the photo. Collision shapes are the visible shapes: build hollow \
things hollow (a microwave cavity from 5 walls, a cup from a base and a ring of thin boxes) so things \
can go inside them.
Every object is tested in MuJoCo before it goes in; build it to pass:
- Each hinge or slide moves over its whole range: a door swings fully open and shut without hitting its frame, \
the next door or the worktop (leave 2-3 mm gaps), with its axis on the door's hinge edge. Never give a joint more \
range than the part can really move (an elbow can't fold through its own arm).
- Containers (cups, beakers, bowls, bins, trays, tubs, sinks, drawers) are open at the top with a closed bottom.
- Nothing is thinner than 3 mm (walls, bases, shelves, wires, rods), so things dropped on it don't pass through.
- Collision shapes follow the visible outside and keep handles, openings and rims usable; the mass of each part \
fits its material and size.
5. BUILD each object from simple shapes into a recognisable form: a mug = cylinder walls + base + handle, \
a chair = seat + back + 4 legs, a microwave = hollow box + hinged door with a handle. Use the colours in the \
photo.

ANSWER FORMAT. After your short notes, write the scene and nothing after it:

<scene title="Short name of the place" objects="N">
<object name="Microwave" kind="fixed" x="0.40" y="2.10" z="0.90" yaw="0">
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
- N = how many <object> elements follow (at most 40, plus the walls). Name each object plainly ("Coffee mug", "Fridge").
- x, y = the middle of the object's footprint in the room frame; z = the height of its BOTTOM above the floor \
(0 for things on the floor, 0.90 for things on a 0.90 m counter); yaw = degrees it is turned about z, \
counter-clockwise seen from above, 0 = its front faces the camera.
- Inside <mujoco>, build the object around its own origin with its front facing -y (towards the camera). \
Angles are in degrees.
- One top <body> per object. Moving parts are child bodies, each with one hinge or slide <joint> and a plain name \
saying what it is ("door_left", "drawer_top", "lid").
- Allowed: <asset> with <material name rgba specular shininess reflectance> only; <body>, <geom> \
(type box, cylinder, capsule, sphere or ellipsoid), <joint> (type hinge or slide), <inertial>. NOT allowed: \
meshes, textures, files, <include>, <default>, lights, cameras, actuators, <freejoint> (the playground adds \
those itself).
- Every geom has mass= (or density=) and rgba= or material=. At most 40 bodies and 160 geoms per object.
- Parts must not start inside each other where they move, and nothing may stick out below the object's \
bottom.
"""

# Split mode: one call plans the whole place (what, where, how big), then several calls build
# their share of the objects at the same time. Same instructions; the long writing is shared out.
SPLIT = os.environ.get("WETLAB_PHOTOSCENE_SPLIT", "") not in ("", "0")
PER_BUILDER = 8               # objects each builder makes
MAX_BUILDERS = 6

PLAN = """Do steps 1-3 above (inventory, scale, measure) for this photo, but don't build anything yet. \
Answer with the plan only, and nothing after it:

<plan title="Short name of the place">
<item name="Microwave" kind="fixed" x="0.40" y="2.10" z="0.90" yaw="0" w="0.50" d="0.36" h="0.28" \
looks="stainless steel, black glass door, handle on the right" moves="door hinged on the left, opens 0-110 degrees"/>
...
</plan>

One <item> per object you will build (at most 40, plus the walls), with the same names, kinds and \
positions you would use in the scene; w, d, h = width, depth, height in metres; looks = colours, materials \
and the main parts; moves = its moving parts (or "none")."""

BUILD = """Here is the plan for the whole place in the photo, already worked out (positions in the room \
frame, sizes w x d x h in metres):

{plan}

Now do steps 4 and 5 for ONLY these {n} objects from the plan: {names}.
Keep each one's name, kind, x, y, z and yaw exactly as in the plan, and match its size, looks and moving \
parts. Answer in the scene format with only these objects, and nothing after it: \
<scene title="{title}" objects="{n}"> ... </scene>"""

FIX = """Your object "{name}" failed its physics check in MuJoCo:
{error}

Here is what you wrote:
{block}

Write a fixed version of this one object: one <object> element in the same format, and nothing after it."""


# ------------------------------------------------------------------ streaming a model's answer
def _stream_lines(url: str, headers: dict, body: dict, timeout: float = 300.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        raise ModelError(f"the model's company said no ({e.code}{': ' + msg[:200] if msg else ''})") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"couldn't reach the model ({e})") from None
    return r


def _sse(r):
    """The JSON payloads of a server-sent event stream."""
    with r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue


def _anthropic_stream(model, system, content, key, effort, on_think, on_text, stopped):
    body = {"model": model, "max_tokens": 64000, "stream": True, "system": system,
            "messages": [{"role": "user", "content": content}],
            "thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": effort}}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        r = _stream_lines("https://api.anthropic.com/v1/messages", headers, body)
    except ModelError as e:
        if "(400" not in str(e):
            raise
        body.pop("thinking")            # a model without adaptive thinking or effort levels
        body.pop("output_config")
        r = _stream_lines("https://api.anthropic.com/v1/messages", headers, body)
    text, stop = [], ""
    for ev in _sse(r):
        if stopped():
            break
        t = ev.get("type")
        if t == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") == "thinking_delta" and d.get("thinking"):
                on_think(d["thinking"])
            elif d.get("type") == "text_delta" and d.get("text"):
                text.append(d["text"])
                on_text("".join(text))
        elif t == "content_block_start" and (ev.get("content_block") or {}).get("type") == "thinking":
            on_think("\n\n")
        elif t == "message_delta":
            stop = (ev.get("delta") or {}).get("stop_reason") or stop
        elif t == "error":
            raise ModelError(f"the model stopped with an error ({(ev.get('error') or {}).get('message', '')[:200]})")
    if stop == "refusal":
        raise ModelError("the model declined this request")
    return "".join(text)


def _openai_stream(model, system, content, key, effort, on_think, on_text, stopped):
    parts = []
    for c in content:
        if c["type"] == "image":
            src = c["source"]
            parts.append({"type": "input_image", "image_url": f"data:{src['media_type']};base64,{src['data']}"})
        else:
            parts.append({"type": "input_text", "text": c["text"]})
    body = {"model": model, "instructions": system, "stream": True, "max_output_tokens": 64000,
            "input": [{"role": "user", "content": parts}],
            "reasoning": {"effort": effort, "summary": "auto"}}
    headers = {"authorization": f"Bearer {key}"}
    try:
        r = _stream_lines("https://api.openai.com/v1/responses", headers, body)
    except ModelError as e:
        if "(400" not in str(e):
            raise
        body.pop("reasoning")
        r = _stream_lines("https://api.openai.com/v1/responses", headers, body)
    text = []
    for ev in _sse(r):
        if stopped():
            break
        t = ev.get("type", "")
        if t == "response.reasoning_summary_text.delta":
            on_think(ev.get("delta", ""))
        elif t == "response.reasoning_summary_part.added":
            on_think("\n\n")
        elif t == "response.output_text.delta":
            text.append(ev.get("delta", ""))
            on_text("".join(text))
        elif t in ("response.failed", "error"):
            err = (ev.get("response") or {}).get("error") or ev.get("error") or {}
            raise ModelError(f"the model stopped with an error ({str(err.get('message', ''))[:200]})")
    return "".join(text)


def _codex_stream(model, system, content, login, effort, on_think, on_text, stopped):
    """Through Codex on the person's ChatGPT plan: `codex exec --json -i photo.jpg`, whose event
    stream carries the model's reasoning summaries."""
    prompt = system + "\n\n" + "\n\n".join(c["text"] for c in content if c["type"] == "text") + \
        "\n\nDon't run any commands or change any files: answer in the format above, as your final message."
    imgs = [base64.b64decode(c["source"]["data"]) for c in content if c["type"] == "image"]

    seen: set = set()
    said: set = set()                    # thoughts shown, without spaces (both sources give each one)
    out = {"stdout": False}              # stdout has given reasoning items: the log is then not needed

    def event(line: str, log: bool = False):
        """One line of Codex's --json output or of its session log (CODEX_HOME/sessions/*.jsonl):
        a finished reasoning item is a thinking step, with its summary when there is one. The
        log is only a fallback for when stdout gives none, so a thought isn't shown twice."""
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(ev, dict):
            return
        body = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
        it = body.get("item") or body.get("msg") or {}
        if not isinstance(it, dict):
            return
        kind = str(it.get("type") or it.get("item_type") or "").lower()
        what = str(body.get("type") or ev.get("type") or "").lower()
        if "reasoning" not in kind or "start" in what or "delta" in what:
            return
        if log and out["stdout"]:
            return
        if not log:
            out["stdout"] = True
        key = it.get("id")
        if key:
            if key in seen:
                return
            seen.add(key)
        txt = it.get("text") or it.get("summary") or it.get("summary_text") or ""
        if isinstance(txt, list):
            txt = " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in txt)
        flat = "".join(str(txt).split())
        if flat:
            if flat in said:
                return
            said.add(flat)
        on_think("\n\n" + str(txt).strip() if str(txt).strip() else STEP)

    if SG.WHERE == "modal":
        text, new = _codex_modal_stream(model, prompt, imgs, login, effort, event, stopped)
    else:
        text, new = _codex_local_stream(model, prompt, imgs, login, effort, event, stopped)
    if new and new.strip() != login.strip():
        try:
            SG.ACCT.update_login("openai", new)
        except Exception as e:  # noqa: BLE001
            print("could not keep Codex's refreshed login:", e)
    if not text.strip() and stopped():
        return ""                        # Stop was pressed: the build ends as "stopped"
    if not text.strip():
        raise ModelError("Codex gave no answer (is the ChatGPT sign-in still good? Try signing in again in Settings)")
    on_text(text)
    return text


def _follow_logs(folder: str, event) -> threading.Event:
    """Feeds every line Codex adds to its session logs under `folder` to event(), once a second,
    until the returned event is set. (`codex exec --json` doesn't always print its reasoning
    items; its session log does.)"""
    done = threading.Event()

    def run():
        at: dict = {}
        while True:
            last = done.wait(1.0)
            for f in pathlib.Path(folder).rglob("*.jsonl") if os.path.isdir(folder) else []:
                try:
                    with open(f, "rb") as fh:
                        fh.seek(at.get(f, 0))
                        chunk = fh.read()
                    end = chunk.rfind(b"\n") + 1
                    at[f] = at.get(f, 0) + end
                    for line in chunk[:end].decode("utf-8", "replace").splitlines():
                        event(line)
                except OSError:
                    pass
            if last:
                return
    threading.Thread(target=run, daemon=True).start()
    return done


class _watch:
    """Calls kill() once Stop is pressed or PHOTO_TIMEOUT has passed, checking every second on a
    clock of its own (Codex prints nothing while it writes, so its output can't be the clock).
    `over` is set when it was the time limit; done() ends the watch."""

    def __init__(self, kill, stopped):
        self.over, self._done = threading.Event(), threading.Event()
        end = time.time() + PHOTO_TIMEOUT

        def run():
            while not self._done.wait(1.0):
                if stopped() or time.time() > end:
                    if not stopped():
                        self.over.set()
                    try:
                        kill()
                    except Exception:  # noqa: BLE001
                        pass
                    return
        threading.Thread(target=run, daemon=True).start()

    def done(self):
        self._done.set()


def _codex_args(model, effort, out, jail, images):
    # Ask Codex for the model's thinking summaries, so they can stream into the panel.
    cmd = SG._codex_cmd(model, effort, out, jail) + ["--json", "-c", 'model_reasoning_summary="detailed"']
    for p in images:
        cmd += ["--image", p]
    return cmd + ["--"]


def _codex_local_stream(model, prompt, imgs, login, effort, event, stopped):
    import shutil
    import subprocess
    import tempfile
    home = tempfile.mkdtemp(prefix="wetlab-photo-codex-")
    try:
        os.chmod(home, 0o700)
        auth = os.path.join(home, "auth.json")
        with open(os.open(auth, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(login)
        paths = []
        for k, b in enumerate(imgs):
            paths.append(os.path.join(home, f"photo{k}.jpg"))
            pathlib.Path(paths[-1]).write_bytes(b)
        out = os.path.join(home, "answer.txt")
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL")}
        env.update(CODEX_HOME=home, NO_COLOR="1")
        try:
            pfile = os.path.join(home, "prompt.txt")
            pathlib.Path(pfile).write_text(prompt)
            with open(pfile) as pin:   # the prompt goes in through stdin ("-"): see scenegen._from_file
                p = subprocess.Popen(_codex_args(model, effort, out, False, paths) + ["-"], env=env, cwd=home,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=pin)
        except FileNotFoundError:
            raise ModelError("Codex isn't installed on this machine (npm install -g @openai/codex)") from None
        w = _watch(p.kill, stopped)
        follow = _follow_logs(os.path.join(home, "sessions"), lambda ln: event(ln, True))
        try:
            for line in p.stdout:
                event(line)
            p.wait()
        finally:
            w.done()
            follow.set()
        if w.over.is_set():
            raise ModelError(f"the model took longer than {PHOTO_TIMEOUT // 60} minutes, so it was stopped")
        text = open(out).read() if os.path.exists(out) else ""
        if p.returncode not in (0, None) and not text and not stopped():
            tail = " ".join((p.stderr.read() or "").strip().splitlines()[-2:])[:300]
            raise ModelError(f"Codex couldn't answer{': ' + tail if tail else ''}")
        return text, open(auth).read()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _codex_modal_stream(model, prompt, imgs, login, effort, event, stopped):
    import modal

    from wetlabsim.launchers import CHATGPT_HOSTS, ModalSandboxLauncher
    limit = PHOTO_TIMEOUT
    app = modal.App.lookup(ModalSandboxLauncher.APP, create_if_missing=True)
    sb = modal.Sandbox.create("sleep", "infinity", app=app, image=ModalSandboxLauncher.image(),
                              timeout=limit + 120, cpu=0.5, memory=1024, outbound_domain_allowlist=CHATGPT_HOSTS)
    try:
        sb.exec("mkdir", "-p", "/tmp/codex", "/tmp/w").wait()
        sb.filesystem.write_bytes(login.encode(), "/tmp/codex/auth.json")
        sb.exec("chmod", "600", "/tmp/codex/auth.json").wait()
        paths = []
        for k, b in enumerate(imgs):
            paths.append(f"/tmp/w/photo{k}.jpg")
            sb.filesystem.write_bytes(b, paths[-1])
        proc = sb.exec(*SG._from_file(sb, prompt, _codex_args(model, effort, "/tmp/w/answer.txt", True, paths)),
                       workdir="/tmp/w", env={"CODEX_HOME": "/tmp/codex", "NO_COLOR": "1"}, timeout=limit)
        proc.stdin.write_eof()          # see scenegen._codex_modal
        proc.stdin.drain()
        w = _watch(sb.terminate, stopped)
        try:
            for line in proc.stdout:
                event(line)
        finally:
            w.done()
        if w.over.is_set():
            raise ModelError(f"the model took longer than {PHOTO_TIMEOUT // 60} minutes, so it was stopped")
        if stopped():
            return "", ""
        log = proc.stderr.read()
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


def ask_stream(model_id, content, public, effort, on_think, on_text, stopped, system: str | None = None) -> str:
    m = next((m for m in SG.SCENE_MODELS if m["id"] == model_id), None)
    if m is None:
        raise ModelError("that model can't build scenes")
    kind, key = SG._cred(m["provider"], public)
    if not key:
        label = SG.ACCT.PROVIDERS[m["provider"]]["label"]
        raise ModelError(f"connect your {label} API key in Settings to use {m['label']}")
    if kind == "chatgpt":
        call = _codex_stream
    else:
        call = _anthropic_stream if m["provider"] == "anthropic" else _openai_stream
    return call(m["id"], system or SYSTEM, content, key, effort, on_think, on_text, stopped)


# ------------------------------------------------------------------ reading the answer
_OBJ = re.compile(r"<object\b([^>]*)>(.*?)</object>", re.S)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def parse_scene(text: str) -> tuple[str, list[dict]]:
    """(title, objects) from the model's answer: each object's name, kind, place and MJCF."""
    m = re.search(r"<scene\b([^>]*)>", text)
    title = (dict(_ATTR.findall(m.group(1))).get("title", "") if m else "").strip()[:60] or "Photo scene"
    out = []
    for a, body in _OBJ.findall(text[m.start():] if m else text):
        at = dict(_ATTR.findall(a))
        mj = re.search(r"<mujoco\b.*?</mujoco>", body, re.S)
        out.append({"name": (at.get("name") or "Object").strip()[:60], "kind": at.get("kind", "fixed"),
                    "x": _f(at.get("x")), "y": _f(at.get("y")), "z": max(0.0, _f(at.get("z"))),
                    "yaw": math.radians(_f(at.get("yaw"))), "xml": mj.group(0) if mj else "",
                    "block": f"<object{a}>{body}</object>"})
        if len(out) >= MAX_OBJECTS:
            break
    return title, out


_ITEM = re.compile(r"<item\b([^>]*?)/?>", re.S)


def parse_plan(text: str) -> tuple[str, list[dict], str]:
    """(title, items, the plan's text) from a planning answer."""
    m = re.search(r"<plan\b([^>]*)>(.*?)(</plan>|$)", text, re.S)
    if not m:
        return "", [], ""
    title = dict(_ATTR.findall(m.group(1))).get("title", "").strip()[:60]
    items = [dict(_ATTR.findall(a)) for a in _ITEM.findall(m.group(2))]
    items = [i for i in items if i.get("name")][:MAX_OBJECTS]
    return title, items, m.group(0)


def split_items(items: list[dict]) -> list[list[dict]]:
    """The plan's items shared out between the builders, big and small mixed so each takes about as long."""
    n = max(1, min(MAX_BUILDERS, math.ceil(len(items) / PER_BUILDER)))
    big = sorted(items, key=lambda i: -(_f(i.get("w")) * _f(i.get("d")) * _f(i.get("h"))))
    return [g for g in (big[k::n] for k in range(n)) if g]


def _f(v) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else 0.0
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ the photo
def jpeg_from_data_url(s: str) -> tuple[bytes, str]:
    m = re.match(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", (s or "").strip(), re.S)
    if not m:
        raise ModelError("the photo must be a JPEG, PNG or WebP image")
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except ValueError:
        raise ModelError("the photo couldn't be read") from None
    if len(data) > MAX_PHOTO_BYTES:
        raise ModelError("the photo is too big (at most 6 MB)")
    from PIL import Image
    import io
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001
        raise ModelError("the photo couldn't be read") from None
    im = im.convert("RGB")
    im.thumbnail((2000, 2000))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue(), f"{im.width}x{im.height}"


_PHOTO_DIRS: dict = {}       # build id -> the folder its photo is kept in


def keep_photo(build_id: str, data: bytes, runs_dir) -> dict:
    """The photo kept with the session: a file on this server and, on the hosted site, in Blob."""
    from . import savestore as SAVE
    rec = {"id": build_id, "made": time.time(), "file": None, "blob": None}
    try:
        d = pathlib.Path(runs_dir) / "photos"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{build_id}.jpg").write_bytes(data)
        _PHOTO_DIRS[build_id] = d
        rec["file"] = f"photos/{build_id}.jpg"
    except Exception as e:  # noqa: BLE001
        print("could not keep the photo here:", e)

    def up():
        try:
            if SAVE.blob_enabled() and SAVE._upload(f"photo-{build_id}", "photo.jpg", data, "image/jpeg"):
                rec["blob"] = f"runs/photo-{build_id}/photo.jpg"
        except Exception as e:  # noqa: BLE001
            print("could not upload the photo:", e)
    threading.Thread(target=up, daemon=True).start()
    return rec


def keep_answer(rec: dict, text: str) -> None:
    """The model's whole answer (and any fixes) kept next to its photo, to look into a scene later."""
    from . import savestore as SAVE
    data = text.encode()
    d = _PHOTO_DIRS.get(rec["id"])
    try:
        if d is not None:
            (d / f"{rec['id']}.answer.txt").write_bytes(data)
            rec["answer"] = f"photos/{rec['id']}.answer.txt"
    except Exception as e:  # noqa: BLE001
        print("could not keep the model's answer here:", e)

    def up():
        try:
            if SAVE.blob_enabled() and SAVE._upload(f"photo-{rec['id']}", "answer.txt", data, "text/plain"):
                rec["answer_blob"] = f"runs/photo-{rec['id']}/answer.txt"
        except Exception as e:  # noqa: BLE001
            print("could not upload the model's answer:", e)
    threading.Thread(target=up, daemon=True).start()


# ------------------------------------------------------------------ the build
def _looked(b, o: dict, ok: dict) -> dict:
    """An object that passed its physics tests, after the look check (lookcheck.look_object):
    walls are only boxes, so they skip it."""
    if not LC.LOOK or o["name"].lower().startswith("wall"):
        return ok
    return LC.look_object(b, o, ok)


class PhotoBuild(SG.Build):
    """One scene being made from a photo, in a thread of its own: the model's answer streamed
    (thinking shown live), each object checked and tested, then put down on a free spot."""

    STEPS = ["look", "measure", "build", "test", "place", "check"]

    def __init__(self, sim, sess, photo: bytes, note: str, model_id: str, public: bool, photo_rec: dict):
        self.sim, self.sess = sim, sess
        self.photo, self.note = photo, note
        self.model_id, self.public = model_id, public
        self.photo_rec = photo_rec
        self.id = photo_rec["id"]
        self.preset = ""
        self.pick = {"title": "your photo", "robots": [], "items": []}
        self.phase = "look"
        self.error = ""
        self.stop = False
        self.stations: list[str] = []
        self.objects: list[str] = []
        self.skipped: list[str] = []
        self.task = ""
        self.zone = None
        self.undone = False
        self.started = time.time()
        self.now = ""
        self.title = ""
        self.thinking = ""
        self.answer = ""
        self.answers: list[str] = []       # every answer the model gave, kept with the photo
        self.steps = 0                     # thinking steps so far (Codex sends some with no words)
        self.last_heard = time.time()
        self.expected = 0
        self.named: list[str] = []
        self.counts = {"built": 0, "tested": 0, "placed": 0, "total": 0, "retries": 0}
        self.plan_text = ""
        self.station_tasks = {}
        self.items: list[dict] = []        # outlines on the floor while placing (SG.Build._outline)
        self.shown = 0
        self.hl = -1
        self.ostate: dict[str, str] = {}   # each object's step: testing, fixing, ready, failed, ok, bad

    def _rows(self) -> list[dict]:
        """Each object the model named, and where it is: making, testing, fixing, ready, failed,
        then ok (placed) or bad (didn't fit)."""
        return [{"name": n, "state": self.ostate.get(n.lower(), "making")} for n in self.named[:MAX_OBJECTS]]

    def active(self) -> bool:
        return self.phase in self.STEPS

    def status(self) -> dict:
        return {"id": self.id, "photo": True, "phase": self.phase, "error": self.error,
                "title": self.title, "thinking": self.thinking[-THINKING_KEEP:], "now": self.now,
                "counts": self.counts, "expected": self.expected, "names": self.named[-6:],
                "objects": len(self.objects), "skipped": self.skipped, "stations": [], "undone": self.undone,
                "model": next((m["label"] for m in SG.SCENE_MODELS if m["id"] == self.model_id), ""),
                "elapsed": round(time.time() - self.started, 1),
                "steps": self.steps, "quiet": round(time.time() - self.last_heard, 1),
                "rows": self._rows(), "note": self.note[:300], "looks": getattr(self, "looks", [])[-8:], "look_pic": getattr(self, "look_pic", ""),
                "items": [{"name": it["name"], "kind": it["kind"], "state": it["state"], "at": bool(it["rect"])}
                          for it in self.items[:self.shown]],
                "active": self.active()}

    # -------------------------------------------------- streaming
    def _think(self, s: str | None):
        self.last_heard = time.time()
        if s is STEP or s.startswith("\n\n"):
            self.steps += 1
        if s is STEP:
            return
        fix = re.search(r"\*\*Fixing the (.+?)\*\*", s)
        if fix:
            self.ostate[fix.group(1).strip().lower()] = "fixing"
        self.thinking += s
        if len(self.thinking) > 3 * THINKING_KEEP:
            self.thinking = self.thinking[-THINKING_KEEP:]

    def _text(self, full: str):
        self.answer = full
        self.last_heard = time.time()
        if self.phase == "look":
            self.phase = "measure"
        m = re.search(r"<scene\b([^>]*)>", full)
        if m:
            at = dict(_ATTR.findall(m.group(1)))
            self.title = (at.get("title") or self.title)[:60]
            try:
                self.expected = max(0, min(MAX_OBJECTS, int(at.get("objects", 0))))
            except ValueError:
                pass
            body = full[m.end():]
            self.named = [dict(_ATTR.findall(a)).get("name", "") for a in re.findall(r"<object\b([^>]*)>", body)]
            if self.named:
                self.phase = "build"
                self.counts["built"] = len(re.findall(r"</object>", body))
                self.now = self.named[-1]

    def _content(self, text: str) -> list:
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(self.photo).decode()}},
                {"type": "text", "text": text}]

    def _ask(self, text: str, effort: str, on_text=None, images=()) -> str:
        """One streamed answer about the photo; `images`: more pictures after the words, as
        lookcheck.images makes them (pictures of what was built)."""
        on_text = on_text or (self._text if not images else (lambda t: None))
        if SG.fake():
            ans = LC.fake_look(text) if images else _fake_stream(self, text, on_text)
        else:
            ans = ask_stream(self.model_id, self._content(text) + list(images), self.public, effort, self._think,
                             on_text, lambda: self.stop)
        self.answers.append(f"===== asked: {text[:200]}\n\n{ans}")
        return ans

    # -------------------------------------------------- the steps
    def _run(self):
        s = self.sim
        was_playing = not s.paused
        try:
            note = f"\n\nA note from the person who took the photo: {self.note}" if self.note else ""
            if SPLIT:
                title, objs = self._ask_split(note)
            else:
                answer = self._ask("Rebuild the place in this photo as a sim-ready MuJoCo scene." + note, "high")
                title, objs = parse_scene(answer)
            if self.stop:
                return self._end("stopped")
            self.title = self.title or title
            if not objs:
                raise ModelError("the model's answer had no objects in it")
            self.counts["built"] = self.counts["total"] = len(objs)
            self.phase = "test"
            from concurrent.futures import ThreadPoolExecutor
            lock = threading.Lock()

            def make(o):                # objects are tested side by side: a fix waits on the model
                if self.stop:
                    return None
                self.now = o["name"]
                self.ostate[o["name"].lower()] = "testing"
                got = self._make(o)
                self.ostate[o["name"].lower()] = "ready" if got else "failed"
                with lock:
                    self.counts["tested"] += 1
                return got
            with ThreadPoolExecutor(max_workers=FIX_AT_ONCE) as pool:
                ready = [g for g in pool.map(make, objs) if g]
            if self.stop:
                return self._end("stopped")
            if not ready:
                raise ModelError("none of the objects passed the physics check")
            self.phase = "place"
            self.now = ""
            s.pause()
            off = self._free_spot([], ready, [])
            if off is None:
                raise ModelError("there's no free floor space big enough for this scene: remove something first")
            self._show_zone([], ready, [], off)
            order = sorted(ready, key=lambda o: (o["z"], not o["fixed"]))
            self._outline_made(order, off)
            for k, o in enumerate(order):
                if self.stop:
                    return self._end("stopped")
                self.now = o["name"]
                self._mark(k, "now")
                had = len(self.objects)
                self._put(o, off)
                ok = len(self.objects) > had
                self._mark(k, "ok" if ok else "bad")
                self.ostate[o["name"].lower()] = "ok" if ok else "bad"
            self.now = ""
            if LC.LOOK and self.objects:     # level 2 of the look check: the scene against the photo
                self.phase = "check"
                LC.look_scene(self, list(self.objects), [o["item"] for o in ready])
                if self.stop:
                    return self._end("stopped")
            self._end("done")
        except Exception as e:  # noqa: BLE001
            self.error = str(e) if isinstance(e, ModelError) else f"something went wrong: {e}"
            self._end("error")
        finally:
            s.zone = []
            if was_playing and self.phase in ("done", "stopped", "error"):
                s.play()

    def _ask_split(self, note: str) -> tuple[str, list[dict]]:
        """The plan first, then the builders at the same time; their objects in the plan's order."""
        plan_text = self._ask("Plan a sim-ready MuJoCo rebuild of the place in this photo." + note + "\n\n" + PLAN,
                              "high", on_text=lambda t: None)
        title, items, plan = parse_plan(plan_text)
        if self.stop or not items:
            if not self.stop:
                raise ModelError("the model's plan had no objects in it")
            return title, []
        self.title = self.title or title
        self.expected = len(items)
        self.named = [i["name"] for i in items]
        self.phase = "build"
        groups = split_items(items)
        texts = [""] * len(groups)
        errors: list[Exception] = []

        def seen(k):
            def on_text(t):
                texts[k] = t
                self.last_heard = time.time()
                self.counts["built"] = sum(len(re.findall(r"</object>", x)) for x in texts)
            return on_text

        def build(k, group):
            ask = BUILD.format(plan=plan, n=len(group), names="; ".join(i["name"] for i in group),
                               title=title.replace('"', "'"))
            try:
                texts[k] = self._ask(ask, "high", on_text=seen(k))
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=build, args=(k, g), daemon=True) for k, g in enumerate(groups)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        objs = []
        for t in texts:
            objs += parse_scene(t)[1]
        if not objs and errors:
            raise errors[0] if isinstance(errors[0], ModelError) else ModelError(str(errors[0]))
        order = {i["name"]: n for n, i in enumerate(items)}
        objs.sort(key=lambda o: order.get(o["name"], len(order)))
        lost = [i["name"] for i in items if i["name"] not in {o["name"] for o in objs}]
        if lost:
            self.skipped += lost[:20]           # a builder failed or left them out
        return title, objs[:MAX_OBJECTS]

    def _make(self, o: dict) -> dict | None:
        """The object checked and tested (sent back to the model to fix, up to MAX_TRIES)."""
        inspected = False
        for k in range(MAX_TRIES):
            try:
                xml = AI.clean(o["xml"])
                size, frame, mass = AI.measure(xml)
                fixed = o["kind"] != "loose"
                uid = AI.register(o["name"], xml, fixed, size, frame, mass)
                AI.shake(uid)
            except AI.Bad as e:
                err = str(e)
            else:
                ok = {**o, "item": uid, "fixed": fixed, "size": size}
                try:
                    AI.inspect(uid)        # doors and drawers move, containers hold, nothing falls through
                    return _looked(self, o, ok)
                except AI.Bad as e:
                    if inspected:          # it stands and settles; one fix tried: keep it as it is
                        self._think(f"\n\n**Kept the {o['name'].lower()}** as it is: {e}")
                        return _looked(self, o, ok)
                    inspected, err = True, str(e)
            if k == MAX_TRIES - 1 or self.stop:
                break
            self.counts["retries"] += 1
            self._think(f"\n\n**Fixing the {o['name'].lower()}**: {err}")
            try:
                ans = self._ask(FIX.format(name=o["name"], error=err, block=o["block"][:20000]), "medium")
                _, fixed_objs = parse_scene(ans)
            except ModelError:
                break
            if not fixed_objs:
                continue
            f = fixed_objs[0]
            o = {**o, "xml": f["xml"], "block": f["block"], "kind": f["kind"] or o["kind"]}
        self.skipped.append(o["name"])
        return None

    def _outline_made(self, order, off):
        """The made objects' spots as outlines, shown one by one (as SG.Build._outline)."""
        self.items = [{"name": o["name"], "kind": "furniture" if o["fixed"] else "object", "state": "plan", "t": 0.0,
                       "rect": SG._item_rect(o["item"], o["x"] + off[0], o["y"] + off[1], o["yaw"])} for o in order]
        gap = min(0.12, self.REVEAL_S / max(1, len(order)))
        for k in range(len(order)):
            if self.stop:
                break
            self.shown = k + 1
            self._draw()
            time.sleep(gap)
        self.shown = len(order)
        self._draw()

    def _rects(self, stations, furniture, objects, ox=0.0, oy=0.0):
        return [SG._item_rect(f["item"], f["x"] + ox, f["y"] + oy, f["yaw"]) for f in furniture]

    def _put(self, o: dict, off):
        s = self.sim
        x, y, z = o["x"] + off[0], o["y"] + off[1], o["z"]
        spot = s.support(o["item"], x, y, o["yaw"], top=z + 0.12)
        if not spot["valid"]:
            self.skipped.append(o["name"])
            return
        pos = list(spot["pos"])
        if o["fixed"] and pos[2] < z - 0.1:
            pos[2] = z                     # fixed to a wall at its height (a wall cabinet, a shelf)
        try:
            uid = s.add(o["item"], pos, o["yaw"])
        except Exception as e:  # noqa: BLE001
            print("could not place an AI-made object:", e)
            self.skipped.append(o["name"])
            return
        self.objects.append(uid)
        self.counts["placed"] += 1

    def _end(self, phase: str):
        self.phase = phase
        self.sim.zone = []
        if self.answers:
            keep_answer(self.photo_rec, "\n\n".join(self.answers))


# ------------------------------------------------------------------ pretend model (tests)
FAKE_SCENE = """Inventory: a counter with a microwave and a mug on it; a chair.
Scale: counter 0.90 m tall.

<scene title="Small kitchen" objects="3">
<object name="Counter" kind="fixed" x="0" y="1.5" z="0" yaw="0">
<mujoco><worldbody><body name="counter">
<geom type="box" size="0.6 0.3 0.45" rgba="0.85 0.82 0.76 1" mass="80"/>
<body name="drawer" pos="0 -0.3 0.3">
<joint name="slide" type="slide" axis="0 -1 0" range="0 0.4" damping="1" armature="0.01"/>
<geom type="box" size="0.25 0.01 0.08" pos="0 -0.01 0" rgba="0.7 0.6 0.5 1" mass="1"/>
</body></body></worldbody></mujoco>
</object>
<object name="Microwave" kind="fixed" x="0.25" y="1.5" z="0.9" yaw="0">
<mujoco><asset><material name="steel" rgba="0.8 0.8 0.82 1"/></asset><worldbody><body name="mw">
<geom type="box" size="0.25 0.18 0.01" pos="0 0 -0.14" material="steel" mass="3"/>
<geom type="box" size="0.25 0.18 0.01" pos="0 0 0.14" material="steel" mass="2"/>
<geom type="box" size="0.01 0.18 0.13" pos="-0.24 0 0" material="steel" mass="1"/>
<geom type="box" size="0.01 0.18 0.13" pos="0.24 0 0" material="steel" mass="1"/>
<geom type="box" size="0.25 0.01 0.13" pos="0 0.17 0" material="steel" mass="1"/>
<body name="door" pos="-0.25 -0.19 0">
<joint name="hinge" type="hinge" axis="0 0 1" range="-110 0" damping="0.2" armature="0.01"/>
<geom type="box" size="0.25 0.01 0.14" pos="0.25 0 0" rgba="0.1 0.1 0.1 1" mass="0.8"/>
</body></body></worldbody></mujoco>
</object>
<object name="Mug" kind="loose" x="-0.3" y="1.4" z="0.9" yaw="0">
<mujoco><worldbody><body name="mug">
<geom type="cylinder" size="0.04 0.005" pos="0 0 -0.045" rgba="0.2 0.4 0.8 1" mass="0.08"/>
<geom type="box" size="0.04 0.004 0.05" pos="0 0.038 0" rgba="0.2 0.4 0.8 1" mass="0.05"/>
<geom type="box" size="0.04 0.004 0.05" pos="0 -0.038 0" rgba="0.2 0.4 0.8 1" mass="0.05"/>
<geom type="box" size="0.004 0.04 0.05" pos="0.038 0 0" rgba="0.2 0.4 0.8 1" mass="0.05"/>
<geom type="box" size="0.004 0.04 0.05" pos="-0.038 0 0" rgba="0.2 0.4 0.8 1" mass="0.05"/>
</body></worldbody></mujoco>
</object>
</scene>"""

FAKE_THINKING = ["**Looking at the photo**\nA small kitchen: a light counter along the back, a microwave on it, a blue mug.",
                 "**Setting the scale**\nThe counter reads as a standard 0.90 m worktop; the microwave is about 50 cm wide.",
                 "**Building the objects**\nThe microwave gets a hollow box and a hinged door; the counter a sliding drawer."]


def _fake_stream(b: PhotoBuild, text: str, on_text=None) -> str:
    delay = float(os.environ.get("WETLAB_PHOTOSCENE_FAKE_DELAY", "0.3"))
    on_text = on_text or b._text
    if text.startswith("Your object"):
        return ""
    _, objs = parse_scene(FAKE_SCENE)
    if text.startswith("Plan a sim-ready"):
        return '<plan title="Small kitchen">' + "".join(
            f'<item name="{o["name"]}" kind="{o["kind"]}" x="{o["x"]}" y="{o["y"]}" z="{o["z"]}" yaw="0" '
            f'w="0.5" d="0.5" h="0.5" looks="-" moves="-"/>' for o in objs) + "</plan>"
    if text.startswith("Here is the plan"):
        want = re.search(r"ONLY these \d+ objects from the plan: (.*)\.\n", text).group(1).split("; ")
        out = '<scene title="Small kitchen" objects="%d">' % len(want) + "".join(
            o["block"] for o in objs if o["name"] in want) + "</scene>"
        on_text(out)
        return out
    for t in FAKE_THINKING:
        b._think("\n\n" + t)
        time.sleep(delay)
    out = ""
    for chunk in re.split(r"(?=<object )", FAKE_SCENE):
        out += chunk
        on_text(out)
        time.sleep(delay)
    return out
