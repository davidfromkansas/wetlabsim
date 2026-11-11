"""The site sheet an agent gets in the playground: how its robot is installed here.

Like a real lab's site sheet it says how the robot is mounted and which cameras it has.
It says nothing about what is on the table or in the room: the agent finds that out with
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
TABLES = {"table": "a heavy-duty packing table", "wetlab": "a stainless steel lab bench"}


def site_sheet(placed: list[W.Placed], station: W.Station | None = None,
               stations: list[W.Station] | None = None) -> str:
    """The sheet for one station's robot. Nothing about the objects or the rest of the lab:
    the agent sees those with its cameras. `placed` and `stations` are kept for callers."""
    from wetlabsim import scene as WS
    station = station or W.default_stations()[0]
    sx, sy = station.footprint()
    top = station.top
    rx, ry = station.robot_xy
    P = WS.ROBOTS[station.robot]
    tw, td, _ = catalog.meta(station.table_item)["size"]
    return TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                           d_cm=min(tw, td) * 100, x0=-sx / 2 - rx, x1=sx / 2 - rx, y0=-sy / 2 - ry,
                           y1=sy / 2 - ry, robot_name=P["name"],
                           tool=TOOL[station.robot], hand=HAND[station.robot],
                           ready="[" + ", ".join(f"{v:g}" for v in P["ready_q"]) + "]")
