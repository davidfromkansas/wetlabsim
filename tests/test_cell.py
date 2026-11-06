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
    assert set(gt) == {f"tube_{c}" for *_, c, _ in S.TUBES}
    for name, o in gt.items():
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
