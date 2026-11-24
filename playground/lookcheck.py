"""Look-check: the model looks at pictures of what it built and fixes what looks wrong.

Level 1, each AI-made object (after it passes its physics tests, photoscene.PhotoBuild._make):
it is drawn in MuJoCo from the front, the side, above and a front corner (and once more with
every door and drawer open) on a floor of 10 cm squares. The model scores it out of 10 against
the real thing and, below GOOD, writes a fixed version. That goes through the same physics
tests, is drawn and scored again, up to OBJECT_FIXES times. The best-scoring version that passed
its tests is kept, so a fix never makes an object worse.

Level 2, the finished scene (scenegen.Build and photoscene.PhotoBuild, after everything is put
down): it is drawn from above, from a front corner and at each robot's table. The model scores
it against the request and answers with small edits (move, turn, remove, add) that our code puts
down with the same drop check as drag and drop. Up to SCENE_ROUNDS rounds; a round that scores
lower than the scene before it is undone.

Every connection takes the pictures (photoscene.ask_stream: Anthropic and OpenAI API keys, Codex
on a ChatGPT sign-in, Devin). The pictures are only for building: nothing here reaches the
robot's AI.
"""
from __future__ import annotations

import io
import json
import math
import re
import threading

import mujoco
from PIL import Image

from . import aimade as AI
from . import catalog

LOOK = True             # the look check on (off: built as before, with physics tests only)
GOOD = 8                 # a score (out of 10) that needs no fixing
OBJECT_FIXES = 2         # fixes one object may get from what the model sees
SCENE_ROUNDS = 2         # rounds of edits a whole scene may get
MAX_EDITS = 12           # edits in one round
VIEW_PX = 512
SCENE_VIEWS_MAX = 5

_render_lock = threading.Lock()      # one offscreen picture at a time (cheap, and safe on every GL)


# ------------------------------------------------------------------ pictures
def _jpeg(img) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _cam(lookat, distance: float, azimuth: float, elevation: float) -> mujoco.MjvCamera:
    c = mujoco.MjvCamera()
    c.type = mujoco.mjtCamera.mjCAMERA_FREE
    c.lookat[:] = lookat
    c.distance, c.azimuth, c.elevation = float(distance), float(azimuth), float(elevation)
    return c


def _shoot(m, d, cams, px: int = VIEW_PX) -> list[bytes]:
    m.vis.global_.offwidth = max(m.vis.global_.offwidth, px)
    m.vis.global_.offheight = max(m.vis.global_.offheight, px)
    with _render_lock:
        r = mujoco.Renderer(m, px, px)
        try:
            out = []
            for c in cams:
                r.update_scene(d, camera=c)
                out.append(_jpeg(r.render()))
            return out
        finally:
            r.close()


def object_views(id_: str) -> list[tuple[str, bytes]]:
    """An AI-made object (registered with aimade) from four sides on a 10 cm grid, and with its
    moving parts open when it has any: [(what the picture shows, JPEG)]."""
    m, d, root, bodies = AI._world(id_, True, grid=True)
    lo, hi = AI._bounds(m, d, bodies)
    c = (lo + hi) / 2
    span = float(max(hi - lo))
    dist = max(0.3, 1.7 * span + 0.1)
    # The object's front faces -y: the camera stands at -y looking along +y (azimuth 90).
    views = [("front", 90, -12), ("right side", 180, -12), ("from above", 90, -89.5), ("front-right corner", 135, -30)]
    cams = [_cam(c, dist, az, el) for _, az, el in views]
    pics = list(zip([v[0] for v in views], _shoot(m, d, cams)))
    moving = [j for j in range(m.njnt) if int(m.jnt_bodyid[j]) in bodies and m.jnt_limited[j]
              and m.jnt_type[j] in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))]
    if moving:
        for j in moving:              # each part at the end of its range furthest from where it starts
            a = m.jnt_qposadr[j]
            lo_j, hi_j = m.jnt_range[j]
            d.qpos[a] = hi_j if abs(hi_j - d.qpos[a]) >= abs(lo_j - d.qpos[a]) else lo_j
        mujoco.mj_kinematics(m, d)
        mujoco.mj_camlight(m, d)
        pics.append(("front-right corner, every moving part opened", _shoot(m, d, [cams[3]])[0]))
    return pics


