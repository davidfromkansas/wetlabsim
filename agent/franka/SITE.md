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

## Start state

At the start of a run the arm is at joint angles
`[0, -0.5, 0, -2.3, 0, 1.8, 0.7854]` (rad), hand pointing down, gripper open, not in a
protective stop.
