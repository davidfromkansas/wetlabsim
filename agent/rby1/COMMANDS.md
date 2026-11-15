# Command reference

The robot is controlled from Python through `wetlabsim.robot`, a client for the robot's
controller. It is the only Python package you can import for the robot.

The RB-Y1 has two arms, each with a gripper, on a 6-joint torso with a pan-tilt head, on a
two-wheeled base. Each arm has its own client; the whole robot has one more. All of them
report in the same frame, the base frame (see `SITE.md`):

```python
from wetlabsim.robot import Robot, RobotError
left = Robot(arm="left")
right = Robot(arm="right")
body = Robot()          # the whole robot: wheels, torso, head, all three cameras,
                        # reads both arms, stops everything; no arm motion commands
```

The controller runs in real time and never pauses. Every joint holds its last commanded
position until it gets a new command, and the wheels stop when a drive command ends. Nothing
balances or moves the robot for you. Commands that fail raise `RobotError`. Parts move at the
same time when you start a move on one with `wait=False` and then command another.

Units: metres, radians, seconds. Poses are `[x, y, z, rx, ry, rz]` in the base frame: the TCP
position plus its orientation as a rotation vector (axis × angle, radians). The base frame
moves with the robot when it drives or turns.

## Arm motion (per arm)

| Call | Description |
| --- | --- |
| `a.move_l(pose, speed=0.25, wait=True)` | Move the TCP along a straight line to `pose`. `speed` in m/s. Raises `RobotError` if the line is unreachable or the motion is stopped. |
| `a.move_j_pose(pose, speed=1.0, wait=True)` | Move to `pose` by interpolating joint angles. The TCP path is not straight. `speed` in rad/s. |
| `a.move_j(joints, speed=1.0, wait=True)` | Move to 7 joint angles (rad), Rainbow's order: shoulder pitch, shoulder roll, shoulder yaw, elbow, wrist yaw 1, wrist pitch, wrist yaw 2. Raises `RobotError` for targets outside the joint limits. |
| `a.stop()` | Stop this arm's current motion. |
| `a.is_moving()` | True while a motion is running. |

With `wait=True` a move returns when the motion has finished; with `wait=False` it returns
at once. A new move replaces one that is still running on the same arm. Motions are slowed
down where needed to stay within the joint speed and acceleration limits. Arm moves are
solved for where the torso is when the move starts: move the torso first, then the arms.

## Grippers (per arm)

| Call | Description |
| --- | --- |
| `a.gripper_move(position, speed=255, force=150, wait=True)` | Move the fingers from open (0: 106 mm apart) to closed (255: 6 mm apart). Returns the gripper's status. |
| `a.gripper_open(wait=True)` | Same as `gripper_move(0)`. |
| `a.gripper_close(force=150, wait=True)` | Same as `gripper_move(255, force=force)`. |
| `a.get_gripper_status()` | `position`, `requested`, `object_detected`, `status_code`, `moving`. |

`speed` and `force` are on a 0 to 255 scale (255 is the fastest and strongest). `position`
in the status is how far the fingers have closed on the same 0 to 255 scale.
`object_detected` is True when the fingers stopped on something before reaching their target
(`status_code` 2 while closing, 1 while opening; 3 means they reached it; 0 means still
moving).

## Base, torso and head (whole robot, `body = Robot()`)

| Call | Description |
| --- | --- |
| `body.drive(vx=0, yaw_rate=0, seconds=1.0, wait=True)` | Drive forward at `vx` (m/s, negative backs up), turning counter-clockwise at `yaw_rate` (rad/s), for `seconds`, then stop. Each wheel turns at most 1.57 m/s (`vx ± yaw_rate × 0.265`); the wheels speed up and slow down gradually. The base can't move sideways. |
| `body.move_torso(joints, speed=None, wait=True)` | Move the 6 torso joints (rad), Rainbow's order: ankle roll, ankle pitch, knee, hip pitch, hip roll, hip yaw. Bending the ankle and knee one way and the hip the other lowers the chest; `[0, a, -2a, a, 0, 0]` keeps it upright. `speed` in rad/s (at most each joint's limit). |
| `body.move_head(joints, speed=None, wait=True)` | Pan and tilt the head (rad): pan positive turns it left, tilt positive looks down. |
| `body.stop()` | Stop the wheels, the torso, the head and both arms. |

The torso and head joint limits (rad), narrowed to what their motors are commanded within:

| Joint | Range |
| --- | --- |
| torso 0 (ankle roll) | -0.262 to 0.262 |
| torso 1 (ankle pitch) | -0.524 to 1.571 |
| torso 2 (knee) | -2.478 to 1.571 |
| torso 3 (hip pitch) | -0.785 to 1.571 |
| torso 4 (hip roll) | -0.524 to 0.524 |
| torso 5 (hip yaw) | -1.571 to 1.571 |
| head 0 (pan) | -0.523 to 0.523 |
| head 1 (tilt) | -0.35 to 1.57 |

A move outside them raises `RobotError` with the limits.

## Protective stops

An arm stops and refuses motion commands when it cannot follow its commanded path (for
example because it is blocked).

| Call | Description |
| --- | --- |
| `a.is_protective_stopped()` | True while stopped. |
| `a.unlock_protective_stop()` | Clear the stop so the arm accepts commands again. |

`get_state()["protective_stop_reason"]` says why it stopped.

## Readings

| Call | Returns |
| --- | --- |
| `a.get_state()` | One arm: `time` (controller clock, s), `mode` (`"running"` or `"protective_stop"`), `moving`, `joint_positions`, `joint_velocities`, `tcp_pose`, `tcp_force` (the wrist force/torque sensor: `[Fx, Fy, Fz, Mx, My, Mz]` in N and Nm, in the TCP frame, the gripper's weight removed) and `gripper` (status as above). |
| `body.get_state()` | `time`, `mode`, `moving`, `"left"` and `"right"` (each arm's readings as above), and `"body"`: `torso` and `head` (each `joint_positions`, `joint_velocities`, `joint_torques`, `moving`), `wheels` (`joint_velocities` rad/s, `joint_torques`), the current `drive_command` `[vx, yaw_rate]`, `driving`, and `odometry` `[x, y, heading]` (m, m, rad): how far the base has travelled since the start, from its wheel encoders (wheels can slip a little, so it drifts). |
| `a.get_joint_positions()` | 7 arm joint angles (rad). |
| `a.get_tcp_pose()` | Current TCP pose `[x, y, z, rx, ry, rz]`. |
| `a.zero_ft_sensor()` | Tare the arm's wrist force/torque sensor. |
| `a.get_time()` | Controller clock (s). |

## Cameras

Three cameras: `"head"` (on the pan-tilt head) and one on each gripper. An arm's client calls
its own wrist camera `"wrist"`; the `body` client calls them `"left_wrist"` and `"right_wrist"`.

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
- `camera_position`, `camera_rotation`: the camera's pose in the base frame, at the moment
  the image was taken (OpenCV axes: x right, y down, z forward; the rotation maps camera
  coordinates into that frame).
- `save(path)`: write the colour image as a PNG.

## Agent tools

Besides Python, these tools are available directly:

| Tool | Description |
| --- | --- |
| `look(camera)` | Shows you a camera image (`head`, `left_wrist`, `right_wrist`), with its calibration in the base frame. |
| `robot_state()` | The same as `body.get_state()`. |
| `emergency_stop()` | Stops the wheels, torso, head and both arms at once. |

## Rules

- Use only this command interface, the agent tools and what the robot senses.
- The robot cell's own software and files are not available to you; don't look for them.