def scene_views(sim, focus: list[tuple[float, float]], stations: list) -> list[tuple[str, bytes]]:
    """The scene around the points in `focus` (x, y) from above (+x to the right, +y up the
    picture), from a front corner, and at up to three robots' tables."""
    with sim.lock:
        m = sim.m
        d = mujoco.MjData(m)
        d.qpos[:] = sim.d.qpos
    mujoco.mj_forward(m, d)
    xs = [p[0] for p in focus] or [0.0]
    ys = [p[1] for p in focus] or [0.0]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    views = [("from above (+x to the right, +y up the picture)", _cam((cx, cy, 0.4), 1.25 * span + 1.2, 90, -89.5)),
             ("from the front-left corner", _cam((cx, cy, 0.5), 1.1 * span + 1.6, 125, -32))]
    for st in stations[:SCENE_VIEWS_MAX - 2]:
        v = sim.station_view(st)
        views.append((f"close up: {st.name}'s table", _cam(v["lookat"], v["distance"] * 0.8, v["azimuth"], v["elevation"])))
    return list(zip([v[0] for v in views], _shoot(m, d, [v[1] for v in views])))


def images(pics) -> list[dict]:
    """Pictures as content blocks for photoscene.ask_stream (each named in a text block before it)."""
    import base64
    out = []
    for k, (what, jpg) in enumerate(pics, 1):
        out.append({"type": "text", "text": f"Rendered picture {k} of {len(pics)}: {what}."})
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}})
    return out


# ------------------------------------------------------------------ reading answers
def parse_score(text: str) -> int | None:
    m = re.search(r"SCORE\s*[:=]\s*(\d+(?:\.\d+)?)\s*(?:/|out of)?\s*10", text or "", re.I)
    if not m:
        return None
    return max(0, min(10, round(float(m.group(1)))))


def _problems(text: str) -> str:
    """The model's list of what's wrong, short (for the progress panel)."""
    t = re.sub(r"SCORE\s*[:=][^\n]*\n?", "", text or "", flags=re.I)
    t = t.split("<object")[0].split("```")[0].strip()
    return " ".join(t.split())[:300]


# ------------------------------------------------------------------ level 1: one object
LOOK_OBJECT = """LOOK CHECK. These pictures show your object "{name}" as MuJoCo draws it, standing on a floor \
of 10 cm squares. It measures {w} x {dp} x {h} cm (width x depth x height) and weighs {kg} kg.{scene}

Judge it as a sim-ready model of a real {name}: shape and proportions, real-world size, every part \
where it belongs, colours, and moving parts that open the right way (the picture marked "opened" shows \
every door, drawer and lid at the far end of its range). Its front should face the first picture.

Answer with one line first: SCORE: n/10. Then list what is wrong, most important first, in a few short lines.
{tail}

Here is what you wrote:
{block}"""

FIX_TAIL = ("If the score is {good} or more, stop there. Otherwise, after the list, write a fixed version of "
            "this one object: one <object> element in the same format (same name and kind), and nothing after it.")
SCORE_TAIL = "Only score it and list what's wrong: don't write a new version."


def look_object(b, o: dict, ok: dict) -> dict:
    """Level 1 for one object that passed its physics tests (`ok`, from PhotoBuild._make): look,
    fix, look again, up to OBJECT_FIXES fixes. Returns the best version that passed its tests.
    `b` is the build (SG.Build or PS.PhotoBuild): it asks the model and shows progress."""
    from . import photoscene as PS
    best, best_score = ok, None
    cur_o, cur_ok = o, ok
    scene = getattr(b, "prompt", "") or getattr(b, "note", "")
    scene_line = f"\nIt is for this scene: {scene[:300]}" if scene else ""
    fixes = 0
    while not b.stop:
        last = fixes >= OBJECT_FIXES
        try:
            pics = object_views(cur_ok["item"])
        except Exception as e:  # noqa: BLE001      no pictures here (no GL): the check is skipped
            print("look check: no pictures of", o["name"], e)
            return best
        sz = cur_ok["size"]
        text = LOOK_OBJECT.format(name=o["name"], w=round(100 * sz[0]), dp=round(100 * sz[1]), h=round(100 * sz[2]),
                                  kg=round(AI.meta(cur_ok["item"])["mass"], 2) if AI.meta(cur_ok["item"]) else "?",
                                  scene=scene_line, block=cur_o.get("block", "")[:20000],
                                  tail=SCORE_TAIL if last else FIX_TAIL.format(good=GOOD))
        b._think(f"\n\n**Looking at the {o['name'].lower()}**")
        try:
            ans = b._ask(text, "medium", images=images(pics))
        except Exception as e:  # noqa: BLE001      the look is extra: a failed one keeps what passed
            print("look check failed for", o["name"], e)
            return best
        score = parse_score(ans)
        _note(b, o["name"], score, _problems(ans), pics)
        if score is None:
            return best
        if best_score is None or score > best_score:
            best, best_score = cur_ok, score
        elif cur_ok is not best:
            b._think(f"\n\n**Kept the earlier {o['name'].lower()}**: the fix scored {score}/10, lower than {best_score}/10")
        if score >= GOOD or last:
            break
        objs = PS.parse_scene(ans)[1]
        if not objs or not objs[0]["xml"]:
            break
        f = objs[0]
        new_o = {**cur_o, "xml": f["xml"], "block": f["block"], "kind": f["kind"] or cur_o["kind"]}
        fixes += 1
        b._think(f"\n\n**Fixing the {o['name'].lower()}** from what it looks like (scored {score}/10)")
        tested = _tested(b, new_o)
        if tested is None:
            b._think(f"\n\n**Kept the {o['name'].lower()}** that passed: the fix failed its physics test")
            break
        cur_o, cur_ok = new_o, tested
    if best_score is not None:
        b._think(f"\n\n**{o['name']} looks {best_score}/10**")
    return best


