"""A scene from a photo (playground/photoscene.py) and AI-made objects (playground/aimade.py):
the model's MJCF is cleaned, measured and shaken before it goes into a scene; a failing object
goes back to the model; the scene is put down in a session and saved with it. No model is asked
(WETLAB_SCENEGEN_FAKE)."""
import base64
import io
import json
import math

import mujoco
import pytest
from PIL import Image

from playground import aimade as AI
from playground import catalog
from playground import photoscene as PS
from playground import world as W

MUG = """<mujoco><worldbody><body name="mug">
<geom type="cylinder" size="0.04 0.005" pos="0 0 -0.045" rgba="0.2 0.4 0.8 1" mass="0.08"/>
<geom type="box" size="0.04 0.004 0.05" pos="0 0.038 0" mass="0.05"/>
<geom type="box" size="0.04 0.004 0.05" pos="0 -0.038 0" mass="0.05"/>
</body></worldbody></mujoco>"""


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv("WETLAB_SCENEGEN_FAKE", "1")
    monkeypatch.setenv("WETLAB_PHOTOSCENE_FAKE_DELAY", "0")


def test_clean_keeps_plain_shapes_and_drops_the_rest():
    xml = AI.clean("""<mujoco><asset><texture name="t" file="/etc/passwd"/><material name="m" rgba="1 0 0 1"/></asset>
<worldbody><light pos="0 0 1"/><camera name="c"/><body name="b"><freejoint/><geom type="box" size=".1 .1 .1" material="m" mass="1"/>
<body name="lid" pos="0 0 .1"><joint type="hinge" axis="1 0 0" range="0 90"/><geom type="box" size=".1 .1 .01" mass=".1"/></body>
</body></worldbody><actuator><motor joint="x"/></actuator></mujoco>""")
    assert "texture" not in xml and "light" not in xml and "camera" not in xml and "freejoint" not in xml
    assert "actuator" not in xml and 'name="j0"' in xml          # unnamed joints get names
    for bad in ('<mujoco><worldbody><geom type="mesh" mesh="x"/></worldbody></mujoco>',
                '<mujoco><include file="x.xml"/><worldbody/></mujoco>',
                '<mujoco><worldbody><body><joint type="ball"/><geom type="sphere" size=".1"/></body></worldbody></mujoco>',
                '<!DOCTYPE x [<!ENTITY a "b">]><mujoco/>', "not xml"):
        with pytest.raises(AI.Bad):
            AI.clean(bad)


def test_measure_gives_size_bottom_centre_and_mass():
    size, frame, mass = AI.measure(AI.clean(MUG))
    assert size == pytest.approx([0.08, 0.084, 0.1], abs=1e-3)
    assert frame[2] == pytest.approx(0.05, abs=1e-3)       # the model's origin sits 5 cm above its bottom
    assert mass == pytest.approx(0.18)


def test_shake_catches_an_object_that_sinks_or_explodes():
    ok = AI.clean(MUG)
    uid = AI.register("Mug", ok, False, *AI.measure(ok))
    AI.shake(uid)
    roll = AI.clean('<mujoco><worldbody><body euler="90 0 0"><geom type="cylinder" size=".05 .2" mass="1"/></body></worldbody></mujoco>')
    uid2 = AI.register("Roller", roll, False, *AI.measure(roll))
    AI.shake(uid2)              # lying on its side it rests (rolls only if pushed)
    ghost = AI.clean('<mujoco><worldbody><body><geom type="box" size=".1 .1 .1" mass="1" contype="0" conaffinity="0"/>'
                     '</body></worldbody></mujoco>')
    uid3 = AI.register("Ghost", ghost, False, *AI.measure(ghost))
    with pytest.raises(AI.Bad, match="sinks"):
        AI.shake(uid3)          # no collision shapes: it falls through the floor


def _reg(name, body, fixed=False):
    xml = AI.clean(f"<mujoco><worldbody>{body}</worldbody></mujoco>")
    return AI.register(name, xml, fixed, *AI.measure(xml))


CUP_WALLS = "".join(
    f'<geom type="box" size="0.012 0.003 0.045" pos="{0.03 * math.cos(a):.4f} {0.03 * math.sin(a):.4f} 0.055" '
    f'euler="0 0 {math.degrees(a) + 90:.2f}" mass="0.02"/>' for a in [k * math.pi / 6 for k in range(12)])


