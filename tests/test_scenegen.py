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
