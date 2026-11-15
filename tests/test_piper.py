"""The AgileX PiPER in the playground: Menagerie's model on a station's table, with a tool centre
point, a wrist camera and a gripper that holds; the AI's kit has AgileX's manual; and a WetRobo
station can have it, with the kit laid out within its shorter reach."""
import mujoco
import numpy as np
import pytest

from playground import catalog, site
from playground import wetrobo as WR
from playground import world as W
from playground.sim import PlaygroundSim
from wetlabsim import scene as WS
from test_wetrobo import _go, _rotvec, _rz, _step

DOWN = [0, np.pi, 0]          # the PiPER's gripper straight down, fingers closing along y


def _lab(item=None, dx=0.30):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("piper", (0, 0), 0.0, "table")
    st = sim.station(uid)
    if item:
        x, y, _ = st.to_world(st.robot_xy[0] + dx, st.robot_xy[1])
        sim.placed = [W.Placed("t1", item, (x, y, st.top + 0.002), 0.0)]
        sim.rebuild()
    return sim, sim.arms[uid], st


def test_the_piper_stands_ready_on_its_table():
    sim, arm, st = _lab()
    _step(sim, 1.0)
    assert st.robot == "piper" and not arm.has_ft and arm.n_arm == 6
    s = arm.state()
    assert "tcp_force" not in s                       # no wrist force/torque sensor
    assert np.allclose(s["tcp_pose"][:3], [0.25, 0.0, 0.10], atol=0.006)      # ready: 25 cm ahead, 10 cm up
    R = sim.d.site_xmat[arm.tcp_site].reshape(3, 3)
    assert R[2, 2] < -0.99                            # pointing straight down
    assert set(arm.P["cameras"]) == {"overhead", "wrist", "side"}
    for cam in arm.P["cameras"].values():
        assert mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_CAMERA, cam) >= 0
    assert any(r["id"] == "piper" for r in catalog.robots())
    with pytest.raises(Exception):
        arm.zero_ft()


def test_limits_are_the_manuals():
    P = WS.ROBOTS["piper"]
    assert np.allclose(np.degrees(P["joint_vmax"]), [180, 195, 180, 225, 225, 225])
    assert P["max_opening_mm"] == 70 and P["ft_site"] is None


def test_the_gripper_opens_70_mm_and_its_force_setting_scales_the_motor():
    sim, arm, st = _lab()
    _step(sim, 1.0)
    q = lambda: float(sim.d.qpos[sim.m.joint(st.prefix + "joint7").qposadr[0]])
    assert abs(2 * q() - 0.070) < 0.002               # open at the start
    arm.gripper_move(255, force=0)
    assert np.allclose(sim.m.actuator_forcerange[arm.grip_act], [-2, 2])
    _step(sim, 1.5)
    assert q() < 0.001 and arm.gripper_status()["status_code"] == 3
    arm.gripper_move(0, force=255)
    assert np.allclose(sim.m.actuator_forcerange[arm.grip_act], [-10, 10])
    _step(sim, 1.5)
    assert abs(2 * q() - 0.070) < 0.002


@pytest.mark.parametrize("item", ["glass_vial", "lab_bottle_small"])
def test_it_picks_up_and_holds(item):
    sim, arm, st = _lab(item)
    _step(sim, 1.0)
    b = sim.m.body("obj_t1").id
    pb = arm.to_base(sim.d.xpos[b].copy())
    pose = lambda z: [pb[0], pb[1], z, *DOWN]
    _go(sim, arm.move_l(pose(0.10), 0.2))
    _go(sim, arm.move_l(pose(0.02), 0.08))
    arm.gripper_move(255, 255, 255)
    _step(sim, 1.5)
    assert arm.gripper_status()["object_detected"]
    _go(sim, arm.move_l(pose(0.10), 0.1))
    z0 = sim.d.xpos[b][2]
    assert z0 - st.top > 0.06
    _step(sim, 10.0)
    assert abs(sim.d.xpos[b][2] - z0) < 0.003 and arm.mode == "running"       # held, not slipping


def test_the_ai_gets_agilexs_manual_and_a_site_sheet(tmp_path):
    from wetlabsim import run_agent as RA
    sim, arm, st = _lab()
    sheet = site.site_sheet(sim.placed, st, sim.stations)
    assert "AgileX PiPER" in sheet and "No force/torque sensing" in sheet and "[0, 1.5313" in sheet
    ws, client = tmp_path / "ws", tmp_path / "client"
    ws.mkdir(), client.mkdir()
    RA.prepare_workspace(ws, client, "piper", "standard", "Lift the lid.", {"camera_calibration": {}})
    assert (ws / "robot_model" / "piper.xml").exists() and (ws / "COMMANDS.md").exists()
    assert [p.name for p in (ws / "datasheets").glob("*.pdf")] == ["PIPER Product User Manual EN.pdf"]
    assert "get_tcp_force" not in (ws / "COMMANDS.md").read_text()


