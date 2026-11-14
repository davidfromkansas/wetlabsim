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

## Start state

At the start of a run both arms are at joint angles `{ready}` (rad), gripper open, not in
a protective stop.
"""
FR3_DUO_TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Franka FR3 Duo with the FR3 Duo Vision & Manipulation Kit: two Franka Research 3 arms
  (`left` and `right`) on the FR3 Duo mount, standing on a riser block near the middle of one
  long edge of {table} ({w_cm:.0f} x {d_cm:.0f} cm, top {top_cm:.1f} cm above the floor).
  The FR3 Duo origin is {origin_cm:.0f} mm above the table top, as in Franka's reference
  setup. Seen from behind the robot, `left` is on the left and `right` on the right.
- Both arms report in one frame, the FR3 Duo origin frame: origin at the FR3 Duo origin,
  x forward across the table, y to the robot's left, z up. All positions and poses in the
  command interface, for both arms, are in this frame, in metres. (Each arm's own base is
  mounted tilted on the Duo mount, as in Franka's reference kinematics.)
- The table top is the plane z = {table_z:.2f}. It extends from x = {x0:.2f} m to x = {x1:.2f} m
  and from y = {y0:.2f} m to y = {y1:.2f} m. Beyond it is the floor, {top_cm:.1f} cm lower.

## Tool and payload settings

- End effector: a Robotiq 2F-85 two-finger gripper (85 mm stroke) on each arm, with an
  Intel RealSense D405 wrist camera on its mount between the flange and the gripper.
- TCP: the point between the two finger pads.
- Payload: the gripper and wrist camera. Each arm's force/torque reading (estimated by the
  FR3 from its joint torque sensors) is at its flange, with that load's weight removed.
- Tool orientation convention: a TCP pose of `[x, y, z, 3.14159, 0, 0]` points the
  gripper straight down with the fingers closing along the frame's y axis.

## Cameras

Three cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`, once for each arm (`left`, `right`):

- `head`: the Stereolabs ZED Mini on the Duo's head (its left eye), looking forward and
  down at the table. Its pose is given in the FR3 Duo origin frame.
- `wrist`: that arm's D405, on its gripper. Its pose is given in that arm's TCP frame
  (hand-eye calibration). The robot's command interface names them `left_wrist` and
  `right_wrist`.

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## Start state

At the start of a run the left arm is at joint angles `{ready_l}` and the right arm at
`{ready_r}` (rad): both grippers pointing down, open, not in a protective stop.
"""
G1_TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Unitree G1 humanoid (29 body joints) with a Dex3-1 three-finger hand on each arm (`left`
  and `right`). It is not mounted: it stands on its own feet on the floor, facing the middle of one
  edge of {table} ({w_cm:.0f} x {d_cm:.0f} cm, top {top_cm:.1f} cm above the floor), balancing
  under its locomotion controller.
- Both arms report in one frame, the pelvis frame: origin at the pelvis (about {pelvis_cm:.0f} cm
  above the floor when standing), x forward, y to the robot's left, z up. All positions and
  poses in the command interface, for both arms, are in this frame, in metres. The frame
  moves with the robot: after it walks, turns, crouches or leans, the table is somewhere
  else in it.
- At the start the table's near edge is about x = {x0:.2f} m, its top is about z = {table_z:.2f} m,
  and it extends to about x = {x1:.2f} m and from about y = {y0:.2f} m to y = {y1:.2f} m.
  Check with the cameras: the robot settles a few centimetres as it starts balancing.
