"""Convert an industrial arm published as a SimReady USD package (SimReady Central on Hugging
Face) into a MuJoCo model.

    python -m playground.tools.convert_simready_arm comau_n220 <package's root usd> wetlabsim/assets/comau_n220
    python -m playground.tools.convert_simready_arm fanuc_crx30ia <package's root usd> wetlabsim/assets/fanuc_crx30ia

The packages (Comau/N220-27: CC BY 4.0; FANUC-CORPORATION/SimReady-Assets crx30ia: Apache 2.0)
are one serial chain of rigid bodies. Read from the package as published:

- one MuJoCo body per link, placed by the package's joint frames (so the model's zero pose is the
  package's zero pose, whatever pose the file was saved in);
- each link's stated mass, centre of mass and inertia (USD Physics MassAPI);
- each joint's axis and limits, and its position-drive gains and effort limit (stated per
  degree, here per radian); the package's joint speed limits where it states them;
- each link's collision shape (the package's own: one convex hull per link); the links don't
  collide with each other, as the package sets (enabledSelfCollisions = false);
- the visual meshes in the package's own colours (one mesh per link and colour), simplified.

The arm ends at its tool flange (site "flange": z out of the flange). Tools are attached by
wetlabsim/scene.py.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import xml.etree.ElementTree as ET

import numpy as np
import trimesh
from pxr import Gf, Usd, UsdGeom, UsdPhysics

from .convert_fr3_duo import _body_mass, _fmt
from .convert_simready import _quat, _rigid, combine_inertia, material_info, open_stage, read, write_obj

# Per arm: the model's name, the package's link bodies from base to flange, its joints in order,
# the variants to switch on, and where the tool flange is in the last link's frame (position,
# and the rotation that turns the link's frame so z points out of the flange).
ARMS = {
    # Comau N-220-2.7: link_6 is the flange disc; the package's joint 6 turns about its z.
    "comau_n220": {
        "links": ["base_link"] + [f"link_{i}" for i in range(1, 7)],
        "joints": [f"joint_{i}" for i in range(1, 7)],
        "variants": {"Physics": "PhysX"},
        "flange_from": "hull_top_z",
        "tris": 14000, "tris_base": 14000,
    },
    # FANUC CRX-30iA: J6_link turns about its x; the package marks the flange (J6_link/flange).
    "fanuc_crx30ia": {
        "links": ["base_link"] + [f"J{i}_link" for i in range(1, 7)],
        "joints": [f"J{i}" for i in range(1, 7)],
        "variants": {"PhysX": "Enabled"},
        "flange_from": "prim:flange",
        "tris": 9000, "tris_base": 9000,
    },
}
AXES = {"X": np.array([1.0, 0, 0]), "Y": np.array([0, 1.0, 0]), "Z": np.array([0, 0, 1.0])}


def _frame(pos, rot) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = np.array(Gf.Matrix3d(Gf.Quatd(rot.GetReal(), Gf.Vec3d(*rot.GetImaginary()))).GetTranspose())
    T[:3, 3] = np.array(pos, float)
    return T


def convert(arm: str, usd: pathlib.Path, out: pathlib.Path) -> dict:
    import fast_simplification
    cfg = ARMS[arm]
    stage = open_stage(usd)
    root = stage.GetDefaultPrim()
    for vs, sel in cfg["variants"].items():
        if vs in root.GetVariantSets().GetNames():
            root.GetVariantSet(vs).SetVariantSelection(sel)
    xc = UsdGeom.XformCache()
    W = lambda path: np.array(xc.GetLocalToWorldTransform(stage.GetPrimAtPath(path))).T
    rb = {p.GetName(): str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
    jp = {p.GetName(): p for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint)}
    links = cfg["links"]
    names = ["base"] + [f"link{i}" for i in range(1, len(links))]
    # each link's frame as the file has it (meshes are read in the world frame)
    Tw_inv = {n: np.linalg.inv(_rigid(W(rb[l]), 1.0)) for n, l in zip(names, links)}
    groups, colliders, _, _ = read(stage, by_body=True)
    owner = {rb[l]: n for n, l in zip(names, links)}

    (out / "assets").mkdir(parents=True, exist_ok=True)
    for f in (out / "assets").glob("*.obj"):
        f.unlink()
    xml = ET.Element("mujoco", model=arm)
    ET.SubElement(xml, "compiler", angle="radian", meshdir="assets", autolimits="true")
    ET.SubElement(xml, "option", integrator="implicitfast")
    top = ET.SubElement(xml, "default")
    ET.SubElement(top, "mesh", inertia="shell")       # every link states its own inertia
    default = ET.SubElement(top, "default", {"class": arm})
    ET.SubElement(default, "general", dyntype="none", biastype="affine")
    ET.SubElement(ET.SubElement(default, "default", {"class": "visual"}), "geom",
                  type="mesh", contype="0", conaffinity="0", group="2")
    ET.SubElement(ET.SubElement(default, "default", {"class": "collision"}), "geom", type="mesh", group="3")
    asset = ET.SubElement(xml, "asset")

    # ---- visual meshes: one per link and colour
    report: dict = {"links": {}, "joints": {}}
    mats: dict = {}
    vis: dict = {n: {} for n in names}
    for (body, _), g in groups.items():
        n = owner.get(body)
        if n is None:
            continue
        info = material_info(g["mat"])
        key = (tuple(round(float(v), 3) for v in info["rgba"]), round(info["rough"], 2), round(info["metal"], 2))
        V = np.concatenate(g["V"])
        vis[n].setdefault(key, []).append((Tw_inv[n][:3, :3] @ V.T).T + Tw_inv[n][:3, 3])
    geoms: dict = {n: [] for n in names}
    for n, bycol in vis.items():
        budget = cfg["tris_base"] if n == "base" else cfg["tris"]
        total = sum(len(v) for vs in bycol.values() for v in vs) / 3
        for k, (key, vs) in enumerate(sorted(bycol.items(), key=lambda kv: -sum(len(v) for v in kv[1]))):
            V = np.concatenate(vs)
            tm = trimesh.Trimesh(V, np.arange(len(V)).reshape(-1, 3), process=True)
            tm.merge_vertices()
            nf = len(tm.faces)
            target = max(int(budget * nf / max(total, 1)), 60)
            if nf > target * 1.2 and nf > 400:
                v2, f2 = fast_simplification.simplify(np.asarray(tm.vertices, np.float32),
                                                      np.asarray(tm.faces, np.int32), 1 - target / nf)
                tm = trimesh.Trimesh(v2, f2, process=True)
            if len(tm.faces) == 0:
                continue
            rgba, rough, metal = key
            if key not in mats:
                mats[key] = f"c{len(mats)}"
                ET.SubElement(asset, "material", name=mats[key], rgba=_fmt(rgba, 3),
                              specular=f"{0.5 if metal < 0.5 else 0.8:.2g}", shininess=f"{max(0.0, 1 - rough):.2g}",
                              reflectance=f"{0.1 * metal:.2g}")
            fn = f"{n}_{k}.obj"
            write_obj(out / "assets" / fn, np.asarray(tm.vertices), np.asarray(tm.faces))
            ET.SubElement(asset, "mesh", name=fn[:-4], file=fn)
            geoms[n].append((fn[:-4], mats[key]))
            report["links"].setdefault(n, {"visual_tris": 0})["visual_tris"] += len(tm.faces)

    # ---- collision shapes: the package's convex hull of each link
    col: dict = {n: [] for n in names}
    hulls: dict = {}
    for c in colliders:
        n = owner.get(c["body"])
        if n is None:
            continue
        hull = c["mesh"].convex_hull
        V = (Tw_inv[n][:3, :3] @ np.asarray(hull.vertices).T).T + Tw_inv[n][:3, 3]
        hulls.setdefault(n, []).append(V)
        fn = f"{n}_collision_{len(col[n])}.obj"
        write_obj(out / "assets" / fn, V, np.asarray(hull.faces))
        ET.SubElement(asset, "mesh", name=fn[:-4], file=fn)
        col[n].append(fn[:-4])

    # ---- the chain, placed by the joint frames (zero pose)
    world = ET.SubElement(xml, "worldbody")
    parent = world
    for i, (n, l) in enumerate(zip(names, links)):
        attrs = {"name": n}
        joint = None
        if i == 0:
            attrs["childclass"] = arm
        else:
            j = jp[cfg["joints"][i - 1]]
            g = lambda a: j.GetAttribute(a).Get() if j.GetAttribute(a) else None
            F0 = _frame(g("physics:localPos0"), g("physics:localRot0"))
            F1 = _frame(g("physics:localPos1"), g("physics:localRot1"))
            rel = F0 @ np.linalg.inv(F1)          # the child in its parent, at joint angle 0
            attrs["pos"], attrs["quat"] = _fmt(rel[:3, 3]), _fmt(_quat(rel[:3, :3]))
            axis = F1[:3, :3] @ AXES[g("physics:axis")]
            lo, hi = math.radians(g("physics:lowerLimit")), math.radians(g("physics:upperLimit"))
            name = f"joint{i}"
            joint = {"name": name, "pos": _fmt(F1[:3, 3]), "axis": _fmt(axis.round(9)), "range": _fmt([lo, hi])}
            kp = g("drive:angular:physics:stiffness") * 180 / math.pi
            kv = g("drive:angular:physics:damping") * 180 / math.pi
            effort = g("drive:angular:physics:maxForce")
            vmax = g("physxJoint:maxJointVelocity")
            report["joints"][name] = {
                "range_deg": [round(math.degrees(lo), 2), round(math.degrees(hi), 2)],
                "kp": round(kp, 1), "kv": round(kv, 2),
                "effort": None if effort is None or not math.isfinite(effort) else float(effort),
                "velocity_deg_s": None if vmax is None else round(float(vmax), 2),
                "equivalent_inertia": g("physics:JointEquivalentInertia")}
        e = ET.SubElement(parent, "body", attrs)
        props = _body_mass(stage.GetPrimAtPath(rb[l]), _rigid(W(rb[l]), 1.0))
        inert = combine_inertia([props], Tw_inv[n])
        ET.SubElement(e, "inertial", pos=_fmt(inert["pos"]), quat=_fmt(inert["quat"]),
                      mass=f"{inert['mass']:.6g}", diaginertia=_fmt(inert["diaginertia"]))
        report["links"].setdefault(n, {})["mass"] = round(inert["mass"], 3)
        if joint:
            ET.SubElement(e, "joint", joint)
        for mesh, mat in geoms[n]:
            ET.SubElement(e, "geom", {"class": "visual", "mesh": mesh, "material": mat})
        for mesh in col[n]:
            ET.SubElement(e, "geom", {"class": "collision", "mesh": mesh, "name": mesh})
        parent = e

    # ---- the tool flange on the last link: z out of the flange
    last = names[-1]
    if cfg["flange_from"].startswith("prim:"):
        fp = next(p for p in stage.Traverse() if p.GetName() == cfg["flange_from"][5:])
        rel = Tw_inv[last] @ _rigid(np.array(xc.GetLocalToWorldTransform(fp)).T, 1.0)
        # the package's flange frame has x out of the flange (ROS's tool0 convention is z): turn it
        R = rel[:3, :3] @ np.array([[0, 0, 1.0], [0, 1.0, 0], [-1.0, 0, 0]])
        pos, quat = rel[:3, 3], _quat(R)
    else:   # the flange face: the far end of the last link's shape along its own z (the joint's axis)
        V = np.concatenate(hulls[last])
        pos, quat = np.array([0.0, 0.0, float(V[:, 2].max())]), [1, 0, 0, 0]
    ET.SubElement(parent, "site", name="flange", pos=_fmt(pos), quat=_fmt(quat), size="0.01", group="5")
    report["flange"] = {"pos": [round(float(v), 5) for v in pos], "quat": [float(v) for v in quat]}

    # ---- the package switches the arm's self collisions off (enabledSelfCollisions = false)
    contact = ET.SubElement(xml, "contact")
    for i, a_ in enumerate(names):
        for b_ in names[i + 1:]:
            ET.SubElement(contact, "exclude", body1=a_, body2=b_)

    # ---- position actuators with the package's gains and effort limits
    act = ET.SubElement(xml, "actuator")
    for name, j in report["joints"].items():
        a = {"class": arm, "name": name, "joint": name, "gainprm": f"{j['kp']:.6g}",
             "biasprm": f"0 {-j['kp']:.6g} {-j['kv']:.6g}",
             "ctrlrange": _fmt([math.radians(v) for v in j["range_deg"]])}
        if j["effort"]:
            a["forcerange"] = _fmt([-j["effort"], j["effort"]])
        ET.SubElement(act, "general", a)
    ET.indent(xml)
    (out / f"{arm}.xml").write_text(ET.tostring(xml, encoding="unicode") + "\n")
    (out / "conversion.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=list(ARMS))
    ap.add_argument("usd", type=pathlib.Path, help="the package's root USD file")
    ap.add_argument("out", type=pathlib.Path)
    a = ap.parse_args(argv)
    print(json.dumps(convert(a.arm, a.usd, a.out), indent=1, default=float))


if __name__ == "__main__":
    main()