def _tested(b, o: dict) -> dict | None:
    """A fixed version through the same checks as a new object (no fixing round of its own)."""
    try:
        xml = AI.clean(o["xml"])
        size, frame, mass = AI.measure(xml)
        fixed = o["kind"] != "loose"
        uid = AI.register(o["name"], xml, fixed, size, frame, mass)
        AI.shake(uid)
        AI.inspect(uid)
    except AI.Bad:
        return None
    except Exception as e:  # noqa: BLE001
        print("look check: the fix didn't load:", e)
        return None
    return {**o, "item": uid, "fixed": fixed, "size": size}


def _note(b, name: str, score, problems: str, pics):
    """What the look found, for the progress panel: the last pictures and scores."""
    looks = getattr(b, "looks", None)
    if looks is None:
        looks = b.looks = []
    looks.append({"name": name, "score": score, "problems": problems})
    del looks[:-40]
    if pics:                         # a small copy of one picture, for the panel to show
        try:
            import base64
            im = Image.open(io.BytesIO(pics[0][1]))
            im.thumbnail((220, 220))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=70)
            b.look_pic = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ level 2: the whole scene
LOOK_SCENE = """LOOK CHECK OF THE WHOLE SCENE. The request was: {request}

These pictures show the scene as built in MuJoCo. Positions below are in cm from the scene's middle \
(+x to the right and +y up the picture taken from above); z is the height of an object's bottom.

Robots (they stay where they are):
{robots}

Furniture (it stays where it is):
{furniture}

Loose objects (you may move, turn or remove these):
{objects}

Things you may add (library ids): {addable}

Judge it against the request: does it look like the place asked for, is everything a sensible size, \
on a sensible surface, facing the right way, and within reach of the robot that needs it? Look for \
things floating, sunk, overlapping, crowded together, or missing.

Answer with one line first: SCORE: n/10. Then a few short lines on what is wrong.
{tail}"""

EDIT_TAIL = """If the score is {good} or more, stop there. Otherwise end with the edits as JSON, at most {n}, \
and nothing after it:
```json
{{"edits": [
  {{"do": "move", "id": "o3", "x": 12, "y": -40, "z": 76}},
  {{"do": "turn", "id": "o3", "deg": 90}},
  {{"do": "remove", "id": "o5"}},
  {{"do": "add", "item": "<a library id from the list>", "x": 30, "y": 5, "deg": 0}}
]}}
```
"move" puts an object's middle at (x, y) on a surface there; "z" (optional, cm) is the height of the \
surface you mean, such as a worktop under a shelf or a robot's table top: without it the object lands \
on the highest surface at (x, y). "add" takes "z" too. "turn" turns an object where it stands to face \
deg (0 = its front towards -y, counter-clockwise from above)."""


