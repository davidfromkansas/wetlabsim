# CRX-30iA documents given to agents

FANUC's own data sheet, unchanged. Agents get a copy in their workspace (`datasheets/`), because
they have no web access during a run.

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `FANUC CRX-30iA data sheet.pdf` | <https://fanucamerica.com/docs/default-source/robotics-files/crx-30ia-data-sheet.pdf> | 2026-11-15 | 30 kg payload at 1756 mm reach (25 kg at 1889 mm), 6 axes, ±0.05 mm repeatability, 135 kg, motion ranges, collaborative mode 1000 mm/s and high-speed mode 2000 mm/s, allowable wrist moments and inertias, operating space drawing. |

The SHA-256 checksum is in `sources.json`; `python -m wetlabsim.datasheets` checks it and
downloads the file if it is missing.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, inertias, joint frames, collision shapes, colours) | FANUC's own SimReady package, Hugging Face `FANUC-CORPORATION/SimReady-Assets`, `crx30ia` (Apache 2.0), converted by `playground/tools/convert_simready_arm.py` | Package |
| Motion ranges | J1 ±179.9°, J2 ±179.9°, J3 ±270°, J4 ±190°, J5 ±179.9°, J6 ±225° | Package; the data sheet's 360, 360, 540, 380, 360, 450° in all |
| Max joint speed | 80, 80, 120, 180, 180, 180 deg/s | Package (the data sheet gives none per axis) |
| Position-drive gains and torque limits | as the package states them (1500, 1500, 700, 150, 150, 120 N m) | Package |
| Max Cartesian speed | 1 m/s | Data sheet, collaborative mode |
| Links collide with each other | no | Package (`enabledSelfCollisions = false`) |

Where the model and the data sheet differ, the model is kept as it is:

- Weight. Model: 133 kg in all. Data sheet: 135 kg.

Our own choices (no published number):

| Setting | Value | Why |
| --- | --- | --- |
| Tool | a vacuum gripper: four 80 mm suction cups on a 400 x 260 mm frame, 2.8 kg, 160 mm from flange to cup faces | The package has no tool. Vacuum grippers are the usual CRX tool for cases, totes and tires. |
| Vacuum | 60 kPa below ambient over each cup's area: 300 N per cup, 1200 N in all; cups pull from 10 mm away | A usual working vacuum for ejector-driven cups. Simulated with MuJoCo's adhesion actuator. |
| Contact stop, hand guiding | not simulated | The playground reports no force readings for this arm. |
| Gravity | compensated in the controller | An industrial controller feeds its dynamic model forward. |
| Max joint acceleration | 8 rad/s^2 | Not published. |
| Cameras | plain cameras, one high overhead and one on the tool, 640 x 480 | The playground's usual pair. |
| Mounting | on the floor | The data sheet's standard model stands on its base. |
