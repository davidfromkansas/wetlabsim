"""AutoBio's lab items (wetlabsim/assets/autobio, see its NOTICE.md) as library items in
playground/assets/<id>/, in the same form as the converted SimReady assets.

    python -m playground.tools.build_autobio [ids ...]

The shapes, collision proxies and masses are the robot cell's (wetlabsim/scene.py): a tube is
its body mesh's hull with its screw cap as a separate part (held on by a weld, like a SimReady
cap); racks and dishes collide as AutoBio's box proxies; the pipette and its stand as AutoBio's
own collision meshes.
"""
from __future__ import annotations

import argparse
import json
import pathlib

import mujoco
import numpy as np
import trimesh
from PIL import Image

from wetlabsim import scene as S

from .. import catalog
from .convert_simready import write_obj

A = S.AUTOBIO
TUBE = [0.88, 0.92, 0.95, 0.55]
WHITE = [0.95, 0.95, 0.97, 1.0]
POLYPROPYLENE = 900.0      # kg/m3


def _load(file, scale=0.001) -> trimesh.Trimesh:
    m = trimesh.load(A / file, force="mesh")
    m.apply_scale(scale)
    return m


def _box(size, pos, yaw=0.0) -> trimesh.Trimesh:
    T = trimesh.transformations.rotation_matrix(yaw, [0, 0, 1])
    T[:3, 3] = pos
    return trimesh.creation.box(extents=2 * np.asarray(size), transform=T)


class Part:
    def __init__(self, name):
        self.name, self.vis, self.col = name, [], []

    def visual(self, mesh, rgba):
        self.vis.append((mesh, rgba))
        return self

    def collide(self, mesh):
        self.col.append(mesh)
        return self


def _write(id_: str, parts: list[Part], masses: list, turn=None, note=""):
    """Write the parts as asset.json, in the item's frame: its bottom centre at the origin."""
    out = catalog.ASSETS / id_
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    T = np.eye(4) if turn is None else turn
    V = np.vstack([m.vertices for p in parts for m, _ in p.vis]) @ T[:3, :3].T
    lo, hi = V.min(0), V.max(0)
    T = trimesh.transformations.translation_matrix([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]) @ T
    for p in parts:
        for m, _ in p.vis:
            m.apply_transform(T)
        for m in p.col:
            m.apply_transform(T)
    V = np.vstack([m.vertices for p in parts for m, _ in p.vis])
    lo, hi = V.min(0), V.max(0)
    bodies = []
    for i, (p, mass) in enumerate(zip(parts, masses)):
        # a separate part's frame is at its own middle (a weld holds best about its part)
        c = np.zeros(3) if i == 0 else np.vstack([m.vertices for m, _ in p.vis]).mean(0)
        for m in [m for m, _ in p.vis] + p.col:
            m.apply_translation(-c)
        vis, col = [], []
        for k, (m, rgba) in enumerate(p.vis):
            write_obj(out / f"b{i}_vis_{k}.obj", m.vertices, m.faces)
            vis.append({"mesh": f"b{i}_vis_{k}.obj", "rgba": rgba, "roughness": 0.4, "metallic": 0.0})
        for k, m in enumerate(p.col):
            h = m.convex_hull
            write_obj(out / f"b{i}_col_{k}.obj", h.vertices, h.faces)
            col.append({"mesh": f"b{i}_col_{k}.obj", "volume": float(h.volume)})
        b = {"name": p.name, "visuals": vis, "collision_parts": col, "mass": mass,
             "pos": [0, 0, 0], "quat": [1, 0, 0, 0], "frame": [*np.round(c, 6).tolist(), 1, 0, 0, 0]}
        if i == 0:
            b.update(parent=None, root=True)
        else:                           # a screw cap, on the tube by a weld
            b.update(parent=0, weld=True, collide=False)
        bodies.append(b)
    stated = [m for m in masses if m]
    meta = {"source": "AutoBio", "usd": None, "mass": round(sum(stated), 5) if stated else None,
            "friction": 1.0, "com": None, "size": np.round(hi - lo, 4).tolist(),
            "collision": "AutoBio's collision proxies (as the robot cell uses them)" + note,
            "visuals": [], "collision_parts": [], "bodies": bodies,
            "unstated_mass": [b["name"] for b in bodies if not b["mass"]]}
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    _thumb(out, meta)
    return meta


