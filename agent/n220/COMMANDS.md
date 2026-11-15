# Command reference

The robot is controlled from Python through `wetlabsim.robot`, a client for the robot's
controller. It is the only Python package you can import for the robot.

```python
from wetlabsim.robot import Robot, RobotError
r = Robot()
```

The controller runs in real time and never pauses. The arm holds its last commanded
position until it gets a new command. Commands that fail raise `RobotError`.

Units: metres, radians, seconds. Poses are `[x, y, z, rx, ry, rz]` in the robot
base frame (see `SITE.md`): the TCP position plus its orientation as a rotation vector
(axis × angle, radians).

## Arm motion

| Call | Description |
| --- | --- |
| `r.move_l(pose, speed=0.25, wait=True)` | Move the TCP along a straight line to `pose`. `speed` in m/s, up to 2. Raises `RobotError` if the line is unreachable or the motion is stopped. |
| `r.move_j_pose(pose, speed=1.0, wait=True)` | Move to `pose` by interpolating joint angles. The TCP path is not straight. `speed` in rad/s. |
| `r.move_j(joints, speed=1.0, wait=True)` | Move to 6 joint angles (rad), J1 (base) to J6. `speed` in rad/s. Raises `RobotError` for targets outside the joint limits. |
| `r.stop()` | Stop the current motion. |
| `r.is_moving()` | True while a motion is running. |

With `wait=True` a move returns when the motion has finished; with `wait=False` it
returns at once. A new move replaces one that is still running. Motions are slowed down
where needed to stay within the joint speed and acceleration limits. The joints are
position-controlled servos: under load the TCP ends a few millimetres from the commanded pose.

## Protective stops

The controller stops the arm and refuses motion commands when the arm cannot follow its
commanded path (for example because it is blocked or overloaded). There is no force/torque reading.

| Call | Description |
| --- | --- |
| `r.is_protective_stopped()` | True while stopped. |
| `r.unlock_protective_stop()` | Clear the stop so the arm accepts commands again. |

`r.get_state()["protective_stop_reason"]` says why it stopped.

## Readings

| Call | Returns |
| --- | --- |
| `r.get_state()` | A dict with all of the below, plus `time` (controller clock, s), `mode` (`"running"` or `"protective_stop"`), `moving`, `joint_velocities`. |
| `r.get_joint_positions()` | 6 joint angles (rad), J1 (base) to J6. |
| `r.get_tcp_pose()` | Current TCP pose `[x, y, z, rx, ry, rz]`. |
| `r.get_time()` | Controller clock (s). |

## Vacuum tool

The tool has no fingers. It holds things by suction: 6 rubber suction cups on one vacuum
circuit. Put the cups flat on a surface, switch the vacuum on, and lift. The gripper calls
switch the vacuum:

| Call | Description |
| --- | --- |
| `r.gripper_close(force=255, wait=True)` | Vacuum on. Same as `gripper_move(255, force=force)`. |
| `r.gripper_open(wait=True)` | Vacuum off: lets go. Same as `gripper_move(0)`. |
| `r.gripper_move(position, speed=255, force=150, wait=True)` | Set the vacuum directly. Returns the tool's status. |
| `r.get_gripper_status()` | `position`, `requested`, `object_detected`, `status_code`, `moving`. |

Parameters, each on a 0 to 255 scale:

- `position`: 0 is vacuum off, 255 full vacuum. In between, the pull scales with it.
- `force`: the vacuum level, 0 = 20% to 255 = 100% of the rated pull. At 100% all 6 cups
  together hold up to about 6362 N (about 648 kg hanging straight down, before any safety
  margin). The pull is shared by the cups that are on the surface; cups that are not touching
  hold nothing.
- `speed` has no effect: the vacuum builds and vents in about a quarter of a second.

`position` in the status is the vacuum level now, on the same scale. `object_detected` is True
when the vacuum is on and at least one cup is on a surface (`status_code` 2); 3 means the vacuum
is at the requested level with nothing on the cups; 0 means it is still changing.

The cups only pull along their own axis (the TCP's z). A part held from above hangs from
them; held from the side, only the cups' friction keeps it from sliding.

## Cameras

| Call | Returns |
| --- | --- |
| `r.cameras()` | Camera names: `"overhead"`, `"wrist"`. |
| `r.get_camera_frame(name, depth=False)` | A `Frame` (below). |
| `r.get_camera_image(name)` | The colour image as a numpy array (H × W × 3, uint8). |
| `r.save_camera_image(name, path)` | Saves the colour image as a PNG. |

A `Frame` has:

- `rgb`: H × W × 3 uint8 image (640 × 480).
- `depth`: H × W float32, metres along the camera's z axis, or None if `depth=False`.
- `time`: controller clock when the image was taken.
- `intrinsics`: `fx`, `fy`, `cx`, `cy`, `width`, `height` (pixels).
- `camera_position`, `camera_rotation`: the camera's pose in the robot base frame at the
  moment the image was taken (OpenCV axes: x right, y down, z forward; the rotation maps
  camera coordinates into the base frame).
- `save(path)`: write the colour image as a PNG.

## Agent tools

Besides Python, these tools are available directly:

| Tool | Description |
| --- | --- |
| `look(camera)` | Shows you a camera image, with its calibration. |
| `robot_state()` | The same as `r.get_state()`. |
| `emergency_stop()` | Stops the arm at once. |

## Rules

- Use only this command interface, the agent tools and what the robot senses.
- The robot cell's own software and files are not available to you; don't look for them.
