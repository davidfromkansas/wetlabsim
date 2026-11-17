"""Describe a scene, v2: from a typed prompt to a checked list of robots and objects with
enough variety to look like a real place.

1. Plan: a language model (the owner's Anthropic or OpenAI key) reads the category tree
   (playground/object_tree.py, with how many objects sit under each branch) and writes a brief:
   the room, its zones, and a shopping list of slots ("2 drinkware for the table", "1 fridge"),
   each marked as needed for the task or there to make the place look real.
2. Pick: Jev (TypeSafe's decision model) ranks the objects under each slot's branch for that
   slot, every slot at once, and the best few go on a short list. Without a Jev key, or if Jev
   can't be reached, a plain word match ranks them instead.
3. Choose: the model picks the objects from the short lists (variety, one look, no near
   duplicates), and anything we don't have gets a stand-in or goes under "not in our library".

The result has the same shape as scenegen.pick() (so the check card and the build stay as they
are), plus the brief: the zones and each object's slot and role, which the layout step reads.

The tree's tags are for building scenes only: the robot AI never sees them.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import catalog
from . import object_tree as T
from . import scenegen as SG

SHORT = 8          # objects on each slot's short list
JEV_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = "jev-1.14.0"
JEV_MAX_OPTIONS = 40          # options in one Jev choice question (more are split over questions)
STOP = {"a", "an", "the", "of", "and", "or", "for", "with", "to", "in", "on", "at", "some", "set", "box"}


def jev_key() -> str:
    """The Jev key scenes are picked with: David's, for every session (the Modal secret
    JEV_API_KEY, which hosting/app.py hands over as WETLAB_SCENE_JEV_KEY so task runs never
    use it), or on one's own computer JEV_API_KEY."""
    k = os.environ.get("WETLAB_SCENE_JEV_KEY") or os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
    if k or os.environ.get("WETLAB_OWNER_KEY"):      # the hosted site: only the server's own key
        return k or ""
    try:                                             # one's own computer: a Jev key saved in Settings
        from . import accounts as ACCT
        kind, key = ACCT.credential_for("jev")
        return key if kind == "key" else ""
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ 1. the brief
BRIEF_SYSTEM = """You plan scenes for a robot physics playground. Someone types what they want; \
you plan a believable place built only from our library, and the task the robot(s) will do there.

Robots (id: what it is):
{robots}

Our object library as a category tree, with how many objects sit under each branch and, on \
each leaf, the names of every object there:
{tree}

First, match how much the person asked for:
- A test or benchmark setup, or a request that says plain, simple, minimal or bare ("a plain \
table with 6 blocks and 3 bins"): only what they name and what the task needs. No room, no extra \
furniture, no decoration. One zone, "robot".
- A place ("a kitchen", "a wet lab", "our packing station"): the place, with the variety such a \
place has (below).
Every thing the person names must be in the plan: find it by name in the tree's lists (a basket, \
a plate, a shelf, a drawer cabinet...). Only if nothing like it is there does it go in "missing".
If the task works with furniture (a drawer, a cabinet door, a shelf, a microwave), it must be \
one small enough to stand on the robot's table, in reach: these can: {tabletop}. Big furniture \
stands on the floor, out of reach, and is only scenery.
Our objects have fixed colours. For tasks by colour, use the plain toy blocks (red, green, blue \
and yellow, as many of each as needed). Otherwise, if a task sorts or tells things apart, choose \
objects that really differ (different kinds, sizes or colours as they come) and word the task by \
what they are ("put the apples in the bowl and the lemons in the basket"), never by a colour \
they may not have.
Something the task puts things into must be open (a basket, tray, bowl, tote, bin, rack), \
never a closed box.

Plan it like a set designer:
- room: the kind of place, in a few words ("home kitchen", "cell culture lab", "garage workshop").
- robots: which robots and how many (1 to {max_robots} in all). Follow the person if they name \
one or a number; otherwise pick what suits the task (one robot unless the task needs more; a \
two-arm robot for two-handed work).
- task: one sentence, the task the robot(s) will be given, in plain words. Only use things that \
will be in the scene; the robot must be able to do it on its table (each robot works at its own \
table or counter).
- zones: 2 to 5 areas of the place ("cooking wall", "prep island", "dining table"). Exactly one \
zone is "robot": the robot's own table/counter where the task happens.
- slots: the shopping list. Each slot is one branch of the tree above (write its full path, \
like "Kitchen & dining > Tableware > Drinkware"; prefer the deepest branch that fits, and only \
branches with objects under them), how many objects from it, which zone it goes in, its role \
("task": the task needs it, it goes on the robot's table, and must be small enough for a robot \
hand; "scene": there so the place looks real), and "want": a few words on what you'd like from \
that branch ("a white mug", "any toaster").
  For a place, variety makes it look real: cover the different kinds of things such a place has (a \
kitchen has big appliances, countertop appliances, cookware, tableware, food, utensils...), \
usually 6 to 12 different branches. About 8 to 20 objects in all; keep the robot's table to \
what the task needs plus 2 to 5 other things, with room to work. Furniture (counters, fridges, \
shelves, machines) goes in floor zones.
- missing: things the person asked for that the library doesn't have (a branch shows (0) or \
nothing fits), each with "instead": the branch path of the closest stand-in, or "".
- title: a short name for the scene, 2 to 4 words.

Answer with JSON only, exactly this shape:
{{"title": "...", "room": "...", "robots": [{{"robot": "franka", "count": 1}}], "task": "...",
 "zones": [{{"name": "robot", "about": "the robot's counter, where breakfast is made"}}, {{"name": "cooking wall", "about": "..."}}],
 "slots": [{{"node": "Kitchen & dining > Tableware > Drinkware", "count": 1, "zone": "robot", "role": "task", "want": "a mug"}}],
 "missing": [{{"name": "bread", "instead": "Kitchen & dining > Food & drink > Bakery"}}]}}"""


