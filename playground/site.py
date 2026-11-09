"""The site sheet an agent gets in the playground: how the Franka is installed here.

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

- Franka Emika Panda, mounted upright on a heavy-duty packing table (187 x 122 cm, top
  {top_cm:.1f} cm above the floor), on its base flange, near the middle of one long edge.
- The robot base frame has its origin at the centre of the base flange, on the table top.
  x points forward across the table, y to the robot's left, z up. All positions and poses
  in the command interface are in this frame, in metres.
- The table top is the plane z = 0. It extends from x = {x0:.2f} m to x = {x1:.2f} m and
  from y = {y0:.2f} m to y = {y1:.2f} m. Beyond it is the floor, {top_cm:.1f} cm lower.

## Tool and payload settings

- End effector: Franka Hand (0.73 kg), configured as the end effector in the controller.
- TCP: Franka's default for the Franka Hand: 103.4 mm along the flange z axis, rotated
  -45° about it (the flange-to-TCP transform in the Franka Hand manual, section 5.1). It is
  the centre point between the fingertips.
- Payload: none beyond the hand. The force/torque reading has the hand's weight removed.
- Tool orientation convention: the TCP's z axis points out of the hand, between the
  fingers; the fingers close along the TCP's y axis. A TCP pose of
  `[x, y, z, 3.14159, 0, 0]` points the hand straight down with the fingers closing
  along the base y axis.

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

## Start state

At the start of a run the arm is at joint angles
`[0, -0.5, 0, -2.3, 0, 1.8, 0.7854]` (rad), hand pointing down, gripper open, not in a
protective stop.
"""


def site_sheet(placed: list[W.Placed]) -> str:
    tm = catalog.meta(catalog.DEFAULT_TABLE)
    sx, sy, top = tm["size"]
    rx, ry = W.ROBOT_XY
    lines = []
    counts: dict[str, int] = {}
    for p in placed:
        if p.uid == W.TABLE_UID:
            continue
        counts[p.item] = counts.get(p.item, 0) + 1
    for item, n in counts.items():
        it, m = catalog.item(item), catalog.meta(item)
        w, d, h = (round(v * 100, 1) for v in m["size"])
        mass = f", about {m['mass'] * 1000:.0f} g" if m.get("mass") and m["mass"] < 5 else (
            f", about {m['mass']:.1f} kg" if m.get("mass") else "")
        lines.append(f"- {n} x {it['label'].lower()} ({w} x {d} x {h} cm{mass})")
    items = ("Things placed in the scene (on the table, on the floor, or on each other):\n\n"
             + "\n".join(lines)) if lines else "Nothing else is on the table."
    return TEMPLATE.format(top_cm=top * 100, x0=-sx / 2 - rx, x1=sx / 2 - rx, y0=-sy / 2 - ry,
                           y1=sy / 2 - ry, items=items)
