This folder is your workspace for operating a lab robot: an ALOHA 2, two Trossen ViperX
300 S arms (left and right), each with a parallel gripper, facing each other across a table.
You control both arms. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is installed here: mounting, coordinate frames, tool settings,
  cameras.
- `cameras.json`: the camera calibration, for each arm.
- `datasheets/`: Trossen's and ROBOTIS's own documents for the arms, the ALOHA kit and the
  servos.
- `robot_model/aloha.xml`: a MuJoCo model of the two arms and grippers (the robot only).

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
