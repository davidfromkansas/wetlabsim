"""Pictures of WetRobo's two labs for + Station > Benchmarks: each lab's kit and table, from
the front, as they start.

    python -m playground.tools.render_wetrobo_thumbs   ->  playground/static/wetrobo/lab_<x|y>.jpg (the Franka), lab_<x|y>_piper.jpg
"""
from __future__ import annotations

import pathlib

import mujoco
from PIL import Image

from .. import wetrobo as WR
from ..sim import PlaygroundSim

OUT = pathlib.Path(__file__).resolve().parent.parent / "static" / "wetrobo"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for robot, (lab, (kind, label, _)) in ((r, l) for r in WR.ROBOTS for l in WR.LABS.items()):
        name = f"lab_{lab}.jpg" if robot == "franka" else f"lab_{lab}_{robot}.jpg"
        s = PlaygroundSim()
        s.remove_station("st1", keep_table=False)
        uid = s.add_station(robot, (0.0, 0.0), 0.0, kind=kind, task=next(iter(WR.TASKS)))
        for _ in range(500):
            mujoco.mj_step(s.m, s.d)
        st = s.station(uid)
        r = mujoco.Renderer(s.m, 600, 1200)
        cam = mujoco.MjvCamera()
        cam.lookat[:] = [*st.to_world(0.2, 0.0)[:2], st.top + 0.1]
        cam.distance, cam.azimuth, cam.elevation = 2.1, 25.0 if lab == "y" else -25.0, -35.0
        r.update_scene(s.d, camera=cam)
        Image.fromarray(r.render()).save(OUT / name, quality=82)
        print(label, robot, "->", OUT / name)


if __name__ == "__main__":
    main()
