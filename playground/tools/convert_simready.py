"""Convert a NVIDIA SimReady asset (USD with its MuJoCo payload) into files MuJoCo loads.

    python -m playground.tools.convert_simready build/simready/kitchenware_bowl_b01 playground/assets/bowl

The asset's own MuJoCo variant is switched on and read as published:
- visual meshes, one OBJ per material, with the base colour texture (PNG, at most 512 px);
- the mass and centre of mass the asset states (physics:mass, physics:centerOfMass);
- the collision shape it asks for (physics:approximation = convexHull) as an OBJ that MuJoCo
  turns into a convex hull.

Hollow things (a bowl, a crate) can't be one convex hull: MuJoCo collides every mesh as its
convex hull, so the inside would be solid. For those (--hollow) the mesh is split into convex
pieces with CoACD, as MuJoCo's documentation advises for non-convex shapes, and the stated
mass is spread over the pieces by volume.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib

import numpy as np
import trimesh
from PIL import Image
from pxr import Usd, UsdGeom, UsdShade

TEX = 512


def open_stage(path: pathlib.Path) -> Usd.Stage:
    stage = Usd.Stage.Open(str(path))
    root = stage.GetDefaultPrim()
    vs = root.GetVariantSets()
    stage.SetEditTarget(stage.GetSessionLayer())
    for name in vs.GetNames():
        sel = "Enabled" if name == "MuJoCo" else "Disabled"
        if sel in vs.GetVariantSet(name).GetVariantNames():
            vs.GetVariantSet(name).SetVariantSelection(sel)
    return stage


def _tex_path(inp) -> pathlib.Path | None:
    v = inp.Get()
    if not v:
        return None
    st = inp.GetAttr().GetPropertyStack()
    layer = st[0].layer.realPath if st else ""
    p = pathlib.Path(v.resolvedPath or (pathlib.Path(layer).parent / v.path))
    return p if p.exists() else None


def material_info(mat) -> dict:
    """Base colour (and texture), roughness and metalness from an MDL or preview material."""
    info = {"rgba": [0.7, 0.7, 0.72, 1.0], "tex": None, "rough": 0.6, "metal": 0.0, "scale": (1, 1)}
    if not mat:
        return info
    for sp in Usd.PrimRange(mat.GetPrim()):
        sh = UsdShade.Shader(sp)
        if not sh:
            continue
        sid = sh.GetIdAttr().Get() or ""
        if sid == "UsdPreviewSurface":
            i = sh.GetInput("diffuseColor")
            if i and i.HasConnectedSource():
                src, _, _ = i.GetConnectedSource()
                f = src.GetInput("file") if src else None
                if f and info["tex"] is None:
                    info["tex"] = _tex_path(f)
            elif i and i.Get() is not None and info["tex"] is None:
                info["rgba"][:3] = list(i.Get())
            continue
        for name, key in (("diffuse_color_constant", "rgb"), ("diffuse_tint", "tint"),
                          ("reflection_roughness_constant", "rough"), ("metallic_constant", "metal"),
                          ("texture_scale", "scale")):
            i = sh.GetInput(name)
            if i and i.Get() is not None:
                v = i.Get()
                if key == "rgb":
                    info["rgba"][:3] = list(v)
                elif key == "tint":
                    info["tint"] = list(v)
                elif key == "scale":
                    info["scale"] = tuple(v)[:2]
                else:
                    info[key] = float(v)
        i = sh.GetInput("diffuse_texture")
        if i and i.Get():
            info["tex"] = _tex_path(i)
    if info["tex"] is not None:
        info["rgba"][:3] = info.get("tint", [1.0, 1.0, 1.0])
    return info


def _uv(prim, n_idx, n_pts):
    pv = UsdGeom.PrimvarsAPI(prim)
    for nm in ("st", "st0", "UVMap", "uv", "map1"):
        v = pv.GetPrimvar(nm)
        if v and v.HasValue():
            uv = np.array(v.ComputeFlattened(), float)
            interp = v.GetInterpolation()
            if interp == "faceVarying" and len(uv) >= n_idx:
                return uv, "corner"
            if interp in ("vertex", "varying") and len(uv) >= n_pts:
                return uv, "point"
    return None, None


def friction(stage) -> float | None:
    """Static friction of the asset's physics materials (MuJoCo takes one sliding coefficient)."""
    vals = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        a = prim.GetAttribute("physics:staticFriction")
        if a and a.Get() is not None:
            vals.append(float(a.Get()))
    return round(max(vals), 3) if vals else None


