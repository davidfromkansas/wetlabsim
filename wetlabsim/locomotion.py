"""The Unitree G1's balance and walking controller: NVIDIA's GR00T whole-body-control policies.

These are the two policies LeRobot runs on the G1, in simulation and on the real robot, as its
GrootLocomotionController (lerobot/robots/unitree_g1/controllers/gr00t_locomotion.py), here with
the same inputs, scaling and switching: a balance policy for standing and a walking policy for
moving, each a small network that reads the robot's own sensors 50 times a second (the pelvis
IMU, all 29 joint encoders and its last output) and sets position targets for the 12 leg joints
and 3 waist joints. Weights: Hugging Face nepyope/GR00T-WholeBodyControl_g1 (NVIDIA Open Model
License; assets/unitree_g1/locomotion).
"""
from __future__ import annotations

import pathlib
from collections import deque

import numpy as np

POLICIES = pathlib.Path(__file__).parent / "assets" / "unitree_g1" / "locomotion"
CONTROL_DT = 0.02                     # 50 Hz
ACTION_SCALE = 0.25
ANG_VEL_SCALE, DOF_VEL_SCALE = 0.25, 0.05
CMD_SCALE = np.array([2.0, 2.0, 0.25], np.float32)
# The stance both policies act around (LeRobot's GROOT_DEFAULT_ANGLES), Unitree's 29-joint order.
DEFAULT_ANGLES = np.zeros(29, np.float32)
DEFAULT_ANGLES[[0, 6]] = -0.1         # hip pitch
DEFAULT_ANGLES[[3, 9]] = 0.3          # knee
DEFAULT_ANGLES[[4, 10]] = -0.2        # ankle pitch
HEIGHT_DEFAULT = 0.74                 # LeRobot's default pelvis height command (m)
# The ranges LeRobot's G1 teleoperation can command: joystick axes (-1..1) as walking speed and
# turn rate, and the pelvis height buttons (0.50..1.00 m). Measured here: the robot walks at about
# 0.9 m/s for a command of 1.0 and turns about 0.8 rad/s for 1.0; above about 0.79 m the legs are
# straight, so higher height commands change nothing.
VX_RANGE, VY_RANGE, YAW_RANGE = (-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)
HEIGHT_RANGE = (0.50, 1.00)
# The policies' torso orientation command (roll, pitch, yaw of the torso, rad). LeRobot leaves it
# at zero; the policies were trained with it. Measured here: pitch 0.4 leans the torso forward
# 0.4 rad at the waist, -0.2 leans back about 0.1. We allow what the waist joints allow (±0.52).
LEAN_RANGE = (-0.52, 0.52)


def gravity_orientation(q) -> np.ndarray:
    """Gravity in the IMU frame, from its orientation quaternion [w, x, y, z] (LeRobot's
    get_gravity_orientation)."""
    qw, qx, qy, qz = q
    return np.array([2 * (-qz * qx + qw * qy), -2 * (qz * qy + qw * qx), 1 - 2 * (qw * qw + qz * qz)],
                    np.float32)


class GrootLocomotion:
    """Balance + walk policies with their observation history (6 frames of 86 values)."""

    _sessions = None

    def __init__(self):
        if GrootLocomotion._sessions is None:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1       # tiny networks: one thread is fastest (as LeRobot)
            so.inter_op_num_threads = 1
            so.log_severity_level = 3
            GrootLocomotion._sessions = tuple(
                ort.InferenceSession(str(POLICIES / f"GR00T-WholeBodyControl-{n}.onnx"), sess_options=so)
                for n in ("Balance", "Walk"))
        self.balance, self.walk = GrootLocomotion._sessions
        self.reset()

    def reset(self):
        self.cmd = np.zeros(3, np.float32)            # vx, vy (m/s), yaw rate (rad/s)
        self.height = HEIGHT_DEFAULT
        self.lean = np.zeros(3, np.float32)           # torso roll, pitch, yaw
        self.action = np.zeros(15, np.float32)
        self.history = deque([np.zeros(86, np.float32) for _ in range(6)], maxlen=6)
        self.fresh = True

    def step(self, quat, gyro, q29, dq29) -> np.ndarray:
        """One 50 Hz step: the 15 leg and waist position targets (rad)."""
        o = np.zeros(86, np.float32)
        o[:3] = self.cmd * CMD_SCALE
        o[3] = self.height
        o[4:7] = self.lean
        o[7:10] = np.asarray(gyro, np.float32) * ANG_VEL_SCALE
        o[10:13] = gravity_orientation(quat)
        o[13:42] = np.asarray(q29, np.float32) - DEFAULT_ANGLES
        o[42:71] = np.asarray(dq29, np.float32) * DOF_VEL_SCALE
        o[71:86] = self.action
        if self.fresh:          # the first step after a reset: the history is this moment, six times
            self.history.extend([o.copy() for _ in range(6)])
            self.fresh = False
        self.history.append(o)
        x = np.concatenate(self.history)[None]
        pol = self.balance if np.linalg.norm(self.cmd) < 0.05 else self.walk
        self.action = pol.run(None, {pol.get_inputs()[0].name: x})[0].squeeze().astype(np.float32)
        return DEFAULT_ANGLES[:15] + self.action * ACTION_SCALE
