"""Lab items no one publishes with a usable licence and physics, modelled here in Blender:

    python -m playground.tools.build_inhouse [ids ...]

24-well plate and its lid (ANSI/SLAS standard footprint), glass test tubes (16 x 150 mm with a
screw cap, and 13 x 100 mm), a glass stirring rod, a magnetic stir bar, a hot plate stirrer, and
a target mark (a sticker for the bench). Each is written in the library's form
(playground/assets/<id>/asset.json): visual meshes made in Blender (lathed glass, bevelled and
smoothed edges), collision shapes as convex pieces (hollow items stay hollow, so things go into
them), and the mass of its real material and size. The library picture is a Cycles render.

Requires Blender's Python module (pip install bpy).
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib

import bpy
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

from .. import catalog
from .convert_simready import write_obj

MM = 0.001
GLASS = 2230.0          # borosilicate, kg/m3
POLYSTYRENE = 1050.0
POLYPROPYLENE = 900.0
PTFE = 2200.0

CLEAR_GLASS = dict(rgba=[0.86, 0.93, 0.96, 0.32], roughness=0.05, metallic=0.0, glass=True)
CLEAR_PS = dict(rgba=[0.9, 0.94, 0.97, 0.38], roughness=0.08, metallic=0.0, glass=True)


# ---------------------------------------------------------------- Blender modelling


def _reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _arrays(obj, uv=False):
    """An object's evaluated mesh (modifiers applied) as triangles: V, F (and per-vertex UV),
    every face wound outward."""
    V, F, UV = _raw_arrays(obj, uv)
    tm = trimesh.Trimesh(V, F, process=False)
    if tm.is_watertight:
        trimesh.repair.fix_normals(tm)
        F = np.asarray(tm.faces)
    return V, F, UV


def _raw_arrays(obj, uv=False):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    M = np.array(obj.matrix_world)
    V = np.array([M[:3, :3] @ np.array(v.co) + M[:3, 3] for v in me.vertices], dtype=float)
    tris = me.loop_triangles
    if not uv or not me.uv_layers:
        F = np.array([t.vertices[:] for t in tris])
        ev.to_mesh_clear()
        return V, F, None
    layer = me.uv_layers.active.data
    corners_v = np.array([[me.loops[li].vertex_index for li in t.loops] for t in tris]).reshape(-1)
    corners_uv = np.array([[layer[li].uv[:] for li in t.loops] for t in tris]).reshape(-1, 2)
    key = np.round(np.c_[V[corners_v], corners_uv], 6)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    ev.to_mesh_clear()
    return V[corners_v][first], inv.reshape(-1, 3), corners_uv[first]


def lathe(profile, steps=64, smooth=1):
    """A solid of revolution about z from a closed (r, z) profile (metres), Blender's Screw
    modifier, then Subdivision Surface to round its edges."""
    me = bpy.data.meshes.new("profile")
    pts = [(r, 0.0, z) for r, z in profile]
    me.from_pydata(pts, [(i, i + 1) for i in range(len(pts) - 1)], [])
    obj = bpy.data.objects.new("lathe", me)
    bpy.context.scene.collection.objects.link(obj)
    sc = obj.modifiers.new("screw", "SCREW")
    sc.angle, sc.steps, sc.render_steps, sc.axis = 2 * math.pi, steps, steps, "Z"
    sc.use_merge_vertices, sc.merge_threshold = True, 1e-6
    sc.use_normal_calculate = True
    if smooth:
        ss = obj.modifiers.new("smooth", "SUBSURF")
        ss.levels = ss.render_levels = smooth
        ss.boundary_smooth = "PRESERVE_CORNERS"
    return obj


def rounded_box(size, bevel, segments=3, at=(0, 0, 0)):
    """A box (full size, metres) with bevelled edges; at = its bottom centre."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.scale = size
    obj.location = (at[0], at[1], at[2] + size[2] / 2)
    bpy.ops.object.transform_apply(scale=True)
    b = obj.modifiers.new("bevel", "BEVEL")
    b.width, b.segments, b.limit_method = bevel, segments, "ANGLE"
    return obj


