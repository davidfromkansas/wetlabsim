"""Solve each Menagerie arm's starting pose (wetlabsim/menagerie_arms.py READY): the gripper
straight down in front of the base, fingers closing along the base y axis.

    python -m playground.tools.solve_menagerie_ready [robot ...]

Prints the READY table to paste into menagerie_arms.py. Ahead of the base by half the arm's
reach (15 to 55 cm), above the mount by 15% of it (6 to 15 cm).
"""
from __future__ import annotations

import sys
import warnings

import mujoco
import numpy as np

from wetlabsim import menagerie_arms as MA
from wetlabsim import scene as S


def model(robot):
    w = mujoco.MjSpec.from_string(S._world_xml(S.ROBOTS[robot]["mount_quat"]))
    S.add_robot(w, robot)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return w.compile()


def target(robot):
    if "ready_at" in MA.ARMS[robot]:
        return MA.ARMS[robot]["ready_at"]
    r = MA.ARMS[robot]["reach_mm"] / 1000
    return float(np.clip(0.5 * r, 0.15, 0.55)), float(np.clip(0.15 * r, 0.06, 0.15))


def solve(robot, seeds=120, at=None):
    m = model(robot)
    d = mujoco.MjData(m)
    P = S.profile_for(robot)
    qa = np.array([m.joint(j).qposadr[0] for j in P["arm_joints"]])
    da = np.array([m.joint(j).dofadr[0] for j in P["arm_joints"]])
    jid = [m.joint(j).id for j in P["arm_joints"]]
    lim = m.jnt_limited[jid].astype(bool)
    lo = np.where(lim, m.jnt_range[jid, 0], -np.pi)
    hi = np.where(lim, m.jnt_range[jid, 1], np.pi)
    site = m.site(P["tcp_site"]).id
    base = m.body(P.get("frame_body") or P["base_body"]).id
    mujoco.mj_kinematics(m, d)
    bp, bR = d.xpos[base].copy(), d.xmat[base].reshape(3, 3).copy()
    x, h = at or target(robot)
    pw = bp + bR @ np.array([x, 0.0, h])
    # straight down, the fingers closing along the base y axis: [pi, 0, 0] or [0, pi, 0]
    goals = [bR @ np.diag([1.0, -1.0, -1.0]), bR @ np.diag([-1.0, 1.0, -1.0])]
    home = np.zeros(len(qa))
    if m.nkey:
        home = m.key_qpos[0][qa]
    jacp, jacr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
    rng = np.random.default_rng(1)
    best = None
    five = len(qa) < 6
    for k in range(seeds):
        Rg = goals[k % 2]
        q = np.clip(home if k < 2 else home + rng.normal(0, 0.5, len(qa)) if k < seeds // 2
                    else rng.uniform(lo, hi), lo, hi)
        for _ in range(400):
            d.qpos[qa] = q
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            p, R = d.site_xpos[site], d.site_xmat[site].reshape(3, 3)
            ep = pw - p
            qe = np.zeros(4)
            mujoco.mju_mat2Quat(qe, (Rg @ R.T).flatten())
            er = np.zeros(3)
            mujoco.mju_quat2Vel(er, qe, 1.0)
            if np.linalg.norm(ep) < 1e-4 and np.linalg.norm(er) < 1e-3:
                break
            mujoco.mj_jacSite(m, d, jacp, jacr, site)
            J = np.vstack([jacp[:, da], jacr[:, da]])
            dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), np.concatenate([ep, er]))
            n = np.linalg.norm(dq)
            if n > 0.2:
                dq *= 0.2 / n
            q = np.clip(q + dq, lo, hi)
        if np.linalg.norm(ep) < 1e-3 and np.linalg.norm(er) < 5e-3:
            # near the arm's home pose, and clear of the joint limits
            cost = np.sum((q - home) ** 2) + 20 * np.sum(np.maximum(0, 0.3 - np.minimum(q - lo, hi - q)) ** 2)
            if best is None or cost < best[0]:
                best = (cost, q.copy())
    return None if best is None else best[1]


if __name__ == "__main__":
    for r in sys.argv[1:] or list(MA.ARMS):
        q = solve(r)
        print(f'    "{r}": {None if q is None else [round(float(v), 4) for v in q]},  # {target(r)}', flush=True)
