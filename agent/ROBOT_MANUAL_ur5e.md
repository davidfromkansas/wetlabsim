# Robot cell manual

You are operating a real-time robot cell in a wet lab: a **Universal Robots UR5e**
arm with a **Robotiq 2F-85** two-finger gripper, mounted on a lab bench. Treat it
exactly like real hardware:

- **Time never stops.** The physics keeps running while you think. The arm holds
  its last commanded position until you send a new command.
- **You only know what the robot can sense.** Nobody will tell you where objects
  are. Use the cameras (and depth) to find them, and the gripper and wrist force
  readings to check what happened.
- **Collisions are real.** Hitting the bench, a rack or a tube hard triggers a
  *protective stop*. Call `unlock_protective_stop()` before moving again.
- Objects can slip, tip over or be knocked out of place.
- **Only the robot API.** On a real robot there is no simulator code to read. Don't look
  for, open or import the cell's own software or model files; use `wetlabsim.robot`,
  the agent tools and what you sense.

## How to control the robot

Write and run Python that uses the robot API:

```python
from wetlabsim.robot import Robot
r = Robot()
```

You can also call these agent tools directly: `look` (see a camera image),
`robot_state`, and `emergency_stop`.

### Coordinates

Metres, in the **robot base frame**: x points forward over the bench, y to the
robot's left, z up. **The bench top is z = 0.** Tool poses are
`[x, y, z, rx, ry, rz]`, where `(rx, ry, rz)` is a rotation vector (axis × angle in
radians), the Universal Robots convention. `[x, y, z, 3.14159, 0, 0]` points the
gripper straight down. The fingers then close along the y axis. Rotating about the
tool's own axis (for example `rz` changes) turns the finger direction.

The tool centre point (TCP) is the point between the two finger pads.

### Arm

| Call | What it does |
| --- | --- |
| `r.move_l(pose, speed=0.25)` | Straight-line tool move (m/s, max 1.0). Blocks until done. Raises `RobotError` if unreachable or stopped. |
| `r.move_j_pose(pose, speed=1.0)` | Faster joint-space move to a pose. The path curves, so only use it with a clear path. |
| `r.move_j(joints, speed=1.0)` | Move to six joint angles (rad). |
| `r.stop()` | Stop now. |
| `r.unlock_protective_stop()` | Clear a protective stop. |
| `wait=False` (any move) | Return immediately; poll `r.is_moving()`. |

### Readings

| Call | Returns |
| --- | --- |
| `r.get_state()` | Everything below, plus the controller clock. |
| `r.get_tcp_pose()` | Current tool pose. |
| `r.get_joint_positions()` | Six joint angles. |
| `r.get_tcp_force()` | Wrist force/torque `[Fx, Fy, Fz, Tx, Ty, Tz]` (N, Nm), gripper weight removed. About 0.3 N of noise. |
| `r.zero_ft_sensor()` | Tare the force sensor. |
| `r.get_gripper_status()` | `position` (0 open to 255 closed), `object_detected`, `moving`. |

### Gripper

`r.gripper_move(position, speed=255, force=150)`. Position 0 is fully open (85 mm)
and 255 is fully closed. The opening is roughly `85 mm × (1 − position/255)`.
`object_detected` is True when the fingers stopped on something before reaching
the requested position. Opening fully next to other objects can hit them, so open
only as wide as you need.

### Cameras

| Camera | Where |
| --- | --- |
| `overhead` | Fixed above and in front of the bench, looking down at the work area. |
| `wrist` | On the gripper, looking along the fingers. |

```python
f = r.get_camera_frame("overhead", depth=True)   # f.rgb (H x W x 3), f.depth (metres)
f.save("overhead.png")                           # look at it with your image viewer
p = f.pixel_to_point(u, v)                       # 3D point (base frame) at pixel (u, v)
u, v = f.point_to_pixel([x, y, z])               # where a 3D point appears in the image
```

Images are 640 × 480. Depth is distance along the camera's viewing axis.
Cameras are calibrated: `f.camera_position` and `f.camera_rotation` give the
camera pose in the base frame (OpenCV axes: x right, y down, z forward).

## Equipment specs (from the catalogue)

- **Tubes:** 15 ml conical tubes with a pointed bottom, about 17 mm wide and 12.3 cm
  tall with the coloured screw cap on (cap about 23 mm wide, 10 mm tall). Empty, about
  6.5 g. They don't stand up on their own.
- **Racks:** white two-tier centrifuge-tube racks, 205 x 96 mm, 60 mm tall. The top
  plate has 15 ml holes in 3 rows x 6 columns on a 36 mm grid, with bigger 50 ml holes
  between them (2 x 5). A tube stands in a hole on the bottom plate.
- **Other items on the bench:** a blue 60-well rack with two 1.5 ml tubes, a 50 ml
  tube with an orange cap, and a 100 mm petri dish.
- **Gripper:** Robotiq 2F-85, 85 mm maximum opening.

## Good practice

- Look before you move, and look again after each step to check it worked.
- Approach from above, then move down slowly (0.05 to 0.1 m/s) near objects.
- Grip tubes on the body, below the cap and above the rack's top plate.
- After grasping, check `object_detected` and the wrist force before lifting far.
