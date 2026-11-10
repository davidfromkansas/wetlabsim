# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Franka Emika Panda, mounted upright on the bench top, on its base flange.
- The robot base frame has its origin at the centre of the base flange, on the bench top.
  x points forward over the bench, y to the robot's left, z up. All positions and poses
  in the command interface are in this frame, in metres.
- The bench top is the plane z = 0. It extends from x = -0.2 m to x = 0.9 m and from
  y = -0.6 m to y = 0.6 m.

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

- `overhead`: fixed above and in front of the bench. Its pose is given in the robot base
  frame.
- `wrist`: on the hand. Its pose is given in the TCP frame (hand-eye calibration).

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## What's on the bench

Labels are as printed on the equipment. "Left" and "right" are as seen from the robot,
looking forward along x; the "front" row of a rack is the one nearest the robot.

- **Rack A and rack B:** two white two-tier tube racks, 205 x 96 x 60 mm, long side across
  the bench. Rack A is on the robot's right, rack B on its left. Each has 15 ml holes in
  3 rows x 6 columns on a 36 mm grid (18 mm holes) and, between them, 2 x 5 holes for 50 ml
  tubes (30 mm). A tube stands on the rack's bottom plate, 6 mm above the bench.
- **Small-tube rack:** a blue 60-well rack for 1.5 ml tubes, 197 x 72 x 21 mm. Wells are
  labelled rows A-E and columns 1-12; A1 is the corner at the far left (row A is the row
  farthest from the robot, column 1 the column on its left).
- **Tubes:** 15 ml conical tubes (17 mm wide, 123 mm tall with the cap), a 50 ml conical
  tube (29 mm wide, 120 mm tall) and 1.5 ml screw-cap tubes (11 mm wide, 45 mm tall). All
  have pointed bottoms and don't stand up on their own.
- **Petri dishes:** 100 mm dishes (89 mm across the base, 20 mm tall). Wider than the
  hand opens.
- **Pipette and pipette stand:** a single-channel pipette (about 19 cm long, with a finger
  hook at the top) and a stand with a 255 mm beam 20-26 cm above the bench. Pipettes hang
  on the front of the beam by their finger hooks.

## Start state

At the start of a run the arm is at joint angles
`[0, -0.5, 0, -2.3, 0, 1.8, 0.7854]` (rad), hand pointing down, gripper open, not in a
protective stop.
