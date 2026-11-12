"""More of AutoBio's lab items, straight from its own MuJoCo models (autobio/model/object and
autobio/model/instrument), as library items in playground/assets/<id>/.

    python -m playground.tools.build_autobio_mjcf [ids ...] [--src build/autobio]

AutoBio's models are MuJoCo files already. We load each with MuJoCo and write its parts in the
library's form: every body with its visual meshes (and textures), its collision shapes (MuJoCo
collides a mesh as its convex hull, so that is what we store), its mass, and its joint (a lid's
hinge, a rotor's spin, a knob). AutoBio's own plugins (a click-stop "detent" on knobs and
switches, and a screw-thread shape) are not part of MuJoCo, so those are left out: knobs turn
freely within their range, and the cryovial's cap sits on by a weld like our other screw caps.

Source: https://github.com/autobio-bench/AutoBio (commit below), used with credit to its authors;
see wetlabsim/assets/autobio/NOTICE.md.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import trimesh
from PIL import Image

from .. import catalog
from .build_autobio import render_thumb
from .convert_simready import write_obj

REPO = "https://github.com/autobio-bench/AutoBio.git"
COMMIT = "08504213356cbfe9a82bcd33a43cd282945a45df"
POLYPROPYLENE = 900.0      # kg/m3: the small plastic items' mass is their collision volume of it

# library item -> (AutoBio model file, plastic item whose mass comes from its volume?)
MODELS = {
    "pipette_tip": ("object/pipette_tip.gen.xml", True),
    "tip_box": ("object/tip_box.gen.xml", True),
    "pcr_plate": ("object/pcr_plate_96well.gen.xml", True),
    "tube_10ml": ("object/centrifuge_10ml.gen.xml", True),
    "snap_tube": ("object/centrifuge_1500ul_no_lid.gen.xml", True),
    "cryovial": ("object/cryovial_1-8ml.xml", True),
    "centrifuge_5430": ("instrument/centrifuge_eppendorf_5430.xml", False),
    "mini_centrifuge": ("instrument/centrifuge_tiangen_tgear_mini.xml", False),
    "thermal_cycler": ("instrument/thermal_cycler_biorad_c1000.xml", False),
    "thermomixer": ("instrument/thermal_mixer_eppendorf_c.xml", False),
    "vortex_mixer": ("instrument/vortex_mixer_genie_2.xml", False),
}
# AutoBio's own preprocessor names meshes "stl:name" and refers to them as "name:"
_NAME = re.compile(r"^(stl|obj):")


def fetch(src: pathlib.Path) -> pathlib.Path:
    """AutoBio's models and meshes at the pinned commit (only the folders we use)."""
    if not (src / "autobio" / "model").is_dir():
        src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", REPO, str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "checkout", "-q", COMMIT, "--", "autobio/model",
                        "autobio/assets/container", "autobio/assets/rack/tip_box_24slot_vis",
                        "autobio/assets/instrument"], check=True)
    return src / "autobio"


def _clean(path: pathlib.Path, root: pathlib.Path) -> str:
    """The model as stock MuJoCo loads it: without AutoBio's plugins, its controls and sensors."""
    text = re.sub(r"^<\?xml[^>]*\?>", "", path.read_text().lstrip())   # (one file's declaration has a typo)
    r = ET.fromstring(text)
    comp = r.find("compiler")
    for k in ("meshdir", "assetdir", "texturedir"):
        comp.attrib.pop(k, None)
    comp.set("assetdir", str(root / "assets"))
    for tag in ("extension", "equality", "actuator", "sensor", "contact", "keyframe", "option", "visual"):
        for el in r.findall(tag):
            r.remove(el)
    for parent in r.iter():
        for el in list(parent):
            if el.tag == "plugin" or (el.tag == "geom" and el.get("type") == "sdf") \
                    or (el.tag == "mesh" and el.find("plugin") is not None):
                parent.remove(el)
    for el in r.iter("mesh"):
        if el.get("name"):
            el.set("name", _NAME.sub("", el.get("name")))
    for el in r.iter("geom"):
        if el.get("mesh", "").endswith(":"):
            el.set("mesh", el.get("mesh")[:-1])
    return ET.tostring(r, encoding="unicode")


