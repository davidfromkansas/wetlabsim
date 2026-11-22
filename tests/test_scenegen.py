"""Describe a scene (playground/scenegen.py): the model's pick is kept to real robots and
objects and our limits, and the build puts every station, piece of furniture and object down
with the drop check, on free floor clear of what was there, and Undo takes it all away."""
import time

from playground import scenegen as G
from playground.sim import PlaygroundSim
from playground import world as W


class _Sess:
    def __init__(self):
        self.unsent = {}


def _build(sim, pick):
    b = G.Build(sim, _Sess(), "kitchen", pick, "claude-fable-5-2", False)
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 120:
        time.sleep(0.2)
    return b


def test_pick_is_kept_to_the_catalog_and_limits():
    p = G.clean_pick({"title": "x", "robots": [{"robot": "franka", "count": 3}, {"robot": "ur5e", "count": 3},
                                               {"robot": "spot", "count": 1}],
                      "items": [{"id": "mug", "count": 99}, {"id": "unicorn", "count": 1}],
                      "missing": [{"name": "bread", "instead": "nope"}]})
    assert p["robots"] == [{"robot": "franka", "count": 3}, {"robot": "ur5e", "count": 1}]
    assert p["items"] == [{"id": "mug", "count": G.MAX_EACH}]
    assert p["missing"] == [{"name": "bread", "instead": ""}]


