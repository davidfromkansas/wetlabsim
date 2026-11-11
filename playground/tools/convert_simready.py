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
from pxr import Usd, UsdGeom, UsdPhysics, UsdShade

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


def phys_material(prim) -> dict:
    """The physics material bound to a collider (USD Physics, purpose "physics"): its static and
    dynamic friction and restitution, as the asset states them."""
    out = {}
    names = (("static", "staticFriction"), ("dynamic", "dynamicFriction"), ("restitution", "restitution"))
    mat = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial("physics")[0]
    if mat:
        for k, a in names:
            v = mat.GetPrim().GetAttribute("physics:" + a)
            if v and v.Get() is not None:
                out[k] = round(float(v.Get()), 4)
    if not out:     # no physics binding: the same values, as NVIDIA also writes them on the look material
        mat = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
        if mat:
            for k, a in names:
                v = mat.GetPrim().GetAttribute("pxr:usd:physics_" + a)
                if v and v.Get() is not None:
                    out[k] = round(float(v.Get()), 4)
    return out


def mass_props(prim, M: np.ndarray, mpu: float):
    """A collider's stated mass, centre of mass and inertia (USD Physics MassAPI: inertia about its
    centre of mass, along principalAxes, in the collider's own frame), in the world frame:
    (mass, centre, 3x3 inertia), or None when the asset doesn't state all three."""
    import mujoco
    get = lambda a: prim.GetAttribute(a).Get() if prim.GetAttribute(a) else None
    m, c, I, q = get("physics:mass"), get("physics:centerOfMass"), get("physics:diagonalInertia"), get("physics:principalAxes")
    # USD Physics' "not stated" values: a centre of mass at -inf, an inertia of zeros
    if not m or c is None or I is None or not np.all(np.isfinite(c)) or not np.any(np.array(I, float) > 0):
        return None
    R = _rigid(M, 1.0)[:3, :3]
    Rp = np.eye(3)
    if q is not None:
        qq = np.array([q.GetReal(), *q.GetImaginary()], float)
        if np.linalg.norm(qq) > 0:
            Rp = np.zeros(9)
            mujoco.mju_quat2Mat(Rp, qq / np.linalg.norm(qq))
            Rp = Rp.reshape(3, 3)
    Iv = np.array(I, float)
    # physically possible only: no principal moment exceeds the sum of the other two
    if np.any(Iv <= 0) or np.any(Iv > Iv.sum() - Iv + 1e-12):
        return None
    Rw = R @ Rp
    return float(m), (M @ np.r_[np.array(c, float), 1.0])[:3] * mpu, Rw @ np.diag(Iv * mpu ** 2) @ Rw.T


def combine_inertia(props: list, T_inv: np.ndarray):
    """Parts' stated (mass, centre, inertia) combined into one body's, in the frame T_inv maps the
    world into: {"mass", "pos", "diaginertia", "quat"} (MuJoCo's inertial: principal axes)."""
    import mujoco
    m = sum(p[0] for p in props)
    c = sum(p[0] * p[1] for p in props) / m
    I = np.zeros((3, 3))
    for mi, ci, Ii in props:       # parallel axis theorem, about the combined centre
        d = ci - c
        I += Ii + mi * (d @ d * np.eye(3) - np.outer(d, d))
    R = T_inv[:3, :3]
    I = R @ I @ R.T
    w, V = np.linalg.eigh((I + I.T) / 2)
    if np.linalg.det(V) < 0:
        V[:, 0] = -V[:, 0]
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(V).ravel())
    pos = R @ c + T_inv[:3, 3]
    return {"mass": round(m, 6), "pos": [round(float(v), 6) for v in pos],
            "diaginertia": [float(f"{max(v, 1e-12):.6g}") for v in w], "quat": [round(float(v), 6) for v in q]}


def _owner(prim) -> str:
    """The rigid body a prim belongs to (its nearest ancestor with the rigid body API), or ""."""
    while prim and prim.IsValid():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            return str(prim.GetPath())
        prim = prim.GetParent()
    return ""


