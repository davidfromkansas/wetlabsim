"""Tron-style glow for the free-play floor, drawn only into the main (audience) view.

The lines are extra shapes added to the rendered picture, not objects in the physics, so the
robot can't touch them and the AI's cameras never see them. Three effects, all from the clock:
- the 50 cm grid lines breathe softly;
- rings of light ripple outwards from the table;
- a few bright streaks race along the grid lines, like light cycles.
"""
from __future__ import annotations

import math

import mujoco
import numpy as np

CYAN = np.array([0.0, 0.85, 1.0])
STEP = 0.5          # grid spacing of the glowing lines (m)
REACH = 4.0         # how far from the centre they're drawn (m)
SEG = 0.5           # lines are drawn in pieces so the ripple can light them one piece at a time
Z = 0.0015          # just above the floor
WIDTH = 0.012       # line thickness (m)
RIPPLE_SPEED = 1.1  # m/s
RIPPLE_EVERY = 4.0  # m between rings
STREAKS = 10
STREAK_SPEED = 1.6  # m/s
TRAIL = 6           # pieces in each streak's fading tail

_EYE = np.eye(3).flatten()


def _add(sc, pos, half_x, half_y, alpha):
    if sc.ngeom >= sc.maxgeom or alpha < 0.02:
        return
    g = sc.geoms[sc.ngeom]
    mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_BOX, np.array([half_x, half_y, 0.0005]),
                        np.array(pos, float), _EYE, np.array([*CYAN, min(alpha, 1.0)], np.float32))
    g.emission = 0.9
    sc.ngeom += 1


def _hash(i: int, k: int) -> float:
    """A repeatable pseudo-random number in [0, 1) for streak i on its k-th lap."""
    x = math.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return x - math.floor(x)


def draw(sc, t: float):
    lines = np.arange(-REACH, REACH + 1e-9, STEP)
    pieces = np.arange(-REACH + SEG / 2, REACH, SEG)
    breathe = 0.25 + 0.1 * math.sin(t * 1.6)
    front = (t * RIPPLE_SPEED) % RIPPLE_EVERY
    for c in lines:
        for p in pieces:
            for x, y, hx, hy in ((c, p, WIDTH / 2, SEG / 2), (p, c, SEG / 2, WIDTH / 2)):
                r = math.hypot(x, y)
                # distance to the nearest ring (rings every RIPPLE_EVERY metres, moving out)
                d = (r - front) % RIPPLE_EVERY
                d = min(d, RIPPLE_EVERY - d)
                ring = math.exp(-(d / 0.35) ** 2)
                fade = max(0.0, 1.0 - r / REACH)
                _add(sc, (x, y, Z), hx, hy, (breathe + 1.0 * ring) * fade)
    span = 2 * REACH
    for i in range(STREAKS):
        travelled = t * STREAK_SPEED * (0.7 + 0.6 * _hash(i, 0)) + span * _hash(i, 1)
        lap = int(travelled // span)
        head = travelled % span - REACH
        line = lines[int(_hash(i, lap + 7) * len(lines))]
        along_x = _hash(i, lap + 3) < 0.5
        sign = 1 if _hash(i, lap + 5) < 0.5 else -1
        for k in range(TRAIL):
            s = sign * (head - k * 0.06)
            if abs(s) > REACH:
                continue
            fade = (1 - k / TRAIL) * max(0.0, 1.0 - abs(s) / REACH * 0.6)
            pos = (s, line, Z + 0.0002) if along_x else (line, s, Z + 0.0002)
            hx, hy = (0.035, WIDTH) if along_x else (WIDTH, 0.035)
            _add(sc, pos, hx, hy, fade)
