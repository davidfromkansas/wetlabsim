# UFACTORY xArm 7 documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `UFACTORY xArm Hardware Manual v2.7.1.pdf` | <https://www.ufactory.cc/upfiles/download/202611/RE7G3GY52WQE.pdf> | 2026-11-18 | xArm 5, 6 and 7 and their end effectors: specifications (payload, joint ranges and speed, TCP speed), working range, installation, the xArm Gripper. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `ufactory_xarm7`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/ufactory_xarm7>) | Menagerie |
| Gripper | xArm Gripper: the model's own gripper | Menagerie |
| Gripper opening | 85 mm | the model |
| Max joint speed | 180, 180, 180, 180, 180, 180, 180 deg/s (J1 to J7) | UFACTORY hardware manual (180 deg/s) |
| Reach, payload (picker card) | 700 mm, 3.5 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 1 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/ufactory_xarm7/LICENSE` (from Menagerie).
