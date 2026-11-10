# Franka documents given to agents

These are Franka's own documents, unchanged. Agents get a copy in their workspace
(`datasheets/`), because they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Product Manual Franka Emika Robot_10.21_EN.pdf` | <https://download.franka.de/documents/100010_Product%20Manual%20Franka%20Emika%20Robot_10.21_EN.pdf> | 2026-11-06 | The Panda ("Franka Emika Robot") manual. Datasheet on pages 34-36. |
| `Product Manual Franka Hand_R50010_1.2_EN.pdf` | <https://franka.de/hubfs/Product%20Manual%20Franka%20Hand_R50010_1.2_EN.pdf> | 2026-11-06 | Franka Hand manual. Technical specifications in section 5. |
| `FCI Control Interface Specification and Robot Limits.html` | <https://frankarobotics.github.io/docs/robot_specifications.html> | 2026-11-06 | Joint and Cartesian limits the controller enforces ("Limits for Franka Emika Robot (FER)"). |

The files here are unchanged copies, kept in the repo. SHA-256 checksums are in
`sources.json`; `python -m wetlabsim.datasheets` checks them and downloads any file that
is missing from its source.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Joint position limits | Menagerie model, identical to the FER table | FCI page, FER joint-space limits |
| Max joint speed | 2.175 rad/s (A1-A4), 2.61 rad/s (A5-A7) | FCI page, FER joint-space limits |
| Max joint acceleration | 15, 7.5, 10, 12.5, 15, 20, 20 rad/s² | FCI page, FER joint-space limits |
| Max Cartesian speed | 1.7 m/s translation, 2.5 rad/s rotation | FCI page, FER Cartesian limits |
| Joint torque limits | 87 Nm (A1-A4), 12 Nm (A5-A7) | FCI page; datasheet p. 35 |
| Wrist force/torque noise | 0.035 N, 0.005 Nm RMS | Datasheet p. 34, "Force/Torque noise (RMS)" |
| Wrist force/torque bias until tared | up to 0.8 N, 0.15 Nm | Datasheet p. 34, "Relative force/torque accuracy" |
| Protective stop (reflex) | external force outside Fx -125..95, Fy -100..100, Fz -50..150 N, or torque outside ±10 Nm | Datasheet p. 34, "Force range" / "Torque range", nominal case |
| TCP | 103.4 mm past the flange, rotated -45° about z | Hand manual 5.1, flange-to-TCP transform |
| Hand mass | 0.73 kg (centre of mass from the Menagerie model, close to the manual's (0, 9.3, 30.2) mm) | Hand manual 5.1 |
| Gripper stroke | 80 mm | Hand manual 5.1, "Travel range" |
| Gripper speed | 50 mm/s per finger | Hand manual 5.1, "Travel speed" |
| Grip force | 30-70 N, continuous, adjustable | Hand manual 5.1, "Grasping (continuous) force" |

Two places where Franka's documents disagree, and which one the simulator follows:

- Joint speed: the datasheet (p. 34) gives 150°/s for A1-A4 and 180°/s for A5-A7; the FCI
  page gives 2.175 rad/s (125°/s) and 2.61 rad/s (150°/s). The simulator uses the FCI page,
  because those are the limits the controller enforces on commands.
- Cartesian speed: the datasheet says "up to 2 m/s end effector speed"; the FCI page limits
  commands to 1.7 m/s. The simulator uses 1.7 m/s.

The datasheet's force range is the range the force controller works over; we use its
nominal case as the protective-stop threshold. The real robot's collision thresholds are
set by the user (`setCollisionBehavior` in libfranka), so this is our choice of setting,
not a published default.