def test_inspect_passes_a_well_made_cup_and_cabinet():
    AI.inspect(_reg("Coffee cup", f'<body><geom type="cylinder" size="0.03 0.005" pos="0 0 0.005" mass="0.05"/>{CUP_WALLS}</body>'))
    AI.inspect(_reg("Mug", MUG.split("<worldbody>")[1].split("</worldbody>")[0]))
    cabinet = ('<body><geom type="box" size="0.3 0.3 0.01" pos="0 0 0.01" mass="5"/>'
               '<geom type="box" size="0.3 0.01 0.3" pos="0 0.29 0.3" mass="5"/>'
               '<body name="door" pos="-0.3 -0.32 0.3"><joint name="door_hinge" type="hinge" axis="0 0 1" '
               'range="-110 0" damping="0.2" armature="0.01"/>'
               '<geom type="box" size="0.3 0.01 0.28" pos="0.3 0 0" mass="2"/></body></body>')
    AI.inspect(_reg("Cabinet", cabinet, fixed=True))


def test_inspect_catches_a_solid_or_bottomless_container():
    with pytest.raises(AI.Bad, match="hollow"):
        AI.inspect(_reg("Glass beaker", '<body><geom type="cylinder" size="0.03 0.05" pos="0 0 0.05" mass="0.2"/></body>'))
    with pytest.raises(AI.Bad, match="no bottom"):
        AI.inspect(_reg("Plastic cup", f"<body>{CUP_WALLS}</body>"))


def test_inspect_catches_a_door_that_cannot_open():
    blocked = ('<body><geom type="box" size="0.3 0.3 0.01" pos="0 0 0.01" mass="5"/>'
               '<geom name="post" type="box" size="0.02 0.05 0.3" pos="-0.2 -0.4 0.3" mass="1"/>'
               '<body name="door" pos="-0.3 -0.32 0.3"><joint name="door_hinge" type="hinge" axis="0 0 1" '
               'range="-110 0" damping="0.2" armature="0.01"/>'
               '<geom type="box" size="0.3 0.01 0.28" pos="0.3 0 0" mass="2"/></body></body>')
    with pytest.raises(AI.Bad, match="door_hinge.*only opens"):
        AI.inspect(_reg("Blocked cabinet", blocked, fixed=True))


def test_inspect_catches_something_too_thin_to_stay_on_a_table():
    with pytest.raises(AI.Bad, match="passes through"):
        AI.inspect(_reg("Paper sheet", '<body><geom type="box" size="0.1 0.15 0.0003" pos="0 0 0.0003" mass="0.005"/></body>'))


def test_ai_items_work_like_library_items():
    xml = AI.clean(MUG)
    uid = AI.register("Mug", xml, False, *AI.measure(xml))
    assert catalog.item(uid)["label"] == "Mug" and catalog.item(uid)["tab"] == "AI-made"
    m = W.build([W.Placed("o_1", uid, (0.5, 0.0, 0.0), 0.3)], [])
    assert mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "obj_o_1") >= 0
    # saved with a session and registered again from it
    saved = json.loads(json.dumps(AI.export([uid])))
    AI._REG.pop(uid)
    assert AI.load(saved) == [uid] and catalog.meta(uid)["size"] == saved[uid]["size"]


def test_parse_scene():
    title, objs = PS.parse_scene(PS.FAKE_SCENE)
    assert title == "Small kitchen" and [o["name"] for o in objs] == ["Counter", "Microwave", "Mug"]
    assert objs[1]["z"] == pytest.approx(0.9) and objs[2]["kind"] == "loose" and "<mujoco>" in objs[0]["xml"]