def look_scene(b, focus_uids: list[str], addable: list[str]) -> None:
    """Level 2 for a built scene. `b` is the build (its stations, objects, prompt), `focus_uids`
    the things it put down, `addable` the catalog ids the model may add more of."""
    s = b.sim
    before = None
    snap, snap_objects = None, list(b.objects)
    dropped: list[str] = []
    for rnd in range(SCENE_ROUNDS + 1):
        if b.stop:
            return
        last = rnd == SCENE_ROUNDS
        ids, mid = _describe(b, focus_uids)
        if not ids and not b.stations:
            return
        stations = [s.station(u) for u in b.stations if s.station(u) is not None]
        try:
            pics = scene_views(s, [v["at"] for v in ids.values()] + [tuple(st.pos[:2]) for st in stations], stations)
        except Exception as e:  # noqa: BLE001
            print("look check: no pictures of the scene", e)
            return
        text = LOOK_SCENE.format(request=(getattr(b, "prompt", "") or "rebuild the place in the photo")[:1500],
                                 robots=_lines(b, "robot", ids, mid) or "(none)",
                                 furniture=_lines(b, "furniture", ids, mid) or "(none)",
                                 objects=_lines(b, "object", ids, mid) or "(none)",
                                 addable=", ".join(addable[:40]) or "(none)",
                                 tail=SCORE_TAIL if last else EDIT_TAIL.format(good=GOOD, n=MAX_EDITS))
        if dropped:
            text += ("\n\nLast round, these edits didn't fit and weren't made:\n"
                     + "\n".join(f"- {w}" for w in dropped[:MAX_EDITS]))
        b._think("\n\n**Looking at the whole scene**")
        try:
            ans = b._ask(text, "medium", images=images(pics))
        except Exception as e:  # noqa: BLE001
            print("look check of the scene failed:", e)
            return
        score = parse_score(ans)
        _note(b, "the whole scene", score, _problems(ans), pics)
        if score is None:
            return
        if before is not None and score < before:
            b._think(f"\n\n**Put the scene back**: the edits scored {score}/10, lower than {before}/10")
            s.restore_scene(snap)
            b.objects[:] = snap_objects
            return
        if score >= GOOD or last:
            b._think(f"\n\n**The scene looks {score}/10**")
            return
        edits = parse_edits(ans)
        if not edits:
            return
        before, snap, snap_objects = score, s.scene_state(), list(b.objects)
        dropped = []
        done = apply_edits(b, edits, ids, mid, set(addable), dropped)
        b._think(f"\n\n**Changed the scene** ({done} of {len(edits)} edits fit), scored {score}/10 before"
                 + "".join(f"\n- left out: {w}" for w in dropped))
        if not done and not dropped:
            return
        focus_uids = [u for u in focus_uids if s.find(u) is not None] + \
            [u for u in b.objects if u not in focus_uids]


