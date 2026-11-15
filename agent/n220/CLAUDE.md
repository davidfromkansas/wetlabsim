This folder is your workspace for operating an industrial robot: a Comau N-220-2.7 with a vacuum lifting frame,
standing on the floor. Work in this folder.

What's here:
- `COMMANDS.md`: the robot's command interface (Python) and the agent tools.
- `SITE.md`: how this robot is installed here: mounting, coordinate frames, tool settings,
  cameras.
- `cameras.json`: the camera calibration.
- `datasheets/`: Comau's own brochure and technical data sheet for the N-220.
- `robot_model/comau_n220.xml`: a MuJoCo model of the arm (the robot only, without its tool).

Do the task you were given using only the robot's command interface and the agent tools.

Keep everything you write (scripts, notes, saved images) in this folder, not in a scratchpad
or temporary folder elsewhere, so it is kept with the run.