def read(stage, by_body: bool = False):
    """Visual groups by material, colliders, and the stated total mass and centre of mass. Each
    collider: its mesh (world frame, metres), rigid body, stated mass, approximation, physics
    material, stated mass properties and (from a MuJoCo layer) contact solref. by_body: the
    visual groups are keyed (rigid body, material), for assets with moving parts."""
    xc = UsdGeom.XformCache()
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    groups: dict = {}
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
            tm = trimesh.Trimesh(P, idx[tri_corner], process=True)
            a = prim.GetAttribute("physics:mass")
            sr = prim.GetAttribute("mjc:solref")
            props = mass_props(prim, M, mpu)
            if props is not None:      # a centre of mass must lie inside the part (some assets state the origin)
                hull = tm.convex_hull
                if not hull.is_watertight or hull.nearest.signed_distance([props[1]])[0] < 0.02 * float(np.min(hull.extents)):
                    props = None
            colliders.append({"body": _owner(prim), "mesh": tm, "mass": float(a.Get()) if a and a.Get() else None,
                              "approx": str(approx.Get()) if approx and approx.Get() else "convexHull",
                              "material": phys_material(prim), "props": props,
                              "solref": [float(v) for v in sr.Get()] if sr and sr.Get() is not None else None})
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
            if by_body:
                key = (_owner(prim), key)
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


def usd_dir(src: pathlib.Path) -> pathlib.Path:
    """NVIDIA's packages keep their USD under simready_usd/, Tripo's under usd/."""
    return src / "simready_usd" if (src / "simready_usd").is_dir() else src / "usd"


def _rigid(M: np.ndarray, mpu: float) -> np.ndarray:
    """A prim's world transform without scale: rotation and translation (in metres)."""
    R = M[:3, :3]
    U, _, Vt = np.linalg.svd(R)
    T = np.eye(4)
    T[:3, :3] = U @ Vt
    T[:3, 3] = M[:3, 3] * mpu
    return T


def _quat(R: np.ndarray) -> list:
    q = np.zeros(4)
    import mujoco
    mujoco.mju_mat2Quat(q, np.asarray(R, float).ravel())
    return [round(float(v), 6) for v in q]


def _joints(stage, mpu: float) -> list[dict]:
    """Every USD Physics joint: its type, the rigid bodies it joins (a joint may name a mesh
    inside a body), its anchor and axis in the world, its limits, and the MuJoCo joint
    properties the asset's MuJoCo variant states (damping, frictionloss, armature, stiffness)."""
    import mujoco
    xc = UsdGeom.XformCache()
    out = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdPhysics.Joint):
            continue
        j = UsdPhysics.Joint(prim)
        t0, t1 = j.GetBody0Rel().GetTargets(), j.GetBody1Rel().GetTargets()
        b0 = [_owner(stage.GetPrimAtPath(t)) or str(t) for t in t0]
        b1 = [_owner(stage.GetPrimAtPath(t)) or str(t) for t in t1]
        kind = {"PhysicsRevoluteJoint": "hinge", "PhysicsPrismaticJoint": "slide",
                "PhysicsFixedJoint": "weld"}.get(prim.GetTypeName())
        if kind is None or not b1:
            continue
        rec = {"name": prim.GetName(), "path": str(prim.GetPath()), "type": kind, "body0": b0[0] if b0 else "", "body1": b1[0],
               # USD Physics: the two parts of a joint don't collide unless the joint says so
               "collide": bool(prim.GetAttribute("physics:collisionEnabled").Get())}
        if kind != "weld":
            ax = {"X": [1, 0, 0], "Y": [0, 1, 0], "Z": [0, 0, 1]}[prim.GetAttribute("physics:axis").Get() or "X"]
            r1 = prim.GetAttribute("physics:localRot1").Get()
            R1 = np.eye(3)
            if r1 is not None:
                q = np.array([r1.GetReal(), *r1.GetImaginary()], float)
                R1 = np.zeros(9)
                mujoco.mju_quat2Mat(R1, q / np.linalg.norm(q))
                R1 = R1.reshape(3, 3)
            p1 = prim.GetAttribute("physics:localPos1").Get()
            # the joint frame is given on body1's target prim (its own transform, scale and all)
            M = np.array(xc.GetLocalToWorldTransform(stage.GetPrimAtPath(t1[0]))).T
            rec["anchor"] = (M @ np.r_[np.array(p1 if p1 is not None else (0, 0, 0), float), 1.0])[:3] * mpu
            a = _rigid(M, 1.0)[:3, :3] @ R1 @ np.array(ax, float)
            rec["world_axis"] = a / np.linalg.norm(a)
            lo, hi = prim.GetAttribute("physics:lowerLimit").Get(), prim.GetAttribute("physics:upperLimit").Get()
            if lo is not None and hi is not None and np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                scale = np.pi / 180 if kind == "hinge" else mpu
                rec["range"] = [round(float(lo) * scale, 6), round(float(hi) * scale, 6)]
            for k in ("damping", "frictionloss", "armature", "stiffness", "springref"):
                a = prim.GetAttribute(f"mjc:{k}")
                if a and a.Get() is not None:
                    rec[k] = float(a.Get())
            for k in ("solreffriction", "solimpfriction", "solreflimit", "solimplimit"):
                a = prim.GetAttribute(f"mjc:{k}")
                if a and a.Get() is not None:
                    rec[k] = [float(v) for v in a.Get()]
        out.append(rec)
    return out