def cylinder(r, h, at=(0, 0, 0), verts=48, bevel=0.0):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, vertices=verts,
                                        location=(at[0], at[1], at[2] + h / 2))
    obj = bpy.context.active_object
    if bevel:
        b = obj.modifiers.new("bevel", "BEVEL")
        b.width, b.segments, b.limit_method = bevel, 3, "ANGLE"
    return obj


def boolean(obj, cutters, op="DIFFERENCE"):
    for c in cutters:
        m = obj.modifiers.new("bool", "BOOLEAN")
        m.operation, m.object, m.solver = op, c, "EXACT"
    bpy.context.view_layer.objects.active = obj
    for m in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)
    for c in cutters:
        bpy.data.objects.remove(c)
    return obj


def arc(cr, cz, r, a0, a1, n=8):
    return [(cr + r * math.cos(a), cz + r * math.sin(a)) for a in np.linspace(math.radians(a0), math.radians(a1), n)]


# ---------------------------------------------------------------- collision pieces


def _hull(P) -> trimesh.Trimesh:
    return trimesh.Trimesh(np.asarray(P)).convex_hull


def shell(ro, ri, zs, n=12):
    """Convex pieces for a hollow shape of revolution (a tube): between heights zs, its wall from
    radius ri(z) out to ro(z) in n sectors; a band with no inside (ri = 0) is one solid piece."""
    out = []
    a = np.linspace(0, 2 * math.pi, n + 1)
    for z0, z1 in zip(zs[:-1], zs[1:]):
        if ri(z0) < 1e-5 and ri(z1) < 1e-5:
            ring = [(ro(z) * math.cos(t), ro(z) * math.sin(t), z) for z in (z0, z1) for t in a[:-1]]
            out.append(_hull(ring))
            continue
        for t0, t1 in zip(a[:-1], a[1:]):
            P = [(r * math.cos(t), r * math.sin(t), z) for z in (z0, z1) for t in (t0, t1) for r in (ro(z), max(ri(z), 1e-4))]
            out.append(_hull(P))
    return out


def box(size, center) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=size, transform=trimesh.transformations.translation_matrix(center))


# ---------------------------------------------------------------- textures


def _font(px):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if pathlib.Path(f).exists():
            return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def target_texture(path):
    S = 512
    img = Image.new("RGB", (S, S), (250, 250, 248))
    d = ImageDraw.Draw(img)
    for k, col in enumerate([(214, 40, 40), (250, 250, 248), (214, 40, 40), (250, 250, 248), (214, 40, 40)]):
        r = S / 2 * (1 - k * 0.19)
        d.ellipse([S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r], fill=col)
    d.line([S / 2, 6, S / 2, S - 6], fill=(30, 30, 30), width=4)
    d.line([6, S / 2, S - 6, S / 2], fill=(30, 30, 30), width=4)
    img.save(path)


def panel_texture(path):
    """The hot plate's front panel: display, labels and scale marks round the two knobs."""
    W, H = 1024, 362
    img = Image.new("RGB", (W, H), (52, 56, 62))
    d = ImageDraw.Draw(img)
    f, small = _font(30), _font(22)
    cy = H // 2
    for cx, label, col in ((256, "HEAT", (236, 120, 40)), (768, "STIR", (60, 140, 230))):
        for k in range(11):
            a = math.radians(225 - k * 27)
            r0, r1 = 92, 112 if k % 5 == 0 else 102
            d.line([cx + r0 * math.cos(a), cy - r0 * math.sin(a), cx + r1 * math.cos(a), cy - r1 * math.sin(a)],
                   fill=(220, 222, 226), width=3)
        d.text((cx, 22), label, font=f, fill=col, anchor="mt")
    d.rounded_rectangle([430, cy - 46, 594, cy + 10], 8, fill=(18, 20, 22))
    d.text((512, cy - 18), "25 °C", font=f, fill=(255, 150, 60), anchor="mm")
    d.rounded_rectangle([450, cy + 22, 574, cy + 62], 8, fill=(18, 20, 22))
    d.text((512, cy + 42), "0 rpm", font=small, fill=(140, 190, 240), anchor="mm")
    img.save(path)


