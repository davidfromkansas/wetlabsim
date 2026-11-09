"""Copy what the LIBERO-Goal scene needs out of a LIBERO checkout into playground/libero_assets.

    git clone https://github.com/Lifelong-Robot-Learning/LIBERO
    python -m playground.tools.import_libero LIBERO

Copied as published: the object and fixture models (their MJCF, collision shapes, masses,
textures), the room textures, the ten LIBERO-Goal task files (.bddl) and their 50 official
starting states each. Two conversions, so it loads in MuJoCo 4 without LIBERO's code:
- visual meshes in MuJoCo's old binary .msh format (no longer read by MuJoCo) become .obj;
- the starting states (pickled numpy arrays) become .npz. They are read with an unpickler
  that only allows numpy arrays.
"""
from __future__ import annotations

import argparse
import codecs
import importlib
import pathlib
import pickle
import re
import shutil
import struct
import zipfile

import numpy as np

OUT = pathlib.Path(__file__).resolve().parent.parent / "libero_assets"

# LIBERO-Goal's objects and fixtures: (category folder, model folder, xml)
MODELS = {
    "akita_black_bowl": ("stable_scanned_objects", "akita_black_bowl", "akita_black_bowl.xml"),
    "plate": ("stable_scanned_objects", "plate", "plate.xml"),
    "cream_cheese": ("stable_hope_objects", "cream_cheese", "cream_cheese.xml"),
    "wine_bottle": ("turbosquid_objects", "wine_bottle", "wine_bottle.xml"),
    "wine_rack": ("turbosquid_objects", "wine_rack", "wine_rack.xml"),
    "wooden_cabinet": ("articulated_objects", "", "wooden_cabinet.xml"),
    "flat_stove": ("articulated_objects", "", "flat_stove.xml"),
}
SCENE_TEXTURES = ["tile_grigia_caldera_porcelain_floor.png", "martin_novak_wood_table.png",
                  "smooth_light_gray_plaster.png"]


def msh_to_obj(src: pathlib.Path, dst: pathlib.Path):
    """MuJoCo's legacy binary mesh: 4 int32 counts, then vertices, normals, uvs, faces."""
    b = src.read_bytes()
    nv, nn, nt, nf = struct.unpack_from("4i", b, 0)
    o = 16
    v = np.frombuffer(b, np.float32, 3 * nv, o).reshape(-1, 3)
    o += 12 * nv
    n = np.frombuffer(b, np.float32, 3 * nn, o).reshape(-1, 3)
    o += 12 * nn
    t = np.frombuffer(b, np.float32, 2 * nt, o).reshape(-1, 2)
    o += 8 * nt
    f = np.frombuffer(b, np.int32, 3 * nf, o).reshape(-1, 3)
    lines = [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in v]
    lines += [f"vn {x:.5f} {y:.5f} {z:.5f}" for x, y, z in n]
    # .msh stores MuJoCo's own texture coordinates; MuJoCo flips v when it reads an OBJ.
    lines += [f"vt {x:.6f} {1 - y:.6f}" for x, y in t]
    has_t, has_n = nt == nv, nn == nv
    for a in f + 1:
        if has_t and has_n:
            lines.append("f " + " ".join(f"{i}/{i}/{i}" for i in a))
        elif has_t:
            lines.append("f " + " ".join(f"{i}/{i}" for i in a))
        elif has_n:
            lines.append("f " + " ".join(f"{i}//{i}" for i in a))
        else:
            lines.append("f " + " ".join(str(i) for i in a))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines) + "\n")


def copy_model(assets: pathlib.Path, key: str):
    cat, folder, xml = MODELS[key]
    src_dir = assets / cat / folder if folder else assets / cat
    text = (src_dir / xml).read_text()
    out_dir = OUT / "objects" / key
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    def fix(m):
        rel = m.group(1)
        src = (src_dir / rel)
        if rel.endswith(".msh"):
            new = rel[:-4] + ".obj"
            msh_to_obj(src, out_dir / new)
            return f'file="{new}"'
        (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, out_dir / rel)
        return m.group(0)

    text = re.sub(r'file="([^"]+)"', fix, text)
    # Older MuJoCo let two assets share a name and used the first; MuJoCo 4 refuses. Keep the first.
    seen = set()

    def dedupe(m):
        key = (m.group(1), m.group(2))
        if key in seen:
            return ""
        seen.add(key)
        return m.group(0)

    text = re.sub(r'<(texture|material|mesh)\b[^>]*?\bname="([^"]+)"[^>]*/>', dedupe, text)
    (out_dir / "model.xml").write_text(text)


def _load_init(path: pathlib.Path) -> np.ndarray:
    allowed = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
               ("numpy", "ndarray"), ("numpy", "dtype"), ("_codecs", "encode")}

    class OnlyNumpy(pickle.Unpickler):
        def find_class(self, mod, name):
            if (mod, name) not in allowed:
                raise pickle.UnpicklingError(f"refusing {mod}.{name}")
            if mod == "_codecs":
                return codecs.encode
            return getattr(importlib.import_module(mod.replace("numpy.core", "numpy._core")), name)

    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith("data.pkl"))
        return OnlyNumpy(z.open(name)).load()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("libero", help="a LIBERO checkout")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.libero) / "libero" / "libero"
    assets = root / "assets"
    for key in MODELS:
        copy_model(assets, key)
        print("model", key)
    (OUT / "textures").mkdir(parents=True, exist_ok=True)
    for t in SCENE_TEXTURES:
        shutil.copy(assets / "textures" / t, OUT / "textures" / t)
    (OUT / "tasks").mkdir(exist_ok=True)
    for bddl in sorted((root / "bddl_files" / "libero_goal").glob("*.bddl")):
        shutil.copy(bddl, OUT / "tasks" / bddl.name)
        states = _load_init(root / "init_files" / "libero_goal" / (bddl.stem + ".pruned_init"))
        np.savez_compressed(OUT / "tasks" / (bddl.stem + ".npz"), states=states)
        print("task", bddl.stem, states.shape)
    lic = pathlib.Path(a.libero) / "LICENSE"
    if lic.exists():
        shutil.copy(lic, OUT / "LICENSE")


if __name__ == "__main__":
    main()
