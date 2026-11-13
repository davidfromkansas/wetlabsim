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
# CoACD's settings for convex pieces: (concavity threshold, most pieces). FINE keeps small holes
# open (a tube rack's deck has dozens), at the cost of more pieces.
COACD = (0.04, 24)
FINE = (0.02, -1)
# Clear glass and plastic, as the viewer draws them: never fainter than this (a stated opacity of
# 8% would be invisible without the refraction a path tracer adds).
GLASS_ALPHA = 0.3


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
                    info.update(_uv_placement(UsdShade.Shader(src.GetPrim())))
            elif i and i.Get() is not None and info["tex"] is None:
                info["rgba"][:3] = list(i.Get())
            for name, key in (("roughness", "rough"), ("metallic", "metal")):
                i = sh.GetInput(name)
                if i and i.Get() is not None and not i.HasConnectedSource():
                    info[key] = float(i.Get())
            i = sh.GetInput("opacity")
            if i and i.Get() is not None and not i.HasConnectedSource() and float(i.Get()) < 1:
                info["rgba"][3] = max(float(i.Get()), GLASS_ALPHA)
            continue
        src = sh.GetSourceAsset("mdl") if sh.GetImplementationSource() == "sourceAsset" else None
        if src and "glass" in src.path.lower():     # NVIDIA's OmniGlass: clear
            info["rgba"][3], info["rough"] = GLASS_ALPHA, 0.05
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
    info["rgba"] = list(info["rgba"])
    return info


def _uv_placement(tex) -> dict:
    """How a UsdUVTexture places its image (UsdPreviewSurface spec): a UsdTransform2d on its
    st input (scale, then a counter-clockwise rotation in degrees, then translation), and its wrap
    modes ("clamp": coordinates outside 0..1 take the edge's colour)."""
    out = {}
    st = tex.GetInput("st")
    if st and st.HasConnectedSource():
        src, _, _ = st.GetConnectedSource()
        sh = UsdShade.Shader(src.GetPrim()) if src else None
        if sh and sh.GetIdAttr().Get() == "UsdTransform2d":
            get = lambda n, d: sh.GetInput(n).Get() if sh.GetInput(n) and sh.GetInput(n).Get() is not None else d
            out["uv_transform"] = {"scale": [float(v) for v in get("scale", (1, 1))],
                                   "rotation": float(get("rotation", 0.0)),
                                   "translation": [float(v) for v in get("translation", (0, 0))]}
    wrap = [tex.GetInput(n).Get() if tex.GetInput(n) else None for n in ("wrapS", "wrapT")]
    out["uv_clamp"] = [w == "clamp" for w in wrap]
    return out


def _place_uv(UV: np.ndarray, info: dict) -> np.ndarray:
    """Texture coordinates as the material places its image (_uv_placement, or an MDL texture_scale),
    baked in: our viewers draw every texture repeating, so a clamped one is clamped here."""
    UV = UV * np.array(info["scale"])
    t = info.get("uv_transform")
    if t:
        UV = UV * np.array(t["scale"])
        a = np.radians(t["rotation"])
        c, s = np.cos(a), np.sin(a)
        UV = np.c_[c * UV[:, 0] - s * UV[:, 1], s * UV[:, 0] + c * UV[:, 1]] + np.array(t["translation"])
    for k, clamp in enumerate(info.get("uv_clamp", [False, False])):
        if clamp:
            UV[:, k] = np.clip(UV[:, k], 0.0, 1.0)
    return UV


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
        is_collider = prim.HasAPI("PhysicsCollisionAPI") or bool(prim.GetAttribute("physics:approximation").Get()) \
            if prim.GetAttribute("physics:approximation") else prim.HasAPI("PhysicsCollisionAPI")
        if im.ComputeVisibility() == "invisible" and not is_collider:     # hidden colliders still collide
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
    """NVIDIA's packages keep their USD under simready_usd/, Tripo's under usd/, USDCraft's under physx/."""
    for d in ("simready_usd", "usd", "physx"):
        if (src / d).is_dir():
            return src / d
    return src / "usd"


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


