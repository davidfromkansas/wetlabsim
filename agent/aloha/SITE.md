# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- ALOHA 2: two Trossen ViperX 300 S arms on a heavy-duty packing table (187 x 122 cm, top
  99.4 cm above the floor). The arms stand 93.8 cm apart, one at each side
  of the table's middle, facing each other. Seen from the operator's side of the table,
  `left` is on the left and `right` on the right.
- Each arm has its own base frame, with its origin at the centre of its base, 2 cm above the
  table top (the arm mounts). x points toward the other arm, y to the arm's own left, z up.
  Each arm's poses in the command interface are in its own base frame, in metres.
- In the left arm's frame the right arm's base is at (0.938, 0, 0), turned half a turn;
  the same holds the other way round.
- The table top is the plane z = -0.02 in both frames. It extends from x = -0.14 m to
  x = 1.08 m in both frames, and from y = -0.91 m to y = 0.95 m in the left
  arm's frame (-0.95 m to 0.91 m in the right arm's). Beyond it is the floor,
  99.4 cm lower.

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

Nothing else is on the table.

## Start state

At the start of a run both arms are at joint angles `[0, -0.96, 1.16, 0, -0.3, 0]` (rad), gripper open, not in
a protective stop.
