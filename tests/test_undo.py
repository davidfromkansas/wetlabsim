"""Undo / Redo in the scene menu bar: the user's own scene edits go back and forward again."""
from playground import server as S
from playground.sim import PlaygroundSim


def _layout(sim):
    return [(st.uid, st.robot, tuple(round(float(v), 3) for v in st.pos), round(float(st.yaw), 3))
            for st in sim.stations]


def test_scene_state_round_trip():
    sim = PlaygroundSim(stations=[])
    a = sim.add_station("franka", (0, 0), 0.0, "table")
    before, lay0, n0 = sim.scene_state(), _layout(sim), len(sim.placed)
    b = sim.add_station("ur5e", (3.0, 0), 0.0, "table")
    sim.swap_robot(a, "ur5e")
    sim.move_station(a, (0, 1.5), 0.5)
    after, lay1 = sim.scene_state(), _layout(sim)
    # back: one Franka where it was, the second station gone, its arm too
    sim.restore_scene(before)
    assert _layout(sim) == lay0 and len(sim.placed) == n0
    assert set(sim.arms) == {a} and sim.arms[a].robot == "franka"
    assert sim.active_station == a
    # forward again: both stations as they were after the edits
    sim.restore_scene(after)
    assert _layout(sim) == lay1 and set(sim.arms) == {a, b} and sim.arms[a].robot == "ur5e"
    # the model really changed: the restored robot is in it
    assert sim.arms[b].bodies and max(sim.arms[b].bodies) < sim.m.nbody


def test_history_keeps_last_edits_and_a_new_edit_forgets_redo():
    sess = S.Session.__new__(S.Session)
    sess.undo, sess.redo = [], []
    for i in range(S.Session.UNDO_MAX + 5):
        sess.push_undo({"n": i})
    assert len(sess.undo) == S.Session.UNDO_MAX and sess.undo[-1] == {"n": S.Session.UNDO_MAX + 4}
    sess.redo = [{"n": "x"}]
    sess.push_undo({"n": "new"})
    assert sess.redo == []
    sess.forget_undo()
    assert sess.undo == [] and sess.redo == []
