"""Build the soft library items (catalog.SOFT) into playground/assets/<id>/.

    python -m playground.tools.build_soft [ids ...]

Each item is fetched and converted like any other (fetch_simready, convert_simready: its
SimReady meshes, textures and mass), then gets what MuJoCo needs to simulate it as a flex:

- sheet: sim.obj, a single-layer grid across the item's two largest extents: its underside if
         it lies flat, else through its middle;
- shell: sim.obj, the item's own surface simplified to about `nodes` vertices;
- rope:  sim.obj, a chain of `nodes` vertices along the item's centre line, and the tube's
         radius;
- solid: sim.obj, the 8 corners of the item's box (a 3D flex whose shape is interpolated
         from them: MuJoCo's trilinear flex), in the order MuJoCo numbers them.

Every vertex of the item's visual meshes is bound to the closest point on the simulated shape
(bind_<k>.npz: up to three sim vertices and their weights), so the visual mesh follows the
simulated one as a MuJoCo skin. Visual meshes are decimated with their
texture coordinates kept (at most VIS_FACES triangles per item), so the skin stays light.

Needs trimesh, pymeshlab and usd-core (build-time only, like convert_simready).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile

import numpy as np
import pymeshlab
import trimesh

from .. import catalog
from .convert_simready import _merge_uv_mesh, convert, write_obj
from .fetch_simready import fetch

VIS_FACES = 8000          # visual triangles per item, all parts together
SHEET_RADIUS = 0.002      # half the thickness of a cloth (m)
SHELL_RADIUS = 0.002


def read_obj(path: pathlib.Path):
    """The converter's OBJs: v, optional vt with the same indices, triangles."""
    V, UV, F = [], [], []
    for line in path.read_text().splitlines():
        if line.startswith("v "):
            V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vt "):
            UV.append([float(x) for x in line.split()[1:3]])
        elif line.startswith("f "):
            F.append([int(c.split("/")[0]) - 1 for c in line.split()[1:4]])
    return np.array(V), (np.array(UV) if UV else None), np.array(F, dtype=np.int64)


def _decimate(V, UV, F, target):
    """Fewer triangles, keeping the texture coordinates (MeshLab's textured quadric collapse)."""
    if len(F) <= target:
        return V, UV, F
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = pathlib.Path(tmp) / "in.obj", pathlib.Path(tmp) / "out.obj"
        write_obj(src, V, F, UV)
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(str(src))
        if UV is not None:
            ms.meshing_decimation_quadric_edge_collapse_with_texture(targetfacenum=int(target), preserveboundary=True)
        else:
            ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(target), preserveboundary=True)
        ms.save_current_mesh(str(dst), save_wedge_texcoord=UV is not None, save_vertex_coord=False)
        Vn, Fn, UVn = _read_wedge_obj(dst)
    if UV is None:
        return Vn, None, Fn
    # One vertex per (position, uv) corner, as the converter writes them.
    corners = Fn.reshape(-1)
    Vw, UVw, Fw = _merge_uv_mesh(Vn[corners], UVn.reshape(-1, 2))
    return Vw, UVw, Fw


def _read_wedge_obj(path: pathlib.Path):
    """MeshLab's OBJ: v, vt and f v/vt with separate indices. Returns V, F and per-corner UVs."""
    V, T, F, FT = [], [], [], []
    for line in path.read_text().splitlines():
        if line.startswith("v "):
            V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vt "):
            T.append([float(x) for x in line.split()[1:3]])
        elif line.startswith("f "):
            c = [p.split("/") for p in line.split()[1:4]]
            F.append([int(x[0]) - 1 for x in c])
            if len(c[0]) > 1 and c[0][1]:
                FT.append([int(x[1]) - 1 for x in c])
    T = np.array(T)
    UV = T[np.array(FT)] if FT else None
    return np.array(V), np.array(F, dtype=np.int64), UV


def _sheet(lo, hi, nodes):
    ext = hi - lo
    a, b = np.argsort(ext)[::-1][:2]             # the sheet spans the two largest extents
    c = 3 - a - b
    nx = max(3, int(round(np.sqrt(nodes * ext[a] / ext[b]))))
    ny = max(3, int(round(nodes / nx)))
    V = []
    for y in np.linspace(lo[b], hi[b], ny):
        for x in np.linspace(lo[a], hi[a], nx):
            v = np.zeros(3)
            # lying flat, the cloth is its underside (the rest of its mesh rests on it); upright
            # (a bag), the middle between its two faces
            v[a], v[b], v[c] = x, y, lo[c] + SHEET_RADIUS if c == 2 else (lo[c] + hi[c]) / 2
            V.append(v)
    V = np.array(V)
    F = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i, (j + 1) * nx + i + 1
            F += [[a, b, d], [a, d, c]]
    return V, np.array(F)


