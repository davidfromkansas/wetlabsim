# Unitree Z1 documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Unitree Z1 (product page).html` | <https://www.unitree.com/z1> | 2026-11-18 | Z1 arm: degrees of freedom, payload, reach, weight, maximum joint speed, joint parameters, gripper. A live web page. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `unitree_z1`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/unitree_z1>) | Menagerie |
| Gripper | Z1 gripper: the model's own gripper | Menagerie |
| Gripper opening | a swinging jaw (no fixed gap) | the model |
| Max joint speed | 180, 180, 180, 180, 180, 180 deg/s (J1 to J6) | Unitree product page (180 deg/s) |
| Reach, payload (picker card) | 740 mm, 2 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | on the wrist-roll axis, 15 mm back from the fixed jaw tip | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.5 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/unitree_z1/LICENSE` (from Menagerie).