def plate_texture(path):
    """The 24-well plate's printed row letters and column numbers (on its clear deck)."""
    img = Image.new("RGB", (1024, 688), (232, 240, 246))
    img.save(path)


# ---------------------------------------------------------------- the items


class Part:
    def __init__(self, name):
        self.name, self.vis, self.col, self.joint = name, [], [], None

    def visual(self, arrays, look, texture=None):
        self.vis.append((arrays, look, texture))
        return self

    def collide(self, meshes):
        self.col += list(meshes)
        return self


def _write(id_, parts: list[Part], masses, note=""):
    """Write the parts in the library's form, the item's bottom centre at its origin. Part 0 is
    the main body; others carry a joint (a knob) or sit on by a weld (a cap)."""
    out = catalog.ASSETS / id_
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    V = np.vstack([a[0] for p in parts for a, _, _ in p.vis])
    lo, hi = V.min(0), V.max(0)
    shift = -np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    bodies = []
    for i, (p, mass) in enumerate(zip(parts, masses)):
        c = np.zeros(3) if i == 0 else (np.vstack([a[0] for a, _, _ in p.vis]).mean(0) + shift)
        if p.joint:
            c = np.array(p.joint["at"]) + shift
        vis, col = [], []
        for k, ((Vv, F, UV), look, tex) in enumerate(p.vis):
            name = f"b{i}_vis_{k}.obj"
            write_obj(out / name, Vv + shift - c, F, UV)
            v = {"mesh": name, "rgba": look["rgba"], "roughness": look["roughness"], "metallic": look["metallic"]}
            if tex:
                tex(out / f"b{i}_tex_{k}.png")
                v["texture"] = f"b{i}_tex_{k}.png"
            vis.append(v)
        for k, m in enumerate(p.col):
            h = m.convex_hull
            name = f"b{i}_col_{k}.obj"
            write_obj(out / name, h.vertices + shift - c, h.faces)
            col.append({"mesh": name, "volume": float(h.volume)})
        b = {"name": p.name, "visuals": vis, "collision_parts": col, "mass": round(mass, 6),
             "frame": [*np.round(c, 6).tolist(), 1, 0, 0, 0]}
        if i == 0:
            b.update(parent=None, root=True, pos=[0, 0, 0], quat=[1, 0, 0, 0])
        elif p.joint:
            j = {k: v for k, v in p.joint.items() if k != "at"}
            b.update(parent=0, collide=False, pos=np.round(c - bodies[0]["frame"][:3], 6).tolist(),
                     quat=[1, 0, 0, 0], joint={"pos": [0, 0, 0], **j})
        else:
            b.update(parent=0, weld=True, collide=False, pos=np.round(c, 6).tolist(), quat=[1, 0, 0, 0])
        bodies.append(b)
    meta = {"source": "Built in-house (Blender)", "usd": None, "mass": round(sum(masses), 5),
            "friction": None, "com": None, "size": np.round(hi - lo, 4).tolist(),
            "collision": "convex pieces" + note, "visuals": [], "collision_parts": [], "bodies": bodies,
            "unstated_mass": []}
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    thumb(out, meta)
    return meta


def _solid_mass(arrays, density):
    V, F, _ = arrays
    return abs(float(trimesh.Trimesh(V, F, process=True).volume)) * density


