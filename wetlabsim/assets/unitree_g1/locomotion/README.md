# G1 balance and walking policies

NVIDIA's GR00T WholeBodyControl policies for the Unitree G1, the ones LeRobot's
`GrootLocomotionController` runs on the G1 in simulation and on the real robot
(`lerobot/robots/unitree_g1/controllers/gr00t_locomotion.py`). `wetlabsim/locomotion.py` runs
them the same way: 50 Hz, 6 frames of 86 observations, 15 leg and waist position targets.

| File | SHA-256 |
| --- | --- |
| `GR00T-WholeBodyControl-Balance.onnx` | `f645da599d4ca3d29ed273c8f4712620bb680d34977469ca3aeabe5bb9631c18` |
| `GR00T-WholeBodyControl-Walk.onnx` | `7c82255b6905ffcc4468fa7f8ddcf7b70db168cf1042107ccab887cb6a8e5407` |

Source: Hugging Face `nepyope/GR00T-WholeBodyControl_g1` (revision 7bb8a672), the files
LeRobot downloads. License: NVIDIA Open Model License (`LICENSE`, from
NVlabs/GR00T-WholeBodyControl). Unchanged.

These run inside the robot's controller; agents don't get them (run_agent's KIT_LEAVE_OUT).
