"""Render the Menagerie arms' pictures for the robot picker (wetlabsim/menagerie_arms.py):
station_<robot>.png (its station) and robot_<robot>.png (the robot alone, transparent background).

    MUJOCO_GL=egl python -m playground.tools.render_menagerie_arm_pictures playground/static [robot ...]
"""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tests"))
import numpy as np
import mujoco
from PIL import Image
from playground.sim import PlaygroundSim
from test_playground_grip import _step
from wetlabsim import menagerie_arms as MA


def cam(look, dist, az, el):
    c = mujoco.MjvCamera()
    c.type = mujoco.mjtCamera.mjCAMERA_FREE
    c.lookat[:] = look
    c.distance, c.azimuth, c.elevation = dist, az, el
    return c


def render(robot, out):
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station(robot, (0, 0), 0.0, "table", starter=False)
    g = sim.arms[uid]
    _step(sim, 2.0)
    m, d = sim.m, sim.d
    opt = mujoco.MjvOption()
    opt.geomgroup[:] = [1, 1, 1, 0, 0, 0]
    base = d.xpos[g.base_body].copy()
    bodies = set(int(b) for b in g.bodies)
    # the robot's size: its visible shapes' extent
    pts = np.vstack([d.geom_xpos[i] for i in range(m.ngeom) if m.geom_bodyid[i] in bodies])
    lo, hi = pts.min(0), pts.max(0)
    size = float(max(hi - lo))
    mid = (lo + hi) / 2
    # station picture, 400x300 like the others: three-quarter view from the robot's front-left
    r = mujoco.Renderer(m, 600, 800)
    r.update_scene(d, cam(np.array([base[0] + 0.42, base[1], base[2] - 0.15]), 2.2, 125, -24), opt)
    Image.fromarray(r.render()).resize((400, 300), Image.LANCZOS).save(f"{out}/station_{robot}.png")
    # robot picture, 256x256 with a transparent background: segment the robot's shapes
    r2 = mujoco.Renderer(m, 768, 768)
    c = cam(mid, 1.6 * size + 0.25, 155, -12)
    r2.update_scene(d, c, opt)
    rgb = r2.render()
    r2.enable_segmentation_rendering()
    r2.update_scene(d, c, opt)
    seg = r2.render()
    r2.disable_segmentation_rendering()
    gid, typ = seg[..., 0], seg[..., 1]
    mine = np.zeros(gid.shape, bool)
    ok = (typ == int(mujoco.mjtObj.mjOBJ_GEOM)) & (gid >= 0)
    mine[ok] = np.isin(m.geom_bodyid[gid[ok]], list(bodies))
    img = Image.fromarray(np.dstack([rgb, (mine * 255).astype(np.uint8)]), "RGBA")
    ys, xs = np.nonzero(mine)
    pad = 20
    img = img.crop((max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + pad, 767), min(ys.max() + pad, 767)))
    w, h = img.size
    s = max(w, h)
    sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sq.paste(img, ((s - w) // 2, (s - h) // 2))
    sq.resize((256, 256), Image.LANCZOS).save(f"{out}/robot_{robot}.png")


if __name__ == "__main__":
    for robot in sys.argv[2:] or MA.ARMS:
        render(robot, sys.argv[1])
        print("rendered", robot)
