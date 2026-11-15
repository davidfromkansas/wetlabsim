This folder is your workspace for operating a lab robot: a Rainbow Robotics RB-Y1, a wheeled
humanoid with two arms, each with a two-finger gripper and a camera, on a bending torso with a
camera on its pan-tilt head, standing on its wheels on the floor at the edge of a table. You
control the wheels, the torso, the head, both arms and both grippers. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is set up here: where it stands, coordinate frames, grippers,
  cameras.
- `cameras.json`: the camera calibration, for each arm.
- `datasheets/`: Rainbow Robotics' own documentation pages for the RB-Y1 (specifications,
  motors, gripper, driving the base).
- `robot_model/rby1a_1.2.xml`: a MuJoCo model of the RB-Y1 (the robot only).

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
