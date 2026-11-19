# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Unitree Z1, mounted upright on the table top, on its base.
- The robot base frame has its origin at the centre of the base, on the table top. x points
  forward over the table, y to the robot's left, z up. All positions and poses in the
  command interface are in this frame, in metres.
- The table top is the plane z = 0.

## Tool settings

- End effector: Z1 gripper, on the last joint's flange.
- TCP: on the wrist-roll (last joint) axis, 15 mm back from the tip of the fixed jaw.
- Tool orientation convention: the TCP's z axis points out of the gripper, between the
  fingers; the fingers close along the TCP's y axis. TCP poses of
  `[x, y, z, 3.14159, 0, 0]` and `[x, y, z, 0, 3.14159, 0]` both point the gripper straight
  down with the fingers closing along the base y axis.
- No force/torque sensing.

## Cameras

Two RGB-D cameras, 640 x 480, colour and depth (metres along the camera's z axis). The
calibration is in `cameras.json`:

- `overhead`: fixed above and in front of the robot, looking down at the table. Its pose
  is given in the robot base frame.
- `wrist`: on the gripper. Its pose is given in the TCP frame (hand-eye calibration).

Poses use OpenCV camera axes (x right, y down, z forward); `rotation` maps camera
coordinates into the named frame. The lenses have no distortion.

## Start state

At the start of a run the arm is at joint angles
`[0.0, 1.997, -1.71, 1.2838, -0.0, -1.5708]` (rad), gripper pointing down, gripper open, not in a
protective stop.
