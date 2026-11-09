"""In LIBERO's stack: for every exported task, make test scenes where each goal predicate may
or may not hold (the object moved onto / into its target at various offsets, joints set
across their range), let them settle, and record qpos plus LIBERO's verdict on each goal
predicate. Our checker then has to agree on the same qpos (tests/test_libero.py).

    <LIBERO venv>/bin/python libero_crosscheck.py <export dir> playground/libero_assets/crosscheck
"""
import json
import pathlib
import sys

import numpy as np

from libero.libero import get_libero_path
from libero.libero.envs import OffScreenRenderEnv

EXPORT = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
rng = np.random.default_rng(0)

ONLY = sys.argv[3] if len(sys.argv) > 3 else None
for meta_path in sorted(EXPORT.glob("*/*/meta.json")):
    if ONLY and f"{meta_path.parent.parent.name}/{meta_path.parent.name}" != ONLY:
        continue
    meta = json.loads(meta_path.read_text())
    bddl = None
    for p in pathlib.Path(get_libero_path("bddl_files")).glob(f"{meta['suite']}/{meta['name']}.bddl"):
        bddl = p
    env = OffScreenRenderEnv(bddl_file_name=str(bddl), camera_heights=64, camera_widths=64)
    env.seed(0)
    env.reset()
    e = env.env
    sim = e.sim
    init = np.load(meta_path.parent / "init_states.npy")
    cases = []
    for trial in range(24):
        env.set_init_state(init[trial % len(init)])
        for g in meta["goal"]:
            p = g[0].lower()
            if p in ("on", "in"):
                a, b = g[1], g[2]
                if b in e.object_sites_dict:
                    for j in e.object_sites_dict[b].joints or []:   # a drawer: open it first
                        lo, hi = sim.model.jnt_range[sim.model.joint_name2id(j)]
                        sim.data.qpos[sim.model.get_joint_qpos_addr(j)] = lo if trial % 2 else hi
                    sim.forward()
                    tgt = sim.data.get_site_xpos(b).copy()
                else:
                    tgt = sim.data.body_xpos[e.obj_body_id[b]].copy()
                jn = e.objects_dict[a].joints[-1]
                adr = sim.model.get_joint_qpos_addr(jn)[0]
                off = rng.normal(0, [0.03, 0.03, 0.0]) * (trial % 3 > 0)
                q = sim.data.qpos.copy()
                q[adr:adr + 3] = tgt + off + np.array([0, 0, 0.03 + 0.05 * (trial % 4)])
                sim.data.qpos[:] = q
                sim.forward()
            else:
                name = g[1]
                joints = (e.object_sites_dict[name].joints if name in e.object_sites_dict
                          else e.get_object(name).joints)
                for j in joints:
                    adr = sim.model.get_joint_qpos_addr(j)
                    lo, hi = sim.model.jnt_range[sim.model.joint_name2id(j)]
                    sim.data.qpos[adr] = rng.uniform(lo, hi) if trial % 2 else rng.choice([lo, hi])
                sim.forward()
        for _ in range(int(rng.integers(0, 400))):
            sim.step()
        sim.forward()
        verdict = [bool(e._eval_predicate(g)) for g in meta["goal"]]
        cases.append({"qpos": sim.data.qpos.tolist(), "verdict": verdict})
    d = OUT / meta["suite"] / meta_path.parent.name
    d.mkdir(parents=True, exist_ok=True)
    (d / "cases.json").write_text(json.dumps(cases))
    print(meta["suite"], meta_path.parent.name, "true per predicate:",
          np.sum([c["verdict"] for c in cases], axis=0).tolist(), flush=True)
    env.close()
