# Rethink Robotics Sawyer documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `sawyer_base.urdf.xacro` | <https://raw.githubusercontent.com/RethinkRobotics/sawyer_robot/master/sawyer_description/urdf/sawyer_base.urdf.xacro> | 2026-11-18 | Sawyer arm description from Rethink's own SDK repository: link lengths, joint ranges, joint torque and speed limits. Rethink's spec sheets are no longer online. |
| `Robotiq 2F-85 2F-140 Instruction Manual (General).pdf` | <https://blog.robotiq.com/hubfs/support-files/2F-85_2F-140_General_PDF_20210623.pdf> | 2026-11-12 | 2F-85 and 2F-140 Adaptive Grippers: stroke, grasp force, finger speed, the 0-255 position/speed/force registers and object detection. Release 2021-06-23. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `rethink_robotics_sawyer`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/rethink_robotics_sawyer>) | Menagerie |
| Gripper | Robotiq 2F-85: Robotiq 2F-85 from Menagerie `robotiq_2f85`, added by us on the flange | Menagerie |
| Gripper opening | 85 mm | Robotiq manual |
| Max joint speed | 100, 76, 112, 112, 200, 200, 260 deg/s (J1 to J7) | Rethink's URDF |
| Reach, payload (picker card) | 1260 mm, 4 kg | the documents above |
| Wrist force/torque | readings from a MuJoCo force/torque sensor at the flange; no protective stop on force | the arm has joint torque sensing (documents above) |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | The gripper model's own pinch point. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 1 m/s, 2 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/rethink_robotics_sawyer/LICENSE` (from Menagerie).
