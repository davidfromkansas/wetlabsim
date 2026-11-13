This folder is your workspace for operating a lab robot: a Unitree G1 humanoid with a Dex3-1
three-fingered hand on each arm, a depth camera and a lidar in its head and a camera on each
wrist, standing on the floor at the edge of a table. You control both arms, both hands, and
where it walks. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is set up here: where it stands, coordinate frames, hands,
  cameras.
- `cameras.json`: the camera calibration, for each arm.
- `datasheets/`: Unitree's own pages for the G1 and the Dex3-1 hand, LeRobot's G1
  documentation, and the Livox Mid-360 lidar manual.
- `robot_model/g1_with_hands.xml`: a MuJoCo model of the G1 with its hands (the robot only).

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
