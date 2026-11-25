"""The look check (playground/lookcheck.py): the model sees pictures of what it built and fixes it.
Level 1 keeps the best-looking version of an object that passed its physics tests; level 2 edits
a whole scene with the drop check and undoes a round that made it worse; the pictures reach the
model on every kind of connection."""
import base64
import time

import pytest

from playground import aimade as AI
from playground import lookcheck as LC
from playground import photoscene as PS
from playground import scenegen as SG
from playground.sim import PlaygroundSim

BOX = ('<object name="Toaster" kind="loose" x="0" y="0" z="0" yaw="0"><mujoco><worldbody><body name="b">'
       '<geom type="box" size="{w} 0.08 0.09" rgba="0.8 0.8 0.8 1" mass="1.5"/></body></worldbody></mujoco></object>')
SINKS = ('<object name="Toaster" kind="loose" x="0" y="0" z="0" yaw="0"><mujoco><worldbody><body name="b">'
         '<geom type="box" size="0.1 0.08 0.09" rgba="1 0 0 1" mass="1.5" contype="0" conaffinity="0"/>'
         '</body></worldbody></mujoco></object>')


def _registered(block: str) -> tuple[dict, dict]:
    o = PS.parse_scene(block)[1][0]
    xml = AI.clean(o["xml"])
    size, frame, mass = AI.measure(xml)
    uid = AI.register(o["name"], xml, False, size, frame, mass)
    return o, {**o, "item": uid, "fixed": False, "size": size}


class _B:
    """A stand-in build: answers come from a list, every question is kept."""

    def __init__(self, answers):
        self.answers_in = list(answers)
        self.asked = []
        self.stop = False
        self.prompt = "a breakfast kitchen"
        self.thoughts = []

    def _ask(self, text, effort, on_text=None, images=()):
        self.asked.append((text, list(images)))
        return self.answers_in.pop(0)

    def _think(self, s):
        self.thoughts.append(s)


def test_object_views_four_sides_and_opened():
    _, ok = _registered(BOX.format(w=0.12))
    pics = LC.object_views(ok["item"])
    assert [w for w, _ in pics] == ["front", "right side", "from above", "front-right corner"]
    assert all(j[:2] == b"\xff\xd8" for _, j in pics)           # JPEGs
    o = PS.parse_scene(PS.FAKE_SCENE)[1][1]                     # the microwave: a hinged door
    xml = AI.clean(o["xml"])
    size, frame, mass = AI.measure(xml)
    uid = AI.register(o["name"], xml, True, size, frame, mass)
    assert "opened" in LC.object_views(uid)[-1][0]


def test_a_low_score_is_fixed_and_the_better_version_kept():
    o, ok = _registered(BOX.format(w=0.12))
    b = _B(["SCORE: 4/10\nFar too wide for a toaster.\n" + BOX.format(w=0.13), "SCORE: 9/10\nGood."])
    got = LC.look_object(b, o, ok)
    assert got["item"] != ok["item"]                         # the fixed version
    assert len(b.asked) == 2
    text, imgs = b.asked[0]
    assert "SCORE: n/10" in text and "Toaster" in text
    assert sum(1 for c in imgs if c["type"] == "image") == 4   # the pictures went with the question
    assert [x["score"] for x in b.looks] == [4, 9]


def test_a_fix_that_looks_worse_is_not_kept():
    o, ok = _registered(BOX.format(w=0.12))
    b = _B(["SCORE: 7/10\nA bit plain.\n" + BOX.format(w=0.13),
            "SCORE: 5/10\nWorse.\n" + BOX.format(w=0.14),
            "SCORE: 6/10\nStill worse."])
    got = LC.look_object(b, o, ok)
    assert got["item"] == ok["item"]
    assert len(b.asked) == 3 and "don't write a new version" in b.asked[-1][0]   # the last look only scores


def test_a_fix_that_fails_physics_keeps_what_passed():
    o, ok = _registered(BOX.format(w=0.12))
    b = _B(["SCORE: 3/10\nWrong.\n" + SINKS])
    assert LC.look_object(b, o, ok)["item"] == ok["item"]
    assert any("failed its physics test" in t for t in b.thoughts)


