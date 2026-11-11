"""Library items' surfaces come from their own physics materials (tools/convert_simready.py,
world.set_surface): each collision shape has its material's friction, and bounces back about as
much as the asset's restitution says (averaged with the table's, as PhysX combines them)."""
import mujoco
import numpy as np

from playground import catalog
from playground.sim import PlaygroundSim


def _parts(item):
    m = catalog.meta(item)
    return m.get("collision_parts", []) + [c for b in m.get("bodies", []) for c in b["collision_parts"]]


def test_each_part_has_its_own_friction():
    sim = PlaygroundSim(stations=[])
    uid = sim.add("toaster", (3, 3, 0))
    m = sim.m
    mus = sorted({round(float(m.geom_friction[g][0]), 3) for g in range(m.ngeom)
                  if m.body(m.geom_bodyid[g]).name.startswith(f"obj_{uid}") and m.geom_contype[g]})
    want = sorted({c["friction"] for c in _parts("toaster") if "friction" in c})
    assert mus == want and len(mus) > 1          # its rubber crumb tray grips more than its plastic


def _bounce(item):
    sim = PlaygroundSim(stations=[])
    st = sim.station(sim.add_station("franka", (0, 0), 0.0, "table"))
    uid = sim.add(item, (0.5, 0.0, st.top + 0.20))
    m, d = sim.m, sim.d
    b = m.body(f"obj_{uid}").id
    z0, zs = d.xpos[b][2], []
    for _ in range(int(1.5 / m.opt.timestep)):
        mujoco.mj_step(m, d)
        zs.append(d.xpos[b][2])
    zs = np.array(zs)
    up = int(np.argmax(np.diff(zs) > 0))
    rest = zs[-1]
    return float(np.sqrt(max(zs[up:up + 600].max() - rest, 0) / (z0 - rest)))


def test_bouncy_and_dead_items_bounce_as_their_materials_say():
    table = catalog.meta(catalog.DEFAULT_TABLE)["collision_parts"][0]["restitution"]
    for item in ("pong_ball", "mug"):
        e = _parts(item)[0]["restitution"]
        assert abs(_bounce(item) - (e + table) / 2) < 0.06, item
