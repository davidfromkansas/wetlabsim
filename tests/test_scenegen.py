"""Describe a scene (playground/scenegen.py): the model's pick is kept to real robots and
objects and our limits, and the build puts every station, piece of furniture and object down
with the drop check, on free floor clear of what was there, and Undo takes it all away."""
import time

from playground import scenegen as G
from playground.sim import PlaygroundSim


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


def test_stream_items_reads_a_list_still_being_written():
    t = '{"plan": "a [b] {c}", "stations": [{"robot": "x"}], "objects": [{"item": "a", "n": "}]"}, {"item": "b'
    assert G.stream_items(t, "stations") == ([{"robot": "x"}], True, True)
    assert G.stream_items(t, "objects") == ([{"item": "a", "n": "}]"}], True, False)
    assert G.stream_items(t, "furniture") == ([], False, False)


def test_scene_fills_in_as_the_layout_is_written(monkeypatch):
    """Objects go down while the model is still writing; things inside others wait for their
    holder; what it left out goes down at the end."""
    import json
    sim = PlaygroundSim(stations=[])
    pick = {"title": "t", "robots": [{"robot": "franka", "count": 1}], "missing": [], "task": "x",
            "items": [{"id": "shelf_three_level", "count": 1}, {"id": "block_red", "count": 2},
                      {"id": "block_blue", "count": 1}, {"id": "libero_alphabet_soup", "count": 1}]}
    lay = {"plan": "p", "stations": [{"robot": "franka", "kind": "table", "x": 0, "y": 0, "yaw": 0}],
           "furniture": [],
           "objects": [{"item": "libero_alphabet_soup", "on": "inside", "object": 1, "level": 1},
                       {"item": "shelf_three_level", "on": "station", "station": 0, "x": 0.45, "y": 0.3},
                       {"item": "block_red", "on": "station", "station": 0, "x": 0.2, "y": -0.2},
                       {"item": "block_red", "on": "station", "station": 0, "x": 0.2, "y": -0.05}],
           "task": "Stack the blocks."}
    txt = json.dumps(lay, indent=1)
    seen = []
    b = G.Build(sim, _Sess(), "x", pick, "claude-fable-5-2", False)
    b.look = False

    def stream(*a, **k):
        for i in range(0, len(txt), 25):
            seen.append(len(b.objects))
            yield txt[i:i + 25]
    monkeypatch.setattr(G, "ask_stream", stream)
    monkeypatch.setattr(G, "layout_messages", lambda *a: ("s", "u"))
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 120:
        time.sleep(0.2)
    st = b.status()
    assert st["phase"] == "done", st["error"]
    assert max(seen) >= 2                       # things were down before the answer was finished
    items = sorted(sim.find(u).item for u in b.objects)
    assert items == sorted(["shelf_three_level", "libero_alphabet_soup", "block_red", "block_red", "block_blue"])
    soup = next(sim.find(u) for u in b.objects if sim.find(u).item == "libero_alphabet_soup")
    shelf = next(sim.find(u) for u in b.objects if sim.find(u).item == "shelf_three_level")
    assert abs(soup.pos[0] - shelf.pos[0]) < 0.2 and soup.pos[2] - shelf.pos[2] < 0.05    # on its bottom level
    assert st["task"] == "Stack the blocks."