def test_tube(id_, od, length, wall, cap):
    """A round-bottomed borosilicate test tube (od x length), with a screw cap (GL thread) or a
    beaded rim."""
    _reset()
    R, t = od / 2 * MM, wall * MM
    L = length * MM
    ri = R - t
    neck = L - 12 * MM if cap else L
    prof = [(0.0, 0.0)] + arc(0, R, R, -90, 0, 10)[1:]
    if cap:            # three thread turns on the neck (drawn as rings)
        prof += [(R, neck)]
        for k in range(3):
            z = neck + (2 + k * 3.5) * MM
            prof += [(R, z), (R + 0.5 * MM, z + 0.8 * MM), (R + 0.5 * MM, z + 1.4 * MM), (R, z + 2.2 * MM)]
        prof += [(R, L - 0.6 * MM)] + arc(R - t / 2, L - 0.6 * MM, t / 2, 0, 180, 6)[1:]
    else:              # a fire-polished beaded rim
        prof += [(R, L - 1.2 * MM)] + arc(R - t / 2 + 0.25 * MM, L - 0.8 * MM, t / 2 + 0.3 * MM, -60, 180, 8)
    prof += [(ri, R)] + arc(0, R, ri, 0, -90, 10)[1:]
    glass = lathe(prof, 48, 1)
    tube = _arrays(glass)
    body = Part("tube").visual(tube, CLEAR_GLASS)
    ro_f = lambda z: math.sqrt(max(R ** 2 - (R - z) ** 2, 0)) if z < R else R
    ri_f = lambda z: (math.sqrt(max(ri ** 2 - (R - z) ** 2, 0)) if z < R else ri) if z > t else 0.0
    zs = [0.0, t, 0.45 * R, 0.75 * R, R, L]
    body.collide(shell(ro_f, ri_f, zs, 12))
    masses = [_solid_mass(tube, GLASS)]
    parts = [body]
    if cap:
        Rc, h = R + 1.6 * MM, 13 * MM
        z0 = L + 1.2 * MM - h
        cp = [(0.0, L + 1.2 * MM)] + arc(Rc - 1 * MM, L + 0.2 * MM, 1 * MM, 90, 0, 5) + \
             [(Rc, z0 + 0.6 * MM)] + arc(Rc - 0.6 * MM, z0 + 0.6 * MM, 0.6 * MM, 0, -90, 4) + \
             [(R + 0.55 * MM, z0), (R + 0.55 * MM, L), (0.0, L)]
        cobj = lathe(cp, 96, 0)
        Vc, Fc, _ = _arrays(cobj)
        # knurled grip: 36 ridges round the side
        rr = np.hypot(Vc[:, 0], Vc[:, 1])
        side = (rr > Rc - 0.05 * MM) & (Vc[:, 2] > z0 + 1.2 * MM) & (Vc[:, 2] < L - 0.2 * MM)
        th = np.arctan2(Vc[:, 1], Vc[:, 0])
        k = 1 + (0.35 * MM * np.maximum(0, np.cos(36 * th)) / Rc) * side
        Vc = Vc * np.c_[k, k, np.ones(len(k))]
        capm = (Vc, Fc, None)
        cpart = Part("cap").visual(capm, dict(rgba=[0.08, 0.09, 0.1, 1], roughness=0.55, metallic=0.0))
        cpart.collide([_hull([(Rc * math.cos(a), Rc * math.sin(a), z) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)
                              for z in (z0, L + 1.2 * MM)])])
        parts.append(cpart)
        masses.append(_solid_mass(capm, 1300.0))      # phenolic resin
    return _write(id_, parts, masses, "; a hollow glass wall, so a tube holds things")


def stirring_rod():
    _reset()
    r, L = 3 * MM, 200 * MM
    prof = [(0.0, 0.0)] + arc(0, r, r, -90, 0, 8)[1:] + [(r, L - r)] + arc(0, L - r, r, 0, 90, 8)[1:]
    obj = lathe(prof, 32, 1)
    obj.rotation_euler = (0, math.pi / 2, 0)      # it lies on the bench
    bpy.context.view_layer.update()
    rod = _arrays(obj)
    p = Part("rod").visual(rod, CLEAR_GLASS).collide([_hull(rod[0])])
    return _write("stirring_rod", [p], [_solid_mass(rod, GLASS)])


