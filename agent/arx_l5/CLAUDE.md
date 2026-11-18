This folder is your workspace for operating a lab robot: a ARX L5 arm (ARX Robotics) with
a ARX parallel gripper, on a table. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is installed here: mounting, coordinate frames, tool settings,
  cameras.
- `cameras.json`: the camera calibration.
- `datasheets/`: empty. ARX publishes no datasheet or manual for the L5.
- `robot_model/arx_l5.xml`: a MuJoCo model of the arm (the robot only).

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
