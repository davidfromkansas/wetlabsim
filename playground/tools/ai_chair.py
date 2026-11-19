"""Test: an AI-written Blender script for one object from a lab photo (the lab chair in
scene-from-photo/demo/lab-photo.png), written in the library's form so the Playground loads it
like any other object, with real masses and moving parts:

    python -m playground.tools.ai_chair [out_dir] [--hero hero.png] [--gpu]

Parts: the five-star base (with the gas spring's shroud), the gas spring's piston (a slide, held
by friction like a locked gas spring), the seat with its back and arms (turns on the piston),
five casters (each swivels) and their twin wheels (each rolls).

Requires Blender's Python module (pip install bpy).
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import time

import bpy
import numpy as np
from PIL import Image, ImageFilter

from . import build_inhouse as B
from .convert_simready import write_obj

MM = 0.001
BLUE_FABRIC = dict(rgba=[0.16, 0.27, 0.44, 1], roughness=0.92, metallic=0.0)
GREY_PLASTIC = dict(rgba=[0.80, 0.81, 0.82, 1], roughness=0.42, metallic=0.0)
DARK_PLASTIC = dict(rgba=[0.12, 0.12, 0.13, 1], roughness=0.5, metallic=0.0)
RUBBER = dict(rgba=[0.06, 0.06, 0.065, 1], roughness=0.75, metallic=0.0)
CHROME = dict(rgba=[0.85, 0.86, 0.88, 1], roughness=0.08, metallic=1.0)
BASE_GREY = dict(rgba=[0.62, 0.63, 0.64, 1], roughness=0.38, metallic=0.0)

R_CASTER = 0.30            # hub centre to a caster's swivel
WHEEL_R = 0.025
TRAIL = 0.022              # wheel centre behind the swivel axis
SEAT_Z = 0.40              # where the seat turns on the piston


def fabric_texture(path):
    """A woven blue upholstery fabric (fine twill with fibre noise)."""
    S = 1024
    rng = np.random.default_rng(3)
    y, x = np.mgrid[0:S, 0:S]
    weave = 0.5 + 0.5 * np.sin((x + y) * 2 * math.pi / 6) * np.sin((x - y) * 2 * math.pi / 9)
    noise = np.array(Image.fromarray((rng.random((S, S)) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))) / 255
    v = 0.82 + 0.1 * weave + 0.12 * (noise - 0.5)
    base = np.array([0.16, 0.27, 0.44])
    img = np.clip(v[..., None] * base[None, None] * 255 / 0.5 * 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(img).save(path)


def grid_mesh(name, w, h, nx, ny, bend_r, thick, bevel):
    """A curved panel (a chair back): w x h in x, z, bent round a vertical axis of radius bend_r
    (curving towards -y, round the sitter), given thickness and rounded edges."""
    V, F = [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            u = -w / 2 + w * i / nx
            a = u / bend_r
            V.append((bend_r * math.sin(a), -bend_r * (1 - math.cos(a)), -h / 2 + h * j / ny))
    for j in range(ny):
        for i in range(nx):
            k = j * (nx + 1) + i
            F.append((k, k + 1, k + nx + 2, k + nx + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    s = obj.modifiers.new("thick", "SOLIDIFY")
    s.thickness, s.offset = thick, 0.0
    b = obj.modifiers.new("bevel", "BEVEL")
    b.width, b.segments, b.limit_method = bevel, 3, "ANGLE"
    sub = obj.modifiers.new("smooth", "SUBSURF")
    sub.levels = sub.render_levels = 1
    return obj


def tapered_bar(p0, p1, w0, w1, h0, h1, bevel, name="bar"):
    """A bar from p0 to p1 (bottom centre line), w and h tapering from end to end."""
    p0, p1 = np.array(p0, float), np.array(p1, float)
    d = p1 - p0
    d[2] = 0
    L = np.linalg.norm(d)
    ax = d / L
    side = np.array([-ax[1], ax[0], 0])
    V = []
    for t, w, h in ((0, w0, h0), (1, w1, h1)):
        c = p0 + (p1 - p0) * t
        for s in (-1, 1):
            for z in (0, h):
                V.append(tuple(c + side * s * w / 2 + np.array([0, 0, z])))
    # V order: end0 (s-1,z0),(s-1,zh),(s+1,z0),(s+1,zh), end1 same
    F = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (1, 3, 7, 5), (0, 4, 6, 2)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    me.validate()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    b = obj.modifiers.new("bevel", "BEVEL")
    b.width, b.segments, b.limit_method = bevel, 4, "ANGLE"
    return obj


def place(obj, loc=(0, 0, 0), rot=(0, 0, 0)):
    obj.location, obj.rotation_euler = loc, rot
    bpy.context.view_layer.update()
    return obj


def uv_project(obj):
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.cube_project(cube_size=0.25)
    bpy.ops.object.mode_set(mode="OBJECT")


class P:
    """One part: its visuals (arrays, look, texture), its convex collision hulls, mass, parent
    part and joint (name, type, axis, range..., at: the joint's place)."""
    def __init__(self, name, mass, parent=None, joint=None):
        self.name, self.mass, self.parent, self.joint = name, mass, parent, joint
        self.vis, self.col = [], []

    def add(self, obj, look, texture=None, hull=True, uv=False):
        arr = B._arrays(obj, uv=uv)
        self.vis.append((arr, look, texture))
        if hull:
            self.col.append(B._hull(arr[0]))
        return arr


def build():
    B._reset()
    parts: list[P] = []

    # ---- base: five legs, hub, the gas spring's shroud
    base = P("base", 3.6)
    parts.append(base)
    hub = B.lathe([(0, 0.07), (0.05, 0.07), (0.052, 0.09), (0.047, 0.125), (0, 0.128)], 64, 1)
    base.add(hub, BASE_GREY)
    for k in range(5):
        a = math.radians(90 + 72 * k)
        u = np.array([math.cos(a), math.sin(a), 0])
        leg = tapered_bar(u * 0.035 + [0, 0, 0.075], u * (R_CASTER - 0.005) + [0, 0, 0.062],
                          0.056, 0.038, 0.045, 0.026, 6 * MM, f"leg{k}")
        base.add(leg, BASE_GREY)
        boot = B.cylinder(0.021, 0.028, at=(*(u[:2] * R_CASTER), 0.06), verts=40, bevel=4 * MM)
        base.add(boot, BASE_GREY)
    shroud = B.lathe([(0, 0.12), (0.03, 0.12), (0.03, 0.14), (0.027, 0.15), (0.027, 0.315), (0.024, 0.33), (0, 0.33)], 64, 1)
    base.add(shroud, DARK_PLASTIC)

    # ---- piston: chrome rod; slides in the shroud, locked by friction like a gas spring
    lift = P("gas_spring", 0.55, parent=0,
             joint={"name": "height", "type": "slide", "axis": [0, 0, 1], "range": [-0.08, 0.03],
                    "frictionloss": 1500.0, "damping": 200.0, "solimpfriction": [0.9999, 0.99999, 0.001, 0.5, 2.0],   # a locked gas spring barely creeps
                    "at": [0, 0, 0.33]})
    parts.append(lift)
    rod = B.cylinder(0.014, 0.10, at=(0, 0, 0.30), verts=48)
    lift.add(rod, CHROME)

    # ---- seat, back and arms: turn on the piston
    seat = P("seat", 9.2, parent=1,
             joint={"name": "swivel", "type": "hinge", "axis": [0, 0, 1], "damping": 0.6,
                    "frictionloss": 0.4, "at": [0, 0, SEAT_Z]})
    parts.append(seat)
    mech = B.rounded_box((0.24, 0.26, 0.045), 6 * MM, 3, at=(0, 0.01, SEAT_Z))
    seat.add(mech, DARK_PLASTIC)
    lever = tapered_bar((0.11, -0.04, SEAT_Z + 0.02), (0.20, -0.07, SEAT_Z + 0.012),
                                                    0.012, 0.016, 0.008, 0.008, 2 * MM, "lever")
    seat.add(lever, DARK_PLASTIC, hull=False)
    shell = B.rounded_box((0.49, 0.47, 0.03), 10 * MM, 4, at=(0, 0, SEAT_Z + 0.042))
    seat.add(shell, GREY_PLASTIC)
    cushion = B.rounded_box((0.475, 0.455, 0.065), 26 * MM, 5, at=(0, -0.002, SEAT_Z + 0.062))
    sub = cushion.modifiers.new("soft", "SUBSURF")
    sub.levels = sub.render_levels = 1
    uv_project(cushion)
    seat.add(cushion, dict(BLUE_FABRIC, rgba=[1, 1, 1, 1]), fabric_texture, uv=True)
    # spine: from under the seat's rear up behind the back
    spine = tapered_bar((0, 0.12, SEAT_Z + 0.02), (0, 0.29, SEAT_Z + 0.02), 0.07, 0.065, 0.025, 0.025, 6 * MM, "spine")
    seat.add(spine, DARK_PLASTIC)
    up = B.rounded_box((0.065, 0.025, 0.26), 8 * MM, 3, at=(0, 0, -0.13))   # centred: place() moves it
    place(up, (0, 0.30, SEAT_Z + 0.02 + 0.13), (math.radians(-10), 0, 0))
    seat.add(up, DARK_PLASTIC)
    back = grid_mesh("back", 0.46, 0.50, 24, 24, 0.55, 0.028, 6 * MM)
    place(back, (0, 0.30, SEAT_Z + 0.43), (math.radians(-12), 0, 0))
    seat.add(back, GREY_PLASTIC)
    pad = grid_mesh("back_pad", 0.42, 0.40, 24, 24, 0.55, 0.02, 9 * MM)
    place(pad, (0, 0.30 - 0.022, SEAT_Z + 0.41), (math.radians(-12), 0, 0))
    uv_project(pad)
    seat.add(pad, dict(BLUE_FABRIC, rgba=[1, 1, 1, 1]), fabric_texture, hull=False, uv=True)
    for s in (-1, 1):
        x = s * 0.265
        bracket = tapered_bar((s * 0.11, 0.02, SEAT_Z + 0.025), (x, 0.02, SEAT_Z + 0.025), 0.05, 0.05, 0.014, 0.014, 4 * MM, "arm_bracket")
        seat.add(bracket, DARK_PLASTIC)
        post = B.rounded_box((0.028, 0.06, 0.22), 9 * MM, 4, at=(x, 0.02, SEAT_Z + 0.025))
        seat.add(post, DARK_PLASTIC)
        top = B.rounded_box((0.075, 0.25, 0.028), 12 * MM, 4, at=(x, 0.0, SEAT_Z + 0.245))
        seat.add(top, RUBBER)

    # ---- casters: each swivels on its stem; its twin wheel rolls
    for k in range(5):
        a = math.radians(90 + 72 * k)
        u = np.array([math.cos(a), math.sin(a), 0.0])
        t = np.array([-u[1], u[0], 0.0])                      # the wheel's axle
        sw = np.array([*(u[:2] * R_CASTER), 0.06])            # top of the stem
        c = P(f"caster_{k}", 0.06, parent=0,
              joint={"name": "swivel", "type": "hinge", "axis": [0, 0, 1], "damping": 0.002,
                     "frictionloss": 0.0005, "at": sw.tolist()})
        parts.append(c)
        stem = B.cylinder(0.006, 0.02, at=(*sw[:2], 0.045), verts=24)
        c.add(stem, CHROME, hull=False)
        wc = sw[:2] + u[:2] * TRAIL
        hood = tapered_bar((*(sw[:2] - u[:2] * 0.012), WHEEL_R - 0.002), (*(wc + u[:2] * 0.026), WHEEL_R - 0.002),
                           0.026, 0.024, 0.042, 0.03, 8 * MM, "hood")
        c.add(hood, DARK_PLASTIC)       # rides above the floor; the wheels touch it
        ci = len(parts) - 1
        for side in (-1, 1):            # twin wheels, each on its own axle half: they turn apart, so the caster swivels easily
            at = wc + t[:2] * side * 0.0145
            w = P(f"wheel_{k}{'ab'[side > 0]}", 0.02, parent=ci,
                  joint={"name": "roll", "type": "hinge", "axis": np.round(t, 6).tolist(), "damping": 0.0002,
                         "at": [*at, WHEEL_R]})
            parts.append(w)
            wh = B.cylinder(WHEEL_R, 0.012, at=(0, 0, -0.006), verts=48, bevel=3 * MM)
            place(wh, (*at, WHEEL_R), (math.pi / 2, 0, a))
            w.add(wh, RUBBER)
    return parts


def write(out: pathlib.Path, parts: list[P]):
    """The library's form (playground/assets/<id>/asset.json), the item's bottom centre at its
    origin; parts nest (a wheel on its caster on the base)."""
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    V = np.vstack([a[0] for p in parts for a, _, _ in p.vis])
    lo, hi = V.min(0), V.max(0)
    shift = -np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    frames, bodies = [], []
    for i, p in enumerate(parts):
        c = np.zeros(3) if p.joint is None else np.array(p.joint["at"]) + shift
        frames.append(c)
        vis, col = [], []
        for k, ((Vv, F, UV), look, tex) in enumerate(p.vis):
            name = f"b{i}_vis_{k}.obj"
            write_obj(out / name, Vv + shift - c, F, UV)
            v = {"mesh": name, "rgba": look["rgba"], "roughness": look["roughness"], "metallic": look["metallic"]}
            if tex:
                tn = f"b{i}_tex.png"
                if not (out / tn).exists():
                    tex(out / tn)
                v["texture"] = tn
            vis.append(v)
        for k, h in enumerate(p.col):
            h = h.convex_hull
            name = f"b{i}_col_{k}.obj"
            write_obj(out / name, h.vertices + shift - c, h.faces)
            col.append({"mesh": name, "volume": float(h.volume)})
        b = {"name": p.name, "visuals": vis, "collision_parts": col, "mass": round(p.mass, 6),
             "frame": [*np.round(c, 6).tolist(), 1, 0, 0, 0]}
        if p.parent is None:
            b.update(parent=None, root=True, pos=[0, 0, 0], quat=[1, 0, 0, 0])
        else:
            j = {k: v for k, v in p.joint.items() if k != "at"}
            b.update(parent=p.parent, collide=False, pos=np.round(c - frames[p.parent], 6).tolist(),
                     quat=[1, 0, 0, 0], joint={"pos": [0, 0, 0], **j})
        bodies.append(b)
    meta = {"source": "AI-written Blender script (test)", "usd": None, "mass": round(sum(p.mass for p in parts), 5),
            "friction": None, "com": None, "size": np.round(hi - lo, 4).tolist(),
            "collision": "convex pieces; seat turns, gas spring slides (locked by friction), casters swivel, wheels roll",
            "visuals": [], "collision_parts": [], "bodies": bodies, "unstated_mass": []}
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    return meta


def hero(out: pathlib.Path, meta: dict, path: pathlib.Path, gpu: bool, samples=int(os.environ.get("HERO_SAMPLES", 256)),
         res=int(os.environ.get("HERO_RES", 1200))):
    """A photo-style Cycles render: fabric with a woven bump, chrome, a soft-lit lab floor."""
    B._reset()
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    if gpu:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                if any(d.type == kind for d in prefs.devices):
                    break
            except TypeError:
                continue
        for d in prefs.devices:
            d.use = d.type != "CPU"
        sc.cycles.device = "GPU"
        print("devices:", [(d.name, d.type, d.use) for d in prefs.devices])
    sc.cycles.samples, sc.cycles.use_denoising = samples, True
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("w")
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.92, 0.95, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.2
    sc.world = world
    for b in meta["bodies"]:
        for v in b["visuals"]:
            Vv, F, UV = B._read_obj(out / v["mesh"])
            me = bpy.data.meshes.new(v["mesh"])
            me.from_pydata((Vv + np.array(b["frame"][:3])).tolist(), [], F.tolist())
            if UV is not None:
                layer = me.uv_layers.new()
                for li, loop in enumerate(me.loops):
                    layer.data[li].uv = UV[loop.vertex_index]
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(35))
            obj = bpy.data.objects.new(v["mesh"], me)
            sc.collection.objects.link(obj)
            mat = bpy.data.materials.new(v["mesh"])
            nt = mat.node_tree
            bsdf = nt.nodes["Principled BSDF"]
            lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in v["rgba"][:3]]
            bsdf.inputs["Base Color"].default_value = (*lin, 1)        # the colours are sRGB
            bsdf.inputs["Roughness"].default_value = v["roughness"]
            bsdf.inputs["Metallic"].default_value = v["metallic"]
            if v.get("texture"):
                tn = nt.nodes.new("ShaderNodeTexImage")
                tn.image = bpy.data.images.load(str(out / v["texture"]))
                nt.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
                bsdf.inputs["Sheen Weight"].default_value = 0.6
                bump = nt.nodes.new("ShaderNodeBump")
                bump.inputs["Strength"].default_value = 0.35
                bump.inputs["Distance"].default_value = 0.0005
                nt.links.new(tn.outputs["Color"], bump.inputs["Height"])
                nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
            elif v["metallic"] < 0.5:      # moulded plastic: a faint texture
                nz = nt.nodes.new("ShaderNodeTexNoise")
                nz.inputs["Scale"].default_value = 900.0
                bump = nt.nodes.new("ShaderNodeBump")
                bump.inputs["Strength"].default_value = 0.05
                nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
                nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
                bsdf.inputs["Coat Weight"].default_value = 0.1 if v["roughness"] < 0.45 else 0.0
            me.materials.append(mat)
    # floor: grey speckled lab vinyl
    bpy.ops.mesh.primitive_plane_add(size=8)
    fl = bpy.context.active_object
    fm = bpy.data.materials.new("floor")
    nt = fm.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 400.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.10, 0.105, 0.11, 1)
    ramp.color_ramp.elements[1].color = (0.22, 0.225, 0.23, 1)
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.35
    fl.data.materials.append(fm)
    # wall behind: the photo's yellow
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 2.2, 2), rotation=(math.pi / 2, 0, 0))
    wall = bpy.context.active_object
    wm = bpy.data.materials.new("wall")
    wm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.86, 0.66, 0.14, 1)
    wm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.8
    wall.data.materials.append(wm)
    for loc, e, s in (((1.6, -1.8, 2.6), 260, 1.6), ((-2.2, -0.8, 1.6), 70, 2.0), ((0.4, 1.6, 2.8), 90, 1.5)):
        ld = bpy.data.lights.new("l", "AREA")
        ld.energy, ld.size = e, s
        lo = bpy.data.objects.new("l", ld)
        lo.location = loc
        lo.rotation_euler = B._look(np.array([0, 0, 0.5]) - np.array(loc))
        sc.collection.objects.link(lo)
    cam = bpy.data.cameras.new("c")
    cam.lens = 55
    co = bpy.data.objects.new("c", cam)
    co.location = (1.55, -1.95, 1.25)
    co.rotation_euler = B._look(np.array([0, 0.02, 0.48]) - np.array(co.location))
    sc.collection.objects.link(co)
    sc.camera = co
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    gpu = "--gpu" in argv
    argv = [a for a in argv if a != "--gpu"]
    heropath = None
    if "--hero" in argv:
        i = argv.index("--hero")
        heropath = pathlib.Path(argv[i + 1])
        del argv[i:i + 2]
    out = pathlib.Path(argv[0]) if argv else B.catalog.ASSETS / "ai_lab_chair"
    times = {}
    t = time.time()
    parts = build()
    meta = write(out, parts)
    times["model_and_export_s"] = round(time.time() - t, 2)
    t = time.time()
    B.thumb(out, meta)
    times["thumbnail_s"] = round(time.time() - t, 2)
    if heropath:
        t = time.time()
        hero(out, meta, heropath, gpu)
        times["hero_render_s"] = round(time.time() - t, 2)
    print(json.dumps({"mass": meta["mass"], "size": meta["size"], "bodies": len(meta["bodies"]),
                      "pieces": sum(len(b["collision_parts"]) for b in meta["bodies"]), **times}))


if __name__ == "__main__":
    main()