def joint_extras(usd: pathlib.Path) -> dict:
    """What the asset's neutral physics says about each joint (NVIDIA's MuJoCo layer deletes it):
    its drive, as USD Physics states it (a spring or damper toward a target; a motor if it has a
    target velocity), its starting position (joint state), and from the PhysX layer its joint
    friction coefficient. Angles in radians, lengths in metres; drive gains per radian or metre."""
    stage = Usd.Stage.Open(str(usd))
    root = stage.GetDefaultPrim()
    vs = root.GetVariantSets()
    stage.SetEditTarget(stage.GetSessionLayer())
    for name in vs.GetNames():
        if "Disabled" in vs.GetVariantSet(name).GetVariantNames():
            vs.GetVariantSet(name).SetVariantSelection("Disabled")
    physx = None
    if "PhysX" in vs.GetNames() and "Enabled" in vs.GetVariantSet("PhysX").GetVariantNames():
        physx = Usd.Stage.Open(str(usd))
        pv = physx.GetDefaultPrim().GetVariantSets()
        physx.SetEditTarget(physx.GetSessionLayer())
        for name in pv.GetNames():
            pv.GetVariantSet(name).SetVariantSelection("Enabled" if name == "PhysX" else "Disabled")
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    out = {}
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        t = prim.GetTypeName()
        if t not in ("PhysicsRevoluteJoint", "PhysicsPrismaticJoint"):
            continue
        ang = t == "PhysicsRevoluteJoint"
        kind = "angular" if ang else "linear"
        unit = np.pi / 180 if ang else mpu            # USD Physics: degrees, or the stage's length unit
        get = lambda a, p=prim: p.GetAttribute(a).Get() if p.GetAttribute(a) else None
        rec = {}
        if prim.HasAPI(UsdPhysics.DriveAPI, kind):
            d = {k: get(f"drive:{kind}:physics:{k}") for k in ("stiffness", "damping", "targetPosition", "targetVelocity", "maxForce")}
            drive = {}
            if d["stiffness"]:
                drive["stiffness"] = float(d["stiffness"]) / unit    # force per degree -> per radian
            if d["damping"]:
                drive["damping"] = float(d["damping"]) / unit
            if d["targetPosition"]:
                drive["target"] = float(d["targetPosition"]) * unit
            if d["targetVelocity"]:
                drive["target_velocity"] = float(d["targetVelocity"]) * unit
            if d["maxForce"] is not None and np.isfinite(d["maxForce"]):
                drive["max_force"] = float(d["maxForce"])
            if drive:
                rec["drive"] = {k: round(v, 8) for k, v in drive.items()}
        pos = get(f"state:{kind}:physics:position")
        if pos:
            rec["initial"] = round(float(pos) * unit, 6)
        if physx is not None:
            pp = physx.GetPrimAtPath(prim.GetPath())
            jf = pp.GetAttribute("physxJoint:jointFriction") if pp else None
            if jf and jf.Get():
                rec["physx_joint_friction"] = float(jf.Get())
        if rec:
            out[str(prim.GetPath())] = rec
    return out