def test_no_score_or_a_failed_call_keeps_the_object():
    o, ok = _registered(BOX.format(w=0.12))
    assert LC.look_object(_B(["I can't tell."]), o, ok) is ok

    class Boom(_B):
        def _ask(self, *a, **k):
            raise SG.ModelError("the model's company said no (529)")
    assert LC.look_object(Boom([]), o, ok) is ok


def test_parse_score_and_edits():
    assert LC.parse_score("SCORE: 7/10\n...") == 7
    assert LC.parse_score("score = 8.6 out of 10") == 9
    assert LC.parse_score("looks fine") is None
    e = LC.parse_edits('SCORE: 5/10\nmug floats\n```json\n{"edits": [{"do": "move", "id": "o1", "x": 1, "y": 2},'
                       '{"do": "fly", "id": "o2"}, {"do": "remove", "id": "o3"}]}\n```')
    assert [x["do"] for x in e] == ["move", "remove"]


def _fake_scene(monkeypatch):
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    monkeypatch.setattr(LC, "LOOK", False)          # build first, look by hand below
    sim = PlaygroundSim(stations=[])
    sim.pause()
    pick = SG.clean_pick({"title": "Breakfast", "robots": [{"robot": "franka", "count": 1}],
                          "items": [{"id": "mug", "count": 2}]})
    b = SG.Build(sim, type("S", (), {"unsent": {}})(), "a robot making breakfast", pick, "claude-fable-5-2", False)
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 120:
        time.sleep(0.2)
    assert b.status()["phase"] == "done"
    return sim, b


def test_scene_edits_go_down_with_the_drop_check(monkeypatch):
    sim, b = _fake_scene(monkeypatch)
    mugs = [u for u in b.objects if sim.find(u).item == "mug"]
    assert len(mugs) == 2
    gone = mugs[1]
    asked = []
    answers = ['SCORE: 5/10\nOne mug too many.\n```json\n{"edits": [{"do": "remove", "id": "o2"},'
               '{"do": "move", "id": "o9", "x": 0, "y": 0}, {"do": "add", "item": "sofa", "x": 0, "y": 0}]}\n```',
               "SCORE: 9/10\nGood."]

    def ask(text, effort, on_text=None, images=()):
        asked.append((text, images))
        return answers.pop(0)
    b._ask = ask
    LC.look_scene(b, list(b.objects), ["mug"])
    assert sim.find(gone) is None and gone not in b.objects       # removed; the unknown id and item left out
    assert not any(p.item == "sofa" for p in sim.placed)
    assert "o1: Mug" in asked[0][0] and "r1:" in asked[0][0]
    assert sum(1 for c in asked[0][1] if c["type"] == "image") >= 3   # above, corner, the robot's table
    assert [x["score"] for x in b.looks] == [5, 9]


def test_scene_edits_that_score_lower_are_undone(monkeypatch):
    sim, b = _fake_scene(monkeypatch)
    before = sorted(p.uid for p in sim.placed)
    answers = ['SCORE: 6/10\nx\n```json\n{"edits": [{"do": "remove", "id": "o1"}]}\n```', "SCORE: 3/10\nworse"]
    b._ask = lambda text, effort, on_text=None, images=(): answers.pop(0)
    LC.look_scene(b, list(b.objects), ["mug"])
    assert sorted(p.uid for p in sim.placed) == before
    assert len(b.objects) == len(before)


def test_build_runs_the_look_with_a_fake_model(monkeypatch):
    """The whole build with the look on: objects made, scene placed, then checked (fake answers)."""
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    sim = PlaygroundSim(stations=[])
    sim.pause()
    pick = SG.clean_pick({"title": "Bakery", "robots": [{"robot": "franka", "count": 1}], "items": [],
                          "make": [{"name": "Loaf of bread", "count": 1, "kind": "object", "size": [0.2, 0.1, 0.08]}]})
    b = SG.Build(sim, type("S", (), {"unsent": {}})(), "a bakery", pick, "claude-fable-5-2", False)
    b.start()
    t = time.time()
    while b.status()["active"] and time.time() - t < 120:
        time.sleep(0.2)
    st = b.status()
    assert st["phase"] == "done", st
    assert [x["name"] for x in st["looks"]] == ["Loaf of bread", "the whole scene"]


