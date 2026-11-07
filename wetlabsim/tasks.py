"""The task library: what each task asks, how the bench starts, and how it is scored.

Every task starts from the same bench (scene.py) with its own starting layout. Scoring
uses only the true state of the simulation at the end of the run (and, for the one
"look and report" task, the agent's final answer). Agents never see any of this.

Task IDs follow the task doc (T-numbers). The two screw-cap tasks are T24 and T25.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import scene as S

BH = S.BENCH_HEIGHT
UP = (1.0, 0.0, 0.0, 0.0)
FLAT_X = (math.cos(math.pi / 4), 0.0, math.sin(math.pi / 4), 0.0)   # lying, axis along x
FLAT_Y = (math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0, 0.0)   # lying, axis along y
UPSIDE_DOWN = (0.0, 1.0, 0.0, 0.0)
# Pipette lying along x on its side, finger hook pointing at -y.
PIPETTE_ON_SIDE = (-0.500000, 0.500000, -0.500000, 0.500000)
YAW90 = (math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4))
MOVED_TOL = 0.005      # m: an object counts as moved (or disturbed) past this


# ------------------------------------------------------------------------ layouts
def _tube15_in(slot_xy, z_floor):
    return (slot_xy[0], slot_xy[1], z_floor + S.TUBE_HALF_LEN + 0.0005), UP


def default_layout() -> dict:
    """name -> (base-frame position, quat) for every free object. Caps go with their tubes."""
    L = {}
    for rack, row, col, colour, _ in S.TUBES:
        L[f"tube_{colour}"] = _tube15_in(S.slot_center(rack, row, col), S.RACK_FLOOR)
    _, px, py = S.PLATE_60
    L["rack_60well"] = ((px, py, 0.0105), YAW90)
    w = S.well_center("C9")
    L["microtube"] = ((w[0], w[1], 0.0224 + 0.0005), UP)
    L["tube50"] = ((0.76, 0.06, 0.0176 + 0.001), FLAT_Y)
    L["petri_dish_1"] = ((0.60, 0.29, 0.0005), UP)
    L["petri_dish_2"] = ((0.70, 0.19, 0.0005), UP)
    L["pipette"] = ((0.45, -0.42, 0.0086), PIPETTE_ON_SIDE)
    return L


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    layout: Callable[[dict], None] = lambda L: None        # edits the default layout
    caps: dict = field(default_factory=dict)               # colour -> "off" (cap lies on the bench)
    cap_colours: dict = field(default_factory=dict)        # body -> rgba override (e.g. a red 50 ml cap)
    score: Callable = None
    needs_answer: bool = False


# ------------------------------------------------------------------------ helpers
def _pos(gt, name):
    return np.array(gt["objects"][name]["pos"])


def _up(gt, name):
    """Cosine between the object's z axis and straight up."""
    w, x, y, z = gt["objects"][name]["quat"]
    return 1 - 2 * (x * x + y * y)


def _moved(gt0, gt1, name):
    return float(np.linalg.norm(_pos(gt1, name) - _pos(gt0, name)))


def _upright(gt, name, deg=15):
    return _up(gt, name) > math.cos(math.radians(deg))


def in_15ml_slot(gt, name):
    """(rack, row, col) of the 15 ml rack slot or clamp slot a tube stands in, or None."""
    p = _pos(gt, name)
    if not _upright(gt, name):
        return None
    for rack in S.RACKS:
        for r in range(S.RACK_ROWS):
            for c in range(S.RACK_COLS):
                s = S.slot_center(rack, r, c)
                if np.hypot(*(p[:2] - s[:2])) < 0.006 and p[2] < S.RACK_FLOOR + S.TUBE_HALF_LEN + 0.01:
                    return (rack, r, c)
    for r in range(S.CLAMP_ROWS):
        for c in range(S.CLAMP_COLS):
            s = S.clamp_slot(r, c)
            if np.hypot(*(p[:2] - s[:2])) < 0.006 and p[2] < S.CLAMP_FLOOR + S.TUBE_HALF_LEN + 0.01:
                return ("clamp", r, c)
    return None


def in_50ml_hole(gt, name):
    p = _pos(gt, name)
    if not _upright(gt, name):
        return None
    for rack in S.RACKS:
        for r in range(2):
            for c in range(5):
                s = S.hole50_center(rack, r, c)
                if np.hypot(*(p[:2] - s[:2])) < 0.008 and p[2] < S.RACK_FLOOR + 0.0598 + 0.01:
                    return (rack, r, c)
    return None


