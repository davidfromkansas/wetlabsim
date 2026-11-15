# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- Comau N-220-2.7, bolted upright to the floor.
- The robot base frame has its origin at the centre of the base, on the floor. x points
  forward, y to the robot's left, z up. All positions and poses in the command interface are
  in this frame, in metres.
- The floor is the plane z = 0.

## Tool settings

- End effector: a vacuum lifting frame on the axis 6 flange: a steel frame with six rubber
  suction cups (150 mm across) in two rows of three, 360 mm apart along the tool's x and
  560 mm apart along its y. It weighs 32 kg.
- TCP: the middle of the plane of the cup faces, 300 mm from the flange.
- Tool orientation convention: the TCP's z axis points out of the cups. A TCP pose of
  `[x, y, z, 0, 3.14159, 0]` points the cups straight down with the frame's long side (three
  cups) along the base x axis; `[x, y, z, 0, 1.5708, 0]` points them straight ahead along the
  base x axis.
- A cup starts to pull about 10 mm from a surface.
- No force/torque sensing.

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
`[0, 0, -1.5708, 0, 1.5708, 0]` (rad), vacuum tool pointing down, vacuum off, not in a
protective stop.