def _shell(V, F, nodes):
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(V, F))
    ms.meshing_merge_close_vertices(threshold=pymeshlab.PercentageValue(0.5))
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=max(8, 2 * nodes - 4), preservetopology=True,
                                                 planarquadric=True)
    ms.meshing_remove_unreferenced_vertices()
    m = ms.current_mesh()
    t = trimesh.Trimesh(m.vertex_matrix(), m.face_matrix(), process=True)
    return t.vertices, t.faces


def _centre_line(P, nodes):
    """A hose's centre line: the centroid of each thin slice across its main axis (a hose that
    runs one way along that axis), resampled to `nodes` points evenly spaced along it; and the
    tube's radius around it."""
    c = P.mean(0)
    axis = np.linalg.svd(P - c, full_matrices=False)[2][0]
    s = (P - c) @ axis
    edges = np.linspace(s.min(), s.max(), 4 * nodes + 1)
    L = np.array([P[(s >= a) & (s <= b)].mean(0) for a, b in zip(edges[:-1], edges[1:]) if ((s >= a) & (s <= b)).any()])
    L = np.array([L[max(0, i - 1):i + 2].mean(0) for i in range(len(L))])     # light smoothing
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(L, axis=0), axis=1))]
    t = np.linspace(0, arc[-1], nodes)
    line = np.c_[[np.interp(t, arc, L[:, j]) for j in range(3)]].T
    # the tube's radius as most of its surface has it (the 90th percentile, so its thicker parts,
    # fittings and bends rest on the table instead of sinking into it)
    return line, float(np.percentile(_seg_dist(P, line)[0], 90)), float(arc[-1])


def _seg_dist(P, line):
    """Each point's distance to a polyline, its closest segment and the position along it."""
    A, B = line[:-1], line[1:]
    AB = B - A
    t = np.clip(np.einsum("nsk,sk->ns", P[:, None] - A[None], AB) / np.einsum("sk,sk->s", AB, AB), 0, 1)
    Q = A[None] + t[..., None] * AB[None]
    d = np.linalg.norm(P[:, None] - Q, axis=2)
    seg = d.argmin(1)
    return d[np.arange(len(P)), seg], seg, t[np.arange(len(P)), seg]


def _bind_line(line, V):
    _, seg, t = _seg_dist(V, line)
    idx = np.c_[seg, seg + 1, seg + 1].astype(np.int32)
    w = np.c_[1 - t, t, np.zeros_like(t)].astype(np.float32)
    return idx, w


def _box(lo, hi):
    """The 8 corners, ordered as MuJoCo numbers a 2x2x2 flex grid's nodes (4*ix + 2*iy + iz)."""
    return np.array([[(lo, hi)[ix][0], (lo, hi)[iy][1], (lo, hi)[iz][2]]
                     for ix in (0, 1) for iy in (0, 1) for iz in (0, 1)])


def _bind_box(lo, hi, V):
    """Trilinear weights of each point over the box's 8 corners."""
    t = np.clip((V - lo) / (hi - lo), 0, 1)
    idx, w = [], []
    for ix in (0, 1):
        for iy in (0, 1):
            for iz in (0, 1):
                idx.append(4 * ix + 2 * iy + iz)
                w.append((t[:, 0] if ix else 1 - t[:, 0]) * (t[:, 1] if iy else 1 - t[:, 1]) * (t[:, 2] if iz else 1 - t[:, 2]))
    return np.tile(np.array(idx, np.int32), (len(V), 1)), np.array(w, np.float32).T


def _bind(sim_V, sim_F, V):
    """Each point: the three sim vertices of its closest sim triangle and its barycentric weights."""
    sim = trimesh.Trimesh(sim_V, sim_F, process=False)
    pts, _, tri = trimesh.proximity.closest_point(sim, V)
    bary = trimesh.triangles.points_to_barycentric(sim.triangles[tri], pts)
    bary = np.clip(bary, 0, None)
    bary /= bary.sum(1, keepdims=True)
    return sim_F[tri].astype(np.int32), bary.astype(np.float32)


