"""Box select in the playground: copying or removing several objects at once."""
import pytest

from playground.sim import PlaygroundSim, RobotError


@pytest.fixture(scope="module")
def lab():
    sim = PlaygroundSim(stations=[])
    uid = sim.add_station("franka", (0, 0), 0.0, "table")
    sim.placed = []
    sim.rebuild()
    return sim, sim.station(uid)


def _obj(sim, uid):
    return next(o for o in sim.scene_info()["objects"] if o["uid"] == uid)


def test_duplicate_keeps_layout_height_and_turn(lab):
    sim, st = lab
    a = sim.add("rubiks_cube", (st.pos[0] + 0.55, st.pos[1] - 0.15, st.top))
    b = sim.add("mug", (st.pos[0] + 0.55, st.pos[1] - 0.05, st.top))
    sim.orient(b, axis="z", degrees=45)
    before = {u: _obj(sim, u) for u in (a, b)}
    new = sim.duplicate_many([a, b])
    assert len(new) == 2 and set(new).isdisjoint({a, b})
    after = [_obj(sim, u) for u in new]
    # every copy rests at its original's height, turned the same way, and the pair keeps its spacing
    for o, u in zip(after, (a, b)):
        assert o["item"] == before[u]["item"]
        assert o["pos"][2] == pytest.approx(before[u]["pos"][2], abs=0.01)
        assert o["euler"][2] == pytest.approx(before[u]["euler"][2], abs=1)
    gap = [after[1]["mid"][i] - after[0]["mid"][i] for i in (0, 1)]
    orig = [before[b]["mid"][i] - before[a]["mid"][i] for i in (0, 1)]
    assert gap == pytest.approx(orig, abs=0.005)
    # the copies sit beside the originals, not on them
    assert max(abs(after[0]["mid"][i] - before[a]["mid"][i]) for i in (0, 1)) > 0.05
    sim.remove_many([a, b] + new)


def test_remove_many_in_one_go(lab):
    sim, st = lab
    uids = [sim.add("rubiks_cube", (st.pos[0] + 0.5, st.pos[1] + y, st.top)) for y in (-0.2, 0.0, 0.2)]
    ver = sim._model_ver
    assert sim.remove_many(uids[:2] + ["nope"]) == 2
    assert sim._model_ver == ver + 1                       # one rebuild, not one per object
    assert [o["uid"] for o in sim.scene_info()["objects"]] == [uids[2]]
    with pytest.raises(RobotError):
        sim.remove_many(["nope"])
    sim.remove_many([uids[2]])
