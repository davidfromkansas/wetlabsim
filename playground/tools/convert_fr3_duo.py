"""Convert Franka Robotics' FR3 Duo vision & manipulation kit (their SimReady USD on Hugging Face,
frankarobotics/simready-assets, fr3_duo_vision_manipulation_kit) into a MuJoCo model.

    python -m playground.tools.convert_fr3_duo <package dir> wetlabsim/assets/franka_fr3_duo

The kit: two FR3 v2 arms on Franka's Duo mount, each with a Robotiq 2F-85 gripper and an Intel
RealSense D405 on its wrist, and a Stereolabs ZED Mini on the head. Read from the package as
published (the MuJoCo variant switched on, the "position" control mode):

- one MuJoCo body per arm link, in the kit's own kinematic tree; parts the kit holds with a fixed
  joint (the mount, head and head camera; the flange adapter and wrist camera) join the body
  they are fixed to;
- each link's stated mass, centre of mass and inertia (USD Physics MassAPI);
- each joint's axis, limits, armature and friction loss (the kit's MuJoCo layer), its effort
  limit, and the position-drive gains of the "position" control mode (stated per degree, here
  per radian);
- each link's collision shape (the kit's convex hulls);
- the visual meshes in the kit's own colours (one mesh per body and colour), simplified;
- the cameras' poses and fields of view (the D405s' colour sensors, the ZED Mini's left eye).

The grippers are MuJoCo Menagerie's Robotiq 2F-85 (assets/robotiq_2f85, unchanged), attached
where the kit attaches its own: the 2F-85 closes a four-bar linkage, which MuJoCo needs written
as equality constraints, and the kit's MuJoCo layer doesn't (its validation report fails the
MuJoCo check). Menagerie's model is the 2F-85 made for MuJoCo.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import xml.etree.ElementTree as ET

import numpy as np
import trimesh
from pxr import Usd, UsdGeom, UsdPhysics, UsdShade

from .convert_simready import _rigid, _quat, combine_inertia, open_stage, read, write_obj

KIT = "fr3_duo_vision_manipulation_kit"
SIDES = ("left", "right")
# Visual triangles per body after simplification (the kit's meshes are CAD exports: a link has up
# to 80,000; the mount 250,000). Small parts keep theirs.
TRI_BUDGET = 9000
TRI_BUDGET_BASE = 16000


def _set_variant(stage):
    root = stage.GetDefaultPrim()
    vs = root.GetVariantSets()
    if "ControlMode" in vs.GetNames():
        vs.GetVariantSet("ControlMode").SetVariantSelection("position")


def _mat_value(mat, name):
    """A UsdPreviewSurface input's value, following its connection to the material's interface
    (the kit's materials set their colours there)."""
    for sp in Usd.PrimRange(mat.GetPrim()):
        sh = UsdShade.Shader(sp)
        if not sh or (sh.GetIdAttr().Get() or "") != "UsdPreviewSurface":
            continue
        i = sh.GetInput(name)
        if not i:
            continue
        for a in i.GetValueProducingAttributes():
            v = a.Get()
            if v is not None:
                return v
    return None


def colour(mat) -> tuple:
    """(r, g, b, a), roughness, metalness of a material, as the kit states them."""
    if not mat:
        return (0.7, 0.7, 0.7, 1.0), 0.5, 0.0
    c = _mat_value(mat, "diffuseColor")
    o = _mat_value(mat, "opacity")
    r = _mat_value(mat, "roughness")
    m = _mat_value(mat, "metallic")
    rgb = tuple(round(float(x), 3) for x in (c if c is not None else (0.7, 0.7, 0.7)))
    return (*rgb, round(float(o) if o is not None else 1.0, 3)), round(float(r if r is not None else 0.5), 2), \
        round(float(m if m is not None else 0.0), 2)


def _body_mass(prim, M):
    """A rigid body's stated mass, centre and inertia (MassAPI on the body), in the world frame."""
    import mujoco
    get = lambda a: prim.GetAttribute(a).Get() if prim.GetAttribute(a) else None
    m, c, I, q = get("physics:mass"), get("physics:centerOfMass"), get("physics:diagonalInertia"), \
        get("physics:principalAxes")
    if not m:
        return None
    T = _rigid(M, 1.0)
    if c is None or not np.all(np.isfinite(c)):
        c = (0.0, 0.0, 0.0)       # not stated: at the body's origin
    I = np.array(I if I is not None else (0, 0, 0), float)
    if not np.any(I > 0):
        I = np.full(3, 1e-7)      # not stated: a point mass
    Rp = np.eye(3)
    if q is not None:
        qq = np.array([q.GetReal(), *q.GetImaginary()], float)
        if np.linalg.norm(qq) > 0:
            Rp = np.zeros(9)
            mujoco.mju_quat2Mat(Rp, qq / np.linalg.norm(qq))
            Rp = Rp.reshape(3, 3)
    Rw = T[:3, :3] @ Rp
    return float(m), (T @ np.r_[np.array(c, float), 1.0])[:3], Rw @ np.diag(I) @ Rw.T


def _short(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def body_plan(stage):
    """MuJoCo bodies: name -> (USD rigid bodies merged into it, parent body, joint prim or None)."""
    joints = {}
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Joint):
            j = UsdPhysics.Joint(prim)
            b0 = [str(t) for t in j.GetBody0Rel().GetTargets()]
            b1 = [str(t) for t in j.GetBody1Rel().GetTargets()]
            joints[prim.GetName()] = (prim, b0[0] if b0 else None, b1[0] if b1 else None)
    rb = {_short(str(p.GetPath())): str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
    plan = {"base": ([rb[n] for n in ("fr3_duo_mount_mounting_point", "head_link", "head_camera_mounting_point",
                                      "head_camera_center")], None, None)}
    for s in SIDES:
        parent = "base"
        for i in range(8):
            jp = joints[f"{s}_fr3v2_1_joint{i}"][0] if i else None
            plan[f"{s}/link{i}"] = ([rb[f"{s}_fr3v2_1_link{i}"]], parent, jp)
            parent = f"{s}/link{i}"
        # What the kit bolts to the flange: the gripper adapter and the wrist camera with its mount
        # (the gripper itself goes on this body too). A body of its own, so the arm's estimate of
        # the external wrench at the flange can take this load's weight out.
        plan[f"{s}/hand"] = ([rb[f"{s}_ur_to_robotiq_link"], rb[f"{s}__wrist_camera_mount_casing_link"],
                              rb[f"{s}__wrist_camera_link"]], parent, None)
    return plan, rb, joints


def _fmt(v, n=6):
    return " ".join(f"{float(x):.{n}g}" if abs(float(x)) > 1e-12 else "0" for x in v)


def convert(src: pathlib.Path, out: pathlib.Path) -> dict:
    import fast_simplification
    import mujoco
    usd = src / "simready_usd" / f"{KIT}.usda"
    stage = open_stage(usd)
    _set_variant(stage)
    xc = UsdGeom.XformCache()
    W = lambda path: np.array(xc.GetLocalToWorldTransform(stage.GetPrimAtPath(path))).T
    plan, rb, joints = body_plan(stage)
    owner = {u: b for b, (us, _, _) in plan.items() for u in us}
    groups, colliders, _, _ = read(stage, by_body=True)

    # Each MuJoCo body's frame: its first USD body's (rotation and translation only).
    T = {b: _rigid(W(us[0]), 1.0) for b, (us, _, _) in plan.items()}
    Tinv = {b: np.linalg.inv(t) for b, t in T.items()}

    (out / "assets").mkdir(parents=True, exist_ok=True)
    root = ET.Element("mujoco", model="fr3_duo")
    ET.SubElement(root, "compiler", angle="radian", meshdir="assets", autolimits="true")
    # Menagerie's 2F-85 asks for these (its grip relies on them); the same here so attaching is silent.
    ET.SubElement(root, "option", integrator="implicitfast", cone="elliptic", impratio="10")
    top = ET.SubElement(root, "default")
    # Flat parts (decals, labels) have no volume: their inertia would be a shell's. Every body
    # states its own inertia, so meshes only give shapes.
    ET.SubElement(top, "mesh", inertia="shell")
    default = ET.SubElement(top, "default", {"class": "fr3"})
    ET.SubElement(default, "joint", axis="0 0 1")
    ET.SubElement(default, "general", dyntype="none", biastype="affine")
    ET.SubElement(ET.SubElement(default, "default", {"class": "visual"}), "geom",
                  type="mesh", contype="0", conaffinity="0", group="2")
    ET.SubElement(ET.SubElement(default, "default", {"class": "collision"}), "geom", type="mesh", group="3")
    asset = ET.SubElement(root, "asset")
    ET.SubElement(asset, "model", name="robotiq_2f85", file="robotiq_2f85/2f85.xml")

    # ---- visual meshes: one per body and colour
    mats, vis = {}, {b: {} for b in plan}
    for (body, mpath), g in groups.items():
        b = owner.get(body)
        if b is None:        # the kit's own Robotiq grippers: Menagerie's take their place
            continue
        rgba, rough, metal = colour(g["mat"])
        key = (rgba, rough, metal)
        V = np.concatenate(g["V"])
        vis[b].setdefault(key, []).append((Tinv[b][:3, :3] @ V.T).T + Tinv[b][:3, 3])
    report = {"bodies": {}}
    for b, bycol in vis.items():
        budget = TRI_BUDGET_BASE if b == "base" else TRI_BUDGET
        total = sum(len(v) for vs in bycol.values() for v in vs) / 3
        for k, (key, vs) in enumerate(sorted(bycol.items(), key=lambda kv: -sum(len(v) for v in kv[1]))):
            V = np.concatenate(vs)
            tm = trimesh.Trimesh(V, np.arange(len(V)).reshape(-1, 3), process=True)
            tm.merge_vertices()
            n = len(tm.faces)
            target = max(int(budget * n / max(total, 1)), 60)
            if n > target * 1.2 and n > 400:
                v2, f2 = fast_simplification.simplify(np.asarray(tm.vertices, np.float32),
                                                      np.asarray(tm.faces, np.int32), 1 - target / n)
                tm = trimesh.Trimesh(v2, f2, process=True)
            if len(tm.faces) == 0:
                continue
            rgba, rough, metal = key
            mname = f"c{len(mats)}" if key not in mats else mats[key]
            if key not in mats:
                mats[key] = mname
                ET.SubElement(asset, "material", name=mname, rgba=_fmt(rgba, 3),
                              specular=f"{0.5 if metal < 0.5 else 0.8:.2g}", shininess=f"{max(0.0, 1 - rough):.2g}",
                              reflectance=f"{0.1 * metal:.2g}")
            fn = f"{b.replace('/', '_')}_{k}.obj"
            write_obj(out / "assets" / fn, np.asarray(tm.vertices), np.asarray(tm.faces))
            ET.SubElement(asset, "mesh", name=fn[:-4], file=fn)
            vis[b][key] = fn[:-4]
            report["bodies"].setdefault(b, {"visual_tris": 0})["visual_tris"] += len(tm.faces)

    # ---- collision shapes: the kit's convex hulls
    col = {b: [] for b in plan}
    for c in colliders:
        b = owner.get(c["body"])
        if b is None:
            continue
        hull = c["mesh"].convex_hull
        V = (Tinv[b][:3, :3] @ np.asarray(hull.vertices).T).T + Tinv[b][:3, 3]
        fn = f"{b.replace('/', '_')}_collision_{len(col[b])}.obj"
        write_obj(out / "assets" / fn, V, np.asarray(hull.faces))
        ET.SubElement(asset, "mesh", name=fn[:-4], file=fn)
        col[b].append(fn[:-4])

    # ---- the tree
    world = ET.SubElement(root, "worldbody")
    elems = {}
    joint_info = {}
    for b, (us, parent, jp) in plan.items():
        P = elems.get(parent, world)
        rel = (Tinv[parent] @ T[b]) if parent else T[b]
        attrs = {"name": b, "pos": _fmt(rel[:3, 3]), "quat": _fmt(_quat(rel[:3, :3]))}
        if parent is None:
            attrs["childclass"] = "fr3"
        e = ET.SubElement(P, "body", attrs)
        elems[b] = e
        props = [p for p in (_body_mass(stage.GetPrimAtPath(u), W(u)) for u in us) if p is not None]
        inert = combine_inertia(props, Tinv[b])
        ET.SubElement(e, "inertial", pos=_fmt(inert["pos"]), quat=_fmt(inert["quat"]),
                      mass=f"{inert['mass']:.6g}", diaginertia=_fmt(inert["diaginertia"]))
        if jp is not None:
            g = lambda a: jp.GetAttribute(a).Get() if jp.GetAttribute(a) else None
            # The joint frame is body1's own (localPos1 = 0, localRot1 = identity), axis Z.
            assert np.allclose(g("physics:localPos1"), 0) and g("physics:axis") == "Z"
            lo, hi = math.radians(g("physics:lowerLimit")), math.radians(g("physics:upperLimit"))
            name = b.replace("link", "joint")
            ja = {"name": name, "range": _fmt([lo, hi]), "armature": f"{g('mjc:armature'):.6g}",
                  "frictionloss": f"{g('mjc:frictionloss'):.6g}"}
            ET.SubElement(e, "joint", ja)
            # The "position" control mode's drive: stiffness and damping per degree -> per radian.
            kp = g("drive:angular:physics:stiffness") * 180 / math.pi
            kv = g("drive:angular:physics:damping") * 180 / math.pi
            joint_info[name] = {"kp": round(kp, 1), "kv": round(kv, 1), "range": [lo, hi],
                                "effort": float(g("drive:angular:physics:maxForce")),
                                "velocity": float(g("urdf:limit:velocity")),
                                "start": math.radians(g("state:angular:physics:position") or 0.0)}
        for key, mesh in vis[b].items():
            if isinstance(mesh, str):
                ET.SubElement(e, "geom", {"class": "visual", "mesh": mesh, "material": mats[key]})
        for mesh in col[b]:
            ET.SubElement(e, "geom", {"class": "collision", "mesh": mesh, "name": mesh})

    def frame_in(b, path):
        rel = Tinv[b] @ _rigid(W(path), 1.0)
        return _fmt(rel[:3, 3]), _fmt(_quat(rel[:3, :3]))

    def fovy(path):
        cam = UsdGeom.Camera(stage.GetPrimAtPath(path))
        f, vap = cam.GetFocalLengthAttr().Get(), cam.GetVerticalApertureAttr().Get()
        return math.degrees(2 * math.atan(vap / 2 / f))

    cams = {p.GetName(): str(p.GetPath()) for p in stage.Traverse() if p.GetTypeName() == "Camera"}
    # The ZED Mini's left eye (its RGB stream), USD and MuJoCo cameras both look along -z, y up.
    pos, quat = frame_in("base", cams["NativeSensor__head_zed_left_rgb"])
    ET.SubElement(elems["base"], "camera", name="head", pos=pos, quat=quat,
                  fovy=f"{fovy(cams['NativeSensor__head_zed_left_rgb']):.4g}")
    for s in SIDES:
        e = elems[f"{s}/hand"]
        p = cams[f"NativeSensor__{s}_wrist_d405_rgb"]
        pos, quat = frame_in(f"{s}/hand", p)
        ET.SubElement(e, "camera", name=f"wrist_cam_{s}", pos=pos, quat=quat, fovy=f"{fovy(p):.4g}")
        # The flange (where the adapter bolts on): the arm's external wrench is reported there.
        ET.SubElement(e, "site", name=f"{s}/flange", pos="0 0 0", size="0.004", group="5")
        # The gripper goes where the kit mounts its 2F-85 (its base link's frame), as Menagerie's
        # 2F-85 places its base: base_mount 7 mm + base 3.8 mm below, turned -90 deg about z.
        gb = _rigid(W(f"/{KIT}/Geometry/{s}_robotiq_2f85/Robotiq_2F_85/{s}_robotiq_base_link"), 1.0)
        base_in_mount = np.eye(4)
        base_in_mount[:3, :3] = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], float)
        base_in_mount[:3, 3] = [0, 0, 0.0038]
        mount = gb @ np.linalg.inv(base_in_mount)
        rel = Tinv[f"{s}/hand"] @ mount
        # Menagerie's base_mount body sits 7 mm above its model's origin: the frame is the origin.
        rel = rel @ np.r_[np.c_[np.eye(3), [0, 0, -0.007]], [[0, 0, 0, 1]]]
        fr = ET.SubElement(e, "frame", name=f"{s}/gripper_frame", pos=_fmt(rel[:3, 3]), quat=_fmt(_quat(rel[:3, :3])))
        ET.SubElement(fr, "attach", model="robotiq_2f85", body="base_mount", prefix=f"{s}/gripper/")
        gf = _rigid(W(f"/{KIT}/Geometry/{s}_robotiq_2f85/Robotiq_2F_85/{s}_robotiq_base_link/grip_frame"), 1.0)
        report.setdefault("grip_frame", {})[s] = (Tinv[f"{s}/hand"] @ gf)[:3, 3].round(5).tolist()

    # ---- position actuators, the kit's gains and effort limits
    act = ET.SubElement(root, "actuator")
    for name, j in joint_info.items():
        ET.SubElement(act, "general", {"class": "fr3", "name": name, "joint": name, "gainprm": f"{j['kp']:.6g}",
                                       "biasprm": f"0 {-j['kp']:.6g} {-j['kv']:.6g}",
                                       "ctrlrange": _fmt(j["range"]), "forcerange": _fmt([-j["effort"], j["effort"]])})
    ET.indent(root)
    (out / "fr3_duo.xml").write_text(ET.tostring(root, encoding="unicode") + "\n")
    report["joints"] = joint_info
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=pathlib.Path, help="the kit's package folder (fr3_duo_vision_manipulation_kit)")
    ap.add_argument("out", type=pathlib.Path)
    a = ap.parse_args(argv)
    print(json.dumps(convert(a.src, a.out), indent=1, default=float))


if __name__ == "__main__":
    main()
