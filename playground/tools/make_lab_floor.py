"""Draws the playground's floor texture: speckled vinyl composition tile (VCT), the 12-inch
tiles most university wet labs have, laid in a quarter-turn pattern with faint seams.

    python -m playground.tools.make_lab_floor        # writes playground/textures/lab_floor.png

The picture is a 4 x 4 patch of tiles (1.22 m square) that repeats without a visible edge.
It is made from a fixed seed, so running it again gives the same file.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "textures" / "lab_floor.png"
TILES = 4               # tiles per side in the picture
TILE_PX = 256           # pixels per tile (about 1.2 mm a pixel)
SS = 2                  # drawn at twice the size, then scaled down for soft chip edges
BASE = (226, 226, 220)  # the tile's cool off-white
CHIPS = [               # (colour, share of chips)
    ((120, 122, 126), 0.14),  # charcoal
    ((172, 174, 176), 0.34),  # mid grey
    ((204, 196, 180), 0.30),  # tan
    ((242, 242, 238), 0.22),  # white
]


def make(seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    n = TILES * TILE_PX * SS
    t = TILE_PX * SS
    img = Image.new("RGB", (n, n), BASE)
    d = ImageDraw.Draw(img)
    cols = [c for c, _ in CHIPS]
    share = np.array([s for _, s in CHIPS])
    for ty in range(TILES):
        for tx in range(TILES):
            x0, y0 = tx * t, ty * t
            # each tile is a slightly different batch, and laid at a quarter turn to its neighbours
            shade = rng.normal(0, 2.2)
            d.rectangle([x0, y0, x0 + t - 1, y0 + t - 1], fill=tuple(int(c + shade) for c in BASE))
            angle = (0 if (tx + ty) % 2 == 0 else math.pi / 2) + rng.normal(0, 0.15)
            for _ in range(2600):
                cx, cy = x0 + rng.uniform(0, t), y0 + rng.uniform(0, t)
                L = rng.lognormal(math.log(1.5 * SS), 0.4)          # chips are streaked one way
                W = L * rng.uniform(0.3, 0.6)
                a = angle + rng.normal(0, 0.35)
                ca, sa = math.cos(a), math.sin(a)
                pts = [(cx + L * ca * math.cos(k) - W * sa * math.sin(k),
                        cy + L * sa * math.cos(k) + W * ca * math.sin(k))
                       for k in np.linspace(0, 2 * math.pi, 9)[:-1]]
                # keep chips inside their own tile, so seams stay straight
                pts = [(min(max(px, x0 + 1), x0 + t - 2), min(max(py, y0 + 1), y0 + t - 2)) for px, py in pts]
                c = np.array(cols[rng.choice(len(cols), p=share)]) + rng.normal(0, 6) + shade
                d.polygon(pts, fill=tuple(int(v) for v in np.clip(c, 0, 255)))
    img = img.filter(ImageFilter.GaussianBlur(0.6 * SS)).resize((TILES * TILE_PX,) * 2, Image.LANCZOS)
    a = np.asarray(img).astype(np.float32)
    # soft mottling that wraps around (whole waves across the picture), as worn wax gives
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]] / a.shape[0] * 2 * math.pi
    mottle = sum(rng.uniform(0.6, 1.2) * np.sin(fx * xx + fy * yy + rng.uniform(0, 6.3))
                 for fx, fy in rng.integers(-3, 4, size=(6, 2)))
    a += mottle[..., None] * 0.9
    # faint seams on each tile's top and left edge (so the patch repeats with no double line)
    for k in range(TILES):
        a[k * TILE_PX, :, :] *= 0.86
        a[:, k * TILE_PX, :] *= 0.86
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im = make()
    im.save(OUT, optimize=True)
    print(OUT, im.size, "mean", np.asarray(im).reshape(-1, 3).mean(0) / 255)
