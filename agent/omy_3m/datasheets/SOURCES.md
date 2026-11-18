# ROBOTIS OMY-3M documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `ROBOTIS OMY hardware (AI Worker docs).html` | <https://ai.robotis.com/omy/hardware_omy.html> | 2026-11-18 | OMY arms: degrees of freedom, payload 3 kg, reach 580 mm, weight, TCP speed, the DYNAMIXEL-Y actuators. A live web page. |
| `Robotiq 2F-85 2F-140 Instruction Manual (General).pdf` | <https://blog.robotiq.com/hubfs/support-files/2F-85_2F-140_General_PDF_20210623.pdf> | 2026-11-12 | 2F-85 and 2F-140 Adaptive Grippers: stroke, grasp force, finger speed, the 0-255 position/speed/force registers and object detection. Release 2021-06-23. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `robotis_omy_3m`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/robotis_omy_3m>) | Menagerie |
| Gripper | Robotiq 2F-85: Robotiq 2F-85 from Menagerie `robotiq_2f85`, added by us on the flange | Menagerie |
| Gripper opening | 85 mm | Robotiq manual |
| Max joint speed | 86, 86, 86, 86, 86, 86 deg/s (J1 to J6) | not published; our choice (86 deg/s) |
| Reach, payload (picker card) | 580 mm, 3 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | The gripper model's own pinch point. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 1 m/s, 2 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/robotis_omy_3m/LICENSE` (from Menagerie).