- The hands work best from about x = 0.30 m to 0.45 m (10 to 25 cm past the table's edge),
  pointing forward or tilted down. Closer to the chest the arms run out of room, and
  straight-down (top) grasps are mostly out of reach. To work further away, walk closer.

## Tool and payload settings

- End effector: a Unitree Dex3-1 hand on each wrist (thumb with 3 joints, index and middle
  fingers with 2 each), with 33 tactile sensors.
- TCP: a point between the fingertips of the open hand, 125 mm from the wrist.
- Tool orientation convention: a TCP pose of `[x, y, z, 0, 0, 0]` points the fingers forward
  (along x) with the palm facing the robot's middle (the left palm faces -y, the right +y);
  the fingers close toward the palm, so an upright object is gripped from the side.
- Payload: each arm's joint torques are reported with the arm's own weight held by the
  controller.

## Cameras

Three cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`, once for each arm (`left`, `right`):

- `head`: the Intel RealSense D435i in the head, looking forward and down. Its pose is
  given in the pelvis frame, standing upright as at the start (it is on the torso, so it
  moves when the torso leans).
- `wrist`: a camera on each wrist, looking along the hand. Its pose is given in that arm's
  TCP frame. The robot's command interface names them `left_wrist` and `right_wrist`.

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

The robot also has a Livox Mid-360 lidar in its head, mounted upside down so it looks from
7° above level to 52° below (a point cloud, see COMMANDS.md); it also sees the robot's own
arms and body.

## Start state

At the start of a run the robot stands still, the left arm is at joint angles `{ready_l}`
and the right arm at `{ready_r}` (rad): forearms raised in front of the chest, hands open,
above the table top and behind its edge. Nothing is in a protective stop.
"""
TABLES = {"table": "a heavy-duty packing table", "wetlab": "a stainless steel lab bench",
          "island": "a kitchen island's worktop",
          "counter": "a kitchen counter's worktop"}


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
    if station.robot == "aloha":
        bx, by, bz, _ = ALOHA_BASES["left"]
        # The left arm's frame: x toward the right arm (station -y), y = station +x.
        x0, x1 = by - sy / 2, by + sy / 2
        y0, y1 = -sx / 2 - bx, sx / 2 - bx
        ready = WS.aloha_side("left")["ready_q"]
        return ALOHA_TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                                     d_cm=min(tw, td) * 100, gap=2 * by, gap_cm=200 * by, x0=x0, x1=x1,
                                     y0=y0, y1=y1, ry0=-y1, ry1=-y0,
                                     ready="[" + ", ".join(f"{v:g}" for v in ready) + "]")
    if station.robot == "g1":
        fmt = lambda q: "[" + ", ".join(f"{v:g}" for v in q) + "]"
        h = WS.G1_STANDING_HEIGHT
        e = W.HUMANOID_GAP + 0.07           # the edge, after the robot settles back a little
        return G1_TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                                  d_cm=min(tw, td) * 100, pelvis_cm=h * 100, table_z=top - h,
                                  x0=e, x1=e + sx, y0=-sy / 2 - ry, y1=sy / 2 - ry,
                                  ready_l=fmt(WS.G1_READY["left"]), ready_r=fmt(WS.G1_READY["right"]))
    if station.robot == "fr3_duo":
        h = WS.FR3_DUO_ORIGIN_HEIGHT
        fmt = lambda q: "[" + ", ".join(f"{v:g}" for v in q) + "]"
        return FR3_DUO_TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                                       d_cm=min(tw, td) * 100, origin_cm=h * 1000, table_z=-h,
                                       x0=-sx / 2 - rx, x1=sx / 2 - rx, y0=-sy / 2 - ry, y1=sy / 2 - ry,
                                       ready_l=fmt(WS.FR3_DUO_READY["left"]), ready_r=fmt(WS.FR3_DUO_READY["right"]))
    return TEMPLATE.format(top_cm=top * 100, table=TABLES[station.kind], w_cm=max(tw, td) * 100,
                           d_cm=min(tw, td) * 100, x0=-sx / 2 - rx, x1=sx / 2 - rx, y0=-sy / 2 - ry,
                           y1=sy / 2 - ry, robot_name=P["name"],
                           tool=TOOL[station.robot], hand=HAND[station.robot],
                           ready="[" + ", ".join(f"{v:g}" for v in P["ready_q"]) + "]")
