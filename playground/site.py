"""The site sheet an agent gets in the playground: how its robot is installed here.

Like a real lab's site sheet it says how the robot is mounted and which cameras it has.
It says nothing about what is on the table or in the room: the agent finds that out with
its cameras.
"""
from __future__ import annotations

import math

from . import catalog
from . import world as W

TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- {robot_name}, {mounting}
- The robot base frame has its origin at the centre of the base flange, {origin_at}.
  x points forward{across}, y to the robot's left, z up. All positions and poses
  in the command interface are in this frame, in metres.
- {table_line}

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
    "piper": """- End effector: AgileX's two-finger gripper (70 mm stroke, rubber contact surfaces), on
  the J6 flange.
- TCP: the point between the two finger pads, 15 mm back from the fingertips.
- Tool orientation convention: the TCP's z axis points out of the gripper, between the
  fingers; the fingers close along the TCP's y axis. A TCP pose of
  `[x, y, z, 0, 3.14159, 0]` points the gripper straight down with the fingers closing
  along the base y axis; `[x, y, z, 0, 1.5708, 0]` points it straight ahead along the base
  x axis.
- No force/torque sensing.""",
    "n220": """- End effector: a vacuum lifting frame on the axis 6 flange: a steel frame with six rubber
  suction cups (150 mm across) in two rows of three, 360 mm apart along the tool's x and
  560 mm apart along its y. It weighs 32 kg.
- TCP: the middle of the plane of the cup faces, 300 mm from the flange.
- Tool orientation convention: the TCP's z axis points out of the cups. A TCP pose of
  `[x, y, z, 0, 3.14159, 0]` points the cups straight down with the frame's long side (three
  cups) along the base x axis; `[x, y, z, 0, 1.5708, 0]` points them straight ahead along the
  base x axis.
- A cup starts to pull about 10 mm from a surface.
- No force/torque sensing.""",
    "crx30ia": """- End effector: a vacuum gripper on the J6 flange: a light frame with four rubber suction
  cups (80 mm across) at the corners of a 400 x 260 mm rectangle (400 mm along the tool's x).
  It weighs 2.8 kg.
- TCP: the middle of the plane of the cup faces, 160 mm from the flange.
- Tool orientation convention: the TCP's z axis points out of the cups. A TCP pose of
  `[x, y, z, 0, 3.14159, 0]` points the cups straight down with the frame's long side along
  the base x axis; `[x, y, z, 0, 1.5708, 0]` points them straight ahead along the base x axis.
- A cup starts to pull about 10 mm from a surface.
- The arm's contact-stop and hand-guiding functions are not available here: no force/torque
  readings.""",
}
HAND = {"franka": "hand", "ur5e": "tool", "piper": "gripper", "n220": "vacuum tool", "crx30ia": "vacuum tool"}

# A big floor-standing arm (the Comau N-220, the FANUC CRX-30iA): on the floor, facing its
# table, pallet, conveyor or car body.
FLOOR_ARM_TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- {robot_name}, bolted upright to the floor.
- The robot base frame has its origin at the centre of the base, on the floor. x points
  forward, y to the robot's left, z up. All positions and poses in the command interface are
  in this frame, in metres.
- The floor is the plane z = 0.
- {table_line}

## Tool settings

{tool}

## Cameras