def _photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, "PNG")
    data, _ = PS.jpeg_from_data_url("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
    return data


class _Sess:
    def __init__(self):
        self.unsent = {}


def _build(tmp_path, sim):
    rec = PS.keep_photo("feedbeef", _photo(), tmp_path)
    assert (tmp_path / rec["file"]).exists()
    return PS.PhotoBuild(sim, _Sess(), _photo(), "", "claude-fable-5-2", False, rec)


def test_photo_build_puts_a_settled_scene_down(tmp_path):
    from playground.sim import PlaygroundSim
    s = PlaygroundSim(placed=[], stations=[])
    b = _build(tmp_path, s)
    b._run()
    st = b.status()
    assert st["phase"] == "done" and st["counts"]["placed"] == 3 and not st["skipped"], st
    assert "Setting the scale" in st["thinking"] and st["title"] == "Small kitchen"
    for _ in range(int(2.0 / s.m.opt.timestep)):
        mujoco.mj_step(s.m, s.d)
    mug = next(p for p in s.placed if catalog.item(p.item)["label"] == "Mug")
    z = s.d.xpos[s.m.body(f"obj_{mug.uid}").id][2]
    assert 0.85 < z < 0.95                     # still standing on the counter
    b.undo()
    assert not s.placed


def test_a_failing_object_goes_back_to_the_model(tmp_path, monkeypatch):
    from playground.sim import PlaygroundSim
    s = PlaygroundSim(placed=[], stations=[])
    b = _build(tmp_path, s)
    bad = '<scene title="Desk" objects="1"><object name="Mug" kind="loose" x="0" y="0" z="0" yaw="0"><mujoco><worldbody><body><geom type="mesh"/></body></worldbody></mujoco></object></scene>'
    good = f'<object name="Mug" kind="loose" x="0" y="0" z="0" yaw="0">{MUG}</object>'
    asked = []

    def ask(text, effort):
        asked.append(text)
        return bad if len(asked) == 1 else good
    monkeypatch.setattr(b, "_ask", ask)
    b._run()
    assert b.phase == "done" and b.counts["retries"] == 1 and len(asked) == 2
    assert "geom type 'mesh' isn't allowed" in asked[1]


def test_an_object_that_never_passes_is_left_out(tmp_path, monkeypatch):
    from playground.sim import PlaygroundSim
    s = PlaygroundSim(placed=[], stations=[])
    b = _build(tmp_path, s)
    title, objs = PS.parse_scene(PS.FAKE_SCENE)
    broken = PS.FAKE_SCENE.replace('<geom type="cylinder" size="0.04 0.005"', '<geom type="mesh" size="0.04 0.005"')
    monkeypatch.setattr(b, "_ask", lambda text, effort: broken if "Rebuild" in text else "no fix")
    b._run()
    assert b.phase == "done" and b.skipped == ["Mug"] and b.counts["placed"] == 2


def test_an_inspection_problem_gets_one_fix_then_the_object_is_kept(tmp_path, monkeypatch):
    from playground.sim import PlaygroundSim
    s = PlaygroundSim(placed=[], stations=[])
    b = _build(tmp_path, s)
    solid = ('<scene title="Lab" objects="1"><object name="Glass beaker" kind="loose" x="0" y="0" z="0" yaw="0">'
             '<mujoco><worldbody><body><geom type="cylinder" size="0.03 0.05" pos="0 0 0.05" mass="0.2"/>'
             '</body></worldbody></mujoco></object></scene>')
    asked = []

    def ask(text, effort):
        asked.append(text)
        return solid               # the "fix" is still solid
    monkeypatch.setattr(b, "_ask", ask)
    b._run()
    assert b.phase == "done" and b.counts["placed"] == 1 and not b.skipped
    assert b.counts["retries"] == 1 and len(asked) == 2 and "hollow" in asked[1]
    assert "Kept the glass beaker" in b.thinking


def test_object_card_lists_moving_parts_and_friction():
    xml = AI.clean('<mujoco><worldbody><body name="cab"><geom type="box" size=".3 .2 .4" friction="0.6" mass="20"/>'
                   '<body name="door_1" pos="-.3 -.2 0"><joint type="hinge" axis="0 0 1" range="0 90"/>'
                   '<geom type="box" size=".15 .01 .4" mass="2"/></body>'
                   '<body name="door_2" pos=".3 -.2 0"><joint type="hinge" axis="0 0 1" range="-90 0"/>'
                   '<geom type="box" size=".15 .01 .4" mass="2"/></body>'
                   '<body pos="0 -.2 .3"><joint type="slide" axis="0 -1 0" range="0 .3"/>'
                   '<geom type="box" size=".2 .01 .05" mass="1"/></body></body></worldbody></mujoco>')
    uid = AI.register("Cabinet", xml, True, *AI.measure(xml))
    m = catalog.meta(uid)
    assert m["parts"] == "2 doors and 1 sliding part" and m["friction"] == 0.6


def test_a_wall_is_allowed(tmp_path):
    wall = AI.clean('<mujoco><worldbody><body name="wall"><geom type="box" size="5 0.06 1.5" mass="750" '
                    'rgba="0.9 0.8 0.3 1"/></body></worldbody></mujoco>')
    uid = AI.register("Wall (back)", wall, True, *AI.measure(wall))
    AI.shake(uid)
    assert catalog.meta(uid)["size"][0] == pytest.approx(10.0)


def test_the_answer_is_kept_with_the_photo(tmp_path):
    from playground.sim import PlaygroundSim
    s = PlaygroundSim(placed=[], stations=[])
    b = _build(tmp_path, s)
    b._run()
    rec = b.photo_rec
    assert rec.get("answer") and "<scene" in (tmp_path / rec["answer"]).read_text()


def test_thinking_steps_without_words_are_counted(tmp_path):
    from playground.sim import PlaygroundSim
    b = _build(tmp_path, PlaygroundSim(placed=[], stations=[]))
    b._think(PS.STEP)
    b._think(PS.STEP)
    st = b.status()
    assert st["steps"] == 2 and st["thinking"] == "" and st["quiet"] < 5


def test_time_limit_stops_a_silent_model(monkeypatch):
    import subprocess
    import time as T
    monkeypatch.setattr(PS, "PHOTO_TIMEOUT", 1)
    p = subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE, text=True)   # prints nothing, like Codex writing
    t0 = T.time()
    w = PS._watch(p.kill, lambda: False)
    for _ in p.stdout:
        pass
    p.wait()
    w.done()
    assert w.over.is_set() and T.time() - t0 < 5