def _robots_text() -> str:
    return SG._robots_text()


def brief_messages(prompt: str) -> tuple[str, str]:
    sys_ = BRIEF_SYSTEM.format(robots=_robots_text(), tree=T.tree_text(labels=True), tabletop=", ".join(sorted({T.tags()[i]["label"] for i in tabletop()})), max_robots=SG.MAX_ROBOTS)
    return sys_, f"The person's request:\n{prompt.strip()[:2000]}"


def _node(path: str) -> str:
    """A path the model wrote, as one of the tree's nodes ('' if it isn't one)."""
    p = " > ".join(x.strip() for x in str(path or "").split(">") if x.strip())
    nodes = T.counts()
    if p in nodes:
        return p
    low = {k.lower(): k for k in nodes}
    if p.lower() in low:
        return low[p.lower()]
    last = p.split(" > ")[-1].lower() if p else ""        # just the leaf's own name
    hits = [k for k in nodes if k.split(" > ")[-1].lower() == last]
    return hits[0] if len(hits) == 1 else ""


def clean_brief(raw: dict) -> dict:
    zones = []
    for z in raw.get("zones") or []:
        name = str((z or {}).get("name") or "").strip()[:40]
        if name and name not in [x["name"] for x in zones]:
            zones.append({"name": name, "about": str(z.get("about") or "").strip()[:200]})
    if "robot" not in [z["name"] for z in zones]:
        zones.insert(0, {"name": "robot", "about": "the robot's own table, where the task happens"})
    slots = []
    for s in raw.get("slots") or []:
        node = _node((s or {}).get("node"))
        if not node or not T.under(node):
            continue
        role = "task" if s.get("role") == "task" else "scene"
        zone = str(s.get("zone") or "").strip()[:40]
        slots.append({"node": node, "count": max(1, min(SG.MAX_EACH, SG._int(s.get("count"), 1))),
                      "zone": zone if zone in [z["name"] for z in zones] else ("robot" if role == "task" else zones[-1]["name"]),
                      "role": role, "want": str(s.get("want") or "").strip()[:120]})
    missing = []
    for m in raw.get("missing") or []:
        name = str((m or {}).get("name") or "").strip()[:40]
        if name:
            missing.append({"name": name, "instead": _node(m.get("instead"))})
    robots = SG.clean_pick({"robots": raw.get("robots") or []})["robots"]
    return {"title": (str(raw.get("title") or "").strip() or "New scene")[:40],
            "room": str(raw.get("room") or "").strip()[:60], "robots": robots,
            "task": str(raw.get("task") or "").strip()[:600], "zones": zones[:6], "slots": slots[:24],
            "missing": missing[:8]}


