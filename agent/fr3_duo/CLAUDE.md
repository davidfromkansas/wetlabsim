This folder is your workspace for operating a lab robot: a Franka FR3 Duo, two Franka
Research 3 arms (left and right) on one mount, each with a Robotiq 2F-85 gripper and a
wrist camera, with a stereo camera on its head, at the edge of a table. You control both
arms. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is installed here: mounting, coordinate frames, tool settings,
  cameras.
- `cameras.json`: the camera calibration, for each arm.
- `datasheets/`: Franka Robotics' and Robotiq's own documents for the arms, the FR3 Duo
  and its kit, and the grippers.
- `robot_model/fr3_duo.xml`: a MuJoCo model of the FR3 Duo with its grippers and cameras
  (the robot only).

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