def in_well(gt, name):
    """Name of the 60-well rack well the 1.5 ml tube stands in, wherever the rack now is."""
    p = _pos(gt, name)
    if not _upright(gt, name, 20):
        return None
    rp = _pos(gt, "rack_60well")
    w, x, y, z = gt["objects"]["rack_60well"]["quat"]
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s = math.cos(-yaw), math.sin(-yaw)
    d = p[:2] - rp[:2]
    lx, ly = c * d[0] - s * d[1], s * d[0] + c * d[1]   # rack frame
    col = round((lx + 0.0873) / 0.0162)
    row = round((0.0244 - ly) / 0.0132)
    if not (0 <= col < 12 and 0 <= row < 5):
        return None
    if abs(lx - (-0.0873 + 0.0162 * col)) > 0.005 or abs(ly - (0.0244 - 0.0132 * row)) > 0.005:
        return None
    if p[2] > 0.035:
        return None
    return f"{'ABCDE'[4 - row]}{12 - col}"


def in_clamp(gt, name) -> bool:
    """Held upright in a slot of the spring-grip rack: square in the slot, with its tip at
    least 15 mm down inside the rack (a tube pulled up a little is still gripped by the pads)."""
    p = _pos(gt, name)
    if not _upright(gt, name):
        return False
    tip = p[2] - S.TUBE_HALF_LEN
    return any(np.hypot(*(p[:2] - S.clamp_slot(r, c)[:2])) < 0.006 and tip <= S.CLAMP_H - 0.015
               for r in range(S.CLAMP_ROWS) for c in range(S.CLAMP_COLS))


def knocked_over(gt0, gt1) -> list[str]:
    """Things that stood upright at the start and lie down at the end."""
    return [n for n in gt0["objects"] if not n.endswith("_cap") and n in gt1["objects"]
            and _up(gt0, n) > math.cos(math.radians(30)) and _up(gt1, n) < math.cos(math.radians(60))]


def _others_still(gt0, gt1, keep: set):
    """Names of objects (other than keep) that moved more than MOVED_TOL."""
    return [n for n in gt0["objects"] if n not in keep and not n.endswith("_cap")
            and _moved(gt0, gt1, n) > MOVED_TOL]


def _result(score, passed, **detail):
    return {"score": round(float(score), 3), "passed": bool(passed), "detail": detail}


# ------------------------------------------------------------------------ scorers
def score_t1(gt0, gt1, ctx):
    slot = in_15ml_slot(gt1, "tube_red")
    disturbed = _others_still(gt0, gt1, {"tube_red"})
    ok = slot is not None and slot[0] == "rack_b"
    return _result(1.0 if ok and not disturbed else 0.5 if ok else 0.0, ok and not disturbed,
                   red_tube_in=slot, disturbed=disturbed)


def score_t3(gt0, gt1, ctx):
    slot = in_15ml_slot(gt1, "tube_green")
    disturbed = _others_still(gt0, gt1, {"tube_green"})
    wrong_moved = [n for n in ("tube_red", "tube_blue") if n in disturbed]
    ok = slot is not None and slot[0] == "rack_b" and not wrong_moved
    return _result(1.0 if ok and not disturbed else 0.5 if ok else 0.0, ok and not disturbed,
                   green_tube_in=slot, disturbed=disturbed)


def score_t5(gt0, gt1, ctx):
    slots = {c: in_15ml_slot(gt1, f"tube_{c}") for c in ("red", "green", "blue")}
    front = {c: s for c, s in slots.items() if s and s[0] == "rack_b" and s[1] == 0}
    # Left to right as seen from the robot = decreasing y = decreasing column.
    order_ok = len(front) == 3 and front["red"][2] > front["green"][2] > front["blue"][2]
    score = len(front) / 3 * 0.75 + (0.25 if order_ok else 0)
    return _result(score, order_ok, slots=slots)


def score_t7(gt0, gt1, ctx):
    slot = in_15ml_slot(gt1, "tube_green")
    disturbed = _others_still(gt0, gt1, {"tube_green"})
    ok = slot is not None and slot[0] != "clamp"
    return _result(1.0 if ok and not disturbed else 0.5 if ok else 0.0, ok and not disturbed,
                   green_tube_in=slot, disturbed=disturbed)


