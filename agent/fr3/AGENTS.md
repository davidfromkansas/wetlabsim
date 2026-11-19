This folder is your workspace for operating a lab robot: a Franka Research 3 arm (Franka Robotics) with
a Franka Hand, on a table. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is installed here: mounting, coordinate frames, tool settings,
  cameras.
- `cameras.json`: the camera calibration.
- `datasheets/`: Franka Robotics and Franka Robotics GmbH and Franka Robotics GmbH (Franka Control Interface documentation)'s own documents for the arm and the gripper.
- `robot_model/fr3.xml`: a MuJoCo model of the arm (the robot only).
- `robot_model/franka_hand/hand.xml`: a MuJoCo model of the Franka Hand.

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
