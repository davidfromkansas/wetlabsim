"""WetRobo stations: the same kit in two labs. Each lab builds for each task, its kit stands
settled (the lid seated on its dish), no task starts with its goal met, and each check holds
once its own goal does."""
import mujoco
import numpy as np
import pytest

from playground import catalog, site
from playground import wetrobo as WR
from playground.sim import PlaygroundSim


def _station(lab, task):
    s = PlaygroundSim()
    uid = s.add_station("franka", (3.0, 0.0), 0.0, kind=WR.LABS[lab][0], task=task)
    for _ in range(1500):
        mujoco.mj_step(s.m, s.d)
    return s, uid


def test_tasks_and_board():
    assert set(WR.TASKS) == {"lid", "cap", "incubator"}
    rows = [{"model": "m", "task": "lid", "lab": "x", "passed": True, "seconds": 10, "cost_usd": 0.1},
            {"model": "m", "task": "lid", "lab": "y", "passed": False, "seconds": 20, "cost_usd": 0.2}]
    b = WR.board(rows)["board"][0]
    assert b["cells"] == {"lid:x": {"tried": 1, "passed": 1}, "lid:y": {"tried": 1, "passed": 0}}
    assert b["labs"]["x"]["passed"] == 1 and b["labs"]["y"]["passed"] == 0 and b["avg_seconds"] == 15.0


def test_a_task_is_needed():
    with pytest.raises(Exception):
        PlaygroundSim().add_station("franka", (3.0, 0.0), 0.0, kind="wetrobo_x")


@pytest.mark.parametrize("lab", list(WR.LABS))
def test_lab(lab):
    s, uid = _station(lab, "lid")
    m, d = s.m, s.d
    st = s.station(uid)
    assert st.robot == "franka" and s.scene_info()["robots"][-1]["wetrobo"]["lab"] == lab
    sheet = site.site_sheet(s.placed, st, s.stations)        # the AI's sheet: the table, not the kit
    assert "incubator" not in sheet.lower() and "petri" not in sheet.lower()
    kit = {p.item: p for p in s._on_table(st) if p.item in WR.KIT}
    assert set(kit) == set(WR.KIT)
    for p in s._on_table(st):                         # everything stands upright, at rest
        b = m.body("obj_" + p.uid).id
        assert d.xmat[b].reshape(3, 3)[2, 2] > 0.95, p.item
    dish, lid = (m.body("obj_" + kit[k].uid).id for k in (WR.DISH, WR.LID))
    assert np.allclose(d.xpos[lid] - d.xpos[dish], [0, 0, WR.LID_SEAT], atol=0.002)   # the lid sits on its dish
    joints = WR.kit_joints(m, [(p.uid, p.item) for p in kit.values()], st.top)
    assert set(joints) == {"door", "cap", "dish", "lid", "top"}
    for t in WR.TASKS.values():                       # no task starts done
        assert not all(WR.check(t, joints, d)) and len(WR.check(t, joints, d)) == len(t.goal)
    assert s.wetrobo_goal(uid) == [False, True]
    # each check holds once its goal does: the door swung open, the cap unscrewed, the lid lifted
    d.qpos[joints["door"][0]] = joints["door"][1][1]
    assert WR.check(WR.task("incubator"), joints, d) == [True]
    assert WR.check(WR.task("cap"), joints, d) == [False]
    d.qpos[joints["cap"][0]] = joints["cap"][1][1]
    assert WR.check(WR.task("cap"), joints, d) == [True]
    a = m.joint(f"obj_{kit[WR.LID].uid}_joint").qposadr[0]
    d.qpos[a + 2] += 0.02                             # lifted, but not clear of the dish yet
    mujoco.mj_forward(m, d)
    assert s.wetrobo_goal(uid) == [False, True]
    d.qpos[a + 2] += 0.03
    mujoco.mj_forward(m, d)
    assert s.wetrobo_goal(uid) == [True, True]
    for _ in range(1500):                             # let go: it drops back onto the dish
        mujoco.mj_step(m, d)
    assert s.wetrobo_goal(uid) == [False, True]
    q = d.qpos.copy()
    lx, ly = st.to_local(*d.qpos[a:a + 2])
    d.qpos[a:a + 2] = st.to_world(lx, ly + (0.12 if ly < 0 else -0.12))[:2]  # set aside on the table: done
    for _ in range(1500):
        mujoco.mj_step(m, d)
    assert s.wetrobo_goal(uid) == [True, True]
    d.qpos[:] = q                                     # knocked off the table: the lid is off, but not done
    d.qvel[:] = 0
    d.qpos[a:a + 3] += [0.0, 0.0, -0.5]
    mujoco.mj_forward(m, d)
    assert s.wetrobo_goal(uid) == [True, False]
    b = m.joint(f"obj_{kit[WR.DISH].uid}_joint").qposadr[0]
    d.qpos[:] = q
    d.qpos[b + 2] -= 0.5                              # so is the dish knocked away from under its lid
    mujoco.mj_forward(m, d)
    assert s.wetrobo_goal(uid) == [True, False]


def _rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rotvec(R):
    q, v = np.zeros(4), np.zeros(3)
    mujoco.mju_mat2Quat(q, R.flatten())
    mujoco.mju_quat2Vel(v, q, 1.0)
    return v


def _step(sim, sec):
    for _ in range(int(sec / sim.m.opt.timestep)):
        for a in sim.arms.values():
            a._control()
        mujoco.mj_step(sim.m, sim.d)


def _go(sim, mo):
    t = 0.0
    while not mo.done.is_set() and t < 15:
        _step(sim, 0.05)
        t += 0.05
    _step(sim, 0.3)


