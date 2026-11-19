"""A square grid for laying scenes out: the model places things by square, not by metre.

Two grids, each of equal squares:
- the floor grid, 25 cm squares, in the scene's own frame: stations and floor furniture. A thing
  is placed by the square of its footprint's lowest corner and by which way its front points
  (+x, -x, +y or -y). Its footprint in squares comes from its real size, rounded up.
- a table grid, 5 cm squares, on each robot's table, counted from the robot's base: "f" squares
  forward of the base and "s" squares to its left. The squares within the arm's comfortable reach
  are a ring round the base, given per robot.

The model's answer in squares is turned into the metre layout the builder already takes
(scenegen.Build._clean_layout); MuJoCo's drop check still decides where each thing comes to rest.
On for a build when WETLAB_SCENE_GRID=1.
"""
from __future__ import annotations

import json
import math
import os

from . import catalog
from . import world as W

FLOOR = 0.25          # metres per floor square
TABLE = 0.05          # metres per table square
DIRS = {"+x": 0.0, "+y": math.pi / 2, "-x": math.pi, "-y": -math.pi / 2}

# Where things may go on each kind of station's table, in its own frame (metres): x from, x to, y half-width
AREA = {"table": (-0.15, 0.75, 0.5), "wetlab": (-0.1, 0.3, 0.8), "island": (-0.05, 0.25, 0.55),
        "counter": (-0.05, 0.25, 1.05)}


def on() -> bool:
    return os.environ.get("WETLAB_SCENE_GRID") == "1"


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _dir(v) -> str:
    v = str(v or "").strip().lower().replace(" ", "")
    return v if v in DIRS else "+x"


def long_y(item: str) -> bool:
    """Modelled long from front to back (NVIDIA's counters and benches): its front is its +x side."""
    from .scenegen import front_sign
    sx, sy, _ = catalog.meta(item)["size"]
    return sy > 1.25 * sx and front_sign(item) < 0      # a Tripo model's front is its +y side whatever its shape


def squares(item: str) -> tuple[int, int]:
    """A floor thing's footprint in floor squares: (wide along its front, deep front to back)."""
    sx, sy, _ = catalog.meta(item)["size"]
    wide, deep = (sy, sx) if long_y(item) else (sx, sy)
    return max(1, math.ceil(wide / FLOOR - 0.04)), max(1, math.ceil(deep / FLOOR - 0.04))


def item_yaw(item: str, facing: str) -> float:
    """The turn that points the thing's front along a grid direction."""
    from .scenegen import front_sign
    phi = DIRS[facing]
    if long_y(item):
        return phi
    return phi - math.pi / 2 if front_sign(item) > 0 else phi + math.pi / 2


def _centre(x, y, wide: int, deep: int, facing: str) -> tuple[float, float]:
    """The centre (metres) of a footprint whose lowest corner is square (x, y)."""
    nx, ny = (deep, wide) if facing in ("+x", "-x") else (wide, deep)
    return (_f(x) + nx / 2) * FLOOR, (_f(y) + ny / 2) * FLOOR


def station_squares(kind: str, robot: str) -> tuple[int, int]:
    """A station table's footprint in floor squares: (deep along the way the robot faces, wide)."""
    sx, sy = W.Station("probe", robot, (0.0, 0.0), 0.0, kind=kind).footprint()
    return max(1, math.ceil(sx / FLOOR - 0.04)), max(1, math.ceil(sy / FLOOR - 0.04))


def _base(kind: str, robot: str) -> tuple[float, float]:
    """The table grid's origin in the station's frame: the robot's base (an ALOHA: between its two)."""
    st = W.Station("probe", robot, (0.0, 0.0), 0.0, kind=kind)
    bs = st.bases()
    return sum(b[0] for b in bs) / len(bs), sum(b[1] for b in bs) / len(bs)


def table_text(kind: str, robot: str) -> str:
    """One station's table grid in words: its squares, and the ones in reach."""
    bx, by = _base(kind, robot)
    x0, x1, hy = AREA.get(kind, AREA["table"])
    reach = next((r["reach_mm"] for r in catalog.robots() if r["id"] == robot), 850) / 1000.0
    near = math.ceil(0.25 / TABLE)
    far = int(0.75 * reach / TABLE)
    two = len(W.Station("probe", robot, (0.0, 0.0), 0.0, kind=kind).bases()) > 1
    return (f"{robot} at a {kind}: f from {math.ceil((x0 - bx) / TABLE)} to {int((x1 - bx) / TABLE)}, "
            f"s from {math.ceil((-hy - by) / TABLE)} to {int((hy - by) / TABLE)}; "
            + ("two arms, their bases at s -9 and s +9: each thing within 11 squares of one of them"
               if two else f"in reach: {near} to {far} squares from the base (f 0, s 0), counted straight "
                           f"across (f and s as the two sides of a right triangle)"))