def _tendons(stage, joint_names: dict) -> list[dict]:
    """The asset's MuJoCo tendons (Tripo's door closers and seals): fixed tendons over its joints,
    with their stiffness and spring length (MuJoCo's own tendon attributes)."""
    out = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if prim.GetTypeName() != "MjcTendon":
            continue
        get = lambda a: prim.GetAttribute(a).Get() if prim.GetAttribute(a) else None
        targets = [str(t) for t in prim.GetRelationship("mjc:path").GetTargets()]
        rec = {"name": prim.GetName(), "type": str(get("mjc:type")),
               "joints": [joint_names.get(t) for t in targets], "coef": [float(v) for v in (get("mjc:path:coef") or [])]}
        for k in ("stiffness", "damping"):
            if get(f"mjc:{k}") is not None:
                rec[k] = float(get(f"mjc:{k}"))
        if get("mjc:springlength") is not None:
            rec["springlength"] = [float(v) for v in get("mjc:springlength")]
        out.append(rec)
    return out


def _visuals(groups: dict, origin, T_inv, out: pathlib.Path, prefix: str, budget: float, total: int) -> list[dict]:
    """Write a body's visual groups (in its own frame) as OBJs with their textures."""
    visuals = []
    for k, (key, g) in enumerate(groups.items()):
        info = material_info(g["mat"])
        V = np.vstack(g["V"]) - origin
        V = V @ T_inv[:3, :3].T + T_inv[:3, 3]
        UV = np.vstack(g["UV"])
        has_tex = info["tex"] is not None and g["hasuv"]
        if has_tex:
            UV = UV * np.array(info["scale"])
            Vw, UVw, F = _merge_uv_mesh(V, UV)
        else:
            tm = trimesh.Trimesh(V, np.arange(len(V)).reshape(-1, 3), process=True)
            Vw, UVw, F = tm.vertices, None, tm.faces
        if total > budget and len(F) > 2000:
            tm = trimesh.Trimesh(Vw, F, process=False)
            try:
                tm = tm.simplify_quadric_decimation(face_count=max(1000, int(len(F) * budget / total)))
                Vw, F, UVw, has_tex = tm.vertices, tm.faces, None, False
            except Exception:  # noqa: BLE001
                pass
        vis = {"mesh": f"{prefix}vis_{k}.obj", "rgba": [round(float(c), 4) for c in info["rgba"]],
               "roughness": info["rough"], "metallic": info["metal"]}
        if has_tex:
            img = Image.open(info["tex"]).convert("RGB")
            img.thumbnail((TEX, TEX))
            img.save(out / f"{prefix}tex_{k}.png", optimize=True)
            vis["texture"] = f"{prefix}tex_{k}.png"
        elif info["tex"] is not None:
            img = Image.open(info["tex"]).convert("RGB").resize((8, 8))
            vis["rgba"][:3] = [round(float(c) / 255, 4) for c in np.array(img).reshape(-1, 3).mean(0)]
        write_obj(out / vis["mesh"], Vw, F, UVw if has_tex else None)
        visuals.append(vis)
    return visuals


def _surface(c: dict) -> dict:
    """What a collision part keeps of its collider's surface: friction, restitution, solref."""
    out = {}
    if "static" in c["material"]:
        out["friction"] = c["material"]["static"]
    if "restitution" in c["material"]:
        out["restitution"] = c["material"]["restitution"]
    if c.get("solref"):
        out["solref"] = c["solref"]
    return out