@pytest.mark.parametrize("lab", list(WR.LABS))
@pytest.mark.parametrize("force", [0, 255])
def test_the_hand_lifts_the_lid_alone(lab, force):
    """The Franka Hand spans the lid; closed on its 1 mm skirt, the pads stop at the wall (they
    don't sink through it onto the dish), and the lid comes up alone: the task's goal."""
    s = PlaygroundSim(stations=[])
    uid = s.add_station("franka", (0.0, 0.0), 0.0, kind=WR.LABS[lab][0], task="lid")
    arm, m, d = s.arms[uid], s.m, s.d
    _step(s, 1.0)
    kit = {p.item: p for p in s.placed}
    dish, lid = (m.body("obj_" + kit[k].uid).id for k in (WR.DISH, WR.LID))
    top = s.station(uid).top
    pb = arm.to_base(d.xpos[lid].copy())
    pose = lambda z: [pb[0], pb[1], z, np.pi, 0, 0]
    arm.gripper_move(0)
    _step(s, 0.5)
    _go(s, arm.move_l(pose(0.08), speed=0.2))
    _go(s, arm.move_l(pose(0.012), speed=0.05))
    arm.gripper_move(255, force=force)
    _step(s, 1.5)
    q = [float(d.qpos[m.joint(f"{s.station(uid).prefix}finger_joint{k}").qposadr[0]]) for k in (1, 2)]
    width = catalog.meta(WR.LID)["size"][0]
    assert abs(sum(q) - width) < 0.002, "the pads sank into the lid's wall"
    _go(s, arm.move_l(pose(0.10), speed=0.05))
    assert d.xpos[lid][2] - top > 0.08 and abs(d.xpos[dish][2] - top) < 0.002
    assert s.wetrobo_goal(uid) == [True, True]


@pytest.mark.parametrize("lab", list(WR.LABS))
def test_the_arm_opens_the_door(lab):
    """The incubator stands where the arm can open it: its handle within reach, the hand able to
    follow the door's arc (joint limits, the robot's own straight-line moves) to the goal's 60°
    without the door sweeping the dish or the bottle."""
    s = PlaygroundSim(stations=[])
    uid = s.add_station("franka", (0.0, 0.0), 0.0, kind=WR.LABS[lab][0], task="incubator")
    arm, m, d = s.arms[uid], s.m, s.d
    _step(s, 1.0)
    kit = {p.item: p for p in s.placed}
    start = {k: d.xpos[m.body("obj_" + kit[k].uid).id].copy() for k in (WR.DISH, WR.BOTTLE)}
    door = WR.kit_joints(m, [(p.uid, p.item) for p in kit.values()])["door"][0]
    j = next(j for j in range(m.njnt) if m.jnt_qposadr[j] == door)
    hinge = arm.to_base(d.xanchor[j].copy())
    P = np.array([arm.to_base(d.geom_xpos[g].copy()) for g in range(m.ngeom)
                  if m.geom_bodyid[g] == m.jnt_bodyid[j] and m.geom_contype[g]])
    h = P[np.argmax(np.hypot(*(P[:, :2] - hinge[:2]).T))]           # the handle: the door's far edge
    turn = _rz(kit[WR.INCUBATOR].yaw + np.pi / 2)   # how the door faces the arm
    R0 = turn @ np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)             # the hand toward the door, fingers across the bar

    def pose(th, back=0.0):
        Rz = _rz(-th)
        p = hinge + Rz @ (h - hinge - back * turn[:, 0])
        return [*p[:2], h[2], *_rotvec(Rz @ R0)]
    arm.gripper_move(0)
    _step(s, 0.5)
    _go(s, arm.move_j_ik(pose(0, 0.12)))
    _go(s, arm.move_l(pose(0), speed=0.05))
    arm.gripper_move(255, force=255)
    _step(s, 1.0)
    for th in np.radians(np.arange(5, 71, 5)):
        _go(s, arm.move_l(pose(th), speed=0.05))
        if all(s.wetrobo_goal(uid)):
            break
    assert s.wetrobo_goal(uid) == [True] and arm.mode == "running"
    for k, p0 in start.items():
        assert np.linalg.norm(d.xpos[m.body("obj_" + kit[k].uid).id] - p0) < 0.005, k


def test_every_run_starts_from_the_first_start():
    """A second run doesn't start where the first one ended (the lid lifted: an instant pass)."""
    s, uid = _station("y", "lid")
    st = s.station(uid)
    kit = {p.item: p for p in s._on_table(st) if p.item in WR.KIT}
    lid = s.m.body("obj_" + kit[WR.LID].uid)
    adr = s.m.jnt_qposadr[lid.jntadr[0]]
    at = s.d.qpos[adr:adr + 3].copy()
    assert s.wetrobo_run_start(uid) is None and s.wetrobo_goal(uid) == [False, True]
    s.d.qpos[adr:adr + 3] = at + [0.10, 0.0, 0.0]            # the run's end: the lid beside its dish
    for _ in range(500):
        mujoco.mj_step(s.m, s.d)
    assert all(s.wetrobo_goal(uid))
    assert s.wetrobo_run_start(uid) is None                  # the next run: back to the start
    assert s.wetrobo_goal(uid) == [False, True] and np.allclose(s.d.qpos[adr:adr + 3], at, atol=1e-6)
    s._wr_start.clear()                                      # no start known and the task done: refused
    s.d.qpos[adr:adr + 3] = at + [0.10, 0.0, 0.0]
    for _ in range(500):
        mujoco.mj_step(s.m, s.d)
    assert "already done" in s.wetrobo_run_start(uid)
