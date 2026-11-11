"""The site sheet an agent gets in the playground: how its robot is installed here.

Like a real lab's site sheet it says how the robot is mounted and which cameras it has,
and names the things on the table, but never where they are: the agent finds them with
its cameras.
"""
from __future__ import annotations

from . import catalog
from . import world as W

TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- {robot_name}, mounted upright on {table} ({w_cm:.0f} x {d_cm:.0f} cm, top
  {top_cm:.1f} cm above the floor), on its base flange, near the middle of one long edge.
- The robot base frame has its origin at the centre of the base flange, on the table top.
  x points forward across the table, y to the robot's left, z up. All positions and poses
  in the command interface are in this frame, in metres.
- The table top is the plane z = 0. It extends from x = {x0:.2f} m to x = {x1:.2f} m and
  from y = {y0:.2f} m to y = {y1:.2f} m. Beyond it is the floor, {top_cm:.1f} cm lower.

## Tool and payload settings

{tool}

## Cameras

Two RGB-D cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`:

- `overhead`: fixed above and in front of the robot, looking down at the table. Its pose
  is given in the robot base frame.
- `wrist`: on the hand. Its pose is given in the TCP frame (hand-eye calibration).

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## What's here

{items}
{others}
## Start state

At the start of a run the arm is at joint angles
`{ready}` (rad), {hand} pointing down, gripper open, not in a
protective stop.
"""


TOOL = {
    "franka": """- End effector: Franka Hand (0.73 kg), configured as the end effector in the controller.
- TCP: Franka's default for the Franka Hand: 103.4 mm along the flange z axis, rotated
  -45° about it (the flange-to-TCP transform in the Franka Hand manual, section 5.1). It is
  the centre point between the fingertips.
- Payload: none beyond the hand. The force/torque reading has the hand's weight removed.
- Tool orientation convention: the TCP's z axis points out of the hand, between the
  fingers; the fingers close along the TCP's y axis. A TCP pose of
  `[x, y, z, 3.14159, 0, 0]` points the hand straight down with the fingers closing
  along the base y axis.""",
    "ur5e": """- End effector: Robotiq 2F-85 two-finger gripper (85 mm stroke), on the tool flange.
- TCP: the point between the two finger pads.
- Payload: none beyond the gripper. The force/torque reading has the gripper's weight removed.
- Tool orientation convention: a TCP pose of `[x, y, z, 3.14159, 0, 0]` points the
  gripper straight down with the fingers closing along the base y axis.""",
}
HAND = {"franka": "hand", "ur5e": "tool"}

# An ALOHA: two arms facing each other across the middle of the table. Each arm's base, in
# the station's frame (table centre, x away from the operator's side): Menagerie's mounts.
ALOHA_BASES = {"left": (-0.019, 0.469, 0.02, -1), "right": (-0.019, -0.469, 0.02, 1)}

ALOHA_TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- ALOHA 2: two Trossen ViperX 300 S arms on {table} ({w_cm:.0f} x {d_cm:.0f} cm, top
  {top_cm:.1f} cm above the floor). The arms stand {gap_cm:.1f} cm apart, one at each side
  of the table's middle, facing each other. Seen from the operator's side of the table,
  `left` is on the left and `right` on the right.
- Each arm has its own base frame, with its origin at the centre of its base, 2 cm above the
  table top (the arm mounts). x points toward the other arm, y to the arm's own left, z up.
  Each arm's poses in the command interface are in its own base frame, in metres.
- In the left arm's frame the right arm's base is at ({gap:.3f}, 0, 0), turned half a turn;
  the same holds the other way round.
- The table top is the plane z = -0.02 in both frames. It extends from x = {x0:.2f} m to
  x = {x1:.2f} m in both frames, and from y = {y0:.2f} m to y = {y1:.2f} m in the left
  arm's frame ({ry0:.2f} m to {ry1:.2f} m in the right arm's). Beyond it is the floor,
  {top_cm:.1f} cm lower.

## Tool settings

- End effector: the ALOHA 2 parallel gripper on each arm: two fingers sliding on a rail,
  driven by one servo.
- TCP: between the fingertips. A TCP pose of `[x, y, z, 0, 1.5708, 0]` points the gripper
  straight down with the fingers closing along the base y axis; `[x, y, z, 0, 0, 0]`
  points it straight ahead along the base x axis.
- No force/torque sensing.

## Cameras

Four RGB-D cameras (Intel RealSense D405), 640 x 480, colour and depth (metres along the
camera's z axis). The calibration is in `cameras.json`, once for each arm (`left`,
`right`), in that arm's frames:

- `overhead`: fixed above the operator's side of the table, looking down at the middle.
  Its pose is given in the arm's base frame.
- `low`: fixed at the operator's edge of the table, low down, looking across it. Its pose
  is given in the arm's base frame.
- `wrist`: on that arm's gripper. Its pose is given in that arm's TCP frame (hand-eye
  calibration).

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## What's here

{items}
{others}
## Start state

At the start of a run both arms are at joint angles `{ready}` (rad), gripper open, not in
a protective stop.
"""
TABLES = {"table": "a heavy-duty packing table", "wetlab": "a stainless steel lab bench"}


def site_sheet(placed: list[W.Placed], station: W.Station | None = None,
               stations: list[W.Station] | None = None) -> str:
    """The sheet for one station's robot. Things on its table are listed as on the table;
    the rest of the lab is described only in outline."""
    from wetlabsim import scene as WS
    station = station or W.default_stations()[0]
    stations = stations or [station]
    sx, sy = station.footprint()
    top = station.top
    rx, ry = station.robot_xy
    P = WS.ROBOTS[station.robot]
    lines = []
    counts: dict[str, int] = {}
    for p in placed:
        if not station.holds(p.pos[0], p.pos[1]):
            continue
        counts[p.item] = counts.get(p.item, 0) + 1
    for item, n in counts.items():
        it, m = catalog.item(item), catalog.meta(item)
        w, d, h = (round(v * 100, 1) for v in m["size"])
        mass = f", about {m['mass'] * 1000:.0f} g" if m.get("mass") and m["mass"] < 5 else (
            f", about {m['mass']:.1f} kg" if m.get("mass") else "")
        soft = {"sheet": ", soft: a cloth that folds and drapes", "shell": ", soft: limp",
                "rope": ", soft: bends like a rope"}.get((it["soft"] or {}).get("kind"), "")
        lines.append(f"- {n} x {it['label'].lower()} ({w} x {d} x {h} cm{mass}{soft})")
    items = ("Things on this table (on the table top or on each other):\n\n"
             + "\n".join(lines)) if lines else "Nothing else is on the table."
    others = [s for s in stations if s.uid != station.uid]
    other = ""
    if others:
        names = ", ".join(f"a {WS.ROBOTS[s.robot]['name']}" for s in others)
        other = (f"\nThis room has {len(others)} other robot station(s) ({names}), each on its own table. "
                 "Other agents may be working at them at the same time. Your robot can only be "
                 "commanded through your own interface.\n")
    tw, td, _ = catalog.meta(station.table_item)["size"]
    if station.robot == "aloha":
        bx, by, bz, _ = ALOHA_BASES["left"]
        # The left arm's frame: x toward the right arm (station -y), y = station +x.
        x0, x1 = by - sy / 2, by + sy / 2
        y0, y1 = -sx / 2 - bx, sx / 2 - bx
        from wetlabsim import scene as WS2
        ready = WS2.aloha_side("left")["ready_q"]
        return ALOHA_TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                                     d_cm=min(tw, td) * 100, gap=2 * by, gap_cm=200 * by, x0=x0, x1=x1,
                                     y0=y0, y1=y1, ry0=-y1, ry1=-y0, items=items, others=other,
                                     ready="[" + ", ".join(f"{v:g}" for v in ready) + "]")
    return TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                           d_cm=min(tw, td) * 100, x0=-sx / 2 - rx, x1=sx / 2 - rx, y0=-sy / 2 - ry,
                           y1=sy / 2 - ry, items=items, others=other, robot_name=P["name"],
                           tool=TOOL[station.robot], hand=HAND[station.robot],
                           ready="[" + ", ".join(f"{v:g}" for v in P["ready_q"]) + "]")