def stir_bar():
    _reset()
    r, L = 4 * MM, 25 * MM
    prof = [(0.0, 0.0)] + arc(0, r, r, -90, 0, 8)[1:] + [(r, L / 2 - 1.2 * MM), (r + 0.6 * MM, L / 2 - 0.6 * MM),
                                                         (r + 0.6 * MM, L / 2 + 0.6 * MM), (r, L / 2 + 1.2 * MM),
                                                         (r, L - r)] + arc(0, L - r, r, 0, 90, 8)[1:]
    obj = lathe(prof, 32, 1)
    obj.rotation_euler = (0, math.pi / 2, 0)
    bpy.context.view_layer.update()
    bar = _arrays(obj)
    p = Part("bar").visual(bar, dict(rgba=[0.97, 0.97, 0.96, 1], roughness=0.35, metallic=0.0)).collide([_hull(bar[0])])
    # a PTFE shell round an alnico magnet: about 3 g
    return _write("stir_bar", [p], [_solid_mass(bar, PTFE) + 0.0008])


def target_mark():
    _reset()
    obj = cylinder(25 * MM, 0.6 * MM, verts=64, bevel=0.2 * MM)
    V, F, _ = _arrays(obj)
    UV = V[:, :2] / (50 * MM) + 0.5            # printed from above
    m = (V, F, UV)
    p = Part("sticker").visual(m, dict(rgba=[1, 1, 1, 1], roughness=0.6, metallic=0.0), target_texture)
    p.collide([_hull(V)])
    return _write("target_mark", [p], [0.0012])


W24, D24, H24 = 127.76 * MM, 85.48 * MM, 17.5 * MM     # ANSI/SLAS 1-2004 footprint
PITCH, WELL_R, WELL_FLOOR = 19.3 * MM, 7.8 * MM, 1.6 * MM


def _wells():
    return [((c - 2.5) * PITCH, (1.5 - r) * PITCH) for r in range(4) for c in range(6)]


def plate_24well():
    _reset()
    # deck and skirt: a bevelled block, hollowed underneath, with 24 wells through the deck
    outer = rounded_box((W24, D24, H24), 0.8 * MM)
    under = rounded_box((W24 - 2.4 * MM, D24 - 2.4 * MM, H24 - 2.0 * MM), 0.3 * MM, at=(0, 0, -0.01 * MM))
    holes = [cylinder(WELL_R, H24, at=(x, y, 2 * MM)) for x, y in _wells()]
    # A1 corner chamfer
    bpy.ops.mesh.primitive_cube_add(size=1)
    ch = bpy.context.active_object
    ch.scale = (8 * MM, 8 * MM, 3 * H24)
    ch.rotation_euler = (0, 0, math.pi / 4)
    ch.location = (-W24 / 2, D24 / 2, 0)
    deck = boolean(outer, [under, *holes, ch])
    wells = []
    for x, y in _wells():          # each well: a clear tube with a flat floor
        w = cylinder(WELL_R + 0.9 * MM, H24 - WELL_FLOOR + 0.2 * MM, at=(x, y, WELL_FLOOR - 0.2 * MM), verts=40)
        cut = cylinder(WELL_R, H24, at=(x, y, WELL_FLOOR + 1.0 * MM), verts=40)
        wells.append(boolean(w, [cut]))
    for w in wells:
        w.select_set(True)
    deck.select_set(True)
    bpy.context.view_layer.objects.active = deck
    bpy.ops.object.join()
    plate = _arrays(deck)
    p = Part("plate").visual(plate, CLEAR_PS)
    # collision: well floors, the walls between the wells, the border and the skirt
    t = PITCH - 2 * WELL_R
    gx, gy = 6 * PITCH, 4 * PITCH
    cols = [box((gx, gy, 1.0 * MM), (0, 0, WELL_FLOOR + 0.5 * MM))]
    zc, hh = (WELL_FLOOR + H24) / 2, H24 - WELL_FLOOR
    cols += [box((t, gy, hh), ((c - 3) * PITCH, 0, zc)) for c in range(1, 6)]
    cols += [box((gx, t, hh), (0, (r - 2) * PITCH, zc)) for r in range(1, 4)]
    bx, by = (W24 - gx) / 2, (D24 - gy) / 2
    cols += [box((bx, D24, 2 * MM), (s * (W24 - bx) / 2, 0, H24 - 1 * MM)) for s in (-1, 1)]
    cols += [box((gx, by, 2 * MM), (0, s * (D24 - by) / 2, H24 - 1 * MM)) for s in (-1, 1)]
    cols += [box((1.2 * MM, D24, H24), (s * (W24 - 1.2 * MM) / 2, 0, H24 / 2)) for s in (-1, 1)]
    cols += [box((W24, 1.2 * MM, H24), (0, s * (D24 - 1.2 * MM) / 2, H24 / 2)) for s in (-1, 1)]
    p.collide(cols)
    return _write("plate_24well", [p], [0.032], "; open wells, so tips and tubes go in")


