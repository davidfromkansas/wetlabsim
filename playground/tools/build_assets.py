"""Fetch and convert every library item (catalog.ITEMS) into playground/assets/<id>/.

    python -m playground.tools.build_assets [ids ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

from .. import catalog
from .build_autobio import render_thumb
from .convert_simready import convert, usd_dir
from .fetch_simready import fetch


SOURCES = {
    "nvidia": ("NVIDIA SimReady", "https://huggingface.co/datasets/nvidia/simready-assets"),
    "tripo": ("Tripo SimReady", "https://huggingface.co/datasets/VAST-AI/Tripo-Simready-Assets"),
    "quiktech": ("QUIKTECH SimReady", "https://huggingface.co/datasets/quiktech/SimReady-Assets"),
    "usdcraft": ("NVIDIA USDCraft-10K (Apache 2.0)", "https://huggingface.co/datasets/nvidia/USDCraft-10K"),
    "forgecad": ("ForgeCAD SimReady", "https://huggingface.co/datasets/ForgeCAD/simready-assets"),
    "palatial": ("Palatial NV Asset Library (Palatial Platforms)", "https://huggingface.co/datasets/PalatialSim/palatial-nv-asset-library"),
    "projectsim": ("projectsim SimReady Assets (Kaedim)", "https://huggingface.co/datasets/projectsim/simready-assets"),
    "allsides": ("Allsides SimReady Assets", "https://huggingface.co/datasets/ALLSIDES/simready-scanned-objects"),
    "ndotlight": ("NdotLight SimReady Assets", "https://huggingface.co/datasets/NdotLight/SimReady_Assets"),
    "mxr": ("Marso by M-XR SimReady assets", "https://huggingface.co/datasets/M-XR/marso-simready"),
    "yamato": ("Yamato Protec SimReady fire protection", "https://huggingface.co/datasets/YAMATOPROTEC/simready-fire-protection"),
    "atech": ("atech SimReady assets", "https://huggingface.co/datasets/atechdev/simready-assets"),
}
BIBTEX = """@misc{downs2022scannedobjects,
  title = {Google Scanned Objects: A High-Quality Dataset of 3D Scanned Household Items},
  author = {Downs, Laura and Francis, Anthony and Koenig, Nate and Kinman, Brandon and Hickman, Ryan and Reymann, Krista and McHugh, Thomas B. and Vanhoucke, Vincent},
  publisher = {arXiv}, year = {2022}, url = {https://arxiv.org/abs/2204.11918}
}
@software{zakka2022scannedobjectsmujoco,
  author = {Zakka, Kevin}, title = {{Scanned Objects MuJoCo Models}}, year = {2022},
  url = {https://github.com/kevinzakka/mujoco_scanned_objects}, version = {0.0.1}
}
@inproceedings{robocasa2024,
  title = {RoboCasa: Large-Scale Simulation of Everyday Tasks for Generalist Robots},
  author = {Soroush Nasiriany and Abhiram Maddukuri and Lance Zhang and Adeet Parikh and Aaron Lo and Abhishek Joshi and Ajay Mandlekar and Yuke Zhu},
  booktitle = {Robotics: Science and Systems (RSS)}, year = {2024}
}
@inproceedings{robocasa365,
  title = {RoboCasa365: A Large-Scale Simulation Framework for Training and Benchmarking Generalist Robots},
  author = {Soroush Nasiriany and Sepehr Nasiriany and Abhiram Maddukuri and Yuke Zhu},
  booktitle = {International Conference on Learning Representations (ICLR)}, year = {2026}
}""".splitlines()
AUTOBIO = ("AutoBio", "../../wetlabsim/assets/autobio/NOTICE.md")


def write_credits():
    """playground/assets/CREDITS.md: every library item, its source and licence (CC BY 4.0)."""
    lines = ["# Object library credits", "",
             "Most objects in the playground's library are ready-made assets, used under the",
             "[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) licence",
             "they are published with (USDCraft-10K's under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)).",
             "We converted each to MuJoCo (`playground/tools/convert_simready.py`) and changed nothing else",
             "(the coloured tube racks are one USDCraft rack in five colours). All rights stay with their authors.",
             "Items marked \"Built in-house\" we modelled ourselves in Blender (`playground/tools/build_inhouse.py`).", ""]
    for key, (name, url) in SOURCES.items():
        lines.append(f"- **{name}** ({key}): {url}")
    lines += ["- **Google Scanned Objects, as MuJoCo models** (gso): https://github.com/kevinzakka/mujoco_scanned_objects "
              "(meshes and textures CC BY 4.0, Google; MJCF MIT, Kevin Zakka)",
              "- **RoboCasa kitchen objects** (robocasa): https://github.com/robocasa/robocasa (assets CC BY 4.0; "
              "objects as RoboCasa loads them, `playground/tools/export_robocasa.py`); its Lightwheel objects and its fixtures are from "
              "NVIDIA's https://huggingface.co/datasets/nvidia/PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF (CC BY 4.0)"]
    lines += ["", "## Citations", "", "Sources whose authors ask to be cited:", "", "```bibtex", *BIBTEX, "```"]
    lines += ["", "AutoBio's lab models (the tubes, racks, dish, pipette and its stand) are used with credit to",
              "its authors; see `wetlabsim/assets/autobio/NOTICE.md`.", "",
              "| Item | Library tab | Source | Asset |", "| --- | --- | --- | --- |"]
    for i, tab, label, hf, _, _ in catalog.ITEMS:
        repo, _, folder = hf.rpartition(":")
        if repo == "autobio":             # in the repo already (tools/build_autobio.py)
            lines.append(f"| {label} | {tab} | AutoBio (credit in NOTICE.md) | [`{folder}`]({AUTOBIO[1]}) |")
            continue
        if repo == "inhouse":
            lines.append(f"| {label} | {tab} | Built in-house (Blender) | `{folder}` |")
            continue
        if repo == "mujoco":              # MuJoCo's own model gallery (Apache 2.0), kept as it is
            lines.append(f"| {label} | {tab} | MuJoCo model gallery, by Kevin Zakka (Apache 2.0) | "
                         f"[`{folder}`](https://github.com/google-deepmind/mujoco/tree/main/model/cube) |")
            continue
        if repo == "libero":              # LIBERO's own models (tools/build_libero_objects.py)
            lines.append(f"| {label} | {tab} | LIBERO (MIT) | "
                         f"[`{folder}`](https://github.com/Lifelong-Robot-Learning/LIBERO/tree/master/libero/libero/assets/{folder}) |")
            continue
        if repo == "gso":
            lines.append(f"| {label} | {tab} | Google Scanned Objects (CC BY 4.0), MuJoCo model by Kevin Zakka (MIT) | "
                         f"[`{folder}`](https://github.com/kevinzakka/mujoco_scanned_objects/tree/main/models/{folder}) |")
            continue
        if repo == "robocasa":
            by = "RoboCasa (CC BY 4.0)" + (", model from NVIDIA PhysicalAI Kitchen MJCF (Lightwheel)"
                                           if folder.startswith(("lightwheel/", "fixtures/")) else "")
            path = folder if folder.startswith("fixtures/") else "objects/" + folder
            lines.append(f"| {label} | {tab} | {by} | `{path}` |")
            continue
        name, url = SOURCES[repo or "nvidia"]
        lines.append(f"| {label} | {tab} | {name} | [`{folder}`]({url}/tree/main/{folder}) |")
    (catalog.ASSETS / "CREDITS.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--cache", default="build/simready")
    ap.add_argument("--by-repo", action="store_true", help="cache each source in its own folder")
    ap.add_argument("--no-credits", action="store_true", help="don't rewrite CREDITS.md (tools/build_extra runs many at once)")
    a = ap.parse_args(argv)
    ids = a.ids or [i[0] for i in catalog.ITEMS if not i[3].startswith(("autobio:", "mujoco:", "inhouse:", "libero:", "gso:", "robocasa:"))]
    for id_ in ids:
        it = catalog.item(id_)
        try:
            repo, _, folder = it["hf"].rpartition(":")
            src = fetch(folder, pathlib.Path(a.cache) / (repo or "nvidia") if a.by_repo else pathlib.Path(a.cache), repo or "nvidia")
            m = convert(src, catalog.ASSETS / id_, hollow=it["hollow"], fine=id_ in catalog.FINE_PIECES,
                        per_collider=id_ in catalog.PER_COLLIDER, max_tris=catalog.MAX_TRIS.get(id_, 60000))
            tdir = usd_dir(src) / ".thumbs" / "256x256"
            thumbs = sorted(tdir.glob("*_transparent.png")) or sorted(tdir.glob("*.usd*.png"))
            if id_ in catalog.RECOLOR:      # one rack in another colour: plain colour, no texture
                out = catalog.ASSETS / id_
                for v in m["visuals"]:
                    v["rgba"] = catalog.RECOLOR[id_]
                    if v.get("texture"):
                        (out / v.pop("texture")).unlink()
                (out / "asset.json").write_text(json.dumps(m, indent=1))
                thumbs = []
            if thumbs:
                shutil.copy(thumbs[0], catalog.ASSETS / id_ / "thumb.png")
            else:                           # no picture in the package: render one
                render_thumb(catalog.ASSETS / id_, m)
            print(f"{id_:20s} mass={m['mass']} size={m['size']} parts={len(m['collision_parts'])} bodies={len(m.get('bodies', []))}")
        except Exception as e:  # noqa: BLE001
            print(f"{id_:20s} FAILED: {e}", file=sys.stderr)
    if not a.no_credits:
        write_credits()


if __name__ == "__main__":
    main()
