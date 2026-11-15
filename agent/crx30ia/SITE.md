# Site sheet: this installation

What the datasheets can't tell you: how this particular robot is set up.

## Mounting

- FANUC CRX-30iA, bolted upright to the floor.
- The robot base frame has its origin at the centre of the base, on the floor. x points
  forward, y to the robot's left, z up. All positions and poses in the command interface are
  in this frame, in metres.
- The floor is the plane z = 0.

## Tool settings

- End effector: a vacuum gripper on the J6 flange: a light frame with four rubber suction
  cups (80 mm across) at the corners of a 400 x 260 mm rectangle (400 mm along the tool's x).
  It weighs 2.8 kg.
- TCP: the middle of the plane of the cup faces, 160 mm from the flange.
- Tool orientation convention: the TCP's z axis points out of the cups. A TCP pose of
  `[x, y, z, 0, 3.14159, 0]` points the cups straight down with the frame's long side along
  the base x axis; `[x, y, z, 0, 1.5708, 0]` points them straight ahead along the base x axis.
- A cup starts to pull about 10 mm from a surface.
- The arm's contact-stop and hand-guiding functions are not available here: no force/torque
  readings.

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
`[0.207, 0.2644, 0.8316, 0, -2.138, -0.207]` (rad), vacuum tool pointing down, vacuum off, not in a
protective stop.