# ------------------------------------------------------------------ WetRobo with the paper's arm
@pytest.mark.parametrize("lab", list(WR.LABS))
def test_a_wetrobo_lab_seats_the_piper_by_its_kit(lab):
    s = PlaygroundSim(stations=[])
    uid = s.add_station("piper", (0.0, 0.0), 0.0, kind=WR.LABS[lab][0], task="lid")
    st, arm = s.station(uid), s.arms[uid]
    assert st.robot == "piper" and st.robot_xy == W.KINDS[st.kind]["robot_xy_by"]["piper"]
    _step(s, 1.0)
    kit = {p.item: p for p in s.placed if p.item in WR.KIT}
    assert set(kit) == set(WR.KIT)                    # nothing left off for standing by the base
    r = lambda k: float(np.hypot(*arm.to_base(s.d.xpos[s.m.body("obj_" + kit[k].uid).id].copy())[:2]))
    assert 0.25 < r(WR.DISH) < 0.38 and 0.25 < r(WR.BOTTLE) < 0.45
    assert s.wetrobo_goal(uid) == [False, True]
    with pytest.raises(Exception):                    # the station keeps its robot
        s.swap_robot(uid, "franka")


def test_other_robots_get_the_franka_on_a_wetrobo_station():
    s = PlaygroundSim(stations=[])
    uid = s.add_station("ur5e", (0.0, 0.0), 0.0, kind="wetrobo_x", task="lid")
    assert s.station(uid).robot == "franka"


@pytest.mark.parametrize("lab", list(WR.LABS))
@pytest.mark.parametrize("force", [0, 255])
def test_the_piper_lifts_the_lid_alone(lab, force):
    s = PlaygroundSim(stations=[])
    uid = s.add_station("piper", (0.0, 0.0), 0.0, kind=WR.LABS[lab][0], task="lid")
    arm, m, d = s.arms[uid], s.m, s.d
    _step(s, 1.0)
    kit = {p.item: p for p in s.placed}
    dish, lid = (m.body("obj_" + kit[k].uid).id for k in (WR.DISH, WR.LID))
    top = s.station(uid).top
    pb = arm.to_base(d.xpos[lid].copy())
    pose = lambda z: [pb[0], pb[1], z, *DOWN]
    _go(s, arm.move_l(pose(0.08), speed=0.2))
    _go(s, arm.move_l(pose(0.012), speed=0.05))
    arm.gripper_move(255, force=force)
    _step(s, 1.5)
    _go(s, arm.move_l(pose(0.09), speed=0.05))
    assert d.xpos[lid][2] - top > 0.06 and abs(d.xpos[dish][2] - top) < 0.002
    assert s.wetrobo_goal(uid) == [True, True]


@pytest.mark.parametrize("lab", list(WR.LABS))
def test_the_piper_opens_the_door(lab):
    """The PiPER can't follow the handle all the way round (the handle comes too near its base),
    so it opens the door in two moves, as a person with a short reach would: pull the handle to
    20°, let go, then reach behind the door's free edge and push it the rest of the way."""
    s = PlaygroundSim(stations=[])
    uid = s.add_station("piper", (0.0, 0.0), 0.0, kind=WR.LABS[lab][0], task="incubator")
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
    F = _rz(kit[WR.INCUBATOR].yaw + np.pi / 2)        # the door's frame: x into the incubator
    v0 = F.T @ (h - hinge)
    v0[2] = 0
    assert abs(np.hypot(*h[:2]) - 0.61) < 0.03        # the handle straight ahead, 0.6 m away
    pin = v0 + [0.089, 0.01, 0]                       # 3.5 cm behind the door's inner face, by its free edge
    at = lambda th, v: [*(hinge + F @ (_rz(-th) @ v))[:2], h[2]]
    grasp = _rotvec(F @ np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float))    # toward the door, fingers across the bar

    def away(pt):             # the gripper pointing straight away from the base, one finger above the other
        return [*pt, *_rotvec(_rz(np.arctan2(pt[1], pt[0])) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float))]
    _go(s, arm.move_j_ik([*at(0, v0 - [0.10, 0, 0]), *grasp]))
    _go(s, arm.move_l([*at(0, v0), *grasp], speed=0.05))
    arm.gripper_move(255, force=255)
    _step(s, 1.0)
    for th in np.radians([5, 10, 15, 20]):
        _go(s, arm.move_l([*at(th, v0), *grasp], speed=0.05))
    arm.gripper_move(0)
    _step(s, 1.0)
    a0 = float(d.qpos[door])
    assert a0 > np.radians(12)
    _go(s, arm.move_l([*at(a0, v0 - [0.06, 0, 0]), *grasp], speed=0.05))
    _go(s, arm.move_j_ik(away(at(a0, pin + [-0.10, -0.14, 0]))))
    arm.gripper_move(255)
    _step(s, 0.8)
    _go(s, arm.move_l(away(at(a0, pin + [0, -0.14, 0])), speed=0.1))
    _go(s, arm.move_l(away(at(a0, pin)), speed=0.05))
    for th in np.radians(np.arange(25, 71, 5)):
        _go(s, arm.move_l(away(at(th, pin)), speed=0.05))
        if all(s.wetrobo_goal(uid)):
            break
    assert s.wetrobo_goal(uid) == [True] and arm.mode == "running"
    for k, p0 in start.items():
        assert np.linalg.norm(d.xpos[m.body("obj_" + kit[k].uid).id] - p0) < 0.005, k
