# FR3 Duo documents given to agents

These are the makers' own documents, unchanged: Franka Robotics (the FR3 arm, the FR3 Duo and
its Vision & Manipulation Kit) and Robotiq (the 2F-85 grippers of the kit). Agents get a copy
in their workspace (`datasheets/`), because they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Datasheet Franka Research 3_R02212_2.6_EN.pdf` | <https://franka.de/hubfs/Datasheet%20Franka%20Research%203_R02212_2.6_EN_July%202026.pdf> | 2026-11-12 | The FR3 arm: 7 DOF, 855 mm reach, 3 kg payload, joint position, torque and velocity limits, link-side torque sensors. |
| `FCI Control Interface Specification and Robot Limits.html` | <https://frankarobotics.github.io/docs/robot_specifications.html> | 2026-11-12 | FCI limits for the FR3: joint velocity, acceleration and jerk, Cartesian limits, DH parameters. A live web page. |
| `Quick Installation Guide FR3 Duo_R04240_1.3_EN.pdf` | <https://franka.de/hubfs/Quick%20Installation%20Guide%20FR3%20Duo_R04240_1.3_EN.pdf> | 2026-11-12 | The FR3 Duo, its kit (2 x Robotiq 2F-85, ZED Mini head camera, 2 x RealSense D405 wrist cameras) and its reference kinematics (origin 200 mm above the work surface). |
| `FR3Duo_TwoPager_digital.pdf` | <https://franka.de/hubfs/FR3Duo_TwoPager_digital.pdf> | 2026-11-12 | FR3 Duo overview. |
| `Robotiq 2F-85 2F-140 Instruction Manual (General).pdf` | <https://blog.robotiq.com/hubfs/support-files/2F-85_2F-140_General_PDF_20210623.pdf> | 2026-11-12 | The 2F-85: 85 mm stroke, 20-235 N grasp force, 20-150 mm/s finger speed, 0-255 registers. |

SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Robot model (mount, links, masses and inertias, joint axes and ranges, armature, friction loss, collision hulls, colours, camera poses and fields of view) | Franka's SimReady USD of the kit, converted by `playground/tools/convert_fr3_duo.py` | Hugging Face `frankarobotics/simready-assets`, `fr3_duo_vision_manipulation_kit` (CC-BY-4.0) |
| Joint position gains (kp / kv) | 4500 / 450 (joints 1-2), 3500 / 350 (3-4), 2000 / 200 (5-7) | The kit's "position" control mode (per degree in the USD) |
| Joint torque limits | 87 Nm (joints 1-4), 12 Nm (5-7) | The kit; FR3 datasheet |
| Max joint speed and acceleration | 2.62, 2.62, 2.62, 2.62, 5.26, 4.18, 5.26 rad/s; 10 rad/s^2 | FCI limits for the FR3 |
| Cartesian speed | 3.0 m/s, 2.5 rad/s | FCI limits for the FR3 |
| Grippers | MuJoCo Menagerie Robotiq 2F-85, unchanged, where the kit mounts its own | Menagerie (the kit's MuJoCo layer doesn't close the gripper's four-bar linkage) |
| Height | FR3 Duo origin 200 mm above the table, on a riser | FR3 Duo installation guide, section 8 |
| Cameras | ZED Mini left eye (head), 2 x D405 colour (wrists), 640 x 480 | The kit's camera prims |
| Wrist force/torque | estimated at each flange, gripper load removed | FR3: link-side torque sensors in all 7 axes |

Our own choices (no published number): the start pose (both grippers pointing down in front
of the robot); no force/torque noise, bias or Cartesian reflex thresholds, since Franka
publishes none for the FR3's wrench estimate.
