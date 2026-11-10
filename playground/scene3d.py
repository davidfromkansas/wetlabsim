"""The main view, drawn in the browser: what it needs from the server.

scene(m)        every visible geom (MuJoCo's groups 0-2): its body, shape, size, local pose,
                colour and material, and which mesh and texture it uses. Sent once per model.
mesh_bin(m, i)  one mesh as indexed triangles (positions, texture coordinates, faces).
tex_png(m, i)   one 2D texture as a PNG.
poses(d, ...)   one frame of the stream: every body's position and orientation, plus the
                view's overlay shapes (ghost, selection) and the server's camera, so glides
                and presets reach the browser.

The browser renders with three.js and moves its camera locally, so orbiting is instant; the
server keeps rendering the AI's own cameras as before.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import struct

import mujoco
import numpy as np
from PIL import Image

VISIBLE_GROUPS = (0, 1, 2)       # MuJoCo's default visible geom groups
TYPES = {mujoco.mjtGeom.mjGEOM_PLANE: "plane", mujoco.mjtGeom.mjGEOM_SPHERE: "sphere",
         mujoco.mjtGeom.mjGEOM_CAPSULE: "capsule", mujoco.mjtGeom.mjGEOM_ELLIPSOID: "ellipsoid",
         mujoco.mjtGeom.mjGEOM_CYLINDER: "cylinder", mujoco.mjtGeom.mjGEOM_BOX: "box",
         mujoco.mjtGeom.mjGEOM_MESH: "mesh"}
_DEFAULT_RGBA = np.array([0.5, 0.5, 0.5, 1.0], np.float32)


def _r(v, n=5):
    return [round(float(x), n) for x in v]


def scene(m: mujoco.MjModel, version) -> dict:
    geoms = []
    for g in range(m.ngeom):
        t = TYPES.get(int(m.geom_type[g]))
        if t is None or int(m.geom_group[g]) not in VISIBLE_GROUPS:
            continue
        mat = int(m.geom_matid[g])
        rgba = np.array(m.geom_rgba[g], np.float32)
        # MuJoCo draws a material's colour unless the geom sets its own.
        if mat >= 0 and np.allclose(rgba, _DEFAULT_RGBA):
            rgba = np.array(m.mat_rgba[mat], np.float32)
        if rgba[3] <= 0:
            continue
        tex = int(m.mat_texid[mat, int(mujoco.mjtTextureRole.mjTEXROLE_RGB)]) if mat >= 0 else -1
        if tex >= 0 and int(m.tex_type[tex]) != int(mujoco.mjtTexture.mjTEXTURE_2D):
            tex = -1
        geoms.append({
            "body": int(m.geom_bodyid[g]), "type": t, "size": _r(m.geom_size[g]),
            "pos": _r(m.geom_pos[g]), "quat": _r(m.geom_quat[g]), "rgba": _r(rgba, 3),
            "mesh": int(m.geom_dataid[g]) if t == "mesh" else -1, "tex": tex,
            "texrepeat": _r(m.mat_texrepeat[mat], 3) if mat >= 0 else [1, 1],
            "texuniform": bool(m.mat_texuniform[mat]) if mat >= 0 else False,
            "emission": round(float(m.mat_emission[mat]), 3) if mat >= 0 else 0.0,
            "specular": round(float(m.mat_specular[mat]), 3) if mat >= 0 else 0.5,
            "shininess": round(float(m.mat_shininess[mat]), 3) if mat >= 0 else 0.5,
            "reflectance": round(float(m.mat_reflectance[mat]), 3) if mat >= 0 else 0.0,
            "shadow": True,
        })
    lights = [{"pos": _r(m.light_pos[i]), "dir": _r(m.light_dir[i]), "diffuse": _r(m.light_diffuse[i], 3),
               "ambient": _r(m.light_ambient[i], 3), "directional": int(m.light_type[i]) == 1,
               "castshadow": bool(m.light_castshadow[i])} for i in range(m.nlight)]
    hl = m.vis.headlight
    return {"version": str(version), "nbody": int(m.nbody), "geoms": geoms, "lights": lights,
            "headlight": {"ambient": _r(hl.ambient, 3), "diffuse": _r(hl.diffuse, 3)},
            "meshhash": {str(i): mesh_hash(m, i) for i in {gg["mesh"] for gg in geoms if gg["mesh"] >= 0}}}


def mesh_hash(m, i: int) -> str:
    a, b = int(m.mesh_vertadr[i]), int(m.mesh_vertnum[i])
    fa, fn = int(m.mesh_faceadr[i]), int(m.mesh_facenum[i])
    h = hashlib.sha1(m.mesh_vert[a:a + b].tobytes())
    h.update(m.mesh_face[fa:fa + fn].tobytes())
    return h.hexdigest()[:16]


def mesh_bin(m, i: int) -> bytes:
    """[nv, nf, has_uv] (uint32 x3), positions (nv x 3 float32), normals (nv x 3 float32), uvs
    (nv x 2 float32, if any), faces (nf x 3 uint32). A vertex is a (position, normal, texcoord)
    triple, as MuJoCo indexes them per face corner, so the shading matches MuJoCo's."""
    a, nv = int(m.mesh_vertadr[i]), int(m.mesh_vertnum[i])
    fa, nf = int(m.mesh_faceadr[i]), int(m.mesh_facenum[i])
    na, nn = int(m.mesh_normaladr[i]), int(m.mesh_normalnum[i])
    vert = m.mesh_vert[a:a + nv]
    face = m.mesh_face[fa:fa + nf].astype(np.int64).ravel()
    norm = m.mesh_normal[na:na + nn]
    fnorm = m.mesh_facenormal[fa:fa + nf].astype(np.int64).ravel()
    ta, tn = int(m.mesh_texcoordadr[i]), int(m.mesh_texcoordnum[i])
    has_uv = ta >= 0 and tn > 0
    cols = [face, fnorm]
    if has_uv:
        tc = m.mesh_texcoord[ta:ta + tn]
        cols.append(m.mesh_facetexcoord[fa:fa + nf].astype(np.int64).ravel())
    uniq, inv = np.unique(np.stack(cols, 1), axis=0, return_inverse=True)
    out = io.BytesIO()
    out.write(struct.pack("<III", len(uniq), nf, 1 if has_uv else 0))
    out.write(np.asarray(vert[uniq[:, 0]], "<f4").tobytes())
    out.write(np.asarray(norm[uniq[:, 1]], "<f4").tobytes())
    if has_uv:
        out.write(np.asarray(tc[uniq[:, 2]], "<f4").tobytes())
    out.write(np.asarray(inv.reshape(-1, 3), "<u4").tobytes())
    return out.getvalue()


def tex_png(m, i: int) -> bytes:
    w, h, c = int(m.tex_width[i]), int(m.tex_height[i]), int(m.tex_nchannel[i])
    a = int(m.tex_adr[i])
    img = np.asarray(m.tex_data[a:a + w * h * c], np.uint8).reshape(h, w, c)
    buf = io.BytesIO()
    Image.fromarray(img[:, :, :3] if c >= 3 else img[:, :, 0]).save(buf, format="PNG")
    return buf.getvalue()


def poses(xpos: np.ndarray, xquat: np.ndarray, extra: dict) -> str:
    """One frame for the stream, as a JSON line (positions and orientations as base64 float32)."""
    return json.dumps({"p": base64.b64encode(np.asarray(xpos, "<f4").tobytes()).decode(),
                       "q": base64.b64encode(np.asarray(xquat, "<f4").tobytes()).decode(), **extra})
