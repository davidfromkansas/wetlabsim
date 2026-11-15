"""Render the floor-standing arms' pictures for the robot picker: station_<robot>.png (the arm
at its pallet) and robot_<robot>.png (the robot alone, transparent background), for the Comau
N-220 and the FANUC CRX-30iA.

    MUJOCO_GL=egl python -m playground.tools.render_floor_arm_pictures playground/static
"""
import sys

import mujoco
import numpy as np
from PIL import Image

from playground.sim import PlaygroundSim

VIEW = {"n220": (5.2, 1.3, 6.5), "crx30ia": (3.2, 0.8, 4.0)}     # station distance, look height, robot distance


def cam(look, dist, az, el):
    c = mujoco.MjvCamera()
    c.type = mujoco.mjtCamera.mjCAMERA_FREE
    c.lookat[:] = look
    c.distance, c.azimuth, c.elevation = dist, az, el
    return c


for robot, (far, high, near) in VIEW.items():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station(robot, (0, 0), 0.0, "pallet", starter=False)
    g = sim.arms[uid]
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, 1500)
    opt = mujoco.MjvOption()
    opt.geomgroup[:] = [1, 1, 1, 0, 0, 0]
    base = d.xpos[g.base_body].copy()
    r = mujoco.Renderer(m, 600, 800)
    r.update_scene(d, cam(np.array([base[0] + 0.6, base[1], high]), far, 125, -18), opt)
    Image.fromarray(r.render()).resize((400, 300), Image.LANCZOS).save(f"{sys.argv[1]}/station_{robot}.png")
    r.close()
    bodies = {int(b) for b in g.bodies} | {m.body(g.P["tool_body"]).id}
    r2 = mujoco.Renderer(m, 768, 768)
    c = cam(np.array([base[0] + 0.4, base[1], high]), near, 150, -10)
    r2.update_scene(d, c, opt)
    rgb = r2.render()
    r2.enable_segmentation_rendering()
    r2.update_scene(d, c, opt)
    seg = r2.render()
    r2.close()
    gid, typ = seg[..., 0], seg[..., 1]
    ok = (typ == int(mujoco.mjtObj.mjOBJ_GEOM)) & (gid >= 0)
    mine = np.zeros(gid.shape, bool)
    mine[ok] = np.isin(m.geom_bodyid[gid[ok]], list(bodies))
    img = Image.fromarray(np.dstack([rgb, (mine * 255).astype(np.uint8)]), "RGBA")
    ys, xs = np.nonzero(mine)
    pad = 20
    img = img.crop((max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + pad, 767), min(ys.max() + pad, 767)))
    w, h = img.size
    s = max(w, h)
    sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sq.paste(img, ((s - w) // 2, (s - h) // 2))
    sq.resize((256, 256), Image.LANCZOS).save(f"{sys.argv[1]}/robot_{robot}.png")
    sim.stop_threads()