def _tube(id_, body, cap, top, cap_t, body_mass, cap_mass, cap_rgba):
    tb = _load(body)
    cp = _load(cap)
    flip = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
    cp.apply_transform(flip)
    cp.apply_translation([0, 0, top])                 # the cap's mesh is upside down (as in the cell)
    return _write(id_, [Part("body").visual(tb, TUBE).collide(tb.copy()),
                        Part("cap").visual(cp, cap_rgba).collide(cp.copy())], [body_mass, cap_mass])


def _rack():
    """The tube rack's box proxies (wetlabsim.scene._rack_xml), 15 ml holes HOLE15 across."""
    r15 = S.HOLE15 / 2
    stub = S.PITCH / 2 - r15
    t50 = S.PITCH / 2 - S.HOLE50 / 2
    P = S.PITCH
    boxes = [_box((0.1025, 0.048, 0.003), (0, 0, -0.027)),
             _box((0.1025, (0.048 - P - r15) / 2, 0.03), (0, (0.048 + P + r15) / 2, 0)),
             _box((0.1025, (0.048 - P - r15) / 2, 0.03), (0, -(0.048 + P + r15) / 2, 0)),
             _box(((0.1025 - 2.5 * P - r15) / 2, 0.048, 0.03), ((0.1025 + 2.5 * P + r15) / 2, 0, 0)),
             _box(((0.1025 - 2.5 * P - r15) / 2, 0.048, 0.03), (-(0.1025 + 2.5 * P + r15) / 2, 0, 0))]
    boxes += [_box((t50, stub, 0.03), (-0.09 + P * j, -0.018 + P * i, 0)) for i in range(2) for j in range(6)]
    boxes += [_box((stub, t50, 0.03), (-0.072 + P * j, -0.036 + P * i, 0)) for i in range(3) for j in range(5)]
    part = Part("rack")
    for f in ("rack_upper_plane_visual.obj", "rack_lower_plane_visual.obj", "rack_pillars_visual.obj"):
        part.visual(_load(f), WHITE)
    for b in boxes:
        part.collide(b)
    mass = POLYPROPYLENE * sum(b.volume for b in boxes)
    return _write("tube_rack", [part], [round(mass, 4)],
                  note="; mass is its proxies' volume of polypropylene")


def _plate60():
    walls = [((0.0985, 0.001, 0.0105), (0, -0.035, 0)), ((0.0985, 0.003, 0.0105), (0, 0.033, 0)),
             ((0.0028, 0.036, 0.0105), (-0.0957, 0, 0)), ((0.001, 0.036, 0.0105), (0.0975, 0, 0))]
    walls += [((0.0025, 0.032, 0.0105), (-0.0792 + 0.0162 * k, -0.002, 0)) for k in range(11)]
    walls += [((0.0947, 0.001, 0.0105), (0.0018, -0.0218 + 0.0132 * k, 0)) for k in range(4)]
    part = Part("rack").visual(_load("rack_plate_60well.obj"), [0.2, 0.35, 0.75, 1])
    for s, p in walls:
        part.collide(_box(s, p))
    return _write("rack_60well", [part], [0.045])


def _dish():
    part = Part("dish").visual(_load("cell_dish_100.obj"), [0.92, 0.95, 0.97, 0.45])
    part.collide(trimesh.creation.cylinder(radius=0.0445, height=0.002, transform=trimesh.transformations.translation_matrix([0, 0, 0.001])))
    for k in range(16):
        a = k * np.pi / 8
        part.collide(_box((0.00868, 0.00098, 0.009), (0.04266 * np.sin(a), 0.04266 * np.cos(a), 0.011), -a))
    return _write("petri_dish", [part], [0.023])


