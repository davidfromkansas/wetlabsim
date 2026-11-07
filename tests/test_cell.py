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


# ---------------------------------------------------------------- task library, caps, clamp
def _step(s, secs, before=None):
    for _ in range(int(secs / s.m.opt.timestep)):
        if before:
            before()
        s.threads.step()
        mujoco.mj_step(s.m, s.d)


@pytest.mark.parametrize("task", [None, "T1", "T7", "T18", "T23", "T24", "T25"])
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


class _Hand:
    """Stands in for fingers on a cap: an outside twist (and push) the thread controller counts
    as if it came through contacts."""

    def __init__(self, s, cap):
        self.s, self.cap, self.tq, self.push = s, cap, 0.0, 0.0
        measured = s.threads._contacts
        s.threads._contacts = lambda c: (
            (measured(c)[0] + self.tq, measured(c)[1]) if c is cap else measured(c))

    def apply(self, tq, push, secs):
        self.tq = tq
        s, cap = self.s, self.cap

        def before():
            axis = s.d.xmat[cap.tube].reshape(3, 3)[:, 2]
            s.d.xfrc_applied[cap.cap, :3] = -push * axis
            s.d.xfrc_applied[cap.cap, 3:6] = tq * axis
        _step(s, secs, before)
        s.d.xfrc_applied[cap.cap] = 0
        self.tq = 0.0


def _cap_on_rim(s, cap, tilt_deg=0.0, offset=0.0):
    """Set a loose cap on its tube's rim (optionally tilted about x and off-centre along x)."""
    m, d = s.m, s.d
    ta, ca = m.jnt_qposadr[m.body_jntadr[cap.tube]], m.jnt_qposadr[m.body_jntadr[cap.cap]]
    tp = d.qpos[ta:ta + 3].copy()
    a = np.radians(tilt_deg)
    d.qpos[ca:ca + 3] = tp + [offset, 0, S.CAP_SEAT + S.THREAD_LEN + 0.0005]
    d.qpos[ca + 3:ca + 7] = [np.cos(a / 2), np.sin(a / 2), 0, 0]
    d.qvel[m.jnt_dofadr[m.body_jntadr[cap.cap]]:][:6] = 0
    _step(s, 0.5)


def test_screw_cap_unscrews():
    s = Sim(robot="franka")
    s.reset("T24")                             # red tube in the clamp, cap tight
    th = s.threads
    hand = _Hand(s, th.by_colour["red"])
    hand.apply(0.05, 0, 1.0)                   # below its tightness: holds
    assert th.state()["red"]["seated"]
    hand.apply(0.15, 0, 0.5)                   # breaks loose and climbs the thread
    st = th.state()["red"]
    assert st["on"] and not st["seated"] and st["turns_from_seated"] > 0.5
    for _ in range(40):
        if not th.state()["red"]["on"]:
            break
        hand.apply(0.02, 0, 0.2)
    assert not th.state()["red"]["on"]


def test_square_pressed_cap_screws_on_and_tightens():
    s = Sim(robot="franka")
    s.reset("T25")                             # tube in the clamp, cap off
    th = s.threads
    cap = th.by_colour["red"]
    _cap_on_rim(s, cap, tilt_deg=1.0, offset=0.0006)
    hand = _Hand(s, cap)
    hand.apply(-0.02, 2.0, 0.3)
    assert th.state()["red"]["on"] and not th.state()["red"]["cross_threaded"]
    for _ in range(60):
        hand.apply(-0.02, 2.0, 0.25)
        if th.state()["red"]["seated"]:
            break
    hand.apply(-0.08, 2.0, 0.5)
    st = th.state()["red"]
    assert st["seated"] and st["tightness_nm"] >= 0.06
    # The thread centred it: seated square on the axis.
    Rt = s.d.xmat[cap.tube].reshape(3, 3)
    rel = Rt.T @ (s.d.xpos[cap.cap] - s.d.xpos[cap.tube])
    assert np.hypot(rel[0], rel[1]) < 0.0002


def test_cap_resting_without_a_push_does_not_catch():
    s = Sim(robot="franka")
    s.reset("T25")
    th = s.threads
    cap = th.by_colour["red"]
    _cap_on_rim(s, cap)
    _Hand(s, cap).apply(-0.02, 0.0, 1.0)        # twisting, but not pressing on
    assert not th.state()["red"]["on"]


def _catch_held(s, cap, tilt_deg=0.0, offset=0.0, lift=0.0):
    """Pose a cap as fingers would hold it on the rim, pressed and twisted closed, and ask
    the thread whether it catches."""
    m, d = s.m, s.d
    ta, ca = m.jnt_qposadr[m.body_jntadr[cap.tube]], m.jnt_qposadr[m.body_jntadr[cap.cap]]
    a = np.radians(tilt_deg)
    d.qpos[ca:ca + 3] = d.qpos[ta:ta + 3] + [offset, 0, S.CAP_SEAT + S.THREAD_LEN + lift]
    d.qpos[ca + 3:ca + 7] = [np.cos(a / 2), np.sin(a / 2), 0, 0]
    mujoco.mj_forward(m, d)
    s.threads._contacts = lambda c: (-0.02, 2.0)
    s.threads._try_catch(cap)
    return s.threads.state()["red"]


def test_catching_the_thread_needs_a_square_centred_cap_on_the_rim():
    s = Sim(robot="franka")
    cap = s.threads.by_colour["red"]
    for kw, on, cross in [({}, True, False), ({"tilt_deg": 2.0, "offset": 0.0008}, True, False),
                          ({"tilt_deg": 4.0}, True, True), ({"tilt_deg": 7.0}, False, False),
                          ({"offset": 0.0015}, False, False), ({"lift": 0.0012}, False, False)]:
        s.reset("T25")
        st = _catch_held(s, cap, **kw)
        assert (st["on"], st["cross_threaded"]) == (on, cross), kw


def test_cross_threaded_cap_binds_and_never_seats():
    s = Sim(robot="franka")
    s.reset("T25")
    th = s.threads
    cap = th.by_colour["red"]
    measured = th._contacts
    _catch_held(s, cap, tilt_deg=4.0)
    th._contacts = measured
    hand = _Hand(s, cap)
    for _ in range(40):
        hand.apply(-0.05, 2.0, 0.25)
    st = th.state()["red"]
    assert st["on"] and st["cross_threaded"] and not st["seated"]
    assert st["turns_from_seated"] > 1.0


def test_clamp_holds_a_tube_against_twisting():
    s = Sim(robot="franka")
    s.reset("T24")
    tid = s.m.body("tube_red").id
    q0 = s.d.xquat[tid].copy()
    _step(s, 1.0, lambda: s.d.xfrc_applied.__setitem__((tid, 5), 0.15))
    s.d.xfrc_applied[tid] = 0
    turned = np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(q0, s.d.xquat[tid]))))))
    assert turned < 10, turned


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


def test_cap_on_its_thread_stays_square_when_pushed():
    s = Sim(robot="franka")
    s.reset("T24")
    cap = s.threads.by_colour["red"]
    _step(s, 1.0, lambda: s.d.xfrc_applied.__setitem__((cap.cap, 0), 10.0))
    Rt = s.d.xmat[cap.tube].reshape(3, 3)
    tilt = np.degrees(np.arccos(min(1.0, (Rt.T @ s.d.xmat[cap.cap].reshape(3, 3))[2, 2])))
    assert tilt < 0.5, tilt
