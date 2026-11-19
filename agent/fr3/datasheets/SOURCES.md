# Franka Research 3 documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Datasheet Franka Research 3_R02212_2.6_EN.pdf` | <https://franka.de/hubfs/Datasheet%20Franka%20Research%203_R02212_2.6_EN_July%202026.pdf> | 2026-11-12 | Franka Research 3 (the arm, twice on the FR3 Duo): reach, payload, joint position, torque and velocity limits, link-side torque sensing, workspace and link lengths. Release 2.6, July 2026. |
| `FCI Control Interface Specification and Robot Limits.html` | <https://frankarobotics.github.io/docs/robot_specifications.html> | 2026-11-06 | Joint and Cartesian limits enforced by the controller; see 'Limits for Franka Emika Robot (FER)'. A live web page: its checksum changes when Franka edits it. |
| `Product Manual Franka Hand_R50010_1.2_EN.pdf` | <https://franka.de/hubfs/Product%20Manual%20Franka%20Hand_R50010_1.2_EN.pdf> | 2026-11-06 | Franka Hand gripper. Technical specifications in section 5 (pages 11-12). |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `franka_fr3`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/franka_fr3>) | Menagerie |
| Gripper | Franka Hand: Franka Hand from Menagerie `franka_emika_panda/hand.xml`, added by us on the flange | Menagerie |
| Gripper opening | 80 mm | Franka Hand manual |
| Max joint speed | 150, 150, 150, 150, 301, 239, 301 deg/s (J1 to J7) | FR3 datasheet / FCI limits |
| Reach, payload (picker card) | 855 mm, 3 kg | the documents above |
| Wrist force/torque | readings from a MuJoCo force/torque sensor at the flange; no protective stop on force | the arm has joint torque sensing (documents above) |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | The gripper model's own pinch point. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 1.7 m/s, 2.5 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/franka_fr3/LICENSE` (from Menagerie).
