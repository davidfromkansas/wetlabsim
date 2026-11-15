# Rainbow Robotics RB-Y1 documents given to agents

These are the maker's own documents, unchanged: pages of Rainbow Robotics' RB-Y1
documentation (<https://rainbowrobotics.github.io/rby1-dev/>). Agents get a copy in their
workspace (`datasheets/`), because they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `RB-Y1 Technical Specifications (Rainbow Robotics docs).html` | <https://rainbowrobotics.github.io/rby1-dev/hardware/overview.html> | 2026-11-15 | Size, weight, degrees of freedom, arm payload and reach, base speed, every joint's speed and range. |
| `RB-Y1 Mechanical Part (Rainbow Robotics docs).html` | <https://rainbowrobotics.github.io/rby1-dev/hardware/mechanical_part.html> | 2026-11-15 | Motors per joint (wheels 150 rpm), torque table, stiffness, dimensions. |
| `RB-Y1 Gripper (Rainbow Robotics docs).html` | <https://rainbowrobotics.github.io/rby1-dev/options/gripper.html> | 2026-11-15 | The standard gripper (Dynamixel XM430-W210). |
| `RB-Y1 SE2 Velocity Command (Rainbow Robotics docs).html` | <https://rainbowrobotics.github.io/rby1-dev/sdk/cpp/builders/se2-velocity-command-builder.html> | 2026-11-15 | The SDK's command for driving the base: forward and turning speed. |

All four are live web pages: their checksums (in `sources.json`) change when Rainbow edits
them. `python -m wetlabsim.datasheets` checks them and downloads any file that is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Robot model (links, masses and inertias, joint axes and ranges, collision shapes, colours, gripper) | MuJoCo Menagerie `rainbow_robotics_rby1/rby1a_1.2.xml`, unchanged | Menagerie (Apache-2.0), from Rainbow's URDF |
| Joint position gains and torque limits (torso, arms, head, gripper) | Menagerie's | Menagerie |
| Joint speed limits | torso 120-180°/s, arms 180°/s, wrists 360°/s, head 180°/s | Rainbow's specifications and motor table |
| Wheels | 0.1 m radius, 0.53 m apart, at most 15.708 rad/s (1.57 m/s) and 3.14 rad/s² | Rainbow's URDF (`models/rby1a`); specifications (1.5 m/s) |
| Caster friction | 0.05 (sliding), as the casters roll | Rainbow's own MuJoCo scene (`rby1-sdk/models/rby1a/mujoco/rby1.xml`) |
| Arms' start pose | Rainbow's SDK examples' ready pose with the shoulders raised 10° | `rby1-sdk/examples/python/31_multi_controls.py` |
| Cameras | a head camera and one on each wrist, 640 × 480 | Rainbow's own RB-Y1 datasets (`cam_high`, `cam_left_wrist`, `cam_right_wrist`) |
| Wrist force/torque sensors | between each wrist and its gripper | Rainbow's URDF (`FT_sensor_R`, `FT_sensor_L`) |

Our own choices (no published number): the wheel motors' speed-loop gain (Menagerie's is
MuJoCo's default, too weak to turn the wheels), joint accelerations (10 rad/s²), the camera
models (a RealSense D435 on the head mount, D405s on the grippers: the docs leave cameras to
the user) and where they sit, the torso upright at the start, and the force/torque sensors'
noise (none: Rainbow publishes no figure).
