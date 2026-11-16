# Unitree G1 documents given to agents

These are the makers' own documents, unchanged: Unitree Robotics (the G1 humanoid and its
Dex3-1 hands), NVIDIA (GEAR-SONIC, the G1's whole-body controller), Hugging Face's LeRobot
documentation for running the G1, and Livox (the Mid-360 lidar in the G1's head). Agents get a copy in their workspace (`datasheets/`),
because they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Unitree G1 Humanoid Robot (product page).html` | <https://www.unitree.com/g1> | 2026-11-13 | The G1: 1320 mm tall, about 35 kg, 23-43 joints, joint ranges and torque, arm payload, depth camera and 3D lidar. A live web page. |
| `Unitree Dex3-1 Dexterous Hand (product page).html` | <https://www.unitree.com/Dex3-1> | 2026-11-13 | The Dex3-1: 7 joints (thumb 3, index 2, middle 2), joint ranges, 33 tactile sensors. A live web page. |
| `LeRobot Unitree G1 documentation.html` | <https://huggingface.co/docs/lerobot/unitree_g1> | 2026-11-13 | How LeRobot runs the G1 in simulation and on the robot: 29-joint layout, the GR00T balance and walking controller, cameras, the Dex3-1 option. A live web page. |
| `NVIDIA GEAR-SONIC model card.html` | <https://huggingface.co/nvidia/GEAR-SONIC> | 2026-11-15 | GEAR-SONIC, the G1's whole-body controller: what it is, its inputs and outputs, the planner's movement styles, limitations. A live web page. |
| `NVIDIA SONIC keyboard and planner controls.html` | <https://nvlabs.github.io/GR00T-WholeBodyControl/tutorials/keyboard.html> | 2026-11-15 | How SONIC's planner is driven: the movement styles, their speed and height ranges, facing and direction. A live web page. |
| `NVIDIA SONIC kinematic planner reference.html` | <https://nvlabs.github.io/GR00T-WholeBodyControl/references/planner_onnx.html> | 2026-11-15 | The kinematic planner: its inputs and outputs, the list of modes. A live web page. |
| `Livox_Mid-360_User_Manual_EN.pdf` | <https://terra-1-g.djicdn.com/851d20f7b9f64838a34cd02351370894/Livox/Livox_Mid-360_User_Manual_EN.pdf> | 2026-11-13 | The Mid-360 lidar: 360° × 59° field of view, 0.1-40 m range. User manual v1.2. |

SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Robot model (links, masses and inertias, joint axes and ranges, torque limits, collision shapes, colours, hands) | MuJoCo Menagerie `unitree_g1/g1_with_hands.xml`, unchanged | Menagerie (BSD-3-Clause), from Unitree's own model |
| Balance and movement | NVIDIA GEAR-SONIC (default model, V2 planner), 50 Hz, on all 29 body joints (the arms only in the movements that use them); a Python port of NVIDIA's G1 deployment program | Hugging Face `nvidia/GEAR-SONIC` (NVIDIA Open Model License); github.com/NVlabs/GR00T-WholeBodyControl `gear_sonic_deploy` (Apache 2.0) |
| Joint gains (kp / kd) | legs and waist: SONIC's (each motor's armature at 10 Hz, damping ratio 2: hips and knees 99 / 6.3, hip yaw 40 / 2.6, ankles and waist roll/pitch 28.5 / 1.8, waist yaw 40 / 2.6); arms following arm commands: shoulders 50 / 3, shoulder yaw and elbow 80 / 3, wrists 40 / 1.5 with gravity compensation (LeRobot's); arms in SONIC's movements: SONIC's | NVIDIA's deploy (`policy_parameters.hpp`); LeRobot's G1 defaults |
| Joint speed limits | arm 37 rad/s, wrist pitch and yaw 22 rad/s; hand 6.9-12 rad/s | Unitree's G1 URDF |
| Head camera | Intel RealSense D435i at Unitree's `d435_link` | Unitree's G1 URDF |
| Wrist cameras | where LeRobot's G1 simulation puts them | LeRobot `unitree-g1-mujoco` |
| Lidar | Livox Mid-360 at Unitree's `mid360_link`, 360° × -7° to 52°, 0.1-40 m | Unitree's G1 URDF; Livox manual |
| Tactile sensors | 7 areas per hand (palm, thumb, index and middle pads and tips), 10 g to 2.5 kg | Dex3-1 page (33 sensors in 9 arrays) |

Our own choices (no published number): the start pose (forearms raised in front of the
chest), and the lidar scans in one sweep on a regular grid rather than Livox's
non-repeating pattern. The palm's three tactile arrays are reported as one reading.
