# N-220 documents given to agents

Comau's own brochure, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Brochure-N-220-ROBOT.pdf` | <https://www.comau.com/wp-content/uploads/2022/09/Brochure-N-220-ROBOT.pdf> | 2026-11-15 | Edition 4/22. Page 4, technical data sheet for the N-220-2.7: 220 kg wrist payload, 2670 mm horizontal reach, wrist torques, each axis's stroke and maximum speed, 0.05 mm repeatability, ISO 9409-1-A125 flange, 1193 kg, floor mounting, working areas. |

The SHA-256 checksum is in `sources.json`; `python -m wetlabsim.datasheets` checks it and
downloads the file if it is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, inertias, joint frames, collision shapes, colours) | Comau's own SimReady package, Hugging Face `Comau/N220-27` (CC BY 4.0), converted by `playground/tools/convert_simready_arm.py` | Package |
| Axis strokes | ±180°, -77° to +76°, -167° to +74°, ±200°, ±125°, ±200° | Package; axes 1 to 5 as the data sheet |
| Max axis speed | 120, 100, 110, 140, 140, 210 deg/s | Package and data sheet agree |
| Position-drive gains, axes 1 to 5 | as the package states them | Package |
| Wrist torque limits, axes 4 to 6 | 1270, 1270, 780 N m | Data sheet |
| Links collide with each other | no | Package (`enabledSelfCollisions = false`) |

Where the model and the data sheet differ, the model is kept as it is:

- Axis 6 stroke. Model: ±200°. Data sheet: ±2700°.
- Weight. Model: 1182 kg in all. Data sheet: 1193 kg.

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Axis 6 drive gains | the same as axis 4's | The package's axis 6 drive is tuned for its bare 0.1 kg flange disc (about 1000 N m/rad): a loaded tool would swing on it. |
| Torque limits, axes 1 to 3 | none | Not published; the package gives none. |
| Tool | a vacuum lifting frame: six 150 mm suction cups, 32 kg, 300 mm from flange to cup faces | The package has no tool. Big flat car panels are lifted with vacuum frames in car plants. |
| Vacuum | 60 kPa below ambient over each cup's area: 1060 N per cup, 6360 N in all; cups pull from 10 mm away | A usual working vacuum for ejector-driven cups. Simulated with MuJoCo's adhesion actuator. |
| Gravity | compensated in the controller | An industrial controller feeds its dynamic model forward. |
| Max joint acceleration | 6 rad/s^2 | Not published. |
| Max Cartesian speed | 2 m/s, 2 rad/s | Not published. |
| Cameras | plain cameras, one high overhead and one on the tool, 640 x 480 | The playground's usual pair. |
| Mounting | on the floor | Data sheet: mounting position "Floor". |