def _prim(m, g) -> trimesh.Trimesh | None:
    t, s = m.geom_type[g], m.geom_size[g]
    G = mujoco.mjtGeom
    if t == G.mjGEOM_BOX:
        return trimesh.creation.box(extents=2 * s)
    if t == G.mjGEOM_SPHERE:
        return trimesh.creation.icosphere(subdivisions=2, radius=s[0])
    if t == G.mjGEOM_CYLINDER:
        return trimesh.creation.cylinder(radius=s[0], height=2 * s[1], sections=24)
    if t == G.mjGEOM_CAPSULE:
        return trimesh.creation.capsule(radius=s[0], height=2 * s[1], count=[12, 12])
    if t == G.mjGEOM_PLANE:     # a finite plane as a thin plate, its top where the plane is
        return trimesh.creation.box(extents=(2 * s[0], 2 * s[1], 0.001),
                                    transform=trimesh.transformations.translation_matrix([0, 0, -0.0005]))
    if t == G.mjGEOM_ELLIPSOID:
        e = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        e.apply_scale(s)
        return e
    return None


def _mesh(m, g, uv=False):
    """A mesh geom's triangles (and per-corner uv) in the mesh's own frame."""
    i = m.geom_dataid[g]
    va, nv, fa, nf = m.mesh_vertadr[i], m.mesh_vertnum[i], m.mesh_faceadr[i], m.mesh_facenum[i]
    V = m.mesh_vert[va:va + nv].astype(float)
    F = m.mesh_face[fa:fa + nf]
    if not uv or m.mesh_texcoordadr[i] < 0:
        return V, F, None
    ta = m.mesh_texcoordadr[i]
    UV = m.mesh_texcoord[ta:ta + m.mesh_texcoordnum[i]].astype(float)
    FT = m.mesh_facetexcoord[fa:fa + nf]
    Vc, UVc = V[F.reshape(-1)], UV[FT.reshape(-1)]
    UVc = np.c_[UVc[:, 0], 1 - UVc[:, 1]]       # MuJoCo flips v on load; OBJ files count it from the bottom
    key = np.round(np.c_[Vc, UVc], 6)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return Vc[first], inv.reshape(-1, 3), UVc[first]


def _pose(pos, quat) -> np.ndarray:
    T = np.eye(4)
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(quat, float))
    T[:3, :3], T[:3, 3] = R.reshape(3, 3), pos
    return T


def _quat(R) -> list:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(R).reshape(-1))
    return np.round(q, 6).tolist()


