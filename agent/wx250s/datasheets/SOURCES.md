# Trossen WidowX 250 S documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Trossen WidowX-250 6DOF Specifications.html` | <https://docs.trossenrobotics.com/interbotix_xsarms_docs/specifications/wx250s.html> | 2026-11-18 | WidowX-250 6DOF: reach, payload, joint limits, servos, gripper opening (30 to 74 mm), kinematics. A live web page. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `trossen_wx250s`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/trossen_wx250s>) | Menagerie |
| Gripper | Interbotix parallel gripper: the model's own gripper | Menagerie |
| Gripper opening | 74 mm | Trossen specifications |
| Max joint speed | 180, 180, 180, 180, 180, 276 deg/s (J1 to J6) | as the ViperX (the same servo family) |
| Reach, payload (picker card) | 650 mm, 0.25 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.5 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/trossen_wx250s/LICENSE` (from Menagerie).
