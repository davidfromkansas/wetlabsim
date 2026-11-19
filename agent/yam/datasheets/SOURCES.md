# I2RT YAM documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `i2rt README.md` | <https://raw.githubusercontent.com/i2rt-robotics/i2rt/main/README.md> | 2026-11-18 | YAM arms and grippers: models, masses, reach, the DM motors, the CAN interface. The maker's own README on GitHub. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `i2rt_yam`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/i2rt_yam>) | Menagerie |
| Gripper | YAM parallel gripper: the model's own gripper | Menagerie |
| Gripper opening | 75 mm | the model |
| Max joint speed | 86, 86, 86, 86, 86, 86 deg/s (J1 to J6) | not published; our choice (86 deg/s) |
| Reach, payload (picker card) | 807 mm, 1.5 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.5 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/i2rt_yam/LICENSE` (from Menagerie).