def read(stage):
    """Visual groups by material, collision meshes, and the stated mass properties."""
    xc = UsdGeom.XformCache()
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    groups: dict[str, dict] = {}
    colliders, mass, com = [], None, None
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        im = UsdGeom.Imageable(prim)
        if im.ComputeVisibility() == "invisible":
            continue
        mesh = UsdGeom.Mesh(prim)
        pts = np.array(mesh.GetPointsAttr().Get(), float)
        cnt = np.array(mesh.GetFaceVertexCountsAttr().Get())
        idx = np.array(mesh.GetFaceVertexIndicesAttr().Get())
        M = np.array(xc.GetLocalToWorldTransform(prim)).T
        P = (np.c_[pts, np.ones(len(pts))] @ M.T)[:, :3] * mpu
        starts = np.r_[0, np.cumsum(cnt)[:-1]]
        tri_face, tri_corner = [], []
        for f, (c, s) in enumerate(zip(cnt, starts)):
            for k in range(1, c - 1):
                tri_face.append(f)
                tri_corner.append((s, s + k, s + k + 1))
        tri_face, tri_corner = np.array(tri_face), np.array(tri_corner)
        approx = prim.GetAttribute("physics:approximation")
        if prim.HasAPI("PhysicsCollisionAPI") or (approx and approx.Get()):
            colliders.append(trimesh.Trimesh(P, idx[tri_corner], process=True))
            a = prim.GetAttribute("physics:mass")
            if a and a.Get():
                mass = (mass or 0.0) + float(a.Get())
            a = prim.GetAttribute("physics:centerOfMass")
            if a and a.Get() is not None and com is None:
                com = (M[:3, :3] @ np.array(a.Get()) + M[:3, 3]) * mpu
        if im.ComputePurpose() in ("guide", "proxy"):
            continue
        uv, uvmode = _uv(prim, len(idx), len(pts))
        face_mat = np.zeros(len(cnt), int)
        mats = [UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]]
        for sub in UsdGeom.Subset.GetAllGeomSubsets(mesh):
            ind = np.array(sub.GetIndicesAttr().Get() or [], int)
            mats.append(UsdShade.MaterialBindingAPI(sub.GetPrim()).ComputeBoundMaterial()[0])
            face_mat[ind[ind < len(cnt)]] = len(mats) - 1
        for mi, m in enumerate(mats):
            sel = face_mat[tri_face] == mi
            if not sel.any():
                continue
            corners = tri_corner[sel].reshape(-1)
            V = P[idx[corners]]
            UV = None
            if uvmode == "corner":
                UV = uv[corners]
            elif uvmode == "point":
                UV = uv[idx[corners]]
            key = str(m.GetPath()) if m else "none"
            g = groups.setdefault(key, {"V": [], "UV": [], "mat": m, "hasuv": True})
            g["V"].append(V)
            g["UV"].append(UV if UV is not None else np.zeros((len(V), 2)))
            g["hasuv"] &= UV is not None
    return groups, colliders, mass, com


def write_obj(path: pathlib.Path, V, F, UV=None):
    lines = [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in V]
    if UV is not None:
        lines += [f"vt {u:.5f} {v:.5f}" for u, v in UV]
        lines += [f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}" for a, b, c in F]
    else:
        lines += [f"f {a+1} {b+1} {c+1}" for a, b, c in F]
    path.write_text("\n".join(lines) + "\n")


def _merge_uv_mesh(V, UV):
    """Weld corners that share position and uv, so the OBJ stays small."""
    key = np.round(np.c_[V, UV], 6)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return V[first], UV[first], inv.reshape(-1, 3)