Two RGB-D cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`:

- `overhead`: fixed high above the robot's work area, looking straight down. Its pose is given
  in the robot base frame.
- `wrist`: on the tool, under its frame between the cups, looking the way the cups face. Its
  pose is given in the TCP frame (hand-eye calibration).

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## Start state

At the start of a run the arm is at joint angles
`{ready}` (rad), {hand} pointing down, vacuum off, not in a
protective stop.
"""

# An ALOHA: two arms facing each other across the middle of the table. Each arm's base, in
# the station's frame (table centre, x away from the operator's side): Menagerie's mounts.
ALOHA_BASES = {"left": (-0.019, 0.469, 0.02, -1), "right": (-0.019, -0.469, 0.02, 1)}

ALOHA_TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- ALOHA 2: two Trossen ViperX 300 S arms {mounting} The arms stand {gap_cm:.1f} cm apart,{where}
  facing each other. Seen from the operator's side of the table,
  `left` is on the left and `right` on the right.
- Each arm has its own base frame, with its origin at the centre of its base, 2 cm above
  {origin_at}. x points toward the other arm, y to the arm's own left, z up.
  Each arm's poses in the command interface are in its own base frame, in metres.
- In the left arm's frame the right arm's base is at ({gap:.3f}, 0, 0), turned half a turn;
  the same holds the other way round.
- {table_line}

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
  (`left` and `right`) on the FR3 Duo mount, standing on a riser block {mounting}
  The FR3 Duo origin is {origin_cm:.0f} mm above {origin_at}, as in Franka's reference
  setup. Seen from behind the robot, `left` is on the left and `right` on the right.
- Both arms report in one frame, the FR3 Duo origin frame: origin at the FR3 Duo origin,
  x forward{across}, y to the robot's left, z up. All positions and poses in the
  command interface, for both arms, are in this frame, in metres. (Each arm's own base is
  mounted tilted on the Duo mount, as in Franka's reference kinematics.)
- {table_line}

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
  and `right`). It is not mounted: it stands on its own feet on the floor, {facing} ({w_cm:.0f} x {d_cm:.0f} cm, top {top_cm:.1f} cm above the floor), balancing
  under its whole-body controller (NVIDIA's GEAR-SONIC, see `COMMANDS.md`).
- Both arms report in one frame, the pelvis frame: origin at the pelvis (about {pelvis_cm:.0f} cm
  above the floor when standing), x forward, y to the robot's left, z up. All positions and
  poses in the command interface, for both arms, are in this frame, in metres. The frame
  moves with the robot: after it walks, turns, kneels or crawls, the table is somewhere
  else in it.
- {table_line}
  Check with the cameras: the robot settles a few centimetres as it starts balancing.
- The hands work best from about x = 0.30 m to 0.45 m (about 20 to 35 cm past the table's edge),
  pointing forward or tilted down. Closer to the chest the arms run out of room, and
  straight-down (top) grasps are mostly out of reach. To work further away, walk closer.
- The robot and its table are in a room of their own, 5 x 5 m, centred on the table, with
  solid walls about {room_h:.1f} m high. It can walk anywhere in the room; the walls stop it.

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
RBY1_TEMPLATE = """# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Rainbow Robotics RB-Y1 (model A): two 7-joint arms (`left` and `right`), each with the
  standard two-finger gripper, on a 6-joint torso with a 2-joint pan-tilt head, on a
  two-wheeled mobile base. It is not mounted: it stands on its wheels on the floor, {facing}
  ({w_cm:.0f} x {d_cm:.0f} cm, top {top_cm:.1f} cm above the floor).
  Nothing balances it for you and nothing moves on its own: the wheels, torso, head and each
  arm do what you command and hold still otherwise.
- Both arms report in one frame, the base frame (Rainbow's `base` link): origin on the floor
  under the middle of the mobile base, x forward, y to the robot's left, z up. All positions
  and poses in the command interface, for both arms, are in this frame, in metres. The frame
  moves with the robot when it drives or turns: after that, the table is somewhere else in it.
  Moving the torso doesn't move the frame, but it moves the arms' shoulders (and so the grippers).
- {table_line}
- With the torso upright the grippers reach best from about x = 0.40 m to 0.65 m, pointing
  forward or tilted down; straight-down (top) grasps over the table need the torso bent forward.

## Tool and payload settings

- End effector: Rainbow's standard gripper on each wrist: two fingers that slide apart, 6 mm
  apart when closed and 106 mm when open.
- TCP: a point between the fingertips, 245 mm from the last arm joint.
- Tool orientation convention: a TCP pose of `[x, y, z, 0, 0, 0]` points the fingers straight
  down (along -z), with the fingers opening along x. Tilting the fingers forward is a
  rotation about -y (for example `[x, y, z, 0, -0.5, 0]`).
- Payload: none beyond the gripper. Each wrist has a force/torque sensor between the arm and
  the gripper; its readings have the gripper's weight removed.

## Cameras

Three cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`, once for each arm (`left`, `right`):

- `head`: an Intel RealSense D435 on the head's pan-tilt mount, looking where the head points.
  Its pose is given in the base frame with the head and torso as at the start; it moves with
  the head and the torso.
- `wrist`: a RealSense D405 on each gripper, looking along the fingers. Its pose is given in
  that arm's TCP frame. The robot's command interface names them `left_wrist` and `right_wrist`.

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## Start state

