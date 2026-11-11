"""Quick checks that the cell builds and the controller behaves. Run: python -m pytest tests"""
import time

import mujoco
import numpy as np
import pytest


from wetlabsim import scene as S
from wetlabsim.sim import Sim, quat_from_rotvec, rotvec_from_quat


def test_rotvec_roundtrip():
    rv = np.array([0.3, -1.2, 2.0])
    assert np.allclose(rotvec_from_quat(quat_from_rotvec(rv)), rv, atol=1e-9)


ROBOTS = list(S.CELL_ROBOTS)


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


# ---------------------------------------------------------------- task library
def _step(s, secs, before=None):
    for _ in range(int(secs / s.m.opt.timestep)):
        if before:
            before()
        mujoco.mj_step(s.m, s.d)


@pytest.mark.parametrize("task", [None, "T1", "T7", "T18", "T19", "T23"])
def test_task_layouts_settle(task):
    """Every task's starting bench is still after 3 s, and doing nothing doesn't pass it."""
    from wetlabsim import tasks as T
    s = Sim(robot="franka")
    s.reset(task)
    g0 = s.ground_truth()
    _step(s, 3.0)
    g1 = s.ground_truth()
    for n in g0["objects"]:
        assert np.linalg.norm(np.subtract(g1["objects"][n]["pos"], g0["objects"][n]["pos"])) < 0.003, n
    if task:
        assert not T.score(task, g0, g1, {"judge": {"score": 0}})["passed"]


def test_tube_stays_in_a_full_strength_grip():
    """A light tube held at full grip doesn't creep out of the fingers (it used to)."""
    s = Sim(robot="franka")
    s.reset("T1")
    p = np.array(s.ground_truth()["objects"]["tube_red"]["pos"])

    def go(mo):
        while not mo.done.is_set():
            _step(s, 0.05, s._control)
        _step(s, 0.3, s._control)

    go(s.move_l([p[0], p[1], 0.25, np.pi, 0, 0], 0.3))
    go(s.move_l([p[0], p[1], 0.10, np.pi, 0, 0], 0.08))
    s.gripper_move(255, 255, 255)
    _step(s, 1.5, s._control)
    go(s.move_l([p[0], p[1], 0.30, np.pi, 0, 0], 0.15))
    p0 = np.array(s.ground_truth()["objects"]["tube_red"]["pos"])
    _step(s, 20.0, s._control)
    p1 = np.array(s.ground_truth()["objects"]["tube_red"]["pos"])
    assert np.linalg.norm(p1 - p0) < 0.002
    assert s.mode == "running"


def test_agent_workspace_never_names_the_cell_folder(tmp_path):
    """Nothing the agent can read may point at the repo (it once found it in .mcp.json)."""
    from wetlabsim import run_agent as RA
    ws, client = tmp_path / "ws", tmp_path / "client"
    ws.mkdir(), client.mkdir()
    info = {"camera_calibration": Sim(robot="franka").calibration()}
    RA.prepare_workspace(ws, client, "franka", "standard", "Move the red tube.", info)
    RA.build_command("claude", "Move the red tube.", None, ws, tmp_path, "")
    assert RA.workspace_leaks(ws, client) == []
    (ws / "oops.json").write_text(str(RA.ROOT))
    assert RA.workspace_leaks(ws, client) == [ws / "oops.json"]
