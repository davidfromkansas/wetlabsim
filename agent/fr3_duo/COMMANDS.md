# Command reference

The robot is controlled from Python through `wetlabsim.robot`, a client for the robot's
controller. It is the only Python package you can import for the robot.

The FR3 Duo has two arms. Each arm has its own client; both report in the same frame, the
FR3 Duo origin frame (see `SITE.md`):

```python
from wetlabsim.robot import Robot, RobotError
left = Robot(arm="left")
right = Robot(arm="right")
both = Robot()          # reads both arms, all three cameras, stops both; no motion commands
```

The controller runs in real time and never pauses. Each arm holds its last commanded
position until it gets a new command. Commands that fail raise `RobotError`. The two arms
move at the same time when you start a move on one with `wait=False` and then command the
other.

Units: metres, radians, seconds. Poses are `[x, y, z, rx, ry, rz]` in the FR3 Duo origin
frame: the TCP position plus its orientation as a rotation vector (axis × angle, radians).

## Arm motion (per arm)

| Call | Description |
| --- | --- |
| `a.move_l(pose, speed=0.25, wait=True)` | Move the TCP along a straight line to `pose`. `speed` in m/s. Raises `RobotError` if the line is unreachable or the motion is stopped. |
| `a.move_j_pose(pose, speed=1.0, wait=True)` | Move to `pose` by interpolating joint angles. The TCP path is not straight. `speed` in rad/s. |
| `a.move_j(joints, speed=1.0, wait=True)` | Move to 7 joint angles (rad), joint 1 (at the base) to joint 7 (at the flange). Raises `RobotError` for targets outside the joint limits. |
| `a.stop()` | Stop this arm's current motion. |
| `a.is_moving()` | True while a motion is running. |

With `wait=True` a move returns when the motion has finished; with `wait=False` it
returns at once. A new move replaces one that is still running on the same arm. Motions
are slowed down where needed to stay within the joint speed and acceleration limits.

## Protective stops

An arm stops and refuses motion commands when it cannot follow its commanded path (for
example because it is blocked).

| Call | Description |
| --- | --- |
| `a.is_protective_stopped()` | True while stopped. |
| `a.unlock_protective_stop()` | Clear the stop so the arm accepts commands again. |

`a.get_state()["protective_stop_reason"]` says why it stopped.

## Readings

| Call | Returns |
| --- | --- |
| `a.get_state()` | One arm: a dict with all of the below, plus `time` (controller clock, s), `mode` (`"running"` or `"protective_stop"`), `moving`, `joint_velocities`. |
| `both.get_state()` | `time`, `mode`, `moving`, and `"left"` and `"right"`: each arm's readings as above. |
| `a.get_joint_positions()` | 7 joint angles (rad), joint 1 to joint 7. |
| `a.get_tcp_pose()` | Current TCP pose `[x, y, z, rx, ry, rz]`. |
| `a.get_tcp_force()` | External force and torque at that arm's wrist `[Fx, Fy, Fz, Tx, Ty, Tz]` (N, Nm), at the flange, along the TCP frame's axes, with the gripper's and wrist camera's weight removed. Estimated from the joint torque sensors. |
| `a.zero_ft_sensor()` | Take that arm's current force/torque reading as zero. |
| `a.get_time()` | Controller clock (s). |

## Grippers (per arm)

| Call | Description |
| --- | --- |
| `a.gripper_move(position, speed=255, force=150, wait=True)` | Move the fingers. Returns the gripper status. |
| `a.gripper_open(wait=True)` | Same as `gripper_move(0)`. |
| `a.gripper_close(force=150, wait=True)` | Same as `gripper_move(255, force=force)`. |
| `a.get_gripper_status()` | `position`, `requested`, `object_detected`, `status_code`, `moving`. |

Parameters, each on a 0 to 255 scale, as on the Robotiq 2F-85:

- `position`: 0 is fully open (85 mm between the finger pads), 255 fully closed.
- `speed`: 0 is the gripper's slowest, 255 its fastest.
- `force`: 0 = 20 % to 255 = 100 % of the gripper's grip force.

`position` in the status is the measured finger position on the same scale.
`object_detected` is True when the fingers stopped on something before reaching the
requested position (`status_code` 2 while closing, 1 while opening; 3 means they reached
it; 0 means still moving).

## Cameras

Three cameras: `"head"` (fixed on the Duo's head), and one on each wrist. An arm's client
calls its own wrist camera `"wrist"`; the `both` client calls them `"left_wrist"` and
`"right_wrist"`.

| Call | Returns |
| --- | --- |
| `a.cameras()` | Camera names. |
| `a.get_camera_frame(name, depth=False)` | A `Frame` (below). |
| `a.get_camera_image(name)` | The colour image as a numpy array (H × W × 3, uint8). |
| `a.save_camera_image(name, path)` | Saves the colour image as a PNG. |

A `Frame` has:

- `rgb`: H × W × 3 uint8 image (640 × 480).
- `depth`: H × W float32, metres along the camera's z axis, or None if `depth=False`.
- `time`: controller clock when the image was taken.
- `intrinsics`: `fx`, `fy`, `cx`, `cy`, `width`, `height` (pixels).
- `camera_position`, `camera_rotation`: the camera's pose in the FR3 Duo origin frame, at
  the moment the image was taken (OpenCV axes: x right, y down, z forward; the rotation
  maps camera coordinates into that frame).
- `save(path)`: write the colour image as a PNG.

## Agent tools

Besides Python, these tools are available directly:

| Tool | Description |
| --- | --- |
| `look(camera)` | Shows you a camera image (`head`, `left_wrist`, `right_wrist`), with its calibration in the FR3 Duo origin frame. |
| `robot_state()` | The same as `both.get_state()`. |
| `emergency_stop()` | Stops both arms at once. |

## Rules

- Use only this command interface, the agent tools and what the robot senses.
- The robot cell's own software and files are not available to you; don't look for them.
