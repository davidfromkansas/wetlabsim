"""LIBERO test mode: every task's scene loads in MuJoCo 4 with our Franka, its official
starting setups apply, and our success checks agree with LIBERO's own on test scenes
recorded in LIBERO's stack (playground/tools/libero_crosscheck.py)."""
import json
import pathlib

import mujoco
import numpy as np
import pytest

from playground import libero as LB

CROSS = pathlib.Path(LB.__file__).parent / "libero_assets" / "crosscheck"
WIDTH = {0: 7, 1: 4, 2: 1, 3: 1}


def test_forty_tasks():
    assert {k: len(LB.tasks(k)) for k, _, _ in LB.SUITES} == {
        "libero_goal": 10, "libero_spatial": 10, "libero_object": 10, "libero_10": 10}
    for t in LB.tasks():
        assert len(t.states) == 50
        assert LB.done_when(t)


def _set_libero_qpos(m, d, t, q):
    for j in t.meta["joints"]:
        if j["name"].startswith(("robot0_", "gripper0_", "mount0_")):
            continue
        a, w = j["qposadr"], WIDTH[j["type"]]
        d.qpos[m.joint(j["name"]).qposadr[0]:][:w] = q[a:a + w]


@pytest.mark.parametrize("t", LB.tasks(), ids=lambda t: f"{t.suite}-{t.index}")
def test_task(t):
    m = LB.build(t)
    d = mujoco.MjData(m)
    ck = LB.Checker(m, t)
    # The official starting setups: none starts with the goal already met (as in LIBERO).
    arm = [m.joint(f"joint{i}").qposadr[0] for i in range(1, 8)]
    for k in (0, 1, 2):
        mujoco.mj_resetData(m, d)
        LB.apply_setup(m, d, t, k, arm)
        mujoco.mj_forward(m, d)
        assert not ck.check(d)
    # Our checks agree with LIBERO's on the recorded test scenes.
    f = CROSS / t.suite / f"{t.index:02d}" / "cases.json"
    cases = json.loads(f.read_text())
    for c in cases:
        mujoco.mj_resetData(m, d)
        _set_libero_qpos(m, d, t, np.array(c["qpos"]))
        mujoco.mj_forward(m, d)
        assert [ck.check_one(d, g) for g in t.goal] == c["verdict"]
