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
from . import scenegen as SG
from .scenegen import ModelError

MAX_TRIES = 3
MAX_OBJECTS = 40
MAX_PHOTO_BYTES = 6_000_000
THINKING_KEEP = 4000          # characters of thinking the page is sent

SYSTEM = """You are a 3D artist and simulation engineer. Rebuild the place in the attached photo as a \
SIM-READY MuJoCo scene: the same objects, the same sizes, the same positions and the same colours, \
and it must behave like the real thing. Doors open, drawers slide, lids lift, loose things fall and \
can be picked up. Units are metres; z is up.

Work it out in five steps. Keep your written notes short (at most 12 lines before the scene):
1. INVENTORY. Every visible object: furniture, appliances, and small loose items. Note colour, material \
(wood, metal, glass, plastic, fabric, ceramic) and what each rests on. Leave out the floor, the ceiling and \
the walls themselves (the playground has its own floor), but keep things fixed to walls (wall cabinets, \
shelves) at their real height.
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
water/food ~1000 kg/m3, wood ~600, plastic ~950, glass ~2500, steel ~7800, ceramic ~2300; hollow items use \
their shell, not their whole volume) and friction for its material (0.3 smooth to 1.0 rubber). Anything with \
moving parts gets them, even when the object itself is fixed: microwave, oven and fridge doors, cabinet \
doors, drawers, lids, laptop screens, toilet seats, windows. Each moving part is a child body with a \
hinge (turns) or slide (moves in a line) joint at the right edge, with its axis, a limited range \
(e.g. microwave door 0 to 110 degrees, drawer 0 to 0.40 m), damping 0.05-1 and armature 0.01 so it moves \
calmly. Doors start closed unless open in the photo. Collision shapes are the visible shapes: build hollow \
things hollow (a microwave cavity from 5 walls, a cup from a base and a ring of thin boxes) so things \
can go inside them.
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
- N = how many <object> elements follow (at most 40). Name each object plainly ("Coffee mug", "Fridge").
- x, y = the middle of the object's footprint in the room frame; z = the height of its BOTTOM above the floor \
(0 for things on the floor, 0.90 for things on a 0.90 m counter); yaw = degrees it is turned about z, \
counter-clockwise seen from above, 0 = its front faces the camera.
- Inside <mujoco>, build the object around its own origin with its front facing -y (towards the camera). \
Angles are in degrees.
- One top <body> per object. Moving parts are child bodies, each with one hinge or slide <joint>.
- Allowed: <asset> with <material name rgba specular shininess reflectance> only; <body>, <geom> \
(type box, cylinder, capsule, sphere or ellipsoid), <joint> (type hinge or slide), <inertial>. NOT allowed: \
meshes, textures, files, <include>, <default>, lights, cameras, actuators, <freejoint> (the playground adds \
those itself).
- Every geom has mass= (or density=) and rgba= or material=. At most 40 bodies and 160 geoms per object.
- Parts must not start inside each other where they move, and nothing may stick out below the object's \
bottom.
"""

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

    def event(line: str):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return
        it = ev.get("item") or ev.get("msg") or {}
        kind = str(it.get("type") or it.get("item_type") or "")
        if "reasoning" in kind and ev.get("type", "item.completed") in ("item.completed", "item.updated", ""):
            txt = it.get("text") or it.get("summary") or ""
            if isinstance(txt, list):
                txt = " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in txt)
            if txt:
                on_think("\n\n" + str(txt))

    if SG.WHERE == "modal":
        text, new = _codex_modal_stream(model, prompt, imgs, login, effort, event)
    else:
        text, new = _codex_local_stream(model, prompt, imgs, login, effort, event, stopped)
    if new and new.strip() != login.strip():
        try:
            SG.ACCT.update_login("openai", new)
        except Exception as e:  # noqa: BLE001
            print("could not keep Codex's refreshed login:", e)
    if not text.strip():
        raise ModelError("Codex gave no answer (is the ChatGPT sign-in still good? Try signing in again in Settings)")
    on_text(text)
    return text