def build(id_: str, cache: pathlib.Path):
    it, spec = catalog.item(id_), catalog.SOFT[id_]
    out = catalog.ASSETS / id_
    src = fetch(it["hf"], cache)
    meta = convert(src, out, hollow=False, max_tris=10 ** 9)
    tdir = src / "simready_usd" / ".thumbs" / "256x256"
    thumbs = sorted(tdir.glob("*_transparent.png")) or sorted(tdir.glob("*.usd*.png"))
    if thumbs:
        shutil.copy(thumbs[0], out / "thumb.png")
    parts = [read_obj(out / v["mesh"]) for v in meta["visuals"]]
    total = sum(len(F) for _, _, F in parts)
    allV = np.vstack([V for V, _, _ in parts])
    allF = np.vstack([F + sum(len(p[0]) for p in parts[:k]) for k, (_, _, F) in enumerate(parts)])
    lo, hi = allV.min(0), allV.max(0)
    soft = {"kind": spec["kind"]}
    if spec["kind"] == "rope":
        line, r, length = _centre_line(allV, spec["nodes"])
        write_obj(out / "sim.obj", line, np.zeros((0, 3), int))
        soft.update(sim="sim.obj", nodes=len(line), radius=round(r, 4), length=round(length, 4))
        for k, (V, UV, F) in enumerate(parts):
            V, UV, F = _decimate(V, UV, F, max(200, VIS_FACES * len(F) // total))
            write_obj(out / meta["visuals"][k]["mesh"], V, F, UV)
            if UV is None and meta["visuals"][k].get("texture"):
                del meta["visuals"][k]["texture"]
            idx, w = _bind_line(line, V)
            np.savez_compressed(out / f"bind_{k}.npz", idx=idx, w=w)
            meta["visuals"][k]["bind"] = f"bind_{k}.npz"
    elif spec["kind"] == "solid":
        write_obj(out / "sim.obj", _box(lo, hi), np.zeros((0, 3), int))
        soft.update(sim="sim.obj", nodes=8, radius=0.001, young=spec["young"], poisson=spec["poisson"],
                    damping=spec["damping"])
        for k, (V, UV, F) in enumerate(parts):
            V, UV, F = _decimate(V, UV, F, max(200, VIS_FACES * len(F) // total))
            write_obj(out / meta["visuals"][k]["mesh"], V, F, UV)
            if UV is None and meta["visuals"][k].get("texture"):
                del meta["visuals"][k]["texture"]
            idx, w = _bind_box(lo, hi, V)
            np.savez_compressed(out / f"bind_{k}.npz", idx=idx, w=w)
            meta["visuals"][k]["bind"] = f"bind_{k}.npz"
    else:
        if spec["kind"] == "sheet":
            sim_V, sim_F = _sheet(lo, hi, spec["nodes"])
            soft["radius"] = SHEET_RADIUS
        else:
            sim_V, sim_F = _shell(allV, allF, spec["nodes"])
            soft["radius"] = SHELL_RADIUS
        write_obj(out / "sim.obj", sim_V, sim_F)
        soft.update(sim="sim.obj", nodes=len(sim_V))
        for k, (V, UV, F) in enumerate(parts):
            V, UV, F = _decimate(V, UV, F, max(200, VIS_FACES * len(F) // total))
            write_obj(out / meta["visuals"][k]["mesh"], V, F, UV)
            if UV is None and meta["visuals"][k].get("texture"):
                del meta["visuals"][k]["texture"]
            idx, w = _bind(sim_V, sim_F, V)
            np.savez_compressed(out / f"bind_{k}.npz", idx=idx, w=w)
            meta["visuals"][k]["bind"] = f"bind_{k}.npz"
    meta["soft"] = soft
    meta["collision"] = {"sheet": "cloth (MuJoCo flex, 2D)", "shell": "limp shell (MuJoCo flex, 2D)",
                         "rope": "rope (MuJoCo flex, 1D)", "solid": "springy solid (MuJoCo flex, 3D)"}[spec["kind"]]
    meta["collision_parts"] = []
    for f in out.glob("col_*.obj"):
        f.unlink()
    (out / "asset.json").write_text(json.dumps(meta, indent=1))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--cache", default="build/simready")
    a = ap.parse_args(argv)
    for id_ in a.ids or list(catalog.SOFT):
        try:
            m = build(id_, pathlib.Path(a.cache))
            s = m["soft"]
            print(f"{id_:14s} {s['kind']:6s} nodes={s['nodes']} mass={m['mass']} size={m['size']} "
                  f"visual faces={sum(1 for _ in m['visuals'])} parts")
        except Exception as e:  # noqa: BLE001
            print(f"{id_:14s} FAILED: {type(e).__name__}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
