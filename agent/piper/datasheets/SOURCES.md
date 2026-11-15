# PiPER documents given to agents

AgileX Robotics' own user manual, unchanged. Agents get a copy in their workspace
(`datasheets/`), because they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `PIPER Product User Manual EN.pdf` | <https://cdn.shopify.com/s/files/1/0551/0630/6141/files/PIPER_Product_User_Manual_EN_1.pdf?v=1794214904> (linked from <https://global.agilex.ai/products/piper>) | 2026-11-15 | V1.0, 2025.06. Section 1.2: 6 joints, 1.5 kg payload, 626.75 mm working radius, 0.1 mm repeatability, joint ranges, maximum joint speeds, the two-finger gripper. Section 2: coordinate systems, singular positions, workspace. |

The SHA-256 checksum is in `sources.json`; `python -m wetlabsim.datasheets` checks it and
downloads the file if it is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm and gripper model (links, masses, joint ranges, servo gains, friction) | DeepMind MuJoCo Menagerie `agilex_piper`, unchanged (made from AgileX's own URDF) | Menagerie |
| Max joint speed | 180, 195, 180, 225, 225, 225 deg/s (J1 to J6) | Manual, section 1.2 |
| Gripper travel | 0 to 35 mm per finger from the middle (70 mm opening) | Menagerie (AgileX's URDF) |
| Gripper contact surface | rubber | Manual, section 1.2 |
| Gripper force limit | 10 N | Menagerie |
| Wrist force/torque | none | The PiPER has no force/torque sensor |

Where the model and the manual differ, the model is kept as it is:

- Joint ranges. Model: J1 ±150°, J2 0 to 180°, J3 -154.5° to 0, J4 ±105°, J5 ±70°, J6 ±180°.
  Manual: J1 ±154°, J2 0 to 195°, J3 -175° to 0, J4 ±102°, J5 ±75°, J6 ±120°.
- Gripper opening. Model: 70 mm (AgileX's URDF and SDK). The manual's table says 0 to 100 mm.
- Weight. Model: 2.4 kg in all. Manual: 4.2 kg.

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Gripper servo stiffness | 1000 N/m (Menagerie: 40 N/m) | Menagerie's servo squeezes a 60 mm object with about 1 N. Stiffer, the motor's 10 N limit decides the grip, as on the Franka Hand. |
| Tool centre point | between the finger pads, 15 mm back from the fingertips | No TCP in the model. |
| Max joint acceleration | 10 rad/s^2 | Not published. |
| Max Cartesian speed | 0.5 m/s, 3 rad/s | Not published. |
| Cameras | plain cameras, one overhead and one on the gripper, 640 x 480 | The playground's usual pair. |
| Mounting | on the table top | The manual: "install and fix the mechanical arm on the installation table surface". |
