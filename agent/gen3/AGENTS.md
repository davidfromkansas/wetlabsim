This folder is your workspace for operating a lab robot: a Kinova Gen3 (7 joints) arm (Kinova) with
a Robotiq 2F-85, on a table. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is installed here: mounting, coordinate frames, tool settings,
  cameras.
- `cameras.json`: the camera calibration.
- `datasheets/`: Kinova and Robotiq's own documents for the arm and the gripper.
- `robot_model/gen3.xml`: a MuJoCo model of the arm (the robot only).
- `robot_model/robotiq_2f85/2f85.xml`: a MuJoCo model of the gripper.

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
