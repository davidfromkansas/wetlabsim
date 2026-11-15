# NVIDIA GEAR-SONIC for the Unitree G1

The G1's whole-body controller (`wetlabsim/sonic.py`): NVIDIA's released SONIC model files,
unchanged, from Hugging Face `nvidia/GEAR-SONIC` at revision
`6733128a3d8a523b1418b06bca3cdf61c8b0987f` (NVIDIA Open Model License, `LICENSE` here):

| File | Size | What it is |
| --- | --- | --- |
| `model_encoder.onnx` | 50 MB | Turns the next second of reference motion into a 64-number motion token. |
| `model_decoder.onnx` | 41 MB | The controller: token + the robot's sensor history in, 29 joint targets out, 50 Hz. |
| `planner_sonic.onnx` | 774 MB | The kinematic planner (V2): movement style, direction, speed, facing and height in, the next ~2 s of whole-body motion out. |

The `.onnx` files are too big for git: `wetlabsim/sonic.py` downloads them here on first use
(`python -c "import wetlabsim.sonic as s; s.ensure_models()"`), and the hosted playground's
image downloads them when it is built. The code that runs them is a port of NVIDIA's own G1
deployment program (github.com/NVlabs/GR00T-WholeBodyControl, `gear_sonic_deploy`, Apache 2.0,
commit `1e1ec4f`).