def plate_24well_lid():
    _reset()
    LW, LD, LH = W24 + 0.9 * MM, D24 + 0.9 * MM, 8.0 * MM
    outer = rounded_box((LW, LD, LH), 1.0 * MM)
    inner = rounded_box((LW - 2.0 * MM, LD - 2.0 * MM, LH - 1.0 * MM), 0.5 * MM, at=(0, 0, -0.01 * MM))
    lid = boolean(outer, [inner])
    rings = []
    for x, y in _wells():           # condensation rings over each well, on the underside
        r = cylinder(WELL_R + 0.7 * MM, 0.8 * MM, at=(x, y, LH - 1.8 * MM), verts=40)
        rings.append(boolean(r, [cylinder(WELL_R + 0.1 * MM, 2 * MM, at=(x, y, LH - 2.5 * MM), verts=40)]))
    for r in rings:
        r.select_set(True)
    lid.select_set(True)
    bpy.context.view_layer.objects.active = lid
    bpy.ops.object.join()
    m = _arrays(lid)
    p = Part("lid").visual(m, CLEAR_PS)
    cols = [box((LW, LD, 1.0 * MM), (0, 0, LH - 0.5 * MM))]
    cols += [box((1.0 * MM, LD, LH), (s * (LW - 1.0 * MM) / 2, 0, LH / 2)) for s in (-1, 1)]
    cols += [box((LW, 1.0 * MM, LH), (0, s * (LD - 1.0 * MM) / 2, LH / 2)) for s in (-1, 1)]
    p.collide(cols)
    return _write("plate_24well_lid", [p], [0.018], "; its skirt fits over the plate")


