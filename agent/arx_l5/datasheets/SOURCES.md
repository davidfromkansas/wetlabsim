# ARX L5 documents given to agents

Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| (none) | | | ARX publishes no datasheet or manual for the L5 (its site, <https://arx-x.com/>, lists none, and its GitHub model repository has no specifications). The agent gets the command reference, the site sheet and the robot model only. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `arx_l5`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/arx_l5>) | Menagerie |
| Gripper | ARX parallel gripper: the model's own gripper | Menagerie |
| Gripper opening | 88 mm | the model |
| Max joint speed | 86, 86, 86, 86, 86, 86 deg/s (J1 to J6) | not published; our choice (86 deg/s) |
| Reach, payload (picker card) | 620 mm, 1.5 kg | not published; from the model |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.5 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/arx_l5/LICENSE` (from Menagerie).
