# Command reference

The robot is controlled from Python through `wetlabsim.robot`, a client for the robot's
controller. It is the only Python package you can import for the robot.

The G1 has two arms, each with a Dex3-1 hand, on a body that balances and walks by itself.
Each arm has its own client; the whole robot has one more. All of them report in the same
frame, the pelvis frame (see `SITE.md`):

```python
from wetlabsim.robot import Robot, RobotError
left = Robot(arm="left")
right = Robot(arm="right")
body = Robot()          # the whole robot: walking, body pose, lidar, all three cameras,
                        # reads both arms, stops everything; no arm motion commands
```

The controller runs in real time and never pauses. Each arm and hand holds its last
commanded position until it gets a new command; the legs keep the robot balanced on their
own. Commands that fail raise `RobotError`. The two arms move at the same time when you
start a move on one with `wait=False` and then command the other.

Units: metres, radians, seconds. Poses are `[x, y, z, rx, ry, rz]` in the pelvis frame:
the TCP position plus its orientation as a rotation vector (axis × angle, radians). The
pelvis frame moves with the robot when it walks, turns, crouches or leans.

## Arm motion (per arm)

| Call | Description |
| --- | --- |
| `a.move_l(pose, speed=0.25, wait=True)` | Move the TCP along a straight line to `pose`. `speed` in m/s. Raises `RobotError` if the line is unreachable or the motion is stopped. |
| `a.move_j_pose(pose, speed=1.0, wait=True)` | Move to `pose` by interpolating joint angles. The TCP path is not straight. `speed` in rad/s. |
| `a.move_j(joints, speed=1.0, wait=True)` | Move to 7 joint angles (rad): shoulder pitch, shoulder roll, shoulder yaw, elbow, wrist roll, wrist pitch, wrist yaw. Raises `RobotError` for targets outside the joint limits. |
| `a.stop()` | Stop this arm's current motion. |
| `a.is_moving()` | True while a motion is running. |

With `wait=True` a move returns when the motion has finished; with `wait=False` it
returns at once. A new move replaces one that is still running on the same arm. Motions
are slowed down where needed to stay within the joint speed and acceleration limits.

## Hands (per arm)

Each Dex3-1 hand has seven joints, in Unitree's order: thumb 0 (rotates the thumb), thumb 1,
thumb 2, middle 0, middle 1, index 0, index 1.

| Call | Description |
| --- | --- |
| `a.gripper_move(position, speed=255, force=150, wait=True)` | Close all seven joints together from open (0: fingers straight) to a fist (255). Returns the hand's status. |
| `a.gripper_open(wait=True)` | Same as `gripper_move(0)`. |
| `a.gripper_close(force=150, wait=True)` | Same as `gripper_move(255, force=force)`. |
| `a.hand_move(joints, speed=255, force=150, wait=True)` | Set the seven joints (rad) one by one. Raises `RobotError` for targets outside the joint limits. Returns `{"gripper": status, "hand": readings}`. |
| `a.get_gripper_status()` | `position`, `requested`, `object_detected`, `status_code`, `moving`. |

`speed` and `force` are on a 0 to 255 scale (255 is the hand's fastest and strongest).
`position` in the status is how far the fingers have closed on the same 0 to 255 scale.
`object_detected` is True when a finger stopped on something before reaching its target
(`status_code` 2 while closing, 1 while opening; 3 means they reached it; 0 means still
moving).

The two hands are mirror images: the left hand's fingers close toward negative angles and
the right hand's toward positive ones. Joint limits (rad):

| Joint | Left hand | Right hand |
| --- | --- | --- |
| thumb 0 | -1.047 to 1.047 | -1.047 to 1.047 |
| thumb 1 | -0.724 to 1.047 | -1.047 to 0.724 |
| thumb 2 | 0 to 1.745 | -1.745 to 0 |
| middle 0, index 0 | -1.571 to 0 | 0 to 1.571 |
| middle 1, index 1 | -1.745 to 0 | 0 to 1.745 |

## Walking and body (whole robot, `body = Robot()`)

| Call | Description |
| --- | --- |
| `body.walk(vx=0, vy=0, yaw_rate=0, seconds=1.0, wait=True)` | Walk forward at `vx` and to the left at `vy` (m/s, -1 to 1), turning counter-clockwise at `yaw_rate` (rad/s, -1 to 1), for `seconds`, then stand. |
| `body.stand()` | Stop walking and stand where it is. |
| `body.set_body(height=None, pitch=None)` | The balance controller's pelvis height (m, 0.50 to 1.00; legs are straight above about 0.79) and forward lean of the torso (rad, -0.52 to 0.52). Leave one out to keep it. Returns both. |
| `body.get_lidar_points()` | One scan of the head lidar: an N × 3 array of the points it hit (m, pelvis frame). |

Arm moves are solved for where the body is when the move starts: walk or change the body
pose first, then move the arms.

If the robot falls it stops (`fallen` in the body readings) and stays down.

## Protective stops

The robot stops and refuses motion commands when an arm cannot follow its commanded path
(for example because it is blocked) or when it falls.

| Call | Description |
| --- | --- |
| `a.is_protective_stopped()` | True while stopped. |
| `a.unlock_protective_stop()` | Clear the stop so the arm accepts commands again. |

`get_state()["protective_stop_reason"]` says why it stopped.

## Readings

| Call | Returns |
| --- | --- |
| `a.get_state()` | One arm: `time` (controller clock, s), `mode` (`"running"` or `"protective_stop"`), `moving`, `joint_positions`, `joint_velocities`, `joint_torques` (Nm), `tcp_pose`, `gripper` (status as above) and `hand`: `joint_positions`, `joint_velocities`, `joint_torques` of its seven joints and `pressure`. |
| `body.get_state()` | `time`, `mode`, `moving`, `"left"` and `"right"` (each arm's readings as above), and `"body"`: the leg and waist joints (`joint_names`, `joint_positions`, `joint_velocities`, `joint_torques`), `imu` (pelvis `quaternion` [w, x, y, z], `gyroscope` rad/s, `accelerometer` m/s²), the current `walk_command`, `height_command` and `pitch_command`, `walking`, `fallen`. |
| `a.get_joint_positions()` | 7 arm joint angles (rad). |
| `a.get_tcp_pose()` | Current TCP pose `[x, y, z, rx, ry, rz]`. |
| `a.get_time()` | Controller clock (s). |

`pressure` is the hand's tactile sensors, one reading (N) per area: `palm`, `thumb_pad`,
`thumb_tip`, `index_pad`, `index_tip`, `middle_pad`, `middle_tip`. Each reads 0 below about
0.1 N (10 g) and saturates at 24.5 N (2.5 kg). The G1 has no wrist force/torque sensor.

## Cameras

Three cameras: `"head"` (in the head) and one on each wrist. An arm's client calls its own
wrist camera `"wrist"`; the `body` client calls them `"left_wrist"` and `"right_wrist"`.

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
- `camera_position`, `camera_rotation`: the camera's pose in the pelvis frame, at the moment
  the image was taken (OpenCV axes: x right, y down, z forward; the rotation maps camera
  coordinates into that frame).
- `save(path)`: write the colour image as a PNG.

## Agent tools

Besides Python, these tools are available directly:

| Tool | Description |
| --- | --- |
| `look(camera)` | Shows you a camera image (`head`, `left_wrist`, `right_wrist`), with its calibration in the pelvis frame. |
| `robot_state()` | The same as `body.get_state()`. |
| `emergency_stop()` | Stops both arms and walking at once. |

## Rules

- Use only this command interface, the agent tools and what the robot senses.
- The robot cell's own software and files are not available to you; don't look for them.