def hot_plate():
    """A ceramic-top hot plate stirrer: 180 mm square top, a sloped control panel and two knobs."""
    _reset()
    HW, HD, HH = 0.205, 0.30, 0.085
    yf, zf, ys = -HD / 2, 0.035, -HD / 2 + 0.06        # front face height, where the slope meets the top
    side = [(yf, 0.0), (yf, zf), (ys, HH), (HD / 2, HH), (HD / 2, 0.0)]
    V = [(x, y, z) for x in (-HW / 2, HW / 2) for y, z in side]
    n5 = len(side)
    faces = [tuple(range(n5))[::-1], tuple(range(n5, 2 * n5))]
    faces += [(k, (k + 1) % n5, n5 + (k + 1) % n5, n5 + k) for k in range(n5)]
    me = bpy.data.meshes.new("housing")
    me.from_pydata(V, [], faces)
    me.validate()
    housing = bpy.data.objects.new("housing", me)
    bpy.context.scene.collection.objects.link(housing)
    b = housing.modifiers.new("bevel", "BEVEL")
    b.width, b.segments, b.limit_method = 5 * MM, 4, "ANGLE"
    hous = _arrays(housing)
    top = rounded_box((0.18, 0.18, 6 * MM), 2.5 * MM, 4, at=(0, HD / 2 - 0.105, HH - 1 * MM))
    topm = _arrays(top)
    # the control panel: a printed plate on the slope
    a = math.atan2(HH - zf, ys - yf)                                   # the slope's angle (the panel's tilt)
    n = np.array([0, -math.sin(a), math.cos(a)])                       # out of the panel
    pc = np.array([0, (yf + ys) / 2, (zf + HH) / 2])
    pw, ph = 0.17, 0.06
    bpy.ops.mesh.primitive_plane_add(size=1)
    panel = bpy.context.active_object
    panel.scale = (pw, ph, 1)
    panel.rotation_euler = (a, 0, 0)
    panel.location = tuple(pc + n * 0.3 * MM)
    bpy.context.view_layer.update()
    Vp, Fp, _ = _arrays(panel)
    Ml = np.array(panel.matrix_world)
    loc = (np.c_[Vp, np.ones(len(Vp))] @ np.linalg.inv(Ml).T)[:, :2]
    UVp = loc + 0.5
    body = Part("hot plate").visual(hous, dict(rgba=[0.84, 0.85, 0.86, 1], roughness=0.45, metallic=0.0)) \
        .visual(topm, dict(rgba=[0.97, 0.97, 0.96, 1], roughness=0.12, metallic=0.0)) \
        .visual((Vp, Fp, UVp), dict(rgba=[1, 1, 1, 1], roughness=0.3, metallic=0.0), panel_texture)
    body.collide([_hull(hous[0]), _hull(topm[0])])
    parts, masses = [body], [2.55]
    for k, x in enumerate((-0.0425, 0.0425)):
        kp = [(0.0, 0.0), (13 * MM, 0.0), (13 * MM, 2 * MM), (11.5 * MM, 15 * MM)] + arc(10.5 * MM, 15 * MM, 1 * MM, 0, 90, 4)[1:] + [(0.0, 16 * MM)]
        kobj = lathe(kp, 48, 0)
        Vk, Fk, _ = _arrays(kobj)
        bpy.data.objects.remove(kobj)
        ridge = (np.hypot(Vk[:, 0], Vk[:, 1]) > 10.4 * MM) & (Vk[:, 2] > 2.5 * MM) & (Vk[:, 2] < 14.5 * MM)
        th = np.arctan2(Vk[:, 1], Vk[:, 0])
        s = 1 - 0.06 * np.maximum(0, np.cos(18 * th)) * ridge
        Vk = Vk * np.c_[s, s, np.ones(len(s))]
        # pointer line on the knob's face
        pointer = trimesh.creation.box(extents=(1.6 * MM, 8 * MM, 0.6 * MM),
                                       transform=trimesh.transformations.translation_matrix([0, 5 * MM, 16 * MM]))
        R = trimesh.transformations.rotation_matrix(a, [1, 0, 0])[:3, :3]
        at = pc + np.array([x, 0, 0]) + n * 0.3 * MM
        Vk = Vk @ R.T + at
        Vpt = pointer.vertices @ R.T + at
        kn = Part(f"knob_{'heat' if k == 0 else 'stir'}")
        kn.visual((Vk, Fk, None), dict(rgba=[0.1, 0.1, 0.11, 1], roughness=0.5, metallic=0.0))
        kn.visual((Vpt, pointer.faces, None), dict(rgba=[0.95, 0.95, 0.95, 1], roughness=0.5, metallic=0.0))
        kn.collide([_hull(Vk)])
        kn.joint = {"name": "turn", "type": "hinge", "axis": np.round(n, 6).tolist(), "range": [0.0, 4.71],
                    "damping": 0.002, "frictionloss": 0.002, "at": at.tolist()}
        parts.append(kn)
        masses.append(0.012)
    return _write("hot_plate", parts, masses, "; knobs turn on their shafts")


BUILD = {
    "test_tube": lambda: test_tube("test_tube", 16, 150, 1.2, cap=True),
    "test_tube_small": lambda: test_tube("test_tube_small", 13, 100, 0.9, cap=False),
    "stirring_rod": stirring_rod,
    "stir_bar": stir_bar,
    "target_mark": target_mark,
    "plate_24well": plate_24well,
    "plate_24well_lid": plate_24well_lid,
    "hot_plate": hot_plate,
}


# ---------------------------------------------------------------- the library picture


def _read_obj(path):
    V, UV, F, FT = [], [], [], []
    for line in path.read_text().splitlines():
        s = line.split()
        if not s:
            continue
        if s[0] == "v":
            V.append([float(x) for x in s[1:4]])
        elif s[0] == "vt":
            UV.append([float(x) for x in s[1:3]])
        elif s[0] == "f":
            F.append([int(x.split("/")[0]) - 1 for x in s[1:4]])
    return np.array(V), np.array(F), (np.array(UV) if UV else None)