def _codex_args(model, effort, out, jail, images):
    cmd = SG._codex_cmd(model, effort, out, jail) + ["--json"]
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
            p = subprocess.Popen(_codex_args(model, effort, out, False, paths) + [prompt], env=env, cwd=home,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            raise ModelError("Codex isn't installed on this machine (npm install -g @openai/codex)") from None
        t0 = time.time()
        for line in p.stdout:
            event(line)
            if stopped() or time.time() - t0 > SG.CODEX_TIMEOUT * 3:
                p.kill()
                break
        p.wait()
        text = open(out).read() if os.path.exists(out) else ""
        if p.returncode not in (0, None) and not text and not stopped():
            tail = " ".join((p.stderr.read() or "").strip().splitlines()[-2:])[:300]
            raise ModelError(f"Codex couldn't answer{': ' + tail if tail else ''}")
        return text, open(auth).read()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _codex_modal_stream(model, prompt, imgs, login, effort, event):
    import modal

    from wetlabsim.launchers import CHATGPT_HOSTS, ModalSandboxLauncher
    limit = SG.CODEX_TIMEOUT * 3
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
        proc = sb.exec(*_codex_args(model, effort, "/tmp/w/answer.txt", True, paths), prompt, workdir="/tmp/w",
                       env={"CODEX_HOME": "/tmp/codex", "NO_COLOR": "1"}, timeout=limit)
        proc.stdin.write_eof()          # see scenegen._codex_modal
        proc.stdin.drain()
        for line in proc.stdout:
            event(line)
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


def ask_stream(model_id, content, public, effort, on_think, on_text, stopped) -> str:
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
    return call(m["id"], SYSTEM, content, key, effort, on_think, on_text, stopped)


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


def keep_photo(build_id: str, data: bytes, runs_dir) -> dict:
    """The photo kept with the session: a file on this server and, on the hosted site, in Blob."""
    from . import savestore as SAVE
    rec = {"id": build_id, "made": time.time(), "file": None, "blob": None}
    try:
        d = pathlib.Path(runs_dir) / "photos"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{build_id}.jpg").write_bytes(data)
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


# ------------------------------------------------------------------ the build
class PhotoBuild(SG.Build):
    """One scene being made from a photo, in a thread of its own: the model's answer streamed
    (thinking shown live), each object checked and tested, then put down on a free spot."""

    STEPS = ["look", "measure", "build", "test", "place"]

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
        self.expected = 0
        self.named: list[str] = []
        self.counts = {"built": 0, "tested": 0, "placed": 0, "total": 0, "retries": 0}
        self.plan_text = ""
        self.station_tasks = {}

    def status(self) -> dict:
        return {"id": self.id, "photo": True, "phase": self.phase, "error": self.error,
                "title": self.title, "thinking": self.thinking[-THINKING_KEEP:], "now": self.now,
                "counts": self.counts, "expected": self.expected, "names": self.named[-6:],
                "objects": len(self.objects), "skipped": self.skipped, "stations": [], "undone": self.undone,
                "model": next((m["label"] for m in SG.SCENE_MODELS if m["id"] == self.model_id), ""),
                "elapsed": round(time.time() - self.started, 1),
                "active": self.phase in self.STEPS}

    # -------------------------------------------------- streaming
    def _think(self, s: str):
        self.thinking += s
        if len(self.thinking) > 3 * THINKING_KEEP:
            self.thinking = self.thinking[-THINKING_KEEP:]

    def _text(self, full: str):
        self.answer = full
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

    def _ask(self, text: str, effort: str) -> str:
        if SG.fake():
            return _fake_stream(self, text)
        return ask_stream(self.model_id, self._content(text), self.public, effort, self._think,
                          self._text, lambda: self.stop)

    # -------------------------------------------------- the steps
    def _run(self):
        s = self.sim
        was_playing = not s.paused
        try:
            note = f"\n\nA note from the person who took the photo: {self.note}" if self.note else ""
            answer = self._ask("Rebuild the place in this photo as a sim-ready MuJoCo scene." + note, "high")
            if self.stop:
                return self._end("stopped")
            title, objs = parse_scene(answer)
            self.title = self.title or title
            if not objs:
                raise ModelError("the model's answer had no objects in it")
            self.counts["built"] = self.counts["total"] = len(objs)
            self.phase = "test"
            ready = []
            for o in objs:
                if self.stop:
                    return self._end("stopped")
                self.now = o["name"]
                got = self._make(o)
                if got:
                    ready.append(got)
                self.counts["tested"] += 1
            if not ready:
                raise ModelError("none of the objects passed the physics check")
            self.phase = "place"
            self.now = ""
            s.pause()
            off = self._free_spot([], ready, [])
            if off is None:
                raise ModelError("there's no free floor space big enough for this scene: remove something first")
            self._show_zone([], ready, [], off)
            for o in sorted(ready, key=lambda o: (o["z"], not o["fixed"])):
                if self.stop:
                    return self._end("stopped")
                self.now = o["name"]
                self._put(o, off)
            self.now = ""
            self._end("done")
        except Exception as e:  # noqa: BLE001
            self.error = str(e) if isinstance(e, ModelError) else f"something went wrong: {e}"
            self._end("error")
        finally:
            s.zone = []
            if was_playing and self.phase in ("done", "stopped", "error"):
                s.play()

    def _make(self, o: dict) -> dict | None:
        """The object checked and tested (sent back to the model to fix, up to MAX_TRIES)."""
        for k in range(MAX_TRIES):
            try:
                xml = AI.clean(o["xml"])
                size, frame, mass = AI.measure(xml)
                fixed = o["kind"] != "loose"
                uid = AI.register(o["name"], xml, fixed, size, frame, mass)
                AI.shake(uid)
                return {**o, "item": uid, "fixed": fixed, "size": size}
            except AI.Bad as e:
                err = str(e)
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


def _fake_stream(b: PhotoBuild, text: str) -> str:
    delay = float(os.environ.get("WETLAB_PHOTOSCENE_FAKE_DELAY", "0.3"))
    if text.startswith("Your object"):
        return ""
    for t in FAKE_THINKING:
        b._think("\n\n" + t)
        time.sleep(delay)
    out = ""
    for chunk in re.split(r"(?=<object )", FAKE_SCENE):
        out += chunk
        b._text(out)
        time.sleep(delay)
    return out
