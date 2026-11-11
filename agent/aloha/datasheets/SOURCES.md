# ALOHA documents given to agents

These are the makers' own documents, unchanged: Trossen Robotics (the ViperX 300 S arms and
the ALOHA kit) and ROBOTIS (the DYNAMIXEL servos in the arms). Agents get a copy in their
workspace (`datasheets/`), because they have no web access during a run. All four are web
pages saved as HTML (neither maker publishes them as PDFs).

| File | Source | Downloaded | What's in it |
| --- | --- | --- | --- |
| `Trossen ViperX-300 6DOF Specifications.html` | <https://docs.trossenrobotics.com/interbotix_xsarms_docs/specifications/vx300s.html> | 2026-11-11 | The arm: 6 DOF, 750 mm reach, 750 g working payload, 1 mm repeatability, 5-8 mm accuracy, joint limits, servo per joint. |
| `Trossen ALOHA Specifications.html` | <https://docs.trossenrobotics.com/aloha_docs/2.0/specifications.html> | 2026-11-11 | The ALOHA Stationary kit: two ViperX 300 S follower arms, four Intel RealSense D405 cameras. |
| `ROBOTIS DYNAMIXEL XM540-W270 e-Manual.html` | <https://emanual.robotis.com/docs/en/dxl/x/xm540-w270/> | 2026-11-11 | Servo of the first five joints. |
| `ROBOTIS DYNAMIXEL XM430-W350 e-Manual.html` | <https://emanual.robotis.com/docs/en/dxl/x/xm430-w350/> | 2026-11-11 | Servo of the wrist rotate joint and the gripper. |

SHA-256 checksums are in `sources.json`; `python -m wetlabsim.datasheets` checks them and
downloads any file that is missing. These are live web pages, so a changed checksum is only
reported.

## Where the simulator's numbers come from

| Simulator setting | Value | Source |
| --- | --- | --- |
| Arm model (links, masses, joint ranges, servo gains, damping, friction) | DeepMind MuJoCo Menagerie `aloha`, unchanged | Menagerie (system-identified on a real ALOHA 2) |
| Max joint speed | 3.14 rad/s (waist to wrist angle), 4.82 rad/s (wrist rotate) | XM540-W270: 30 rev/min at 12 V; XM430-W350: 46 rev/min at 12 V (no-load speed) |
| Gripper travel | 2-37 mm per finger from centre (fully closed to fully open) | Menagerie, measured on the real gripper |
| Cameras | 4 x RealSense D405 (overhead, low, one per wrist), 640 x 480, 58° vertical field of view | ALOHA kit list; Menagerie camera poses; Intel D405 field of view |
| Wrist force/torque | none | The ViperX has no force/torque sensor |

Our own choices (no published number):

- Max joint acceleration 10 rad/s², max tool speed 0.5 m/s and 3 rad/s: the servos'
  profile settings are user-set, so these are our settings, not Trossen's defaults.
- Protective stop: only when an arm can't follow its commanded path (tracking error), as
  for the other robots. The ViperX has no force-based stop.