def thumb(out: pathlib.Path, meta: dict):
    """A 256 px Cycles render of the item for the library, on its light grey background."""
    _reset()
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples, sc.cycles.use_denoising = 96, False
    sc.render.resolution_x = sc.render.resolution_y = 512
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = 0.0
    world = bpy.data.worlds.new("w")
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.95, 0.955, 0.96, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    sc.world = world
    for b in meta["bodies"]:
        for v in b["visuals"]:
            V, F, UV = _read_obj(out / v["mesh"])
            me = bpy.data.meshes.new(v["mesh"])
            me.from_pydata((V + np.array(b["frame"][:3])).tolist(), [], F.tolist())
            if UV is not None:
                layer = me.uv_layers.new()
                for li, loop in enumerate(me.loops):
                    layer.data[li].uv = UV[loop.vertex_index]
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(35))
            obj = bpy.data.objects.new(v["mesh"], me)
            sc.collection.objects.link(obj)
            mat = bpy.data.materials.new(v["mesh"])
            bsdf = mat.node_tree.nodes["Principled BSDF"]
            r, g, bb, a = v["rgba"]
            bsdf.inputs["Base Color"].default_value = (r, g, bb, 1)
            bsdf.inputs["Roughness"].default_value = v["roughness"]
            bsdf.inputs["Metallic"].default_value = v["metallic"]
            if a < 1:            # clear glass and plastic
                bsdf.inputs["Transmission Weight"].default_value = 1.0
                bsdf.inputs["IOR"].default_value = 1.47
                bsdf.inputs["Base Color"].default_value = (min(1, r + 0.08), min(1, g + 0.05), min(1, bb + 0.04), 1)
            if v.get("texture"):
                tn = mat.node_tree.nodes.new("ShaderNodeTexImage")
                tn.image = bpy.data.images.load(str(out / v["texture"]))
                mat.node_tree.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
            me.materials.append(mat)
    sz = np.array(meta["size"])
    for loc, e in (((1.5, -1.5, 2.5), 2.0), ((-2, -1, 1.5), 0.8), ((0, 2, 2), 0.8)):
        ld = bpy.data.lights.new("l", "AREA")
        ld.energy, ld.size = e * 5 * max(sz.max(), 0.05) ** 2 / 0.01, 2.0 * max(sz.max(), 0.05) * 4
        lo = bpy.data.objects.new("l", ld)
        lo.location = tuple(np.array(loc) * max(sz.max(), 0.05) * 3)
        d = -np.array(lo.location) + np.array([0, 0, sz[2] / 2])
        lo.rotation_euler = _look(d)
        sc.collection.objects.link(lo)
    cam = bpy.data.cameras.new("c")
    cam.lens = 50
    co = bpy.data.objects.new("c", cam)
    az, el = math.radians(-45), math.radians(28)
    dist = max(max(sz), 0.06) * 2.2
    target = np.array([0, 0, sz[2] / 2])
    co.location = tuple(target + dist * np.array([math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el)]))
    co.rotation_euler = _look(target - np.array(co.location))
    sc.collection.objects.link(co)
    sc.camera = co
    sc.render.filepath = str(out / "_thumb.png")
    bpy.ops.render.render(write_still=True)
    img = Image.open(out / "_thumb.png").convert("RGBA")
    bg = Image.new("RGBA", img.size, (242, 243, 245, 255))
    bg.alpha_composite(img)
    bg.convert("RGB").resize((256, 256), Image.LANCZOS).save(out / "thumb.png")
    (out / "_thumb.png").unlink()


def _look(d):
    from mathutils import Vector
    return Vector(tuple(d)).to_track_quat("-Z", "Y").to_euler()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args(argv)
    for id_ in a.ids or list(BUILD):
        m = BUILD[id_]()
        print(f"{id_:18s} mass={m['mass']} size={m['size']} bodies={len(m['bodies'])} "
              f"pieces={sum(len(b['collision_parts']) for b in m['bodies'])}")


if __name__ == "__main__":
    main()
