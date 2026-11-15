"""LIBERO stations: every task's whole room loads in MuJoCo 4 as a playground station (moved
and turned, beside another station), its official starting layouts apply, and our goal checks
agree with LIBERO's own on test scenes recorded in LIBERO's stack
(playground/tools/libero_crosscheck.py)."""
import json
import pathlib

import mujoco
import numpy as np
import pytest

from playground import libero as LB
from playground import world as W

CROSS = pathlib.Path(LB.__file__).parent / "libero_assets" / "crosscheck"
WIDTH = {0: 7, 1: 4, 2: 1, 3: 1}


def test_forty_tasks():
    assert {k: len(LB.tasks(k)) for k, _, _ in LB.SUITES} == {
        "libero_goal": 10, "libero_spatial": 10, "libero_object": 10, "libero_10": 10}
    for t in LB.tasks():
        assert len(t.states) == 50
        assert LB.done_when(t)
        assert LB.goal_parts(t)


def _set_libero_qpos(m, d, t, q, prefix, origin, yaw):
    """A recorded LIBERO scene, put into the station's room (loose objects moved to the world)."""
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    qyaw = np.array([np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)])
    for j in t.meta["joints"]:
        if j["name"].startswith(("robot0_", "gripper0_", "mount0_")):
            continue
        a, w = j["qposadr"], WIDTH[j["type"]]
        v = np.array(q[a:a + w], float)
        if w == 7:
            v[:3] = R @ v[:3] + np.asarray(origin, float)
            qq = np.zeros(4)
            mujoco.mju_mulQuat(qq, qyaw, v[3:])
            v[3:] = qq
        d.qpos[m.joint(prefix + j["name"]).qposadr[0]:][:w] = v


@pytest.mark.parametrize("t", LB.tasks(), ids=lambda t: f"{t.suite}-{t.index}")
def test_task(t):
    st = W.Station("st2", "franka", (4.0, -3.0), 0.7, "LIBERO 1", kind="libero", task=t.id)
    m = W.build([], [W.Station("st1", "franka", (0.0, 0.0), 0.0, "Robot 1"), st])
    d = mujoco.MjData(m)
    origin, yaw = W.libero_origin(st)
    ck = LB.Checker(m, t, st.prefix, origin, yaw)
    for cam in ("overhead", "side"):
        assert m.camera(st.prefix + cam).id >= 0
    # The official starting layouts: none starts with the goal already met (as in LIBERO).
    arm = [m.joint(f"{st.prefix}joint{i}").qposadr[0] for i in range(1, 8)]
    for k in (0, 1, 2):
        mujoco.mj_resetData(m, d)
        LB.apply_setup(m, d, t, k, arm, st.prefix, origin, yaw)
        mujoco.mj_forward(m, d)
        assert not ck.check(d)
        assert not all(ck.each(d))
    # Our checks agree with LIBERO's on the recorded test scenes, in a moved and turned room.
    cases = json.loads((CROSS / t.suite / f"{t.index:02d}" / "cases.json").read_text())
    for c in cases:
        mujoco.mj_resetData(m, d)
        _set_libero_qpos(m, d, t, np.array(c["qpos"]), st.prefix, origin, yaw)
        mujoco.mj_forward(m, d)
        assert [ck.check_one(d, g) for g in t.goal] == c["verdict"]
