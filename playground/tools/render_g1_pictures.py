"""Render the G1's pictures for the robot picker: station_g1.png (its station) and robot_g1.png
(the robot alone, transparent background).

    MUJOCO_GL=egl python -m playground.tools.render_g1_pictures playground/static
"""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tests"))
import numpy as np, mujoco
from PIL import Image
from playground.sim import PlaygroundSim
from test_playground_grip import _step
sim = PlaygroundSim(stations=[])
uid = sim.add_station("g1", (0, 0), 0.0, "table", starter=False); g = sim.arms[uid]
_step(sim, 2.0)
m, d = sim.m, sim.d
def cam(look, dist, az, el):
    c = mujoco.MjvCamera(); c.type = mujoco.mjtCamera.mjCAMERA_FREE
    c.lookat[:] = look; c.distance = dist; c.azimuth = az; c.elevation = el; return c
opt = mujoco.MjvOption(); opt.geomgroup[:] = [1, 1, 1, 0, 0, 0]
pel = d.xpos[g.base_body].copy()
# station picture, 400x300, like the others: three-quarter view from the robot's front-left
r = mujoco.Renderer(m, 600, 800)
r.update_scene(d, cam(np.array([pel[0] + 0.6, pel[1], 0.55]), 3.6, 125, -24), opt)
Image.fromarray(r.render()).resize((400, 300), Image.LANCZOS).save(sys.argv[1] + "/station_g1.png")
bodies = set(int(b) for b in g.bodies)
for i in range(m.ngeom):
    if m.geom_bodyid[i] not in bodies: m.geom_rgba[i,3]=0; m.geom_matid[i]=-1
# robot picture, 256x256 with a transparent background: segment the robot's geoms
r2 = mujoco.Renderer(m, 768, 768)
c = cam(np.array([pel[0], pel[1], 0.62]), 2.0, 155, -12)
r2.update_scene(d, c, opt); rgb = r2.render()
r2.enable_segmentation_rendering(); r2.update_scene(d, c, opt); seg = r2.render(); r2.disable_segmentation_rendering()
gid = seg[..., 0]; typ = seg[..., 1]
mine = np.zeros(gid.shape, bool)
bodies = set(int(b) for b in g.bodies)
ok = (typ == int(mujoco.mjtObj.mjOBJ_GEOM)) & (gid >= 0)
mine[ok] = np.isin(m.geom_bodyid[gid[ok]], list(bodies))
a = (mine * 255).astype(np.uint8)
img = Image.fromarray(np.dstack([rgb, a]), "RGBA")
ys, xs = np.nonzero(mine); pad = 20
box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + pad, 767), min(ys.max() + pad, 767))
img = img.crop(box); w, h = img.size; s = max(w, h)
sq = Image.new("RGBA", (s, s), (0, 0, 0, 0)); sq.paste(img, ((s - w) // 2, (s - h) // 2))
sq.resize((256, 256), Image.LANCZOS).save(sys.argv[1] + "/robot_g1.png")
