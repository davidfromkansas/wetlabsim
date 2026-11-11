"""Jev's step loop (wetlabsim/jev_agent.py): its moves, what it asks, and how its steps reach the chat."""
import json
import math
import sys

import numpy as np

from wetlabsim import robot as robot_client

sys.modules.setdefault("wetlabsim.robot", robot_client)
from wetlabsim import jev_agent as J  # noqa: E402
from wetlabsim import traces  # noqa: E402


class FakeRobot:
    def __init__(self):
        self.calls = []

    def move_l(self, pose, speed=0.25, wait=True):
        self.calls.append(("move_l", pose))

    def gripper_open(self, wait=True):
        self.calls.append(("open",))
        return {"position": 0}

    def gripper_close(self, force=150, wait=True):
        self.calls.append(("close",))
        return {"position": 200, "object_detected": True}

    def unlock_protective_stop(self):
        self.calls.append(("unlock",))


DOWN = [0.45, 0.0, 0.30, math.pi, 0.0, 0.0]


def test_rotvec_round_trip():
    for r in ([0, 0, 0], [0.3, -0.2, 0.1], [math.pi, 0, 0], [0, math.pi, 0], [3.0, 0.4, 0]):
        R = J._rotvec_to_mat(r)
        assert np.allclose(J._rotvec_to_mat(J._mat_to_rotvec(R)), R, atol=1e-6)


def test_moves_keep_the_hand_pointing_down():
    r = FakeRobot()
    J.carry_out(r, "down", "small", {"tcp_pose": DOWN})
    assert np.allclose(r.calls[-1][1], [0.45, 0.0, 0.29, math.pi, 0, 0])
    J.carry_out(r, "left", "large", {"tcp_pose": DOWN})
    assert np.allclose(r.calls[-1][1][:3], [0.45, 0.05, 0.30])
    J.carry_out(r, "turn_left", "small", {"tcp_pose": DOWN})
    R = J._rotvec_to_mat(r.calls[-1][1][3:])
    assert np.allclose(R[:, 2], [0, 0, -1], atol=1e-9)          # still pointing straight down
    assert abs(math.atan2(R[1, 0], R[0, 0]) - math.radians(15)) < 1e-6
    assert J.carry_out(r, "close_gripper", "small", {"tcp_pose": DOWN}) == "closed the fingers on something"


def test_questions_follow_the_api():
    cal = {"rotation": np.diag([1.0, -1.0, -1.0]).tolist()}   # a camera looking straight down
    qs = J.questions(cal)
    assert {q["type"] for q in qs.values()} <= {"choice", "noul", "score", "box"}
    assert all(len(q["criteria"]) <= 255 for q in qs.values() if q["type"] == "choice")
    assert "toward the right of `overhead`" in qs["move"]["criteria"]["forward"]
    assert "toward the top of `overhead`" in qs["move"]["criteria"]["left"]


def test_steps_reach_the_chat_with_everything_jev_sent():
    ans = {"move": {"type": "choice", "choice": "down", "confidence": 0.8, "probabilities": {"down": 0.9, "up": 0.1}},
           "target": {"type": "box", "box": {"top": 0.1, "bottom": 0.3, "left": 0.2, "right": 0.4}, "confidence": None}}
    ev = {"type": "_jev", "kind": "step", "step": 3, "model": "jev-1.14.0", "seconds": 0.4, "answers": ans,
          "usage": {"input_tokens": 1000, "output_tokens": 20}, "input_tokens_total": 3000, "cost_usd": 0.000126,
          "camera_time": 12.5, "did": "moved down 1 cm", "ok": True, "_sim_time": 13.0}
    steps = traces.Parser().feed(ev)
    assert [s.kind for s in steps] == ["decides"]
    d = json.loads(steps[0].text)
    assert d["answers"] == ans and d["model"] == "jev-1.14.0" and d["did"] == "moved down 1 cm"
    meta = traces.RunMeta("jev", "jev-1.14.0")
    assert meta.feed(ev)
    info = meta.info()
    assert info["provider"] == "TypeSafe" and info["input_tokens"] == 3000 and info["cost_usd"] == 0.000126


def test_memory_entry_says_what_jev_chose_and_what_happened():
    ans = {"goal": {"type": "choice", "choice": "grasp", "probabilities": {"grasp": 0.82, "lift": 0.18}},
           "move": {"type": "choice", "choice": "close_gripper", "probabilities": {"close_gripper": 0.6, "up": 0.4}},
           "step": {"type": "choice", "choice": "small", "probabilities": {"small": 1.0}}}
    e = J.memory_entry(4, ans, "closed the fingers (nothing between them)",
                       {"gripper": {"position": 255, "object_detected": False}})
    assert e == {"step": 4, "goal": "grasp (82% sure)", "move": "close_gripper (60% sure)", "step_size": "small",
                 "result": "closed the fingers (nothing between them)", "fingers_after": "closed"}
