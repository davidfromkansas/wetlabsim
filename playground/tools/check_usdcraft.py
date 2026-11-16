"""Drop test for every built USDCraft library item: it is placed 2 cm above the floor and left
for 3 s of physics. It passes when nothing is NaN, no part falls through the floor, it doesn't
wander off (more than 30 cm), its main body has come to rest, and it doesn't make the physics too slow.

    python -m playground.tools.check_usdcraft [--jobs 4] [ids ...]

Writes build/usdcraft_check.json ({id: {"ok", "why", "ms_per_step", ...}}).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
from concurrent.futures import ProcessPoolExecutor

SLOW_MS = 2.0        # one physics step of the item on its own may take at most this long


def check(item: str) -> dict:
    import mujoco
    import numpy as np

    from playground import world as W
    try:
        m = W.build([W.Placed("a", item, (0, 0, 0.02))], [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"doesn't load: {e}"[:200]}
    d = mujoco.MjData(m)
    bodies = [b for b in range(m.nbody) if m.body(b).name == "obj_a" or m.body(b).name.startswith("obj_a__")]
    root = m.body("obj_a").id
    n = int(3.0 / m.opt.timestep)
    t = time.perf_counter()
    for _ in range(n):
        mujoco.mj_step(m, d)
    ms = (time.perf_counter() - t) / n * 1000
    res = {"ms_per_step": round(ms, 3), "bodies": len(bodies)}
    if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all():
        return {**res, "ok": False, "why": "physics blew up"}
    low = min(d.xpos[b][2] for b in bodies)
    if low < -0.08:
        return {**res, "ok": False, "why": "a part fell through the floor"}
    moved = float(np.linalg.norm(d.xpos[root][:2] - m.body_pos[root][:2]))
    if moved > 0.3:
        return {**res, "ok": False, "why": f"wandered off {moved:.2f} m"}
    speed = float(np.linalg.norm(d.cvel[root][3:]))     # its moving parts may still swing or spin
    if speed > 0.2:
        return {**res, "ok": False, "why": f"still moving at {speed:.2f} m/s"}
    if ms > SLOW_MS:
        return {**res, "ok": False, "why": f"too slow ({ms:.1f} ms a step)"}
    return {**res, "ok": True, "why": ""}


def main(argv=None):
    from playground import catalog
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default="build/usdcraft_check.json")
    a = ap.parse_args(argv)
    ids = a.ids or [u["id"] for u in catalog.USDCRAFT if (catalog.ASSETS / u["id"] / "asset.json").exists()]
    out = pathlib.Path(a.out)
    res = json.loads(out.read_text()) if out.exists() else {}
    with ProcessPoolExecutor(a.jobs) as ex:
        for i, r in zip(ids, ex.map(check, ids)):
            res[i] = r
            print(f"{i:40s} {'ok' if r['ok'] else 'FAIL ' + r['why']}  {r.get('ms_per_step', '')}", flush=True)
            out.write_text(json.dumps(res, indent=1))
    bad = [i for i in ids if not res[i]["ok"]]
    print(f"{len(ids) - len(bad)} passed, {len(bad)} failed")


if __name__ == "__main__":
    main()