def tabletop() -> list[str]:
    """Furniture small enough to stand on a robot's table (LIBERO's little cabinets with drawers,
    a microwave, a short fridge...): placed with the same drop check as any object."""
    skip = ("Fixtures", "Doors, windows", "Sinks & taps", "Boards")   # built into rooms, not table things
    return [i for i, t in T.tags().items() if max(t["size_cm"][:2]) <= 50 and t["size_cm"][2] <= 50
            and (t["fixed"] or any("Shelves" in p for p in t["paths"]))
            and not any(k in p for p in t["paths"] for k in skip)]


def lookup(name: str) -> str:
    """A library object whose name matches a thing the model called missing ("flat dinner plate"
    -> Dinner plate), or "": every word of the object's name must be in the thing's name, and
    its last word (what it is) too."""
    want = _words(name)
    best, score = "", 0
    for i, t in T.tags().items():
        lab = [w for w in re.findall(r"[a-z0-9]+", t["label"].lower()) if w not in STOP and not w.isdigit()]
        if not lab or lab[-1] not in want and lab[-1].rstrip("s") not in want:
            continue
        hit = sum(w in want for w in lab)
        if hit == len(lab) and hit > score or (hit == len(lab) == score and t["look"] == "full"):
            best, score = i, hit
    return best


# ------------------------------------------------------------------ 2. the short lists
def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def _candidates(slot: dict, room: str) -> list[str]:
    """The objects under a slot's branch that could fill it: a task slot only takes things a
    hand can pick up; full-quality looks first."""
    ids = T.under(slot["node"])
    # every object under the branch stays a candidate (a basket the task puts things in needn't be
    # one a hand can lift); the ranking and the final choice judge the fit
    return ids


def _word_rank(slot: dict, room: str, ids: list[str]) -> list[tuple[str, float]]:
    want = _words(slot["want"] + " " + room)
    tags = T.tags()

    def score(i):
        t = tags[i]
        lab = _words(t["label"])
        s = 2.0 * len(want & lab) + 0.5 * len(_words(room) & set(t["rooms"]))
        s += 0.6 if t["look"] == "full" else 0.0
        return s
    return sorted(((i, score(i)) for i in ids), key=lambda x: -x[1])


