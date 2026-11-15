# Unitree G1 documents given to agents

These are the makers' own documents, unchanged: Unitree Robotics (the G1 humanoid and its
Dex3-1 hands), Hugging Face's LeRobot documentation for running the G1, and Livox (the
Mid-360 lidar in the G1's head). Agents get a copy in their workspace (`datasheets/`),
because they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Unitree G1 Humanoid Robot (product page).html` | <https://www.unitree.com/g1> | 2026-11-13 | The G1: 1320 mm tall, about 35 kg, 23-43 joints, joint ranges and torque, arm payload, depth camera and 3D lidar. A live web page. |
| `Unitree Dex3-1 Dexterous Hand (product page).html` | <https://www.unitree.com/Dex3-1> | 2026-11-13 | The Dex3-1: 7 joints (thumb 3, index 2, middle 2), joint ranges, 33 tactile sensors. A live web page. |
| `LeRobot Unitree G1 documentation.html` | <https://huggingface.co/docs/lerobot/unitree_g1> | 2026-11-13 | How LeRobot runs the G1 in simulation and on the robot: 29-joint layout, the GR00T balance and walking controller, cameras, the Dex3-1 option. A live web page. |
| `Livox_Mid-360_User_Manual_EN.pdf` | <https://terra-1-g.djicdn.com/851d20f7b9f64838a34cd02351370894/Livox/Livox_Mid-360_User_Manual_EN.pdf> | 2026-11-13 | The Mid-360 lidar: 360° × 59° field of view, 0.1-40 m range. User manual v1.2. |

SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Robot model (links, masses and inertias, joint axes and ranges, torque limits, collision shapes, colours, hands) | MuJoCo Menagerie `unitree_g1/g1_with_hands.xml`, unchanged | Menagerie (BSD-3-Clause), from Unitree's own model |
| Balance and walking | NVIDIA GR00T WholeBodyControl Balance and Walk policies, 50 Hz, on the legs and waist | The same policies and settings LeRobot's `GrootLocomotionController` runs (Hugging Face `nepyope/GR00T-WholeBodyControl_g1`, NVIDIA Open Model License) |
| Joint gains (kp / kd) | hips 150 / 2, knees 300 / 4, ankles 40 / 2, waist 250 / 5, shoulders 50 / 3, shoulder yaw and elbow 80 / 3, wrists 40 / 1.5 | LeRobot's G1 defaults (Unitree's) |
| Joint speed limits | arm 37 rad/s, wrist pitch and yaw 22 rad/s; hand 6.9-12 rad/s | Unitree's G1 URDF |
| Head camera | Intel RealSense D435i at Unitree's `d435_link` | Unitree's G1 URDF |
| Wrist cameras | where LeRobot's G1 simulation puts them | LeRobot `unitree-g1-mujoco` |
| Lidar | Livox Mid-360 at Unitree's `mid360_link`, 360° × -7° to 52°, 0.1-40 m | Unitree's G1 URDF; Livox manual |
| Tactile sensors | 7 areas per hand (palm, thumb, index and middle pads and tips), 10 g to 2.5 kg | Dex3-1 page (33 sensors in 9 arrays) |

Our own choices (no published number): the start pose (forearms raised in front of the
chest), and the lidar scans in one sweep on a regular grid rather than Livox's
non-repeating pattern. The palm's three tactile arrays are reported as one reading.
