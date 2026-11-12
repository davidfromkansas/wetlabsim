"""The puzzle cube (MuJoCo's own 3x3x3 model, playground/assets/rubiks_cube): its faces turn when
one hand holds two layers and the other twists the third, the pieces land back on the grid, and a
rebuild keeps the cube as it was turned."""
import mujoco
import numpy as np

from playground import world as W


def _cube():
    m = W.build([W.Placed("c1", "rubiks_cube", (0.5, 0.0, 0.0))], [])
    return m, mujoco.MjData(m)


def test_cube_is_the_turning_model():
    m, _ = _cube()
    mine = [j for j in range(m.njnt) if m.joint(j).name.startswith("obj_c1__")]
    assert sum(m.jnt_type[j] == mujoco.mjtJoint.mjJNT_BALL for j in mine) == 20     # edges and corners
    assert sum(m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE for j in mine) == 6     # face centres
    assert m.nu == 0                                                                # no face motors
    assert abs(m.body_subtreemass[m.body("obj_c1").id] - 0.0685) < 1e-3


def _rotvec(Ra, Rb):
    q, v = np.zeros(4), np.zeros(3)
    mujoco.mju_mat2Quat(q, (Rb @ Ra.T).ravel())
    mujoco.mju_quat2Vel(v, q, 1.0)
    return v


def test_faces_turn_like_a_real_cube():
    m, d = _cube()
    core = m.body("obj_c1__core").id
    cub = [b for b in range(m.nbody) if m.body(b).name.startswith("obj_c1__") and b != core]

    def local(b):
        R = d.xmat[core].reshape(3, 3)
        return R.T @ (d.geom_xpos[m.body_geomadr[b]] - d.xpos[core]) / 0.019

    for _ in range(300):
        mujoco.mj_step(m, d)
    for axis, sign in [(2, 1), (0, 1), (1, -1)]:          # top, then right, then front
        near = [b for b in cub if local(b)[axis] > 0.5]
        R0 = {b: d.xmat[b].reshape(3, 3).copy() for b in cub}
        a0 = d.xmat[core].reshape(3, 3)[:, axis].copy()
        n = int(1.5 / m.opt.timestep)
        for k in range(n + 800):
            q, Rt = np.zeros(4), np.zeros(9)
            mujoco.mju_axisAngle2Quat(q, a0, sign * np.pi / 2 * min(1, k / n))
            mujoco.mju_quat2Mat(Rt, q)
            d.xfrc_applied[:] = 0
            for b in cub:        # a firm grip: the near layer to the turn, the rest held still
                tgt = Rt.reshape(3, 3) @ R0[b] if b in near else R0[b]
                d.xfrc_applied[b, 3:] = (_rotvec(d.xmat[b].reshape(3, 3), tgt) - 0.003 * d.cvel[b, :3]) / 9
            mujoco.mj_step(m, d)
        d.xfrc_applied[:] = 0
        for _ in range(300):
            mujoco.mj_step(m, d)
        L = np.array([local(b) for b in cub])
        assert np.abs(L - np.round(L)).max() < 0.05, "the pieces didn't land back on the grid"
        moved = [b for b in near if not np.allclose(local(b), np.round(local(b)), atol=0.05)]
        assert not moved


def test_turned_cube_kept_across_rebuild():
    from playground.sim import PlaygroundSim
    sim = PlaygroundSim(stations=[])
    sim.placed = [W.Placed("c1", "rubiks_cube", (2.0, 2.0, 0.0))]
    sim.rebuild(sync=False)
    a = sim.m.jnt_qposadr[sim.m.joint("obj_c1__pX_pY_pZ").id]
    q = np.zeros(4)
    mujoco.mju_axisAngle2Quat(q, np.array([0, 0, 1.0]), np.pi / 2)
    sim.d.qpos[a:a + 4] = q
    mujoco.mj_forward(sim.m, sim.d)
    sim.rebuild()
    a = sim.m.jnt_qposadr[sim.m.joint("obj_c1__pX_pY_pZ").id]
    assert np.allclose(sim.d.qpos[a:a + 4], q, atol=1e-6)