def _screw_couplings(usd: pathlib.Path, joints: list[dict]) -> list[dict]:
    """A screw thread, as the asset's own animation clips show it (ForgeCAD's "Unscrew_and_screw"):
    a slide and a hinge whose keyframes (xformOps named after the joints) move in step, as
    {"slide", "hinge", "ratio": metres per radian, "clip"}. The joints themselves are independent
    in USD Physics, which has no screw joint; MuJoCo couples them with a joint equality."""
    stage = Usd.Stage.Open(str(usd))
    root = stage.GetDefaultPrim()
    vs = root.GetVariantSets()
    if "animation" not in vs.GetNames():
        return []
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    stage.SetEditTarget(stage.GetSessionLayer())
    out = []
    for clip in vs.GetVariantSet("animation").GetVariantNames():
        vs.GetVariantSet("animation").SetVariantSelection(clip)
        keys = {}
        for j in joints:
            if j["type"] not in ("hinge", "slide"):
                continue
            jp = stage.GetPrimAtPath(j["path"])
            axis = "XYZ".index(jp.GetAttribute("physics:axis").Get() or "X")
            body = stage.GetPrimAtPath(j["body1"])
            for a in body.GetAttributes():
                n = a.GetName()
                if not (n.startswith("xformOp:") and n.endswith(":" + j["name"]) and a.GetNumTimeSamples() > 1):
                    continue
                times = a.GetTimeSamples()
                vals = [a.Get(t) for t in times]
                if j["type"] == "slide":
                    q = [float(v[axis] if hasattr(v, "__len__") else v) * mpu for v in vals]
                else:
                    q = [np.radians(float(v)) for v in vals]
                keys[j["name"]] = (j["type"], list(times), np.array(q))
        slides = [k for k, v in keys.items() if v[0] == "slide"]
        hinges = [k for k, v in keys.items() if v[0] == "hinge"]
        for sl in slides:
            for hg in hinges:
                (_, ts, qs), (_, th, qh) = keys[sl], keys[hg]
                if ts != th or np.ptp(qh) == 0 or np.ptp(qs) == 0:
                    continue
                ratio = float(np.ptp(qs) / np.ptp(qh)) * (1 if np.corrcoef(qs, qh)[0, 1] > 0 else -1)
                if np.allclose(qs - qs[0], ratio * (qh - qh[0]), atol=1e-7):
                    out.append({"slide": sl, "hinge": hg, "ratio": round(ratio, 9), "clip": clip})
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
            UV = _place_uv(UV, info)
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


def _convex_polys(poly) -> list:
    """A flat shape with holes (shapely) as convex polygons: triangulate it, then merge triangles
    back together across every diagonal whose removal keeps the piece convex (Hertel-Mehlhorn)."""
    V, F = trimesh.creation.triangulate_polygon(poly, engine="earcut")
    pieces = [list(f) for f in F]
    V = np.asarray(V)

    def convex(ring):
        P = V[ring]
        d1 = np.roll(P, -1, 0) - P
        d2 = np.roll(P, -2, 0) - np.roll(P, -1, 0)
        cr = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
        return np.all(cr >= -1e-12) or np.all(cr <= 1e-12)

    merged = True
    while merged:
        merged = False
        edge = {}
        for k, r in enumerate(pieces):
            for a, b in zip(r, r[1:] + r[:1]):
                edge.setdefault((min(a, b), max(a, b)), []).append(k)
        for (a, b), ks in edge.items():
            if len(ks) != 2:
                continue
            i, j = ks
            ri, rj = pieces[i], pieces[j]
            # join along a-b: walk ri from b to a, then rj from a to b (without repeating them)
            ia = ri.index(a)
            ri2 = ri[ia:] + ri[:ia]                      # starts at a
            if ri2[1] == b:                              # ri runs a->b: reverse so it ends ... b, a
                ri2 = [a] + ri2[1:][::-1]
            # ri2 = a, ..., b (going the long way round ri)
            jb = rj.index(b)
            rj2 = rj[jb:] + rj[:jb]                      # starts at b
            if rj2[1] == a:
                rj2 = [b] + rj2[1:][::-1]
            ring = ri2 + rj2[1:-1]                       # a, ..., b, ..., (back to a)
            if len(set(ring)) == len(ring) and convex(ring):
                pieces[i] = ring
                pieces.pop(j)
                merged = True
                break
    return [V[r] for r in pieces]


def plate_pieces(mesh: trimesh.Trimesh):
    """A flat plate with holes in it (a rack's deck) as exact convex pieces: its outline at
    mid-height, cut into convex polygons, each the plate's thickness. None if it isn't one."""
    ext = mesh.extents
    if ext[2] > 0.25 * min(ext[0], ext[1]):
        return None
    z0, z1 = mesh.bounds[:, 2]
    sec = mesh.section(plane_origin=[0, 0, (z0 + z1) / 2], plane_normal=[0, 0, 1])
    if sec is None:
        return None
    flat, T = sec.to_2D()
    polys = flat.polygons_full
    if not polys or not any(len(p.interiors) for p in polys):
        return None
    out = []
    for poly in polys:
        poly = poly.simplify(0.0002, preserve_topology=True)
        for P2 in _convex_polys(poly):
            P3 = np.c_[P2, np.zeros(len(P2)), np.ones(len(P2))] @ T.T
            P3 = P3[:, :3]
            out.append(trimesh.Trimesh(np.r_[np.c_[P3[:, :2], np.full(len(P3), z0)],
                                             np.c_[P3[:, :2], np.full(len(P3), z1)]]).convex_hull)
    return out


