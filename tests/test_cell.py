"""Quick checks that the cell builds and the controller behaves. Run: python -m pytest tests"""
import time

import numpy as np
import pytest


from wetlabsim import scene as S
from wetlabsim.sim import Sim, quat_from_rotvec, rotvec_from_quat


def test_rotvec_roundtrip():
    rv = np.array([0.3, -1.2, 2.0])
    assert np.allclose(rotvec_from_quat(quat_from_rotvec(rv)), rv, atol=1e-9)


ROBOTS = list(S.ROBOTS)


@pytest.mark.parametrize("robot", ROBOTS)
def test_tubes_settle_in_racks(robot):
    s = Sim(robot=robot)
    gt = s.ground_truth()["objects"]
    tubes = {f"tube_{c}" for *_, c, _ in S.TUBES}
    assert tubes <= set(gt)
    for name in tubes:
        o = gt[name]
        assert abs(o["pos"][2] - (S.RACK_FLOOR + S.TUBE_HALF_LEN)) < 0.003, name


@pytest.mark.parametrize("robot", ROBOTS)
def test_ik_matches_fk(robot):
    s = Sim(robot=robot)
    p, R = s._fk(s.ready_q)
    from wetlabsim.sim import quat_from_mat
    q = s.ik(p + np.array([0.05, -0.1, -0.05]), quat_from_mat(R), s.ready_q)
    assert q is not None
    p2, _ = s._fk(q)
    assert np.linalg.norm(p2 - (p + np.array([0.05, -0.1, -0.05]))) < 1e-3


@pytest.mark.parametrize("robot", ROBOTS)
def test_move_and_force_reading(robot):
    s = Sim(robot=robot)
    s.start()
    try:
        time.sleep(0.3)
        f = np.array(s.state()["tcp_force"][:3])
        assert np.linalg.norm(f) < 3.0           # gripper weight is compensated
        target = [0.45, 0.0, 0.25, np.pi, 0, 0]
        mo = s.move_l(target, speed=0.5)
        assert mo.done.wait(15) and mo.result == "done"
        assert np.allclose(s.state()["tcp_pose"][:3], target[:3], atol=0.004)
    finally:
        s.stop_threads()


@pytest.mark.parametrize("robot", ROBOTS)
def test_gripper_opens_and_closes(robot):
    s = Sim(robot=robot)
    s.start()
    try:
        time.sleep(0.2)
        assert s.gripper_status()["position"] < 10          # starts open
        s.gripper_move(255)
        time.sleep(1.5)
        g = s.gripper_status()
        assert g["position"] > 230 and not g["object_detected"]   # closed on nothing
        s.gripper_move(0)
        time.sleep(1.5)
        assert s.gripper_status()["position"] < 10
    finally:
        s.stop_threads()


def test_franka_joint_speed_limits():
    """A fast joint move is slowed down to Franka's rated joint speeds."""
    s = Sim(robot="franka")
    s.start()
    try:
        time.sleep(0.2)
        q = s.ready_q.copy()
        q[0] += 1.5
        mo = s.move_j(q, speed=10.0)
        peak = np.zeros(7)
        while not mo.done.is_set():
            peak = np.maximum(peak, np.abs(s.d.qvel[s.arm_dadr]))
            time.sleep(0.005)
        assert mo.result == "done"
        assert np.all(peak <= s.P["joint_vmax"] * 1.1), peak
    finally:
        s.stop_threads()


def test_franka_stops_when_pushing_into_bench():
    s = Sim(robot="franka")
    s.start()
    try:
        time.sleep(0.2)
        s.gripper_move(255)
        mo = s.move_l([0.30, 0.0, -0.05, np.pi, 0, 0], speed=0.2)   # 5 cm into the bench
        mo.done.wait(20)
        assert s.mode == "protective_stop", mo.result
    finally:
        s.stop_threads()


def test_standard_docs_workspace(tmp_path):
    """The default (standard) workspace has Franka's documents, the robot model, the
    calibration and a command reference, and its client has no pixel/point helpers."""
    from wetlabsim import run_agent as RA
    ws, client = tmp_path / "ws", tmp_path / "client"
    ws.mkdir(), client.mkdir()
    info = {"camera_calibration": Sim(robot="franka").calibration()}
    RA.prepare_workspace(ws, client, "franka", "standard", "Move the red tube.", info)
    names = {p.name for p in ws.iterdir()}
    assert {"GOAL.md", "COMMANDS.md", "SITE.md", "cameras.json", "datasheets", "robot_model"} <= names
    assert "ROBOT_MANUAL.md" not in names
    assert (ws / "robot_model" / "panda.xml").exists()
    assert any(p.suffix == ".pdf" for p in (ws / "datasheets").iterdir())
    robot_py = (client / "wetlabsim" / "robot.py").read_text()
    assert "pixel_to_point" not in robot_py and "def get_camera_frame" in robot_py


def test_run_meta_reads_model_and_usage():
    from wetlabsim import traces
    assert traces.model_label("claude-opus-5-5") == "Claude Opus 5.5"
    assert traces.model_label("gpt-6-astra") == "GPT-6 Astra"
    assert traces.model_label("swe-2-flash-medium") == "SWE-2 Flash Medium"
    m = traces.RunMeta("claude")
    m.feed({"type": "system", "subtype": "init", "model": "claude-opus-5-5"})
    m.feed({"type": "result", "total_cost_usd": 0.5,
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5}})
    i = m.info()
    assert (i["provider"], i["tokens"], i["cached_tokens"], i["cost_usd"]) == ("Anthropic", 105, 90, 0.5)
    c = traces.RunMeta("codex", "gpt-6-astra")
    c.feed({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 7}})
    assert c.info()["tokens"] == 107 and c.info()["provider"] == "OpenAI"
