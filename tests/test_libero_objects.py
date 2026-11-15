"""LIBERO's objects and fixtures in the library (tools/build_libero_objects.py): LIBERO's own
MuJoCo models, attached as they are (world._add_mjcf). They stand as LIBERO stands them, settle
on the table without sinking in, and the fixtures' doors, drawers and knobs move on LIBERO's
joints within LIBERO's ranges."""
import mujoco
import numpy as np
import pytest

from playground import catalog
from playground.sim import PlaygroundSim

LIBERO = [i[0] for i in catalog.ITEMS if i[3].startswith("libero:")]


def _lab(item):
    sim = PlaygroundSim(stations=[])
    st = sim.station(sim.add_station("franka", (0, 0), 0.0, "table"))
    x, y, _ = st.to_world(st.robot_xy[0] + 0.5, st.robot_xy[1])
    return sim, sim.add(item, (x, y, st.top + 0.002))


def test_every_libero_object_is_in_the_library():
    have = {i["id"] for i in catalog.available()}
    assert len(LIBERO) == 47 and set(LIBERO) <= have
    assert {catalog.item(i)["tab"] for i in LIBERO} == {"LIBERO"}


@pytest.mark.parametrize("item", LIBERO)
def test_it_settles_on_the_table(item):
    sim, uid = _lab(item)
    m, d = sim.m, sim.d
    b = m.body(f"obj_{uid}").id
    p0, q0 = d.xpos[b].copy(), d.xquat[b].copy()
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    assert np.linalg.norm(d.xpos[b] - p0) < 0.01          # it only drops its few mm onto the table
    assert abs(float(q0 @ d.xquat[b])) > np.cos(np.radians(2.5))      # and stays upright
    assert min([d.contact[i].dist for i in range(d.ncon)] or [0]) > -0.002
    # LIBERO draws its collision shapes (group 0) only when debugging
    geoms = [g for g in range(m.ngeom) if m.body(m.geom_bodyid[g]).name.startswith(f"obj_{uid}")]
    assert not any(m.geom_group[g] == 0 for g in geoms if m.geom_contype[g] or m.geom_conaffinity[g])
    assert any(m.geom_group[g] == 1 for g in geoms)


def test_ketchup_stands_as_libero_stands_it():
    """LIBERO's own saved starting states have the ketchup turned (0.5, 0.5, 0.5, 0.5)."""
    assert catalog.meta("libero_ketchup")["frame"]["quat"] == [0.5, 0.5, 0.5, 0.5]
    assert catalog.meta("libero_ketchup")["size"][2] > 0.14          # standing, 15 cm tall


@pytest.mark.parametrize("item,joint,force", [
    ("libero_microwave", "microjoint", -2.0), ("libero_white_cabinet", "top_level", -40.0),
    ("libero_flat_stove", "button", 0.2), ("libero_slide_cabinet", "slidedoor_joint", 40.0)])
def test_fixtures_move_on_their_joints(item, joint, force):
    sim, uid = _lab(item)
    m, d = sim.m, sim.d
    j = m.joint(f"obj_{uid}__{joint}").id
    assert not any(m.jnt_type[k] == mujoco.mjtJoint.mjJNT_FREE and m.jnt_bodyid[k] == m.body(f"obj_{uid}").id
                   for k in range(m.njnt))                     # a fixture stands fixed, as in LIBERO
    a = m.jnt_qposadr[j]
    q0 = float(d.qpos[a])
    d.qfrc_applied[m.jnt_dofadr[j]] = force
    mujoco.mj_step(m, d, int(1.0 / m.opt.timestep))
    q = float(d.qpos[a])
    assert abs(q - q0) > 0.02
    lo, hi = m.jnt_range[j]
    assert lo - 0.02 <= q <= hi + 0.02