def sizes_text(items: list[str]) -> dict:
    """Each object's footprint: floor furniture in floor squares (wide x deep) and its height in
    cm; everything else in table squares (x by y as modelled) and its height in cm."""
    out = {}
    for i in sorted(set(items)):
        sx, sy, sz = catalog.meta(i)["size"]
        if catalog.item(i)["fixed"]:
            w, d = squares(i)
            out[i] = f"{w} wide x {d} deep floor squares, {round(100 * sz)} cm tall"
            if max(sx, sy) <= 0.5 and sz <= 0.5:
                out[i] += f" (on a table: {math.ceil(sx / TABLE)} x {math.ceil(sy / TABLE)} table squares)"
        else:
            out[i] = f"{max(1, math.ceil(sx / TABLE))} x {max(1, math.ceil(sy / TABLE))} table squares, {round(100 * sz)} cm tall"
    return out


def to_metres(lay: dict) -> dict:
    """The model's layout in squares as the metre layout the builder takes. Stations and
    furniture: the lowest corner's square and a facing. Objects on a table: f and s squares from
    the robot's base. Objects on the floor: a floor square. dx, dy (on or inside something) stay
    metres."""
    out = {k: v for k, v in lay.items() if k not in ("stations", "furniture", "objects")}
    stations = []
    for st in lay.get("stations") or []:
        st = dict(st or {})
        kind = st.get("kind") if W.is_kind(st.get("kind")) else "table"
        face = _dir(st.get("facing"))
        deep, wide = station_squares(kind, str(st.get("robot", "franka")))
        x, y = _centre(st.get("x"), st.get("y"), wide, deep, face)
        stations.append({**st, "kind": kind, "x": x, "y": y, "yaw": math.degrees(DIRS[face])})
    furniture = []
    for f in lay.get("furniture") or []:
        f = dict(f or {})
        it = str(f.get("item", ""))
        try:
            wide, deep = squares(it)
        except (KeyError, FileNotFoundError):
            continue
        face = _dir(f.get("facing"))
        x, y = _centre(f.get("x"), f.get("y"), wide, deep, face)
        f.pop("face", None)
        furniture.append({**f, "x": x, "y": y, "yaw": math.degrees(item_yaw(it, face))})
    objects = []
    for o in lay.get("objects") or []:
        o = dict(o or {})
        on_ = o.get("on", "station")
        it = str(o.get("item", ""))
        if on_ == "station":
            k = int(_f(o.get("station")))
            st = stations[max(0, min(len(stations) - 1, k))] if stations else {"kind": "table", "robot": "franka"}
            bx, by = _base(st["kind"], str(st.get("robot", "franka")))
            o["x"], o["y"] = bx + _f(o.get("f")) * TABLE, by + _f(o.get("s")) * TABLE
            if o.get("facing") == "robot":          # its front to the robot's base
                o["face"] = [bx, by]
            o["yaw"] = _f(o.get("turn"))
        elif on_ == "floor":
            try:
                sx, sy, _ = catalog.meta(it)["size"]
            except (KeyError, FileNotFoundError):
                continue
            o["x"], o["y"] = (_f(o.get("x")) + 0.5) * FLOOR, (_f(o.get("y")) + 0.5) * FLOOR
            o["yaw"] = _f(o.get("turn"))
        else:
            o["yaw"] = _f(o.get("turn"))
        objects.append(o)
    out.update(stations=stations, furniture=furniture, objects=objects)
    return out


