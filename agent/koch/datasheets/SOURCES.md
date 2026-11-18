# Low-Cost Robot Arm (Koch) documents given to agents

The makers' own documents, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `low_cost_robot README.md` | <https://raw.githubusercontent.com/AlexanderKoch-Koch/low_cost_robot/main/README.md> | 2026-11-18 | Low-Cost Robot Arm (open hardware): parts list, the DYNAMIXEL XL430 and XL330 servos, assembly. The designer's own README on GitHub. |

The SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains) | Google DeepMind MuJoCo Menagerie `low_cost_robot_arm`, unchanged (commit `370c43965323`, <https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/low_cost_robot_arm>) | Menagerie |
| Gripper | Servo-driven jaw: the model's own gripper | Menagerie |
| Gripper opening | a swinging jaw (no fixed gap) | the model |
| Max joint speed | 86, 86, 86, 86, 86 deg/s (J1 to J5) | not published; our choice (86 deg/s) |
| Reach, payload (picker card) | 300 mm, 0.2 kg | the documents above |
| Wrist force/torque | none | not modelled |

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool centre point | on the wrist-roll axis, 15 mm back from the fixed jaw tip | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.3 m/s, 3 rad/s | Our choice. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | |

Model licence: see `wetlabsim/assets/low_cost_robot_arm/LICENSE` (from Menagerie).
