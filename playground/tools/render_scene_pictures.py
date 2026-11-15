"""Render the Add station cards' pictures of the ready-made Factory and Car assembly scenes:
scene_factory.jpg and scene_car.jpg (560x396, like the other scene cards).

    MUJOCO_GL=egl python -m playground.tools.render_scene_pictures playground/static
"""
import sys

import mujoco
from PIL import Image

from playground import scenegen as G
from playground.sim import PlaygroundSim

VIEW = {"factory": (12.5, 150.0, -26.0, 0.9), "car": (12.0, 140.0, -30.0, 0.6)}   # distance, azimuth, elevation, look height


class _Sess:
    def __init__(self):
        self.unsent = {}


for name in VIEW:
    dist, az, el, high = VIEW[name]
    sim = PlaygroundSim(stations=[])
    b = G.Build(sim, _Sess(), "", G.preset_pick(name), "", False, preset=name)
    b._run()
    assert b.phase == "done" and not b.skipped, (b.error, b.skipped)
    m, d = sim.m, sim.d
    mujoco.mj_step(m, d, 2000)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [(b.zone[0] + b.zone[2]) / 2, (b.zone[1] + b.zone[3]) / 2, high]
    cam.distance, cam.azimuth, cam.elevation = dist, az, el
    opt = mujoco.MjvOption()
    opt.geomgroup[:] = [1, 1, 1, 0, 0, 0]
    r = mujoco.Renderer(m, 1188, 1680)
    r.update_scene(d, cam, opt)
    Image.fromarray(r.render()).resize((560, 396), Image.LANCZOS).save(f"{sys.argv[1]}/scene_{name}.jpg", quality=88)
    r.close()
    sim.stop_threads()