def test_parse_json_from_words():
    assert G.parse_json('Here it is:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert G.parse_json('ok {"a": {"b": 2}} done') == {"a": {"b": 2}}


def test_build_on_free_floor_then_undo(monkeypatch):
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    sim = PlaygroundSim(stations=[])
    first = sim.add_station("franka", (0, 0), 0.0, "table")
    sim.pause()
    before = len(sim.placed)
    b = _build(sim, G.clean_pick(G.fake_pick("")))
    st = b.status()
    assert st["phase"] == "done", st
    assert st["counts"]["robots"] == [1, 1] and st["counts"]["furniture"][0] == 3
    assert st["counts"]["objects"][0] == st["counts"]["objects"][1] and not st["skipped"]
    new = sim.station(st["stations"][0])
    old = sim.station(first)
    # the new table stands clear of the old one
    ox0, oy0, ox1, oy1 = G._station_rect(old.kind, old.robot, *old.pos, old.yaw)
    nx0, ny0, nx1, ny1 = G._station_rect(new.kind, new.robot, *new.pos, new.yaw)
    assert not G._hit((ox0, oy0, ox1, oy1), (nx0, ny0, nx1, ny1), 0.3)
    assert new.name == "Kitchen breakfast"
    # the small objects are on the new robot's table, none at its base
    on = sim._on_table(new)
    assert len(on) == st["counts"]["objects"][0]
    assert not any(new.near_base(p.pos[0], p.pos[1]) for p in on)
    assert sim.station(first) is not None          # nothing that was there is removed
    assert b.undo() is None
    assert [s.uid for s in sim.stations] == [first] and len(sim.placed) == before


def test_stop_keeps_what_was_placed(monkeypatch):
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    sim = PlaygroundSim(stations=[])
    sim.pause()
    b = G.Build(sim, _Sess(), "kitchen", G.clean_pick(G.fake_pick("")), "claude-fable-5-2", False)
    b.stop = True
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 30:
        time.sleep(0.1)
    assert b.status()["phase"] == "stopped" and sim.stations == []


def test_chatgpt_sign_in_asks_through_codex(monkeypatch, tmp_path):
    """An OpenAI connection made by ChatGPT sign-in isn't an API key: the question goes to
    `codex exec` with the login file, and a login Codex refreshed is kept."""
    import json
    import os
    import stat
    fake = tmp_path / "codex"
    fake.write_text("#!/usr/bin/env python3\n"
                    "import os, sys, json\n"
                    "a = sys.argv\n"
                    "assert a[1] == 'exec' and 'forced_login_method=\"chatgpt\"' in a\n"
                    "home = os.environ['CODEX_HOME']\n"
                    "assert json.load(open(os.path.join(home, 'auth.json')))['tok'] == 'old'\n"
                    "assert 'OPENAI_API_KEY' not in os.environ\n"
                    "open(a[a.index('--output-last-message') + 1], 'w').write('Sure: {\"title\": \"T\", \"robots\": [{\"robot\": \"ur5e\", \"count\": 1}], \"items\": []}')\n"
                    "open(os.path.join(home, 'auth.json'), 'w').write(json.dumps({'tok': 'new'}))\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")
    monkeypatch.delenv("WETLAB_SCENEGEN_FAKE", raising=False)
    kept = {}
    monkeypatch.setattr(G.ACCT, "credential_for", lambda agent: ("chatgpt", json.dumps({"tok": "old"}))
                        if agent == "codex" else ("key", ""))
    monkeypatch.setattr(G.ACCT, "update_login", lambda prov, login: kept.update({prov: login}))
    monkeypatch.setattr(G, "WHERE", "local")
    out = G.pick("a robot", "gpt-6-astra", True)
    assert out["robots"] == [{"robot": "ur5e", "count": 1}]
    assert json.loads(kept["openai"]) == {"tok": "new"}


def test_things_the_library_lacks_are_kept_to_make():
    """The pick's "make" list: kept to MAX_MADE things (the rest left out, and said so), and a
    name that is a library object's label becomes that object (the library always wins)."""
    lib = G._catalog_rows()
    raw = {"title": "x", "robots": [{"robot": "franka", "count": 1}], "items": [],
           "make": [{"name": f"Thing {k}", "count": 2, "kind": "furniture" if k == 0 else "object",
                     "size": [0.2, 0.1, 0.3], "looks": "red", "moves": "none"} for k in range(G.MAX_MADE + 3)]}
    if lib:
        raw["make"].insert(0, {"name": lib[0]["label"], "count": 1})
    p = G.clean_pick(raw)
    assert len(p["make"]) == G.MAX_MADE
    assert p["make"][0] == {"name": "Thing 0", "count": 2, "kind": "furniture", "size": [0.2, 0.1, 0.3],
                            "looks": "red", "moves": "none"}
    assert [m["name"] for m in p["missing"]] == [f"Thing {k}" for k in range(G.MAX_MADE, G.MAX_MADE + 3)]
    if lib:
        assert p["items"] == [{"id": lib[0]["id"], "count": 1}]
    assert G.clean_pick(p)["make"] == p["make"]          # the checked list comes back unchanged


def test_build_makes_what_the_library_lacks(monkeypatch):
    """Things to make are built by the model first, physics-tested (aimade), then laid out and
    placed like library objects; Undo takes them away too."""
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    sim = PlaygroundSim(stations=[])
    sim.pause()
    pick = G.clean_pick({"title": "Bakery", "robots": [{"robot": "franka", "count": 1}], "items": [],
                         "make": [{"name": "Loaf of bread", "count": 2, "kind": "object", "size": [0.2, 0.1, 0.08]},
                                  {"name": "Bread rack", "count": 1, "kind": "furniture", "size": [0.8, 0.4, 1.2]}]})
    b = G.Build(sim, _Sess(), "a bakery", pick, "claude-fable-5-2", False)
    assert b.status()["phase"] == "make" and b.status()["counts"]["objects"][1] == 2
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 120:
        time.sleep(0.2)
    st = b.status()
    assert st["phase"] == "done", st
    assert st["counts"]["make"] == [2, 2] and not st["skipped"]
    assert [(m["name"], m["state"]) for m in st["making"]] == [("Loaf of bread", "done"), ("Bread rack", "done")]
    asks = [a for a in b.answers if a.startswith("===== asked: Make this object")]
    assert len(asks) == 2                                 # each object in a request of its own
    assert st["counts"]["objects"] == [2, 2] and st["counts"]["furniture"] == [1, 1]
    made = [p for p in sim.placed if p.item.startswith("ai_")]
    assert len(made) == 3
    assert {G.catalog.item(p.item)["label"] for p in made} == {"Loaf of bread", "Bread rack"}
    assert b.undo() is None and sim.placed == []


def test_straight_from_words_picks_then_builds_with_outlines(monkeypatch):
    """No check-list step: the build picks robots and objects itself, then outlines every planned
    thing on the floor (one by one, even when the layout arrives as one answer), and marks each
    as it lands (ok) or doesn't fit (bad)."""
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    sim = PlaygroundSim(stations=[])
    sim.pause()
    b = G.Build(sim, _Sess(), "a robot making breakfast", None, "claude-fable-5-2", False)
    assert b.status()["phase"] == "pick" and b.status()["active"]
    seen_zone = []
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 120:
        if sim.zone:
            seen_zone.append(len(sim.zone))
        time.sleep(0.05)
    st = b.status()
    assert st["phase"] == "done", st
    assert st["picked"]["robots"] and st["stations"]
    assert st["items"] and all(it["state"] in ("ok", "bad") for it in st["items"])
    assert sum(it["state"] == "ok" for it in st["items"]) == st["counts"]["robots"][0] + st["counts"]["furniture"][0] + st["counts"]["objects"][0]
    assert any(it["at"] for it in st["items"])          # robots and furniture have floor spots
    assert seen_zone and max(seen_zone) > 2              # outlines were drawn while it built
    assert sim.zone == []                                # and are gone at the end


def test_recent_prompts_kept_locally(monkeypatch, tmp_path):
    monkeypatch.setenv("WETLAB_ACCOUNT_FILE", str(tmp_path / "account.json"))
    for k in range(12):
        G.remember_prompt(f"scene {k}", False)
    got = G.recent_prompts(False)
    assert got[0] == "scene 11" and len(got) == G.RECENT_KEEP
    G.remember_prompt("scene 5", False)
    assert G.recent_prompts(False)[0] == "scene 5" and G.recent_prompts(False).count("scene 5") == 1
    assert G.recent_prompts(True) == []                  # the public site without sign-in keeps none


def test_robot_without_a_table_works_at_the_scenes_furniture(monkeypatch):
    """A described scene need not be a robot arm on its own packing table: a "bare" station
    stands the robot beside the scene's furniture (a workbench) and its task things go on it."""
    import math
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    pk = G.clean_pick({"title": "Bench", "robots": [{"robot": "franka", "count": 1}],
                       "items": [{"id": "workbench", "count": 1}, {"id": "mug", "count": 1}, {"id": "bowl", "count": 1}]})
    monkeypatch.setattr(G, "fake_layout", lambda p: {
        "plan": "An arm beside the workbench.",
        "stations": [{"robot": "franka", "kind": "bare", "at": 0, "x": -0.75, "y": 0, "yaw": 0}],
        "furniture": [{"item": "workbench", "x": 0, "y": 0, "yaw": 0}],
        "objects": [{"item": "mug", "on": "station", "station": 0, "x": 0.3, "y": 0.1, "yaw": 0},
                    {"item": "bowl", "on": "furniture", "furniture": 0, "dx": -0.1, "dy": -0.2, "yaw": 0}],
        "task": "Put the mug in the bowl."})
    sim = PlaygroundSim(stations=[])
    sim.pause()
    b = _build(sim, pk)
    st = b.status()
    assert st["phase"] == "done", st
    robot = sim.station(st["stations"][0])
    assert robot.kind == "bare" and robot.footprint() == (0.0, 0.0)      # no table of its own
    bench = next(p for p in sim.placed if p.item == "workbench")
    on_bench = [p for p in sim.placed if p.item in ("mug", "bowl") and p.pos[2] > 0.5]
    assert len(on_bench) == 2                                          # both on the workbench
    assert math.hypot(robot.pos[0] - bench.pos[0], robot.pos[1] - bench.pos[1]) < 1.6
    face = math.atan2(bench.pos[1] - robot.pos[1], bench.pos[0] - robot.pos[0])
    assert math.cos(face - robot.yaw) > 0.7                            # facing the bench


def test_robot_at_a_counter_stands_at_its_front_not_behind_its_backsplash(monkeypatch):
    """A countertop's backsplash runs along its -y edge: a robot the model puts behind it is moved
    to the same spot on its front (+y) side, and the things on the counter are mirrored with it."""
    import math
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    pk = G.clean_pick({"title": "Tea", "robots": [{"robot": "ur5e", "count": 1}],
                       "items": [{"id": "countertop_2", "count": 1}, {"id": "mug", "count": 1}]})
    monkeypatch.setattr(G, "fake_layout", lambda p: {
        "plan": "An arm behind the counter (the wrong side).",
        "stations": [{"robot": "ur5e", "kind": "bare", "at": 0, "x": 0, "y": -0.6, "yaw": 90}],
        "furniture": [{"item": "countertop_2", "x": 0, "y": 0, "yaw": 0}],
        "objects": [{"item": "mug", "on": "furniture", "furniture": 0, "dx": 0.1, "dy": -0.15, "yaw": 0}],
        "task": "Pick up the mug."})
    sim = PlaygroundSim(stations=[])
    sim.pause()
    st = _build(sim, pk).status()
    assert st["phase"] == "done", st
    robot = sim.station(st["stations"][0])
    counter = next(p for p in sim.placed if p.item == "countertop_2")
    assert robot.pos[1] - counter.pos[1] > 0.4                          # on the counter's front side
    assert math.sin(robot.yaw) < -0.7                                   # facing the counter (-y)
    mug = next(p for p in sim.placed if p.item == "mug")
    assert mug.pos[2] > 0.5 and mug.pos[1] > counter.pos[1]             # on the counter, front half
    assert math.hypot(mug.pos[0] - robot.pos[0], mug.pos[1] - robot.pos[1]) < 0.65


def test_arm_beside_furniture_stands_up_to_its_worktop(monkeypatch):
    """An arm with no table, beside a lab bench, gets a steel stand up to the bench's worktop
    (0.85 m), not the 0.75 m an arm put down on the floor gets."""
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    pk = G.clean_pick({"title": "Lab", "robots": [{"robot": "piper", "count": 1}],
                       "items": [{"id": "lab_bench", "count": 1}, {"id": "mug", "count": 1}]})
    monkeypatch.setattr(G, "fake_layout", lambda p: {
        "plan": "A small arm beside the lab bench.",
        "stations": [{"robot": "piper", "kind": "bare", "at": 0, "x": 0, "y": -0.65, "yaw": 90}],
        "furniture": [{"item": "lab_bench", "x": 0, "y": 0, "yaw": 0}],
        "objects": [{"item": "mug", "on": "furniture", "furniture": 0, "dx": 0, "dy": -0.1, "yaw": 0}],
        "task": "Pick up the mug."})
    sim = PlaygroundSim(stations=[])
    sim.pause()
    st = _build(sim, pk).status()
    assert st["phase"] == "done", st
    robot = sim.station(st["stations"][0])
    assert W.table_top("lab_bench") > 0.8
    assert abs(robot.mount_z - W.table_top("lab_bench")) < 0.01