def _hulls(meshes: list, approx: list, out: pathlib.Path, prefix: str, surfaces=None) -> list[dict]:
    """A body's collision shapes: each collider as the asset asks (its convex hull, or convex
    pieces by CoACD for a convex decomposition), each with its collider's surface."""
    parts = []
    surfaces = surfaces or [{}] * len(meshes)
    for m, a, sf in zip(meshes, approx, surfaces):
        pieces = [m.convex_hull]
        if a == "convexDecomposition" and len(m.faces) > 20:
            import coacd
            coacd.set_log_level("error")
            lo_c, hi_c = m.bounds
            pieces = [trimesh.Trimesh(np.clip(v, lo_c, hi_c), f).convex_hull for v, f in
                      coacd.run_coacd(coacd.Mesh(m.vertices, m.faces), threshold=0.04, max_convex_hull=24,
                                      preprocess_mode="auto", seed=1)]
        for piece in pieces:
            if len(piece.faces) < 4 or piece.volume <= 1e-12:
                continue
            name = f"{prefix}col_{len(parts)}.obj"
            write_obj(out / name, piece.vertices, piece.faces)
            parts.append({"mesh": name, "volume": float(piece.volume), **sf})
    return parts


def convert_articulated(stage, src: pathlib.Path, usd: pathlib.Path, out: pathlib.Path, max_tris=60000,
                        hollow=False) -> dict:
    """An asset with moving parts: one MuJoCo body per USD rigid body, in a tree by its joints.

    Revolute and prismatic joints become hinge and slide joints with the asset's own axis,
    limits and (from its MuJoCo variant) damping, frictionloss, armature and stiffness. A part
    held by a fixed joint (a cap, a needle) stays its own body, held by a weld. Parts with no
    joint to another part are free (a lid lying on its box, the second glove of a pair). Each
    body's mass is what the asset states for it (on the body, else on its colliders); a body
    with none is left to MuJoCo's default density. hollow: a container, so its parts
    collide as convex pieces (CoACD) whatever the asset says: its lid and insert fit inside it."""
    xc = UsdGeom.XformCache()
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    groups, colliders, _, _ = read(stage, by_body=True)
    joints = _joints(stage, mpu)
    extras = joint_extras(usd)
    paths = sorted({k[0] for k in groups} | {c["body"] for c in colliders})
    paths = [p for p in paths if p]
    allV = np.vstack([np.vstack(g["V"]) for g in groups.values()])
    lo, hi = allV.min(0), allV.max(0)
    origin = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    T = {}
    for p in paths:
        M = _rigid(np.array(xc.GetLocalToWorldTransform(stage.GetPrimAtPath(p))).T, mpu)
        M[:3, 3] -= origin
        T[p] = M
    parent, joint_of = {}, {}
    for j in joints:
        if j["body1"] in T and j["body0"] in T:
            parent[j["body1"]], joint_of[j["body1"]] = j["body0"], j
    vols = {p: sum(c["mesh"].convex_hull.volume for c in colliders if c["body"] == p) for p in paths}
    main_root = max((p for p in paths if p not in parent), key=lambda p: vols.get(p, 0))
    total = sum(len(np.vstack(g["V"])) // 3 for g in groups.values())
    bodies = []
    for i, p in enumerate(paths):
        prim = stage.GetPrimAtPath(p)
        name = prim.GetName()
        mine_g = {k[1]: g for k, g in groups.items() if k[0] == p}
        mine_c = [c for c in colliders if c["body"] == p]
        Tinv = np.linalg.inv(T[p])
        meshes = []
        for c in mine_c:
            m = c["mesh"].copy()
            m.apply_translation(-origin)
            m.apply_transform(Tinv)
            meshes.append(m)
        a = prim.GetAttribute("physics:mass")
        bmass = float(a.Get()) if a and a.Get() else (sum(c["mass"] for c in mine_c if c["mass"]) or None)
        rec = {"name": name, "visuals": _visuals(mine_g, origin, Tinv, out, f"b{i}_", max_tris, total),
               "collision_parts": _hulls(meshes, ["convexDecomposition" if hollow else c["approx"]
                                                  for c in mine_c], out, f"b{i}_", [_surface(c) for c in mine_c]),
               "mass": round(bmass, 6) if bmass else None}
        props = [c["props"] for c in mine_c]
        if props and all(props):          # the mass, centre and inertia the asset states, in this part's frame
            Tw = np.linalg.inv(T[p]) @ np.r_[np.c_[np.eye(3), -origin], [[0, 0, 0, 1]]]
            rec["inertial"] = combine_inertia(props, Tw)
        j = joint_of.get(p)
        if p == main_root:
            rec.update(parent=None, root=True)
        elif j is None:
            rec.update(parent=None, free=True)
        elif j["type"] == "weld":
            rec.update(parent=paths.index(j["body0"]), weld=True, collide=j["collide"])
        else:
            rec.update(parent=paths.index(j["body0"]),
                       collide=j["collide"],
                       joint={k: v for k, v in j.items() if k not in ("body0", "body1", "anchor", "world_axis", "collide", "path")})
            rec["joint"].update(extras.get(j["path"], {}))
            # anchor and axis in the part's own frame
            rec["joint"]["pos"] = [round(float(v), 6) for v in (Tinv @ np.r_[j["anchor"] - origin, 1.0])[:3]]
            rec["joint"]["axis"] = [round(float(v), 6) for v in Tinv[:3, :3] @ j["world_axis"]]
        # pose: relative to the parent body for a jointed part, else in the asset's frame
        rel = np.linalg.inv(T[parent[p]]) @ T[p] if "joint" in rec else T[p]
        rec["pos"] = [round(float(v), 6) for v in rel[:3, 3]]
        rec["quat"] = _quat(rel[:3, :3])
        rec["frame"] = [round(float(v), 6) for v in T[p][:3, 3]] + _quat(T[p][:3, :3])   # in the asset's frame
        bodies.append(rec)
    stated = [b["mass"] for b in bodies if b["mass"]]
    meta = {
        "source": src.name, "usd": usd.name,
        "mass": round(float(sum(stated)), 5) if stated else None,
        "friction": friction(stage), "com": None,
        "size": np.round(hi - lo, 4).tolist(),
        "collision": "convex hulls per part (as the asset specifies), moving parts on their joints",
        "visuals": [], "collision_parts": [], "bodies": bodies,
        "unstated_mass": [b["name"] for b in bodies if not b["mass"]],
    }
    tendons = _tendons(stage, {j["path"]: j["name"] for j in joints})
    if tendons:
        meta["tendons"] = tendons
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    return meta


def convert(src: pathlib.Path, out: pathlib.Path, hollow=False, max_tris=60000, solid=False) -> dict:
    usd = next(p for p in sorted(usd_dir(src).glob("*.usd*")) if p.suffix in (".usd", ".usda"))
    stage = open_stage(usd)
    rigid = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
             if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    if len(rigid) > 1 and not solid:
        return convert_articulated(stage, src, usd, out, max_tris, hollow)
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
    col = trimesh.util.concatenate([c["mesh"] for c in colliders]) if colliders else trimesh.util.concatenate(
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
            parts.append({"mesh": f"col_{k}.obj", "volume": float(trimesh.Trimesh(v, f).convex_hull.volume),
                          **_nearest_surface(colliders, piece.centroid + origin)})
    else:
        hull = col.convex_hull
        write_obj(out / "col_0.obj", hull.vertices, hull.faces)
        # one hull for the whole item: the surface of its biggest collider
        big = max(colliders, key=lambda c: c["mesh"].convex_hull.volume) if colliders else None
        parts.append({"mesh": "col_0.obj", "volume": float(hull.volume), **(_surface(big) if big else {})})
    meta = {
        "source": src.name, "usd": usd.name,
        "mass": round(float(mass), 5) if mass else None,
        "friction": friction(stage),
        "com": None if com is None else np.round(com - origin, 5).tolist(),
        "size": np.round(hi - lo, 4).tolist(),
        "collision": "convex pieces (CoACD)" if hollow else "convex hull (as the asset specifies)",
        "visuals": visuals, "collision_parts": parts,
    }
    props = [c["props"] for c in colliders]
    if props and all(props):        # the stated mass, centre and inertia, in the item's frame
        meta["inertial"] = combine_inertia(props, np.r_[np.c_[np.eye(3), -origin], [[0, 0, 0, 1]]])
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    return meta


def _nearest_surface(colliders: list, point) -> dict:
    """The surface of the collider nearest a point (a convex piece takes the material it came from)."""
    if not colliders:
        return {}
    d = [float(np.min(np.linalg.norm(c["mesh"].vertices - point, axis=1))) for c in colliders]
    return _surface(colliders[int(np.argmin(d))])


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
