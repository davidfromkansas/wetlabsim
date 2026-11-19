"""The arms from MuJoCo Menagerie (wetlabsim/menagerie_arms.py) in the playground: each stands on a
station's table with its gripper pointing straight down, has a wrist camera, picks up a bottle and
holds it; the AI's kit has the makers' documents and a site sheet."""
import json

import mujoco
import numpy as np
import pytest

from playground import catalog, site
from playground import world as W
from playground.sim import PlaygroundSim
from wetlabsim import datasheets as DS
from wetlabsim import menagerie_arms as MA
from wetlabsim import scene as WS
from test_wetrobo import _go, _step

ARMS = list(MA.ARMS)
# The weakest grippers: the Lite 6's (5 N, 16 mm stroke) and the Koch's small jaw servo lift the
# bottle part of the way before it settles in their fingers.
WEAK = {"lite6": 0.015, "koch": 0.03}


def _lab(robot, item=None):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station(robot, (0, 0), 0.0, "table")
    st = sim.station(uid)
    arm = sim.arms[uid]
    if item:
        _step(sim, 0.2)
        p0 = arm.state()["tcp_pose"]
        x, y, _ = arm.to_world(np.array([p0[0], p0[1], 0.0]))
        sim.placed = [W.Placed("t1", item, (x, y, st.top + 0.002), 0.0)]
        sim.rebuild()
        arm = sim.arms[uid]
    return sim, arm, st


@pytest.mark.parametrize("robot", ARMS)
def test_it_stands_ready_with_the_gripper_down(robot):
    sim, arm, st = _lab(robot)
    _step(sim, 1.0)
    A = MA.ARMS[robot]
    assert st.robot == robot and arm.n_arm == A["joints"]
    R = sim.d.site_xmat[arm.tcp_site].reshape(3, 3)
    assert R[2, 2] < -0.99                            # pointing straight down
    assert set(arm.P["cameras"]) == {"overhead", "wrist", "side"}
    for cam in arm.P["cameras"].values():
        assert mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_CAMERA, cam) >= 0
    assert arm.mode == "running"
    assert any(r["id"] == robot for r in catalog.robots())
    assert ("tcp_force" in arm.state()) == bool(WS.ROBOTS[robot].get("ft_site"))


@pytest.mark.parametrize("robot", ARMS)
def test_it_picks_up_and_holds_a_bottle(robot):
    sim, arm, st = _lab(robot, "lab_bottle_small")
    _step(sim, 1.0)
    b = sim.m.body("obj_t1").id
    pb = arm.to_base(sim.d.xpos[b].copy())
    down = list(arm.state()["tcp_pose"][3:])
    up = 0.1 if MA.ARMS[robot]["reach_mm"] > 450 else 0.05
    z = max(pb[2] + catalog.meta("lab_bottle_small")["size"][2] - 0.025, 0.018)
    pose = lambda h: [pb[0], pb[1], h, *down]
    z0 = sim.d.xpos[b][2]
    _go(sim, arm.move_l(pose(z + up), 0.2))
    _go(sim, arm.move_l(pose(z), 0.08))
    arm.gripper_move(255, 255, 255)
    _step(sim, 2.0)
    assert arm.gripper_status()["object_detected"]
    _go(sim, arm.move_l(pose(z + up), 0.1))
    _step(sim, 0.5)
    z1 = sim.d.xpos[b][2]
    assert z1 - z0 > WEAK.get(robot, 0.6 * up)
    _step(sim, 5.0)
    assert abs(sim.d.xpos[b][2] - z1) < 0.004 and arm.mode == "running"     # held, not slipping


@pytest.mark.parametrize("robot", ARMS)
def test_the_ai_gets_the_makers_documents_and_a_site_sheet(robot, tmp_path):
    from wetlabsim import run_agent as RA
    sim, arm, st = _lab(robot)
    A = MA.ARMS[robot]
    sheet = site.site_sheet(sim.placed, st, sim.stations)
    assert A["name"] in sheet and "TCP" in sheet
    ws, client = tmp_path / "ws", tmp_path / "client"
    ws.mkdir(), client.mkdir()
    RA.prepare_workspace(ws, client, robot, "standard", "Pick up the bottle.", {"camera_calibration": {}})
    assert (ws / "robot_model" / A["file"]).exists() and (ws / "COMMANDS.md").exists()
    if A.get("add") == "robotiq":
        assert (ws / "robot_model" / "robotiq_2f85" / "2f85.xml").exists()
    sources = json.loads((DS.DIRS[robot] / "sources.json").read_text())
    assert sorted(p.name for p in (ws / "datasheets").iterdir()) == sorted([s["file"] for s in sources] + ["sources.json"])
    assert (robot == "arx_l5") == (not sources)       # ARX publishes no documents for the L5
    commands = (ws / "COMMANDS.md").read_text()
    assert ("get_tcp_force" in commands) == bool(WS.ROBOTS[robot].get("ft_site"))
    assert "Menagerie" in (DS.DIRS[robot] / "SOURCES.md").read_text()
    # the AI's documents name no scene objects
    for f in ("AGENTS.md", "COMMANDS.md", "SITE.md"):
        assert "bottle" not in (ws / f).read_text().lower()


def test_the_documents_are_present_and_unchanged():
    for robot in ARMS:
        DS.fetch(robot=robot)


def test_limits_come_from_the_documents():
    deg = lambda r: np.round(np.degrees(WS.ROBOTS[r]["joint_vmax"]))
    assert deg("ur10e").tolist() == [120, 120, 180, 180, 180, 180]
    assert deg("iiwa14").tolist() == [85, 85, 100, 75, 130, 135, 135]
    assert deg("rizon4").tolist() == [120, 120, 140, 140, 280, 280, 280]
    assert deg("lite6").tolist() == [180] * 6
    assert WS.ROBOTS["lite6"]["max_opening_mm"] == 38 and WS.ROBOTS["wx250s"]["max_opening_mm"] == 74
