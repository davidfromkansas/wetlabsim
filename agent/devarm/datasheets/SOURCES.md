# Seeed reBot DevArm documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Seeed reBot Arm B601 Quick Start (wiki).html` | <https://wiki.seeedstudio.com/rebot_b601_dm_getting_started/> | 2026-11-18 | reBot Arm B601: wiring, power, setup and safety. A live web page. |
| `reBot-DevArm README.md` | <https://raw.githubusercontent.com/Seeed-Projects/reBot-DevArm/main/README.md> | 2026-11-18 | reBot Arm B601-DM and B601-RS: payload, reach, weight, repeatability, degrees of freedom, supply voltage. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `seeed_rebot_devarm`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/seeed_rebot_devarm>) | Menagerie |
| Gripper | Parallel gripper: the model's own gripper | Menagerie |
| Gripper opening | 98 mm | the model |
| Max joint speed | 86, 86, 86, 86, 86, 86 deg/s (J1 to J6) | not published; our choice (86 deg/s) |
| Reach, payload (picker card) | 754 mm, 2.5 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.5 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/seeed_rebot_devarm/LICENSE` (from Menagerie).