def truth_inventory(gt) -> dict:
    """What a careful person would report for T12, from the true state."""
    occupied = {}
    for n in ("tube_red", "tube_blue", "tube_green"):
        s = in_15ml_slot(gt, n)
        if s:
            occupied[s] = n
    empty15 = {rack: [(r, c) for r in range(S.RACK_ROWS) for c in range(S.RACK_COLS)
                      if (rack, r, c) not in occupied] for rack in S.RACKS}
    return {
        "items": {"15 ml tubes (red, blue, green caps)": 3, "50 ml tube (orange cap, lying down)": 1,
                  "1.5 ml tube (yellow cap)": 1, "white 15/50 ml tube racks": 2,
                  "blue 60-well rack for 1.5 ml tubes": 1, "spring-grip tube rack (clamp)": 1,
                  "petri dishes": 2, "pipette": 1, "pipette stand": 1},
        "empty_15ml_slots": {rack: len(v) for rack, v in empty15.items()},
        "rack_a_occupied": sorted([s[1:] for s in occupied if s[0] == "rack_a"]),
        "rack_b": "empty",
        "60_well_rack": f"one 1.5 ml tube in well {in_well(gt, 'microtube')}, the other 59 wells empty",
        "clamp": "all 24 slots empty",
    }


def score_t12(gt0, gt1, ctx):
    disturbed = _others_still(gt0, gt1, set())
    judge = ctx.get("judge") or {}
    s = judge.get("score", 0.0) if not disturbed else 0.0
    return _result(s, s >= 0.75 and not disturbed, judge=judge, disturbed=disturbed)


def score_t18(gt0, gt1, ctx):
    hole = in_50ml_hole(gt1, "tube50")
    red_moved = _moved(gt0, gt1, "tube_red") > MOVED_TOL
    ok = hole is not None and hole[0] == "rack_b"
    near_b = np.hypot(*(_pos(gt1, "tube50")[:2] - np.array(S.RACKS["rack_b"]))) < 0.11
    score = 1.0 if ok and not red_moved else 0.5 if ok or (near_b and not red_moved) else 0.0
    return _result(score, ok and not red_moved, tube50_in=hole, red_15ml_moved=red_moved)


def score_t19(gt0, gt1, ctx):
    well = in_well(gt1, "microtube")
    ok = well == "B3"
    return _result(1.0 if ok else 0.5 if well else 0.0, ok, microtube_in=well)


def score_t24(gt0, gt1, ctx):
    cap = gt1["caps"]["red"]
    cp = _pos(gt1, "tube_red_cap")
    open_up = _up(gt1, "tube_red_cap") < -math.cos(math.radians(20))
    on_bench = cp[2] < 0.004
    tube_ok = in_clamp(gt1, "tube_red")
    off = not cap["on"]
    score = ((0.5 if off else 0.0) + (0.25 if off and on_bench else 0)
             + (0.25 if off and on_bench and open_up and tube_ok else 0))
    return _result(score, off and on_bench and open_up and tube_ok, cap=cap, cap_on_bench=bool(on_bench),
                   open_side_up=bool(open_up), tube_still_in_clamp=tube_ok)


TIGHT_PASS = 0.06   # N m


def score_t25(gt0, gt1, ctx):
    """Closed tightly, with the tube still upright in the clamp and nothing knocked over."""
    cap = gt1["caps"]["red"]
    closed = cap["on"] and cap["seated"] and cap["tightness_nm"] >= TIGHT_PASS
    tube_ok = in_clamp(gt1, "tube_red")
    knocked = knocked_over(gt0, gt1)
    score = 0.0
    if cap["on"]:
        score = 0.25 + (0.25 if cap["seated"] else 0) + (0.25 if closed else 0) + (0.25 if closed and tube_ok and not knocked else 0)
    return _result(score, closed and tube_ok and not knocked, cap=cap, tube_still_in_clamp=tube_ok,
                   knocked_over=knocked)


def dishes_stacked(gt):
    a, b = _pos(gt, "petri_dish_1"), _pos(gt, "petri_dish_2")
    return bool(np.hypot(*(a[:2] - b[:2])) < 0.015 and 0.012 < abs(a[2] - b[2]) < 0.03
                and _upright(gt, "petri_dish_1", 10) and _upright(gt, "petri_dish_2", 10))