def fine_pieces(mesh: trimesh.Trimesh, cfg=None) -> list:
    """One collider as convex pieces that keep its holes open: itself if it is (near) convex,
    exact pieces for a flat plate with holes, CoACD (fine) otherwise."""
    hull = mesh.convex_hull
    if mesh.is_watertight and mesh.volume > 0.92 * hull.volume:
        return [hull]
    plate = plate_pieces(mesh)
    if plate:
        return plate
    import coacd
    coacd.set_log_level("error")
    th, mx = cfg or FINE
    lo_c, hi_c = mesh.bounds
    return [trimesh.Trimesh(np.clip(v, lo_c, hi_c), f).convex_hull for v, f in
            coacd.run_coacd(coacd.Mesh(mesh.vertices, mesh.faces), threshold=th, max_convex_hull=mx,
                            preprocess_mode="auto", seed=1)]


def _hulls(meshes: list, approx: list, out: pathlib.Path, prefix: str, surfaces=None, pieces_cfg=COACD) -> list[dict]:
    """A body's collision shapes: each collider as the asset asks (its convex hull, or convex
    pieces by CoACD for a convex decomposition), each with its collider's surface."""
    parts = []
    surfaces = surfaces or [{}] * len(meshes)
    for m, a, sf in zip(meshes, approx, surfaces):
        pieces = [m.convex_hull]
        if a == "convexDecomposition" and pieces_cfg == FINE:
            pieces = fine_pieces(m)
        elif a == "convexDecomposition" and len(m.faces) > 20:
            import coacd
            coacd.set_log_level("error")
            lo_c, hi_c = m.bounds
            pieces = [trimesh.Trimesh(np.clip(v, lo_c, hi_c), f).convex_hull for v, f in
                      coacd.run_coacd(coacd.Mesh(m.vertices, m.faces), threshold=pieces_cfg[0], max_convex_hull=pieces_cfg[1],
                                      preprocess_mode="auto", seed=1)]
        for piece in pieces:
            if len(piece.faces) < 4 or piece.volume <= 1e-12:
                continue
            name = f"{prefix}col_{len(parts)}.obj"
            write_obj(out / name, piece.vertices, piece.faces)
            parts.append({"mesh": name, "volume": float(piece.volume), **sf})
    return parts


def convert_articulated(stage, src: pathlib.Path, usd: pathlib.Path, out: pathlib.Path, max_tris=60000,
                        hollow=False, pieces_cfg=COACD) -> dict:
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
                                                  for c in mine_c], out, f"b{i}_", [_surface(c) for c in mine_c], pieces_cfg),
               "mass": round(bmass, 6) if bmass else None}
        props = [c["props"] for c in mine_c]
        if not (props and all(props)) and mine_c:
            # stated on the rigid body itself (ForgeCAD), not its colliders: used if its centre
            # lies within the part's colliders' bounds
            bp = mass_props(prim, np.array(xc.GetLocalToWorldTransform(prim)).T, mpu)
            b_lo = np.min([c["mesh"].bounds[0] for c in mine_c], axis=0)
            b_hi = np.max([c["mesh"].bounds[1] for c in mine_c], axis=0)
            if bp is not None and np.all(bp[1] >= b_lo - 1e-6) and np.all(bp[1] <= b_hi + 1e-6):
                props = [bp]
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
    screws = _screw_couplings(usd, joints)
    if screws:
        meta["screws"] = screws
    tendons = _tendons(stage, {j["path"]: j["name"] for j in joints})
    if tendons:
        meta["tendons"] = tendons
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    return meta


def convert(src: pathlib.Path, out: pathlib.Path, hollow=False, max_tris=60000, solid=False, fine=False) -> dict:
    pieces_cfg = FINE if fine else COACD
    usd = next(p for p in sorted(usd_dir(src).glob("*.usd*")) if p.suffix in (".usd", ".usda", ".usdc"))
    stage = open_stage(usd)
    rigid = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
             if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    if len(rigid) > 1 and not solid:
        return convert_articulated(stage, src, usd, out, max_tris, hollow, pieces_cfg)
    groups, colliders, mass, com = read(stage)
    if not mass:    # some packages (QUIKTECH, USDCraft) state the mass on the rigid body, not its colliders
        mass = sum(float(p.GetAttribute("physics:mass").Get()) for p in rigid
                   if p.GetAttribute("physics:mass") and p.GetAttribute("physics:mass").Get()) or None
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
            UV = _place_uv(UV, info)
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
    if hollow and pieces_cfg == FINE and colliders:     # each collider on its own, holes kept open
        for c in colliders:
            m = c["mesh"].copy()
            m.apply_translation(-origin)
            for piece in fine_pieces(m):
                if len(piece.faces) < 4 or piece.volume <= 1e-12:
                    continue
                name = f"col_{len(parts)}.obj"
                write_obj(out / name, piece.vertices, piece.faces)
                parts.append({"mesh": name, "volume": float(piece.volume), **_surface(c)})
    elif hollow:
        import coacd
        coacd.set_log_level("error")
        pieces = coacd.run_coacd(coacd.Mesh(col.vertices, col.faces), threshold=pieces_cfg[0], max_convex_hull=pieces_cfg[1],
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
        "friction": friction(stage) or None,     # a stated 0 is a packaging slip (no glass is frictionless)
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
