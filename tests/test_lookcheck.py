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


def test_pictures_reach_devin(monkeypatch, key):
    got = {}

    def fake(model, prompt, images, k, on_think, on_text, stopped, timeout):
        got.update(images=images)
        return "SCORE: 9/10"
    monkeypatch.setattr(SG, "devin_answer", fake)
    PS.ask_stream("swe-2-max", [{"type": "text", "text": "look"}, PIC], True, "medium",
                  lambda t: None, lambda t: None, lambda: False)
    assert got["images"] == [b"\xff\xd8jpg"]