def test_codex_session_log_reasoning_counts_as_steps(tmp_path):
    import time as T
    got = []
    log = tmp_path / "sessions" / "2026" / "r.jsonl"
    log.parent.mkdir(parents=True)
    done = PS._follow_logs(str(tmp_path / "sessions"), lambda line: got.append(line))
    log.write_text('{"type":"event_msg","payload":{"type":"item_completed","item":{"id":"r1","type":"Reasoning","summary_text":[]}}}\n')
    T.sleep(1.5)
    done.set()
    T.sleep(1.2)
    assert len(got) == 1


def test_codex_reasoning_lines_become_steps(monkeypatch):
    lines = ['{"type":"event_msg","payload":{"type":"item_completed","item":{"id":"r1","type":"Reasoning","summary_text":[]}}}',
             '{"type":"item.completed","item":{"id":"r1","type":"reasoning","text":""}}',          # same item again
             '{"type":"item.completed","item":{"id":"r2","type":"reasoning","text":"Measuring the bench"}}',
             '{"type":"item.started","item":{"id":"r3","type":"reasoning"}}']

    def fake_local(model, prompt, imgs, login, effort, event, stopped):
        for ln in lines:
            event(ln)
        return "<scene/>", login
    monkeypatch.setattr(PS, "_codex_local_stream", fake_local)
    monkeypatch.setattr(PS.SG, "WHERE", "local")
    got = []
    PS._codex_stream("m", "sys", [{"type": "text", "text": "x"}], "{}", "high", got.append, lambda t: None, lambda: False)
    assert got == [PS.STEP, "\n\nMeasuring the bench"]


def test_a_thought_in_both_stdout_and_the_session_log_shows_once(monkeypatch):
    out = '{"type":"item.completed","item":{"id":"item_0","type":"reasoning","text":"**Mapping the bench**\\n**Hollow flask**"}}'
    log = '{"type":"event_msg","payload":{"type":"item_completed","item":{"id":"rs_1","type":"Reasoning","summary_text":["**Mapping the bench**","**Hollow flask**"]}}}'

    def fake_local(model, prompt, imgs, login, effort, event, stopped):
        event(log, True)                 # the log can come first...
        event(out)
        event(log.replace("rs_1", "rs_2").replace("Hollow", "Thin"), True)   # ...after stdout it is ignored
        return "<scene/>", login
    monkeypatch.setattr(PS, "_codex_local_stream", fake_local)
    monkeypatch.setattr(PS.SG, "WHERE", "local")
    got = []
    PS._codex_stream("m", "sys", [{"type": "text", "text": "x"}], "{}", "high", got.append, lambda t: None, lambda: False)
    assert got == ["\n\n**Mapping the bench** **Hollow flask**"]


def test_split_mode_plans_then_builds_in_parallel(tmp_path, monkeypatch):
    from playground.sim import PlaygroundSim
    monkeypatch.setattr(PS, "SPLIT", True)
    monkeypatch.setattr(PS, "PER_BUILDER", 1)          # 3 objects -> 3 builders at once
    s = PlaygroundSim(placed=[], stations=[])
    b = _build(tmp_path, s)
    asked = []
    real = b._ask
    monkeypatch.setattr(b, "_ask", lambda text, effort, on_text=None: (asked.append(text[:20]), real(text, effort, on_text))[1])
    b._run()
    st = b.status()
    assert st["phase"] == "done" and st["counts"]["placed"] == 3 and not st["skipped"], st
    assert asked[0].startswith("Plan a sim-ready") and sum(a.startswith("Here is the plan") for a in asked) == 3


def test_split_items_mixes_big_and_small():
    items = [{"name": str(k), "w": str(k), "d": "1", "h": "1"} for k in range(1, 21)]
    groups = PS.split_items(items)
    assert len(groups) == 3 and sum(len(g) for g in groups) == 20
    assert {g[0]["name"] for g in groups} == {"20", "19", "18"}