def convert(src: pathlib.Path, out: pathlib.Path, hollow=False, max_tris=60000) -> dict:
    usd = next(p for p in sorted((src / "simready_usd").glob("*.usd*")) if p.suffix in (".usd", ".usda"))
    stage = open_stage(usd)
    groups, colliders, mass, com = read(stage)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    lo = np.min([np.vstack(g["V"]).min(0) for g in groups.values()], axis=0)
    hi = np.max([np.vstack(g["V"]).max(0) for g in groups.values()], axis=0)
    # Body frame: centred in x and y, z = 0 at the bottom, so placing it is easy.
    origin = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    visuals = []
    total = sum(len(np.vstack(g["V"])) // 3 for g in groups.values())
    for k, (key, g) in enumerate(groups.items()):
        info = material_info(g["mat"])
        V = np.vstack(g["V"]) - origin
        UV = np.vstack(g["UV"])
        has_tex = info["tex"] is not None and g["hasuv"]
        if has_tex:
            UV = UV * np.array(info["scale"])
            Vw, UVw, F = _merge_uv_mesh(V, UV)
        else:
            tm = trimesh.Trimesh(V, np.arange(len(V)).reshape(-1, 3), process=True)
            Vw, UVw, F = tm.vertices, None, tm.faces
        if total > max_tris and len(F) > 2000:
            # Too heavy to render live: decimate (keeps the look, drops tiny detail).
            tm = trimesh.Trimesh(Vw, F, process=False)
            target = max(1000, int(len(F) * max_tris / total))
            try:
                tm = tm.simplify_quadric_decimation(face_count=target)
                Vw, F, UVw, has_tex = tm.vertices, tm.faces, None, False
            except Exception:  # noqa: BLE001
                pass
        vis = {"mesh": f"vis_{k}.obj", "rgba": [round(float(c), 4) for c in info["rgba"]],
               "roughness": info["rough"], "metallic": info["metal"]}
        if has_tex:
            img = Image.open(info["tex"]).convert("RGB")
            img.thumbnail((TEX, TEX))
            img.save(out / f"tex_{k}.png", optimize=True)
            vis["texture"] = f"tex_{k}.png"
        elif info["tex"] is not None:
            img = Image.open(info["tex"]).convert("RGB").resize((8, 8))
            vis["rgba"][:3] = [round(float(c) / 255, 4) for c in np.array(img).reshape(-1, 3).mean(0)]
        write_obj(out / vis["mesh"], Vw, F, UVw if has_tex else None)
        visuals.append(vis)
    col = trimesh.util.concatenate(colliders) if colliders else trimesh.util.concatenate(
        [trimesh.Trimesh(np.vstack(g["V"]), np.arange(len(np.vstack(g["V"]))).reshape(-1, 3)) for g in groups.values()])
    col.apply_translation(-origin)
    parts = []
    if hollow:
        import coacd
        coacd.set_log_level("error")
        pieces = coacd.run_coacd(coacd.Mesh(col.vertices, col.faces), threshold=0.04, max_convex_hull=24,
                                 preprocess_mode="auto", seed=1)
        lo_c, hi_c = col.bounds
        for k, (v, f) in enumerate(pieces):
            # CoACD's pieces can stick out of the shape by a few mm (a table top would sit
            # 1 cm above where it's drawn); pull them back inside the object's own bounding box.
            piece = trimesh.Trimesh(np.clip(v, lo_c, hi_c), f).convex_hull
            v, f = piece.vertices, piece.faces
            if len(f) < 4:
                continue
            write_obj(out / f"col_{k}.obj", v, f)
            parts.append({"mesh": f"col_{k}.obj", "volume": float(trimesh.Trimesh(v, f).convex_hull.volume)})
    else:
        hull = col.convex_hull
        write_obj(out / "col_0.obj", hull.vertices, hull.faces)
        parts.append({"mesh": "col_0.obj", "volume": float(hull.volume)})
    meta = {
        "source": src.name, "usd": usd.name,
        "mass": round(float(mass), 5) if mass else None,
        "friction": friction(stage),
        "com": None if com is None else np.round(com - origin, 5).tolist(),
        "size": np.round(hi - lo, 4).tolist(),
        "collision": "convex pieces (CoACD)" if hollow else "convex hull (as the asset specifies)",
        "visuals": visuals, "collision_parts": parts,
    }
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--hollow", action="store_true")
    a = ap.parse_args(argv)
    m = convert(pathlib.Path(a.src), pathlib.Path(a.out), a.hollow)
    print(json.dumps({k: m[k] for k in ("mass", "size", "collision")}), len(m["collision_parts"]), "parts")


if __name__ == "__main__":
    main()
