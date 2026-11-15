"""Pictures of LIBERO's 40 tasks for + Station > Benchmarks: each task's room as a LIBERO station
builds it, in its first official starting layout, seen from LIBERO's front view camera.

    python -m playground.tools.render_libero_thumbs     ->  playground/static/libero/<task id>.jpg
"""
from __future__ import annotations

import pathlib

import mujoco
import numpy as np
from PIL import Image

from playground import libero as LB
from playground import world as W
from wetlabsim import scene as S

OUT = pathlib.Path(__file__).resolve().parents[1] / "static" / "libero"


def render(t: LB.Task, w: int = 480, h: int = 360) -> Image.Image:
    st = W.Station("st1", "franka", (0.0, 0.0), 0.0, "", "libero", task=t.id)
    m = W.build([], [st])
    d = mujoco.MjData(m)
    P = S.profile_for("franka", st.prefix)
    arm_q = np.array([m.joint(j).qposadr[0] for j in P["arm_joints"]])
    org, yaw = W.libero_origin(st)
    q = LB.apply_setup(m, d, t, 0, arm_q, st.prefix, org, yaw)
    d.ctrl[[m.actuator(a).id for a in P["arm_actuators"]]] = q
    for _ in range(300):
        mujoco.mj_step(m, d)
    r = mujoco.Renderer(m, h, w)
    opt = mujoco.MjvOption()
    opt.geomgroup[W.WALL_GROUP] = 1
    r.update_scene(d, camera=st.prefix + "side", scene_option=opt)
    img = Image.fromarray(r.render())
    r.close()
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for t in LB.tasks():
        render(t).save(OUT / f"{t.id}.jpg", quality=82)
        print(t.id)


if __name__ == "__main__":
    main()