def pipette_on_stand(gt):
    p = _pos(gt, "pipette")
    sx, sy = S.PIPETTE_STAND
    return bool(_up(gt, "pipette") > math.cos(math.radians(20)) and p[2] > 0.03
                and abs(p[1] - sy) < 0.06 and abs(p[0] - sx) < 0.15)


def score_t23(gt0, gt1, ctx):
    items = {
        "blue 15 ml tube in a 15 ml slot": in_15ml_slot(gt1, "tube_blue") is not None,
        "50 ml tube in a 50 ml hole": in_50ml_hole(gt1, "tube50") is not None,
        "dishes stacked": dishes_stacked(gt1),
        "pipette on its stand": pipette_on_stand(gt1),
    }
    n = sum(items.values())
    return _result(n / len(items), n == len(items), items=items)


# ------------------------------------------------------------------------ the list
def _t7(L):
    L["tube_green"] = ((0.33, 0.02, S.TUBE_RADIUS + 0.001), FLAT_Y)


def _t18(L):
    L["tube_red"] = _tube15_in(S.slot_center("rack_a", 1, 0), S.RACK_FLOOR)
    L["tube_blue"] = _tube15_in(S.slot_center("rack_a", 0, 4), S.RACK_FLOOR)
    L["tube_green"] = _tube15_in(S.slot_center("rack_a", 2, 5), S.RACK_FLOOR)
    h = S.hole50_center("rack_a", 0, 1)
    L["tube50"] = ((h[0], h[1], S.RACK_FLOOR + 0.0598 + 0.0005), UP)


def _t19(L):
    pass        # the 1.5 ml tube starts in well C9 (the default bench)


def _in_clamp(L):
    L["tube_red"] = _tube15_in(S.clamp_slot(1, 2), S.CLAMP_FLOOR)


def _t25(L):
    _in_clamp(L)
    L["tube_red_cap"] = ((0.36, 0.26, S.CAP_HEIGHT + 0.0005), UP)    # set down open side down


def _t23(L):
    L["tube_blue"] = ((0.30, 0.03, S.TUBE_RADIUS + 0.001), FLAT_Y)


RED = (0.85, 0.15, 0.15, 1)

TASKS = {t.id: t for t in [
    Task("T1", "Move one tube",
         "Move the tube with the red cap into an empty slot of the other rack.", score=score_t1),
    Task("T3", "Which tube",
         "Move the tube that is alone in its row to the other rack.", score=score_t3),
    Task("T5", "Sort by colour",
         "Move all three tubes to rack B's front row, in the order red, green, blue from left to "
         "right (as seen from the robot).", score=score_t5),
    Task("T7", "Fallen tube", "A tube has fallen over. Put it upright in any empty slot.",
         layout=_t7, score=score_t7),
    Task("T12", "Look and report",
         "How many of each item are on the bench, and which slots are empty? Don't move anything.",
         score=score_t12, needs_answer=True),
    Task("T18", "Find by size", "Move the 50 ml tube to rack B.", layout=_t18,
         cap_colours={"tube50": RED}, score=score_t18),
    Task("T19", "Small tube into a named well",
         "Put the 1.5 ml tube into well B3 of the small-tube rack.", layout=_t19, score=score_t19),
    Task("T24", "Unscrew a cap",
         "Open the red tube and put the cap down on the bench, open side up.",
         layout=_in_clamp, score=score_t24),
    Task("T25", "Screw a cap back on", "Close the open tube tightly.", layout=_t25,
         caps={"red": "off"}, score=score_t25),
    Task("T23", "Tidy the bench",
         "Tidy the bench: tubes in racks they fit, dishes stacked, pipette on its stand.",
         layout=_t23, score=score_t23),
]}


def layout_for(task_id: str | None) -> tuple[dict, dict, dict]:
    """(poses, cap states, cap colour overrides) for a task, or the default bench."""
    L = default_layout()
    t = TASKS.get(task_id) if task_id else None
    if t:
        t.layout(L)
    return L, (t.caps if t else {}), (t.cap_colours if t else {})


def score(task_id: str, gt0: dict, gt1: dict, ctx: dict | None = None) -> dict:
    return TASKS[task_id].score(gt0, gt1, ctx or {})