def build(id_: str, root: pathlib.Path) -> dict:
    file, plastic = MODELS[id_]
    xml = _clean(root / "model" / file, root)
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_kinematics(m, d)
    out = catalog.ASSETS / id_
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()

    def kind(g):
        if m.geom_group[g] == 5:                          # AutoBio's mass-only shapes
            return None
        if m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0 and m.geom_group[g] != 3:
            return "vis"
        return "col"

    # the item's frame: centred in x and y, z = 0 at its bottom (as placed upright)
    pts = []
    for g in range(m.ngeom):
        if kind(g) == "vis" and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
            V = _mesh(m, g)[0]
            R = d.geom_xmat[g].reshape(3, 3)
            pts.append(V @ R.T + d.geom_xpos[g])
    P = np.vstack(pts)
    lo, hi = P.min(0), P.max(0)
    shift = -np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])

    bodies, index = [], {}
    tex_saved: dict = {}
    for b in range(1, m.nbody):
        Tb = _pose(d.xpos[b] + shift, d.xquat[b])
        vis, col = [], []
        for g in np.where(m.geom_bodyid == b)[0]:
            k = kind(g)
            if k is None:
                continue
            Tg = _pose(m.geom_pos[g], m.geom_quat[g])
            if k == "vis":
                if m.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH:
                    continue
                mat = m.geom_matid[g]
                tex = m.mat_texid[mat, mujoco.mjtTextureRole.mjTEXROLE_RGB] if mat >= 0 else -1
                V, F, UV = _mesh(m, g, uv=tex >= 0)
                V = V @ Tg[:3, :3].T + Tg[:3, 3]
                name = f"b{len(bodies)}_vis_{len(vis)}.obj"
                write_obj(out / name, V, F, UV)
                rgba = (m.mat_rgba[mat] if mat >= 0 else m.geom_rgba[g]).astype(float)
                v = {"mesh": name, "rgba": np.round(rgba, 4).tolist(),
                     "roughness": round(float(m.mat_roughness[mat]), 3) if mat >= 0 else 0.5,
                     "metallic": round(float(m.mat_metallic[mat]), 3) if mat >= 0 else 0.0}
                if tex >= 0 and UV is not None:
                    if tex not in tex_saved:
                        w, h, c, a = m.tex_width[tex], m.tex_height[tex], m.tex_nchannel[tex], m.tex_adr[tex]
                        img = m.tex_data[a:a + w * h * c].reshape(h, w, c)[:, :, :3]
                        tex_saved[tex] = f"tex_{len(tex_saved)}.png"
                        im = Image.fromarray(img)
                        im.thumbnail((1024, 1024))
                        im.save(out / tex_saved[tex], optimize=True)
                    v["texture"] = tex_saved[tex]
                vis.append(v)
            else:
                if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
                    V, F, _ = _mesh(m, g)
                    tm = trimesh.Trimesh(V, F).convex_hull     # MuJoCo collides a mesh as its hull
                else:
                    tm = _prim(m, g)
                    if tm is None:
                        continue
                tm.apply_transform(Tg)
                name = f"b{len(bodies)}_col_{len(col)}.obj"
                write_obj(out / name, tm.vertices, tm.faces)
                part = {"mesh": name, "volume": float(tm.volume)}
                if (m.geom_contype[g], m.geom_conaffinity[g]) != (1, 1):
                    # AutoBio's contact filter: the tip box's tray only holds tips (their collars)
                    part.update(contype=int(m.geom_contype[g]), conaffinity=int(m.geom_conaffinity[g]))
                col.append(part)
        if not vis and not col:
            continue
        rec = {"name": m.body(b).name or f"part{b}", "visuals": vis, "collision_parts": col,
               "frame": [*np.round(Tb[:3, 3], 6).tolist(), *_quat(Tb[:3, :3])]}
        if plastic:
            rec["mass"] = round(POLYPROPYLENE * sum(c["volume"] for c in col), 6) or None
        else:
            rec["mass"] = round(float(m.body_mass[b]), 6)
            rec["inertial"] = {"mass": rec["mass"], "pos": np.round(m.body_ipos[b], 6).tolist(),
                               "quat": np.round(m.body_iquat[b], 6).tolist(),
                               "diaginertia": np.round(np.maximum(m.body_inertia[b], 1e-9), 9).tolist()}
        parent = m.body_parentid[b]
        jnts = [j for j in range(m.njnt) if m.jnt_bodyid[j] == b]
        if parent == 0 or parent not in index:
            if bodies:      # a second loose body (the cryovial's cap): held on by a weld
                Tp = _pose(*np.split(np.array(bodies[0]["frame"]), [3]))
                rel = np.linalg.inv(Tp) @ Tb
                rec.update(parent=0, weld=True, collide=False, pos=np.round(rel[:3, 3], 6).tolist(),
                           quat=_quat(rel[:3, :3]))
            else:
                rec.update(parent=None, root=True, pos=[0, 0, 0], quat=[1, 0, 0, 0])
        else:
            rec.update(parent=index[parent], pos=np.round(m.body_pos[b], 6).tolist(),
                       quat=np.round(m.body_quat[b], 6).tolist())
            if jnts:                                     # its first joint (a vortex's orbit is AutoBio's own drive)
                j = jnts[0]
                jt = {"name": m.joint(j).name.replace("/", "_"),
                      "type": "hinge" if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE else "slide",
                      "pos": np.round(m.jnt_pos[j], 6).tolist(), "axis": np.round(m.jnt_axis[j], 6).tolist()}
                if m.jnt_limited[j]:
                    jt["range"] = np.round(m.jnt_range[j], 5).tolist()
                da = m.jnt_dofadr[j]
                for key, val in (("damping", m.dof_damping[da]), ("stiffness", m.jnt_stiffness[j]),
                                 ("frictionloss", m.dof_frictionloss[da]), ("armature", m.dof_armature[da])):
                    if val:
                        jt[key] = round(float(val), 6)
                rec["joint"] = jt
                rec["collide"] = False
            else:
                rec.update(weld=True, collide=False)      # a fixed part: its shapes join its parent's
        index[b] = len(bodies)
        bodies.append(rec)
    stated = [b["mass"] for b in bodies if b.get("mass")]
    meta = {"source": "AutoBio", "usd": None, "mass": round(sum(stated), 5) if stated else None,
            "friction": 1.0, "com": None, "size": np.round(hi - lo, 4).tolist(),
            "collision": "AutoBio's own collision shapes (MuJoCo model)" + (
                "; mass is their volume of polypropylene" if plastic else ", moving parts on their joints"),
            "visuals": [], "collision_parts": [], "bodies": bodies,
            "unstated_mass": [b["name"] for b in bodies if not b.get("mass")]}
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    render_thumb(out, meta)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--src", default="build/autobio")
    a = ap.parse_args(argv)
    root = fetch(pathlib.Path(a.src))
    for id_ in a.ids or list(MODELS):
        meta = build(id_, root)
        print(f"{id_:16s} mass={meta['mass']} size={meta['size']} bodies={len(meta['bodies'])}")


if __name__ == "__main__":
    main()
