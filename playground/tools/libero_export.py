"""Run inside LIBERO's own stack (robosuite 1.4, mujoco 2.3.7). For every task of the given
suites, build LIBERO's env and dump: the compiled model XML, the task's goal and language,
each object's root body / contact geoms / joints, each region site, articulation thresholds
(probed from LIBERO's own is_open/is_close/turn_on/turn_off), the qpos layout, the 50 init
states, the robot base pose and the agentview camera.

    LIBERO_CONFIG_PATH=<cfg> PYTHONPATH=<LIBERO repo> MUJOCO_GL=egl \
        <LIBERO venv>/bin/python libero_export.py <out dir> libero_goal,libero_spatial,libero_object,libero_10

Then: python -m playground.tools.import_libero <out dir>
"""
import json
import pathlib
import sys

import numpy as np

from libero.libero import benchmark, get_libero_path
from libero.libero.envs import OffScreenRenderEnv

OUT = pathlib.Path(sys.argv[1])
SUITES = sys.argv[2].split(",")
ONLY = int(sys.argv[3]) if len(sys.argv) > 3 else None

GRID = np.round(np.arange(-3.2, 3.2, 0.0005), 4)


def intervals(fn):
    vals = []
    for q in GRID:
        try:
            vals.append(bool(fn(q)))
        except Exception:
            return None
    out, start = [], None
    for q, v in zip(GRID, vals):
        if v and start is None:
            start = q
        if not v and start is not None:
            out.append([float(start), float(q)]); start = None
    if start is not None:
        out.append([float(start), 99.0])
    if out and out[0][0] == GRID[0]:
        out[0][0] = -99.0
    return out


def articulation(obj):
    res = {}
    for name in ("is_open", "is_close", "turn_on", "turn_off"):
        f = getattr(obj, name, None)
        if f is None:
            continue
        try:
            f(0.0)
        except NotImplementedError:
            continue
        except Exception:
            pass
        iv = intervals(f)
        if iv is not None:
            res[name] = iv
    return res


bm = benchmark.get_benchmark_dict()
for suite in SUITES:
    s = bm[suite]()
    for i in range(s.n_tasks):
        if ONLY is not None and i != ONLY:
            continue
        t = s.get_task(i)
        bddl = pathlib.Path(get_libero_path("bddl_files")) / t.problem_folder / t.bddl_file
        env = OffScreenRenderEnv(bddl_file_name=str(bddl), camera_heights=64, camera_widths=64)
        env.seed(0)
        env.reset()
        e = env.env
        m = e.sim.model
        import torch
        init = torch.load(pathlib.Path(get_libero_path('init_states')) / t.problem_folder / t.init_states_file, weights_only=False)
        objs = {}
        for kind, dct in (("object", e.objects_dict), ("fixture", e.fixtures_dict)):
            for n, o in dct.items():
                objs[n] = {"kind": kind, "category": o.category_name, "root_body": o.root_body,
                           "contact_geoms": list(o.contact_geoms), "joints": list(o.joints),
                           "articulation": articulation(o)}
        sites = {}
        for n, so in e.object_sites_dict.items():
            sites[n] = {"parent": so.parent_name, "joints": list(so.joints or []),
                        "size": [float(x) for x in np.asarray(so.size, dtype=float).reshape(-1)],
                        "under": hasattr(so, "under"), "class": type(so).__name__}
        joints = []
        for j in range(m.njnt):
            joints.append({"name": m.joint_id2name(j), "type": int(m.jnt_type[j]), "qposadr": int(m.jnt_qposadr[j])})
        bid = m.body_name2id("robot0_base")
        cid = m.camera_name2id("agentview")
        meta = {
            "suite": suite, "index": i, "name": t.name, "language": t.language,
            "problem": e.parsed_problem["problem_name"], "goal": e.parsed_problem["goal_state"],
            "obj_of_interest": e.obj_of_interest, "objects": objs, "sites": sites, "joints": joints,
            "nq": int(m.nq), "nv": int(m.nv),
            "robot_base": {"pos": e.sim.data.body_xpos[bid].tolist(), "quat": e.sim.data.body_xquat[bid].tolist()},
            "agentview": {"pos": m.cam_pos[cid].tolist(), "quat": m.cam_quat[cid].tolist(), "fovy": float(m.cam_fovy[cid])},
        }
        d = OUT / suite / f"{i:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.xml").write_text(m.get_xml())
        (d / "meta.json").write_text(json.dumps(meta, indent=1))
        np.save(d / "init_states.npy", np.asarray(init))
        # LIBERO's own verdict on each start state, for checking our checker later
        oks = []
        for st in init:
            env.set_init_state(st)
            oks.append(bool(e._check_success()))
        (d / "start_success.json").write_text(json.dumps(oks))
        print(suite, i, t.name, "nq", m.nq, "starts already done:", sum(oks), flush=True)
        env.close()