def _jev(key: str, state: dict, questions: dict, timeout: float = 30.0) -> dict:
    body = json.dumps({"model": JEV_MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(JEV_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "wetlabsim-scenes"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(float(e.headers.get("retry-after") or 0.5 * 2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(0.5 * 2 ** attempt)
    raise RuntimeError(f"can't reach Jev: {last}")


def _option_key(i: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", i.lower())


def jev_rank(prompt: str, brief: dict, pools: list[list[str]], key: str) -> list[list[tuple[str, float]]]:
    """Jev's probability for every candidate of every slot, in one request (a choice question
    per slot; a slot with many candidates is split over several questions, its ranks merged)."""
    tags = T.tags()
    questions, parts = {}, []
    for k, (slot, ids) in enumerate(zip(brief["slots"], pools)):
        for c in range(0, len(ids), JEV_MAX_OPTIONS):
            chunk = ids[c:c + JEV_MAX_OPTIONS]
            q = f"slot{k}_{c // JEV_MAX_OPTIONS}"
            questions[q] = {"type": "choice",
                            "instructions": f"Which of these objects best fills this part of the scene in `scene`: "
                                            f"{slot['want'] or slot['node'].split(' > ')[-1]} "
                                            f"(for the {slot['zone']} zone; {'the robot task needs it' if slot['role'] == 'task' else 'there so the place looks real'})?",
                            "criteria": {_option_key(i): f"{tags[i]['label']} ({'x'.join(map(str, tags[i]['size_cm']))} cm, "
                                                         f"{'textured' if tags[i]['look'] == 'full' else 'plain grey CAD look'})"
                                         for i in chunk}}
            parts.append((k, q, chunk))
    state = {"scene": {"request": prompt[:2000], "room": brief["room"], "task": brief["task"],
                       "zones": brief["zones"]}}
    resp = _jev(key, state, questions)
    ans = resp.get("answers") or {}
    out = [dict() for _ in brief["slots"]]
    for k, q, chunk in parts:
        a = ans.get(q) or {}
        probs = a.get("probabilities") or {}
        n = len(chunk)
        for i in chunk:
            p = probs.get(_option_key(i))
            if p is None:
                p = (a.get("confidence") or 1.0) if a.get("choice") == _option_key(i) else 0.0
            # a slot split over questions: each question's answer covers fewer options
            out[k][i] = float(p) * n / max(1, len(pools[k]))
    return [sorted(d.items(), key=lambda x: -x[1]) for d in out]


def shortlists(prompt: str, brief: dict) -> tuple[list[list[str]], str]:
    """Each slot's short list, best first, and who ranked them ("jev" or "words")."""
    pools = [_candidates(s, brief["room"]) for s in brief["slots"]]
    key = jev_key()
    ranked, by = None, "words"
    if key and not SG.fake() and any(len(p) > SHORT for p in pools):
        try:
            ranked, by = jev_rank(prompt, brief, pools, key), "jev"
        except Exception:  # noqa: BLE001       Jev busy or down: the word match instead
            ranked = None
    if ranked is None:
        ranked = [_word_rank(s, brief["room"], p) for s, p in zip(brief["slots"], pools)]
    tags = T.tags()
    out = []
    for r in ranked:
        ids = [i for i, _ in r]
        # full-quality looks first among close scores: a plain CAD item only if it ranks well clear
        full = [i for i in ids if tags[i]["look"] == "full"]
        plain = [i for i in ids if tags[i]["look"] != "full"]
        top = ids[:SHORT]
        keep_plain = [i for i in top if i in plain][:max(2, SHORT - len(full))]
        lst = [i for i in top if i in full or i in keep_plain]
        lst += [i for i in full if i not in lst][:SHORT - len(lst)]
        out.append(lst[:SHORT])
    return out, by


# ------------------------------------------------------------------ 3. the final choice
CHOOSE_SYSTEM = """You finish the shopping list for a robot scene. You get the scene's plan and, \
for each slot, a short list of objects from our library (best first). Choose the actual objects.

- Fill every slot with its count, only with ids from that slot's list (an id may repeat when \
the count asks for more than one of the same thing, like 4 dinner plates for a table for 4).
- Variety: avoid near duplicates across the whole scene (not three different kettles) unless \
the task needs them.
- One look: prefer textured objects; a plain grey CAD object only when nothing textured fits.
- Task slots: the object must fit the task; check its size suits a robot hand. Something \
that starts inside a closed drawer must be short enough for it (a small cabinet's drawer is \
about 5.5 cm tall inside): choose a low thing for that, or say so in the task.
- If no object on a slot's list fits at all, leave the slot empty and add it to "missing" \
with "instead": "".

Answer with JSON only:
{"slots": [{"slot": 0, "ids": ["mug"]}], "missing": [{"name": "bread", "instead": ""}],
 "task": "the task, one sentence, rewritten only if a needed object is missing"}"""


def choose_messages(prompt: str, brief: dict, lists: list[list[str]]) -> tuple[str, str]:
    tags = T.tags()
    rows = []
    for k, (s, ids) in enumerate(zip(brief["slots"], lists)):
        opts = "; ".join(f"{i} = {tags[i]['label']} ({'x'.join(map(str, tags[i]['size_cm']))} cm, "
                         f"{'textured' if tags[i]['look'] == 'full' else 'plain CAD'})" for i in ids)
        rows.append(f"slot {k}: {s['count']} x {s['want'] or s['node']} | branch {s['node']} | zone {s['zone']} | "
                    f"role {s['role']}\n  options: {opts or '(none)'}")
    user = (f"The person's request:\n{prompt.strip()[:2000]}\n\nRoom: {brief['room']}\nTask: {brief['task']}\n"
            f"Zones: {json.dumps(brief['zones'])}\n\nSlots:\n" + "\n".join(rows))
    return CHOOSE_SYSTEM, user


def fake_brief(prompt: str) -> dict:
    return {"title": "Kitchen breakfast", "room": "home kitchen", "robots": [{"robot": "fr3_duo", "count": 1}],
            "task": "Put the apple in the bowl.",
            "zones": [{"name": "robot", "about": "the robot's counter"}, {"name": "cooking wall", "about": "fridge and sink"}],
            "slots": [{"node": "Kitchen & dining > Large appliances > Fridges & freezers", "count": 1, "zone": "cooking wall", "role": "scene", "want": "a fridge"},
                      {"node": "Kitchen & dining > Tableware > Plates & bowls", "count": 1, "zone": "robot", "role": "task", "want": "a bowl"},
                      {"node": "Kitchen & dining > Food & drink > Fresh food", "count": 1, "zone": "robot", "role": "task", "want": "an apple"},
                      {"node": "Kitchen & dining > Tableware > Drinkware", "count": 1, "zone": "robot", "role": "scene", "want": "a mug"}],
            "missing": []}


def pick(prompt: str, model_id: str, public: bool) -> dict:
    """The whole pick: brief, short lists, choice. Same shape as scenegen.pick(), plus "brief"
    (room, zones, slots) and "slot_of" (each picked id's slot) for the layout, and "ranked_by"."""
    t0 = time.time()
    if SG.fake():
        brief = clean_brief(fake_brief(prompt))
    else:
        sys_, user = brief_messages(prompt)
        brief = clean_brief(SG.ask_json(model_id, sys_, user, public, effort="low"))
    if not brief["robots"]:
        raise SG.ModelError("the model didn't choose any robot: try saying which robot you want")
    t1 = time.time()
    lists, by = shortlists(prompt, brief)
    t2 = time.time()
    if SG.fake():
        raw = {"slots": [{"slot": k, "ids": l[:1] * s["count"]} for k, (s, l) in enumerate(zip(brief["slots"], lists))]}
    else:
        sys_, user = choose_messages(prompt, brief, lists)
        raw = SG.ask_json(model_id, sys_, user, public, effort="low")
    t3 = time.time()
    items: dict[str, int] = {}
    slot_of: dict[str, int] = {}
    filled = set()
    for s in raw.get("slots") or []:
        k = SG._int((s or {}).get("slot"), -1)
        if not 0 <= k < len(brief["slots"]):
            continue
        ok = [i for i in (s.get("ids") or []) if i in lists[k]][:brief["slots"][k]["count"]]
        for i in ok:
            items[i] = items.get(i, 0) + 1
            slot_of.setdefault(i, k)
        if ok:
            filled.add(k)
    named = {str((m or {}).get("name") or "").lower() for m in raw.get("missing") or []}
    for k, (s, l) in enumerate(zip(brief["slots"], lists)):   # a slot the model skipped silently: its best
        if k not in filled and l and not named:
            items[l[0]] = items.get(l[0], 0) + s["count"]
            slot_of.setdefault(l[0], k)
    missing = brief["missing"] + [{"name": str((m or {}).get("name") or "")[:40], "instead": ""}
                                  for m in raw.get("missing") or [] if (m or {}).get("name")]
    labels = {c["id"]: c for c in SG._catalog_rows()}
    kept = []
    for m in missing:                 # "missing" things we do have: put them in
        i = lookup(m.get("name") or "")
        if i and i in labels:
            if i not in items:
                items[i] = 1
                brief["slots"].append({"node": T.tags()[i]["paths"][0], "count": 1, "zone": "robot",
                                       "role": "task", "want": T.tags()[i]["label"]})
                lists.append([i])
                slot_of[i] = len(brief["slots"]) - 1
        else:
            kept.append(m)
    missing = kept
    miss = []
    for m in missing:
        inst = ""
        node = m.get("instead") or ""
        if node:            # the stand-in: whatever was picked from that branch
            inst = next((i for i in items if any(p == node or p.startswith(node + " > ")
                                                 for p in T.tags()[i]["paths"])), "")
        if m["name"] and m["name"].lower() not in [x["name"].lower() for x in miss]:
            miss.append({"name": m["name"], "instead": inst if inst in labels else ""})
    out = SG.clean_pick({"title": brief["title"], "robots": brief["robots"],
                         "items": [{"id": i, "count": n} for i, n in items.items()],
                         "missing": miss, "task": str(raw.get("task") or "").strip() or brief["task"]})
    out.update(brief=brief, slot_of=slot_of, ranked_by=by, lists=lists,
               seconds={"brief": round(t1 - t0, 1), "shortlist": round(t2 - t1, 1), "choose": round(t3 - t2, 1)})
    return out