At the start of a run the robot stands still with the torso upright (all six torso joints at
0), the head level and facing forward (pan 0, tilt 0), the left arm at joint angles
`{ready_l}` and the right arm at `{ready_r}` (rad): elbows bent, grippers open and pointing
forward and down, above the table and past its edge. Nothing is in a protective stop.
"""
TABLES = {"table": "a heavy-duty packing table", "wetlab": "a stainless steel lab bench",
          "pallet": "a wooden pallet on the floor", "car": "a car body on stands, side on to the robot",
          "conveyor": "a roller conveyor section", "workbench": "a steel workbench",
          "island": "a kitchen island's worktop",
          "counter": "a kitchen counter's worktop",
          "wetrobo_x": "a stainless steel lab bench", "wetrobo_y": "a heavy-duty packing table"}


def _fmt(v: float) -> str:
    return f"{v:.2f}"


def table_extent(station: W.Station, origin, yaw: float, about: bool = False) -> str:
    """Where the station's table top lies in a frame with its origin at origin (station frame
    x, y) turned yaw from the station's: "it extends from x = .. m to x = .. m and from y = .. m
    to y = .. m" while the frame is square to the table, else its four corners."""
    sx, sy = station.footprint()
    c, s_ = math.cos(yaw), math.sin(yaw)
    pts = []
    for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        dx, dy = a * sx / 2 - origin[0], b * sy / 2 - origin[1]
        pts.append((c * dx + s_ * dy, -s_ * dx + c * dy))
    ab = "about " if about else ""
    q = (yaw / (math.pi / 2)) % 1.0
    if min(q, 1 - q) < 1e-3:              # square to the table
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (f"it extends from {ab}x = {_fmt(min(xs))} m to x = {_fmt(max(xs))} m and from {ab}y = "
                f"{_fmt(min(ys))} m to y = {_fmt(max(ys))} m")
    return ("it lies at an angle in this frame, with its corners at " + ab + "(x, y) = "
            + ", ".join(f"({_fmt(x)}, {_fmt(y)})" for x, y in pts[:3]) + f" and ({_fmt(pts[3][0])}, {_fmt(pts[3][1])}) m")


def _mount_words(station: W.Station, table_txt: str, plural: bool = False) -> str:
    """What a moved table arm stands on: its table, a riser on it, or a stand on the floor."""
    stands = station.stands()
    h = 100 * (stands[0][4] - stands[0][3]) if stands else 0.0
    a = "two steel stands" if plural else "a steel stand"
    if station.robot_side() != "on":
        return f"on {a} {h:.1f} cm tall on the floor, beside {table_txt}."
    if stands:
        r = "two steel risers" if plural else "a steel riser"
        return f"on {r} {h:.1f} cm tall on {table_txt}."
    return f"on {table_txt}."


def site_sheet(placed: list[W.Placed], station: W.Station | None = None,
               stations: list[W.Station] | None = None) -> str:
    """The sheet for one station's robot. Nothing about the objects or the rest of the lab:
    the agent sees those with its cameras. `placed` and `stations` are kept for callers.
    A robot the user has moved, turned or raised apart from its table (Station.moved) gets
    the same sheet with its table worked out from where it is now."""
    text = _site_sheet(station or W.default_stations()[0])
    return text