# ------------------------------------------------------------------ the pictures reach every connection
PIC = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"\xff\xd8jpg").decode()}}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(SG, "_cred", lambda provider, public: ("key", "k_test"))


def test_pictures_reach_the_anthropic_api(monkeypatch, key):
    got = {}
    monkeypatch.setattr(PS, "_anthropic_stream", lambda m, s, content, *a: got.setdefault("c", content) and "SCORE: 9/10")
    PS.ask_stream("claude-opus-5-5", [{"type": "text", "text": "look"}, PIC], True, "medium",
                  lambda t: None, lambda t: None, lambda: False)
    assert got["c"][1] == PIC


def test_pictures_reach_the_openai_api(monkeypatch, key):
    sent = {}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter([b'data: {"type": "response.output_text.delta", "delta": "SCORE: 9/10"}\n'])

    def fake_open(url, headers, body, timeout=300.0):
        sent.update(body)
        return R()
    monkeypatch.setattr(PS, "_stream_lines", fake_open)
    out = PS.ask_stream("gpt-6.2-astra", [{"type": "text", "text": "look"}, PIC], True, "medium",
                        lambda t: None, lambda t: None, lambda: False)
    assert out == "SCORE: 9/10"
    parts = sent["input"][0]["content"]
    assert parts[1]["type"] == "input_image" and parts[1]["image_url"].startswith("data:image/jpeg;base64,")


def test_pictures_reach_codex(monkeypatch):
    monkeypatch.setattr(SG, "_cred", lambda provider, public: ("chatgpt", '{"tokens": {}}'))
    monkeypatch.setattr(SG, "WHERE", "local")
    got = {}

    def fake(model, prompt, imgs, login, effort, event, stopped):
        got.update(imgs=imgs, prompt=prompt)
        return "SCORE: 9/10", login
    monkeypatch.setattr(PS, "_codex_local_stream", fake)
    PS.ask_stream("gpt-6.2-astra", [{"type": "text", "text": "look"}, PIC], True, "medium",
                  lambda t: None, lambda t: None, lambda: False)
    assert got["imgs"] == [b"\xff\xd8jpg"] and "look" in got["prompt"]


def test_a_height_aims_at_the_surface_under_a_shelf(monkeypatch):
    """A move with "z" drops from just above that height (under a shelf above it) and needs room
    for the object there; without it, the highest surface wins."""
    class Sim:
        lock = __import__("threading").Lock()
        ray_up = None

        def support(self, item, x, y, yaw, top=3.0, exclude_uid=None):
            self.top = top
            z = 0.76 if top < 1.0 else 1.2           # a worktop at 76 cm under a shelf at 120 cm
            return {"pos": [x, y, z], "valid": True, "level": True}

        def _ray(self, p0, d, excl=-1):
            return self.ray_up, 1
    monkeypatch.setattr(LC.catalog, "meta", lambda item: {"size": [0.1, 0.1, 0.2]})
    s = Sim()
    assert LC._spot(s, "mug", 0.1, 0.2, 0.0)["pos"][2] == 1.2 and s.top == 3.0
    s.ray_up = 0.43                                  # the shelf, 43 cm above the worktop
    assert LC._spot(s, "mug", 0.1, 0.2, 0.0, z=76)["pos"][2] == 0.76 and abs(s.top - 0.80) < 1e-9
    s.ray_up = 0.1                                   # too low to fit under
    assert LC._spot(s, "mug", 0.1, 0.2, 0.0, z=76) is None
    assert LC._spot(s, "mug", 0.1, 0.2, 0.0, z="x") is None


# A workbench: a worktop 90 cm up, a pegboard along its +y edge, a shelf on it at 125 cm over the
# back of the worktop.
BENCH = ('<object name="Workbench" kind="furniture" x="0" y="0" z="0" yaw="0"><mujoco><worldbody><body name="b">'
         '<geom type="box" size="0.6 0.3 0.02" pos="0 0 0.88" rgba="0.6 0.4 0.2 1" mass="30"/>'
         '<geom type="box" size="0.03 0.03 0.43" pos="-0.55 -0.25 0.43" rgba="0.3 0.3 0.3 1" mass="2"/>'
         '<geom type="box" size="0.03 0.03 0.43" pos="0.55 -0.25 0.43" rgba="0.3 0.3 0.3 1" mass="2"/>'
         '<geom type="box" size="0.03 0.03 0.43" pos="-0.55 0.25 0.43" rgba="0.3 0.3 0.3 1" mass="2"/>'
         '<geom type="box" size="0.03 0.03 0.43" pos="0.55 0.25 0.43" rgba="0.3 0.3 0.3 1" mass="2"/>'
         '<geom type="box" size="0.6 0.01 0.4" pos="0 0.29 1.3" rgba="0.5 0.5 0.5 1" mass="5"/>'
         '<geom type="box" size="0.6 0.1 0.01" pos="0 0.18 1.25" rgba="0.5 0.5 0.5 1" mass="3"/>'
         '</body></worldbody></mujoco></object>')


