# KUKA LBR iiwa 14 R820 documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `KUKA LBR iiwa specification.pdf` | <https://git.phschoen.de/phschoen/lwr_server/raw/commit/1debece1117ae5d940d2f15c0647304bf45473c6/lwrserv/doc/LBRiiwa_en.pdf> | 2026-11-18 | LBR iiwa 7 R800 and 14 R820: payload, reach, repeatability, each axis's range, maximum torque and maximum speed, workspace. KUKA's own data sheet; kuka.com only gives it to signed-in customers, so this is a copy hosted on GitHub. |
| `KUKA LBR iiwa (product page).html` | <https://www.kuka.com/en-de/products/robot-systems/industrial-robots/lbr-iiwa> | 2026-11-18 | LBR iiwa family: payload, reach, mounting positions, protection class. A live web page. |
| `Robotiq 2F-85 2F-140 Instruction Manual (General).pdf` | <https://blog.robotiq.com/hubfs/support-files/2F-85_2F-140_General_PDF_20210623.pdf> | 2026-11-12 | 2F-85 and 2F-140 Adaptive Grippers: stroke, grasp force, finger speed, the 0-255 position/speed/force registers and object detection. Release 2021-06-23. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `kuka_iiwa_14`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/kuka_iiwa_14>) | Menagerie |
| Gripper | Robotiq 2F-85: Robotiq 2F-85 from Menagerie `robotiq_2f85`, added by us on the flange | Menagerie |
| Gripper opening | 85 mm | Robotiq manual |
| Max joint speed | 85, 85, 100, 75, 130, 135, 135 deg/s (J1 to J7) | KUKA data sheet |
| Reach, payload (picker card) | 820 mm, 14 kg | the documents above |
| Wrist force/torque | readings from a MuJoCo force/torque sensor at the flange; no protective stop on force | the arm has joint torque sensing (documents above) |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | The gripper model's own pinch point. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 1 m/s, 2 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/kuka_iiwa_14/LICENSE` (from Menagerie).
