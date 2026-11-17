"""The library's category tree (object_tree.txt) and each object's tags, for building scenes
from a prompt: which branches of the tree an object sits on, the rooms it belongs in, its size
class, whether a robot hand could pick it up, and whether it looks full quality (textured) or
like plain CAD.

These tags are for the scene builder and for checking scenes only. The robot AI never sees them.
"""
from __future__ import annotations

import functools
import json
import pathlib

from . import catalog

HERE = pathlib.Path(__file__).resolve().parent
TREE_FILE = HERE / "object_tree.txt"


@functools.lru_cache(maxsize=1)
def leaves() -> dict[str, dict]:
    """Each leaf's path ("Kitchen & dining > Tableware > Drinkware") -> its rooms and labels."""
    out: dict[str, dict] = {}
    cur = None
    for line in TREE_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("=="):
            path, _, rooms = line[2:].partition("|")
            cur = path.strip()
            out[cur] = {"rooms": [r.strip() for r in rooms.split(",") if r.strip()], "labels": []}
        elif cur:
            out[cur]["labels"] += [x.strip() for x in line.split(";") if x.strip()]
    return out


def _textured(asset: dict) -> bool:
    vis = list(asset.get("visuals") or [])
    for b in asset.get("bodies") or []:
        vis += b.get("visuals") or []
    return any(v.get("texture") for v in vis) or bool(asset.get("mjcf"))   # LIBERO's own models are textured


def _size_class(size, fixed: bool) -> str:
    big = max(size)
    if fixed or big > 1.0:
        return "furniture"
    if big <= 0.15:
        return "small"
    if big <= 0.4:
        return "medium"
    return "large"


@functools.lru_cache(maxsize=1)
def tags() -> dict[str, dict]:
    """Every library object (by id) with its tags."""
    by_label: dict[str, list[str]] = {}
    for path, leaf in leaves().items():
        for lab in leaf["labels"]:
            by_label.setdefault(lab, []).append(path)
    out = {}
    for c in catalog.available():
        f = catalog.ASSETS / c["id"] / "asset.json"
        asset = json.loads(f.read_text())
        paths = by_label.get(c["label"], [])
        rooms = sorted({r for p in paths for r in leaves()[p]["rooms"]})
        sx, sy, sz = c["size"]
        out[c["id"]] = {
            "label": c["label"], "paths": paths, "rooms": rooms,
            "size_cm": [round(100 * v) for v in c["size"]],
            "size_class": _size_class(c["size"], c["fixed"]),
            "fixed": c["fixed"], "soft": c["soft"],
            # small enough across for a hand to close round and light enough to lift; each robot's
            # own gripper opening and payload are checked when a scene is built
            "graspable": (not c["fixed"]) and min(sx, sy) <= 0.12 and c["mass"] <= 5.0,
            "look": "full" if _textured(asset) else "plain",
            "source": c["source"],
        }
    return out


def counts() -> dict[str, int]:
    """How many library objects sit under each node of the tree (leaves and every branch)."""
    n: dict[str, int] = {}
    for t in tags().values():
        seen = set()
        for p in t["paths"]:
            parts = [x.strip() for x in p.split(">")]
            for k in range(1, len(parts) + 1):
                seen.add(" > ".join(parts[:k]))
        for s in seen:
            n[s] = n.get(s, 0) + 1
    return dict(sorted(n.items()))


def under(node: str) -> list[str]:
    """Ids of the objects under a node (a leaf or any branch above it)."""
    node = " > ".join(x.strip() for x in node.split(">"))
    return [i for i, t in tags().items()
            if any(p == node or p.startswith(node + " > ") for p in t["paths"])]


def tree_text(labels: bool = False) -> str:
    """The tree with counts, as a planner reads it: one node per line, indented; with labels,
    each leaf also lists the names of what's under it, so the planner knows what we have."""
    lines = []
    lv = leaves()
    have = {t["label"] for t in tags().values()}
    for node, k in counts().items():
        depth = node.count(">")
        line = f"{'  ' * depth}- {node.split(' > ')[-1]} ({k})"
        if labels and node in lv:
            names = sorted({x for x in lv[node]["labels"] if x in have})
            line += ": " + "; ".join(names)
        lines.append(line)
    return "\n".join(lines)