def _bench_sim():
    o = PS.parse_scene(BENCH)[1][0]
    xml = AI.clean(o["xml"])
    size, frame, mass = AI.measure(xml)
    item = AI.register(o["name"], xml, True, size, frame, mass)
    sim = PlaygroundSim(stations=[])
    sim.pause()
    uid = sim.add(item, (0.0, 0.0, 0.0), 0.0)
    return sim, sim.find(uid)


def test_the_worktop_is_measured_under_its_shelf():
    sim, p = _bench_sim()
    assert abs(SG.worktop(sim, p) - 0.90) < 0.02           # not the shelf (1.26) or the pegboard top
    op = SG.open_sides(sim, p, SG.worktop(sim, p))
    assert op["+y"] < 0.2 and op["-y"] > 0.8                 # the pegboard side is shut, the front open


def test_the_worktop_is_still_found_with_things_on_it():
    sim, p = _bench_sim()
    _, box = _registered(BOX.format(w=0.12))
    for x in (-0.45, -0.15, 0.15, 0.45):
        for y in (-0.2, 0.0):
            sim.add(box["item"], (x, y, 0.90), 0.0)
    assert abs(SG.worktop(sim, p) - 0.90) < 0.02


def test_a_robot_behind_the_pegboard_goes_to_the_open_front():
    sim, p = _bench_sim()
    pick = SG.clean_pick({"title": "Bench", "robots": [{"robot": "franka", "count": 1}], "items": []})
    b = SG.Build(sim, type("S", (), {"unsent": {}})(), "a watchmaker's bench", pick, "claude-fable-5-2", False)
    wt = SG.worktop(sim, p)
    x, y = b._open_front({"robot": "franka"}, p, wt, 0.1, 0.62, 0)
    assert abs(x - 0.1) < 1e-6 and abs(y + 0.62) < 1e-6 and b.flip == {0: "y"}
    x, y = b._open_front({"robot": "franka"}, p, wt, 0.1, -0.62, 1)   # already at the front: stays
    assert abs(y + 0.62) < 1e-6 and 1 not in b.flip


def test_things_for_the_bench_go_on_its_worktop_not_the_shelf():
    sim, p = _bench_sim()
    pick = SG.clean_pick({"title": "Bench", "robots": [{"robot": "franka", "count": 1}], "items": []})
    b = SG.Build(sim, type("S", (), {"unsent": {}})(), "a watchmaker's bench", pick, "claude-fable-5-2", False)
    _, box = _registered(BOX.format(w=0.06))
    o = {"item": box["item"], "on": "furniture", "furniture": 0, "dx": 0.0, "dy": 0.18, "yaw": 0.0}   # under the shelf
    uid = b._place_object(o, (0.0, 0.0), [p.uid])
    assert uid and abs(sim.find(uid).pos[2] - 0.90) < 0.02


def test_edits_left_out_say_why_and_the_next_round_hears_it(monkeypatch):
    sim, b = _fake_scene(monkeypatch)
    asked = []
    answers = ['SCORE: 5/10\nx\n```json\n{"edits": [{"do": "move", "id": "r1", "x": 0, "y": 0},'
               '{"do": "move", "id": "o9", "x": 0, "y": 0}]}\n```', "SCORE: 6/10\nbetter",
               "SCORE: 6/10\nok"]

    def ask(text, effort, on_text=None, images=()):
        asked.append(text)
        return answers.pop(0)
    b._ask = ask
    LC.look_scene(b, list(b.objects), ["mug"])
    assert "move r1: a robot can't be moved" in asked[1] and "move o9: no such id" in asked[1]