def _pipette():
    part = Part("pipette")
    for n in S._PIPETTE_VIS:
        rgba = [0.5, 0.7, 0.9, 1] if "pusher" in n or "knob" in n else [0.85, 0.85, 0.85, 1]
        part.visual(_load(f"pipette/{n}.obj", 0.1), rgba)
    for n in S._PIPETTE_COL:
        part.collide(_load(f"pipette/{n}.obj", 0.1))
    # it lies on its side (its frame is along the pipette)
    turn = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
    m = _write("pipette", [part], [0.100], turn=turn)
    return m


def _stand():
    part = Part("stand")
    for n in ("beam_visual", "legs_visual"):
        part.visual(_load(f"pipette_stand/{n}.obj"), WHITE)
    for n in ("beam_collision_0", "leg1_collision_0", "leg2_collision_0"):
        part.collide(_load(f"pipette_stand/{n}.obj"))
    return _write("pipette_stand", [part], [None])


BUILD = {
    "tube_15ml": lambda: _tube("tube_15ml", "centrifuge_tube_15ml_body.STL", "centrifuge_tube_15ml_cap.STL",
                               0.1226, S.CAP_HEIGHT, S.TUBE_MASS, S.CAP_MASS, [0.15, 0.35, 0.85, 1]),
    "tube_50ml": lambda: _tube("tube_50ml", "centrifuge_tube_50ml_body.STL", "centrifuge_tube_50ml_cap.STL",
                               0.11965, 0.0123, 0.0086, 0.0041, [0.95, 0.45, 0.1, 1]),
    "microtube": lambda: _tube("microtube", "centrifuge_1-5ml_screw_body.STL", "centrifuge_1-5ml_screw_cap.STL",
                               0.04455, 0.0086, 0.00097, 0.00028, [0.95, 0.75, 0.1, 1]),
    "petri_dish": _dish,
    "pipette": _pipette,
    "pipette_stand": _stand,
    "tube_rack": _rack,
    "rack_60well": _plate60,
}


def _thumb(out: pathlib.Path, meta: dict):
    """A 256 px picture for the library (AutoBio ships none), rendered by MuJoCo."""
    sp = mujoco.MjSpec()
    sp.visual.global_.offwidth = sp.visual.global_.offheight = 512
    body = sp.worldbody.add_body()
    for i, b in enumerate(meta["bodies"]):
        for k, v in enumerate(b["visuals"]):
            sp.add_mesh(name=f"v{i}_{k}", file=str(out / v["mesh"]),
                        inertia=mujoco.mjtMeshInertia.mjMESH_INERTIA_SHELL)
            body.add_geom(type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"v{i}_{k}", rgba=v["rgba"],
                          pos=b["frame"][:3], quat=b["frame"][3:], contype=0, conaffinity=0, mass=0)
    sp.worldbody.add_light(pos=[0, 0, 3], dir=[0, 0, -1], diffuse=[0.7, 0.7, 0.7])
    sp.worldbody.add_light(pos=[2, -2, 2], dir=[-1, 1, -1], diffuse=[0.4, 0.4, 0.4])
    sp.visual.headlight.ambient = [0.45, 0.45, 0.45]
    m = sp.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    r = mujoco.Renderer(m, 512, 512)
    cam = mujoco.MjvCamera()
    sz = meta["size"]
    cam.lookat[:] = [0, 0, sz[2] / 2]
    cam.distance, cam.azimuth, cam.elevation = max(sz) * 1.9, 135, -30
    r.update_scene(d, cam)
    img = r.render()
    # the library shows pictures on a light background
    bg = (img == img[0, 0]).all(-1)
    img[bg] = [242, 243, 245]
    Image.fromarray(img).resize((256, 256), Image.LANCZOS).save(out / "thumb.png")
    r.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args(argv)
    for id_ in a.ids or list(BUILD):
        m = BUILD[id_]()
        print(f"{id_:14s} mass={m['mass']} size={m['size']} bodies={len(m['bodies'])}")


if __name__ == "__main__":
    main()