def _describe(b, uids):
    """id ("r1", "f2", "o3") -> {"uid", "kind", "label", "at" (x, y) world}, and the scene's middle."""
    s = b.sim
    out = {}
    for k, u in enumerate(b.stations, 1):
        st = s.station(u)
        if st is not None:
            top = "" if st.bare else f", its table top at z {100 * st.top:.0f}"
            out[f"r{k}"] = {"uid": u, "kind": "robot", "label": f"{st.name} ({st.robot}){top}", "at": tuple(st.pos[:2]),
                            "z": 0.0}
    nf = no = 0
    for u in uids:
        p = s.find(u)
        if p is None:
            continue
        it = catalog.item(p.item)
        if it["fixed"]:
            nf += 1
            key = f"f{nf}"
        else:
            no += 1
            key = f"o{no}"
        label = it["label"]
        if it["fixed"]:
            label += f", {100 * catalog.meta(p.item)['size'][2]:.0f} cm tall"
            try:
                from . import scenegen as SG
                wt = SG.worktop(s, p)
                if abs(wt - catalog.meta(p.item)["size"][2]) > 0.03:
                    label += f", its worktop at z {100 * wt:.0f}"
            except Exception:  # noqa: BLE001
                pass
        out[key] = {"uid": u, "kind": "furniture" if it["fixed"] else "object", "label": label,
                    "at": (float(p.pos[0]), float(p.pos[1])), "z": float(p.pos[2]), "yaw": float(p.yaw)}
    pts = [v["at"] for v in out.values()] or [(0.0, 0.0)]
    mid = ((min(p[0] for p in pts) + max(p[0] for p in pts)) / 2, (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2)
    return out, mid


def _lines(b, kind, ids, mid) -> str:
    rows = []
    for key, v in ids.items():
        if v["kind"] != kind:
            continue
        x, y = 100 * (v["at"][0] - mid[0]), 100 * (v["at"][1] - mid[1])
        extra = f", z {100 * v['z']:.0f}, facing {math.degrees(v.get('yaw', 0.0)) % 360:.0f} deg" if kind != "robot" else ""
        rows.append(f"- {key}: {v['label']} at x {x:.0f}, y {y:.0f}{extra}")
    return "\n".join(rows)


def parse_edits(text: str) -> list[dict]:
    f = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    raw = f[-1] if f else None
    if raw is None:
        a = (text or "").rfind('{"edits"')
        if a < 0:
            return []
        raw = text[a:text.rfind("}") + 1]
    try:
        got = json.loads(raw).get("edits") or []
    except (ValueError, AttributeError):
        return []
    return [e for e in got if isinstance(e, dict) and e.get("do") in ("move", "turn", "remove", "add")][:MAX_EDITS]


def _num(v, d=0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except (TypeError, ValueError):
        return d


def _spot(s, item, x, y, yaw, z=None, uid=None) -> dict | None:
    """Where `item` lands with its middle over (x, y): the drop check (sim.support), on the
    highest surface there, or with `z` (cm) on the surface at about that height, with room above
    it for the item (a worktop under a shelf). None if it doesn't fit, or not level."""
    return _fit(s, item, x, y, yaw, z, uid)[0]


def _fit(s, item, x, y, yaw, z=None, uid=None) -> tuple:
    """_spot, and in plain words why it doesn't fit when it doesn't."""
    top = 3.0
    if z is not None:
        top = _num(z, -1) / 100 + 0.04
        if top <= 0.02:
            return None, "the surface height z wasn't a height above the floor"
    spot = s.support(item, x, y, yaw, top=top, exclude_uid=uid)
    if not spot["valid"]:
        return None, spot["reason"] or "something is in the way there"
    if not spot["level"]:
        return None, f"it would stand tilted there, half on {spot.get('surface', 'two things')}"
    if z is not None:
        if spot.get("surface") == "the floor" and _num(z, 0) > 5:
            return None, f"there is no surface at z {_num(z, 0):.0f} cm there, only the floor"
        h = float(catalog.meta(item)["size"][2])
        bottom = spot["pos"][2]
        excl = -1
        if uid:
            with s.lock:
                excl = s.m.body(f"obj_{uid}").id
        dist, _ = s._ray((x, y, bottom + 0.005), (0, 0, 1.0), excl)
        if dist is not None and dist < h:
            return None, (f"no room: it is {100 * h:.0f} cm tall and there are only "
                          f"{100 * dist:.0f} cm under what is above it")
    return spot, ""


def apply_edits(b, edits, ids, mid, addable: set, why: list | None = None) -> int:
    """The model's edits, each put down with the drop check (sim.support) or left out. Robots and
    furniture never move. Returns how many fit; `why` gets a line for each one left out."""
    s = b.sim
    done = 0
    why = [] if why is None else why

    def no(e, reason):
        line = f"{e.get('do')} {e.get('id') or e.get('item') or ''}: {reason}"
        why.append(line)
        print("look check: an edit didn't fit:", line)
    for e in edits:
        if b.stop:
            break
        try:
            if e["do"] == "add":
                item = str(e.get("item") or "")
                if item not in addable:
                    no(e, "only objects already in this scene can be added")
                    continue
                x, y = mid[0] + _num(e.get("x")) / 100, mid[1] + _num(e.get("y")) / 100
                yaw = math.radians(_num(e.get("deg")))
                spot, r = _fit(s, item, x, y, yaw, e.get("z"))
                if spot:
                    uid = s.add(item, spot["pos"], yaw)
                    b.objects.append(uid)
                    done += 1
                else:
                    no(e, r)
                continue
            v = ids.get(str(e.get("id") or ""))
            if v is not None and v["kind"] != "object":
                no(e, f"a {v['kind']} can't be moved or removed, only loose objects")
                continue
            if v is None or s.find(v["uid"]) is None:
                no(e, "no such id in the list")
                continue
            uid = v["uid"]
            if e["do"] == "remove":
                s.remove(uid)
                if uid in b.objects:
                    b.objects.remove(uid)
                done += 1
                continue
            p = s.find(uid)
            if e["do"] == "move":
                x, y = mid[0] + _num(e.get("x")) / 100, mid[1] + _num(e.get("y")) / 100
                yaw = p.yaw
            else:                                   # turn, where it stands
                cx, cy, _ = s.obj_at(uid)
                x, y, yaw = cx, cy, math.radians(_num(e.get("deg")))
            spot, r = _fit(s, p.item, x, y, yaw, e.get("z") if e["do"] == "move" else None, uid)
            if spot:
                s.move(uid, spot["pos"], yaw)
                done += 1
            else:
                no(e, r)
        except Exception as ex:  # noqa: BLE001     one edit that doesn't fit is left out
            no(e, f"error: {ex}")
    return done


def fake_look(text: str) -> str:
    """A pretend model's look (tests, WETLAB_SCENEGEN_FAKE): fine as it is."""
    return "SCORE: 9/10\nLooks like the real thing; nothing to change."
