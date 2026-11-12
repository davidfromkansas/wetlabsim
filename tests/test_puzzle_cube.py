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


def test_new_cube_starts_mixed_up():
    from playground.sim import PlaygroundSim
    sim = PlaygroundSim(stations=[])
    sim.placed = [W.Placed("c1", "rubiks_cube", (2.0, 2.0, 0.0))]
    sim.rebuild(sync=False)
    m, d = sim.m, sim.d
    core = m.body("obj_c1__core").id
    pieces = [b for b in range(m.nbody) if m.body_parentid[b] == core]
    L = np.array([d.geom_xpos[m.body_geomadr[b]] - d.xpos[core] for b in pieces]) / 0.019
    home = np.array([m.geom_pos[m.body_geomadr[b]] for b in pieces]) / 0.019
    assert np.abs(L - np.round(L)).max() < 1e-6                  # a real cube state, on the grid
    assert len({tuple(np.round(v)) for v in L}) == 26             # every piece in its own place
    assert sum(not np.allclose(a, b, atol=0.1) for a, b in zip(L, home)) >= 8   # mixed up


def test_a_hard_squeeze_doesnt_push_pieces_out_of_line():
    """Two pads squeeze the top layer's middle at 50 N (a robot gripper's force)."""
    world = mujoco.MjSpec.from_string(W._world_xml())
    W._add_item(world, W.Placed("c1", "rubiks_cube", (0, 0, 0)), W.catalog.meta("rubiks_cube"), False, set())
    for name, x, ax in (("a", 0.06, -1), ("b", -0.06, 1)):
        b = world.worldbody.add_body(name=f"pad{name}", pos=[x, 0, 0.038])
        j = b.add_joint(name=f"s{name}", type=mujoco.mjtJoint.mjJNT_SLIDE, axis=[ax, 0, 0])
        j.damping[0] = 5
        b.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.005, 0.012, 0.009], mass=0.05)
        world.add_actuator(name=f"m{name}", target=f"s{name}", trntype=mujoco.mjtTrn.mjTRN_JOINT)
    m = world.compile()
    d = mujoco.MjData(m)
    core = m.body("obj_c1__core").id
    pieces = [b for b in range(m.nbody) if m.body_parentid[b] == core]
    worst = 0.0
    for k in range(3000):
        d.ctrl[:] = 50.0 * min(1, k / 300)
        mujoco.mj_step(m, d)
        R = d.xmat[core].reshape(3, 3)
        L = np.array([R.T @ (d.geom_xpos[m.body_geomadr[b]] - d.xpos[core]) / 0.019 for b in pieces])
        worst = max(worst, float(np.abs(L - np.round(L)).max()))
    assert worst < 0.03


def test_3d_view_draws_the_cube_colours():
    from playground import scene3d as S3
    import struct
    m, _ = _cube()
    sc = S3.scene(m, 1)
    cube = [g for g in sc["geoms"] if g["body"] in
            {b for b in range(m.nbody) if m.body(b).name.startswith("obj_c1__")} and g["mesh"] >= 0]
    assert len(cube) == 26 and all(g["tex"] >= 0 for g in cube)
    nv, nf, has_uv = struct.unpack("<III", S3.mesh_bin(m, cube[0]["mesh"])[:12])
    assert has_uv == 1