def _site_sheet(station: W.Station) -> str:
    from wetlabsim import scene as WS
    sx, sy = station.footprint()
    top = station.top
    rx, ry = station.robot_xy
    turn = station.robot_turn
    moved = station.moved
    mz = station.mount_z
    P = WS.ROBOTS[station.robot]
    tw, td, _ = catalog.meta(station.table_item)["size"]
    table = TABLES[station.kind]
    table_txt = f"{table} ({max(tw, td) * 100:.0f} x {min(tw, td) * 100:.0f} cm, top {top * 100:.1f} cm above the floor)"
    common = dict(top_cm=top * 100, table=table, w_cm=max(tw, td) * 100, d_cm=min(tw, td) * 100)
    ext = lambda origin, yaw, about=False: table_extent(station, origin, yaw, about)
    floor_line = (f"Beyond it is the floor, {top * 100:.1f} cm lower." if not moved
                  else f"The floor is the plane z = {_fmt(-mz)}.")
    if station.robot == "aloha":
        bz = ALOHA_BASES["left"][2]
        bx, by = ALOHA_BASES["left"][:2]
        el = ext(station.from_robot(bx, by), turn - math.pi / 2)
        er = ext(station.from_robot(bx, -by), turn + math.pi / 2)
        tz = top - (mz + bz)
        ready = WS.aloha_side("left")["ready_q"]
        if not moved:
            el = el.replace(" and from y", " in both frames, and from y", 1) + " in the left arm's frame"
            ry0, ry1 = er.split("from y = ")[1].split(" m to y = ")
            line = (f"The table top is the plane z = {_fmt(tz)} in both frames. {el[0].upper()}{el[1:]} "
                    f"({ry0} m to {ry1.rstrip(' m')} m in the right arm's). {floor_line}")
        else:
            line = (f"The table top is the plane z = {_fmt(tz)} in both frames. In the left arm's frame {el}; "
                    f"in the right arm's frame {er}. {floor_line}")
        return ALOHA_TEMPLATE.format(**common, gap=2 * by, gap_cm=200 * by,
                                     mounting=f"on {table_txt}." if not moved else _mount_words(station, table_txt, True),
                                     where=" one at each side of the table's middle," if not moved else "",
                                     origin_at="the table top (the arm mounts)" if not moved else "its mount",
                                     table_line=line, ready="[" + ", ".join(f"{v:g}" for v in ready) + "]")
    if station.robot in ("g1", "rby1"):
        fmt = lambda q: "[" + ", ".join(f"{v:.4g}" if station.robot == "rby1" else f"{v:g}" for v in q) + "]"
        if station.robot == "g1":
            h = WS.G1_STANDING_HEIGHT
            origin = station.from_robot(WS.G1_SETTLE, 0.0)   # after the robot settles forward a little
            tz, zt = top - h, "about z = "
        else:
            h, origin, tz, zt = 0.0, station.robot_xy, top, "z = "
        e = ext(origin, turn, about=True)
        if not moved:
            x0 = e.split("x = ")[1].split(" m")[0]
            rest = e.split(" m to x = ", 1)[1]
            if station.robot == "g1":
                line = (f"At the start the table's near edge is about x = {x0} m, its top is about z = {_fmt(tz)} m,\n"
                        f"  and it extends to about x = {rest}.")
            else:
                line = (f"At the start the table's near edge is at about x = {x0} m, its top at z = {tz:.3f} m, and it\n"
                        f"  extends to about x = {rest}. The front of the\n"
                        f"  base is about 6 cm from the table's edge: don't drive forward into the table.")
        else:
            line = f"At the start the table top is at {zt}{_fmt(tz) if station.robot == 'g1' else f'{tz:.3f}'} m and {e}."
        facing = (f"facing the middle of one\n  edge of {table}" if station.robot == "g1" else f"facing the\n  middle of one edge of {table}") \
            if not moved else f"near {table}"
        if station.robot == "g1":
            return G1_TEMPLATE.format(**common, pelvis_cm=h * 100, facing=facing, table_line=line,
                                      ready_l=fmt(WS.G1_READY["left"]), ready_r=fmt(WS.G1_READY["right"]),
                                      room_h=station.work_box()[2])
        return RBY1_TEMPLATE.format(**common, facing=facing, table_line=line,
                                    ready_l=fmt(WS.RBY1_READY["left"]), ready_r=fmt(WS.RBY1_READY["right"]))
    if station.robot == "fr3_duo":
        h = WS.FR3_DUO_ORIGIN_HEIGHT
        fmt = lambda q: "[" + ", ".join(f"{v:g}" for v in q) + "]"
        e = ext(station.robot_xy, turn)
        line = f"The table top is the plane z = {_fmt(top - mz - h)}. {e[0].upper()}{e[1:]}. {floor_line}"
        return FR3_DUO_TEMPLATE.format(**common, origin_cm=h * 1000, table_line=line,
                                       mounting=(f"near the middle of one\n  long edge of {table_txt}." if not moved
                                                 else "that stands " + _mount_words(station, table_txt)),
                                       origin_at="the table top" if not moved else f"its mount ({mz * 100:.1f} cm above the floor)",
                                       across=" across the table" if not moved else "",
                                       ready_l=fmt(WS.FR3_DUO_READY["left"]), ready_r=fmt(WS.FR3_DUO_READY["right"]))
    e = ext(station.robot_xy, turn)
    if station.floor_arm:
        line = (f"In front of the robot stands {table_txt}. {e[0].upper()}{e[1:]}." if not moved
                else f"Near the robot stands {table_txt}. {e[0].upper()}{e[1:]}.")
        return FLOOR_ARM_TEMPLATE.format(
            **common, table_line=line, robot_name=P["name"], tool=TOOL[station.robot], hand=HAND[station.robot],
            ready="[" + ", ".join(f"{v:g}" for v in P["ready_q"]) + "]")
    line = (f"The table top is the plane z = {'0' if not moved else _fmt(top - mz)}. {e[0].upper()}{e[1:]}. {floor_line}")
    return TEMPLATE.format(**common, robot_name=P["name"],
                           mounting=(f"mounted upright on {table_txt}, on its base flange, near the middle of one long edge."
                                     if not moved else "mounted upright on its base flange, " + _mount_words(station, table_txt)),
                           origin_at="on the table top" if not moved else f"{mz * 100:.1f} cm above the floor",
                           across=" across the table" if not moved else "",
                           table_line=line, tool=TOOL[station.robot], hand=HAND[station.robot],
                           ready="[" + ", ".join(f"{v:g}" for v in P["ready_q"]) + "]")
