"""Scene settings (playground/settings.py) and repeat runs' station reset (playground/sim.py):
the session's MuJoCo settings reach the compiled model, bad ones are refused, and a station
goes back exactly to where a batch started."""
import mujoco
import numpy as np
import pytest

from playground import settings as ST
from playground import world as W
from playground.sim import PlaygroundSim


def test_defaults_read_back():
    lab = ST.read_model(W.build([], []))
    assert lab["option"]["integrator"] == "discrete"       # the Playground's own choice
    assert set(lab["flag"]) == set(ST.FLAGS) and len(ST.FLAGS) == 28
    mj = ST.mujoco_defaults()
    assert mj["option"]["timestep"] == pytest.approx(0.002)
    assert mj["option"]["integrator"] == "Euler"


def test_settings_reach_the_model():
    cfg = ST.clean({"option": {"timestep": 0.003, "solver": "CG", "gravity": [0, 0, -5]},
                    "flag": {"energy": True, "gravity": False},
                    "actuatorgroupdisable": [3],
                    "materials": {"prop": {"condim": 4}, "robot": {"friction": [0.8, 0.01, 0.001]}}})
    m = W.build([], W.default_stations(), cfg)
    r = ST.read_model(m)
    assert r["option"]["timestep"] == pytest.approx(0.003)
    assert r["option"]["solver"] == "CG"
    assert r["option"]["gravity"] == pytest.approx([0, 0, -5])
    assert r["flag"]["energy"] is True and r["flag"]["gravity"] is False
    assert r["actuatorgroupdisable"] == [3]
    # The robot's own geoms take the robot material (scene._set_material).
    robot = [g for g in range(m.ngeom) if m.geom_condim[g] == 3 and abs(m.geom_friction[g][0] - 0.8) < 1e-9]
    assert robot, "the robot material's friction did not reach the robot"
    # And a build without settings is the Playground's own again.
    assert ST.read_model(W.build([], []))["option"]["timestep"] != pytest.approx(0.003)


@pytest.mark.parametrize("raw", [
    {"option": {"timestep": 5}},
    {"option": {"iterations": 2.5}},
    {"option": {"solver": "magic"}},
    {"option": {"gravity": [0, 0]}},
    {"option": {"nope": 1}},
    {"flag": {"nope": True}},
    {"materials": {"prop": {"condim": 2}}},
    {"materials": {"glass": {"condim": 3}}},
    {"actuatorgroupdisable": [99]},
])
def test_bad_settings_refused(raw):
    with pytest.raises(ValueError):
        ST.clean(raw)


def test_apply_settings_and_station_reset():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    st = sim.station(uid)
    x, y, _ = st.to_world(st.robot_xy[0] + 0.45, st.robot_xy[1])
    sim.placed = [W.Placed("t1", "tube_15ml", (x, y, st.top + 0.01), 0.0)]
    sim.rebuild()
    for _ in range(200):
        mujoco.mj_step(sim.m, sim.d)
    snap = sim.station_snapshot(uid)
    b = mujoco.mj_name2id(sim.m, mujoco.mjtObj.mjOBJ_BODY, "obj_t1")
    x0, q0 = sim.d.xpos[b].copy(), sim.d.qpos.copy()
    assert len(snap["qpos_i"]) > 9                      # the arm and the tube on its table
    sim.d.qpos[snap["qpos_i"]] += 0.05
    mujoco.mj_forward(sim.m, sim.d)
    assert sim.restore_station(snap)
    assert np.allclose(sim.d.xpos[b], x0, atol=1e-6)
    assert np.allclose(sim.d.qpos, q0, atol=1e-9)
    # New settings rebuild the lab: an old snapshot no longer applies.
    sim.apply_settings({"option": {"timestep": 0.002}})
    assert sim.m.opt.timestep == pytest.approx(0.002)
    assert not sim.restore_station(snap)


def test_run_video_layout_and_parts(tmp_path):
    from playground import runvideo as RV
    for n in (2, 3):
        big, smalls = RV.layout(n)
        assert len(smalls) == n
        for x, y, w, h in [big, *smalls]:
            assert x >= 0 and y >= RV.HEAD and x + w <= RV.W and y + h <= RV.H and w % 2 == 0 and h % 2 == 0
    f = tmp_path / "v.mp4"
    data = bytes(range(256)) * 30000          # ~7.7 MB: three parts
    f.write_bytes(data)
    chunks, man = RV.parts(f)
    assert b"".join(chunks) == data and man["size"] == len(data) and man["parts"] == [len(c) for c in chunks]
    assert all(len(c) <= RV.PART for c in chunks) and len(chunks) == 3