SYSTEM = """You lay out a scene in a robot physics playground on a square grid. Write a short \
layout plan, then place everything by square. You decide anything the person didn't say.

The floor grid: squares of 25 cm, x to the east and y to the north, counted from square (0, 0); \
squares may be negative. Stations (a robot at its table) and floor furniture go on it. Each has a \
footprint in squares: "wide" squares along its front and "deep" squares front to back. You give \
the square of its footprint's lowest corner (smallest x and smallest y it covers) and "facing": \
the way its front points, one of "+x", "-x", "+y", "-y". Facing +x or -x it covers deep squares \
in x and wide squares in y; facing +y or -y it covers wide in x and deep in y. Work out the \
squares each thing covers; no two footprints may share a square.
- Two things side by side in a run share an edge: the next one starts on the square right after \
the last one ends (no empty square between). A walkway is 3 to 4 empty squares.
- A station's facing is the way its robot looks across its table. Its footprint: {stations}. \
The robot stands at the middle of the table's edge behind it. Kinds: "table" (a packing table), \
"wetlab" (a lab bench), "island" (a kitchen island), "counter" (a kitchen counter): the last two \
for kitchens. A Unitree G1 stands on the floor at its table's near edge. Keep 2 or more empty \
squares between stations, unless robots share a job: then their tables share an edge.
- The room's shape: the robots' tables in the middle. Furniture that lines walls (counters, \
fridges, cabinets, racks, benches, machines) forms one run 3 to 4 squares behind the robots, \
fronts facing the robots' tables, each piece starting where the last ends; a long run turns the \
corner down one side. The side the robots face stays clear of anything taller than the tables.
- Furniture the task uses or feeds (a fridge to load, a machine to tend, the sink and dishwasher \
of a dish line, the conveyor a robot loads, the pallet it stacks, a shelf to stock) shares an \
edge with the robot's table at one of its side ends, front facing the table, add "gap": 0.05.
- A fence: just list its panels and door; the builder stands them in a ring round the cell.
- Small things never go on the bare floor (only bins, buckets, boxes, signs and things made to \
stand there, by floor square).

The table grid: each robot's table has squares of 5 cm, counted from the robot's base: "f" \
squares forward (the way the robot faces) and "s" squares to its left (negative: to its right). \
Each object on a table is placed by the square of its centre. The tables here: {tables}
- Everything the task uses must be on a square in reach; nothing closer than the nearest \
reach square. Check each thing's distance in squares before you write it.
- Keep at least 2 empty squares between objects' footprints so a gripper fits, unless the \
request asks for clutter: then footprints touch or sit 1 square apart in one patch about 8 by 8 \
squares, at mixed turns. "Scattered" means uneven spots and turns, never a row.
- A row or arc of things for a task (bins to sort into, bottles in a line) keeps the same f or \
the same distance from the base, evenly spaced in s.
- "turn" is an object's turn about the vertical in degrees. For a thing with a front (a \
cabinet, a microwave, a box with a lid) give "facing": "robot" instead.
- Small furniture can stand on a table like an object, front facing the robot. Only these \
can: {tabletop}.
- Things the request says start in or on something (parts in a tote, bottles in a crate, cans \
on a shelf, a mug in a drawer) go "on": "inside" it: "object": the index (from 0) in your \
"objects" list of the holder (or "furniture": its index), "level": 1 for the lowest space \
inside, 2 the next up, -1 the highest, and dx, dy in metres from its centre to spread several \
things out. On top of a piece of furniture: "on": "furniture" with its index and dx, dy in metres.
- "open": true on a container, lid, door or drawer the task puts things into or takes things \
out of, when the request doesn't ask the robot to open it (the robot can't lift a lid it isn't \
asked to). Leave it out when opening is part of the task.
- When the request wants stations to match ("identical", "the same setup"), give every station \
the same things on the same squares.

The scene's robots (each entry is one station): {robots}
The scene's objects: {items}
Footprints: {sizes}

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
 "stations": [{{"robot": "franka", "kind": "table", "x": 0, "y": 0, "facing": "+x"}}],
 "furniture": [{{"item": "refrigerator", "x": -8, "y": 2, "facing": "+x"}}],
 "objects": [{{"item": "mug", "on": "station", "station": 0, "f": 8, "s": -3, "turn": 0}},
             {{"item": "kettle", "on": "furniture", "furniture": 0, "dx": 0, "dy": 0, "turn": 0}},
             {{"item": "waste_bin", "on": "floor", "x": 6, "y": -4, "turn": 0}},
             {{"item": "can", "on": "inside", "object": 0, "level": 1, "dx": 0.05, "dy": 0, "turn": 0}}],
 "task": "the robot's task, one sentence, naming things in plain words (never by index or id)"}}
List every station and every object exactly once per copy (an item asked for twice appears \
twice). Put furniture items in "furniture" only."""


def system(robots: list[str], items: list[str], tabletop: list[str]) -> str:
    kinds = ("table", "wetlab", "island", "counter")
    st = "; ".join(f"{k}: {station_squares(k, robots[0])[1]} wide x {station_squares(k, robots[0])[0]} deep"
                   for k in kinds)
    tables = " | ".join(table_text(k, r) for r in sorted(set(robots)) for k in kinds)
    return SYSTEM.format(stations=st, tables=tables, robots=json.dumps(robots), items=json.dumps(items),
                         sizes=json.dumps(sizes_text(items)), tabletop=json.dumps(tabletop or "none in this scene"))
