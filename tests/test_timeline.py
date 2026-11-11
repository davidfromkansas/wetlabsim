"""The run timeline (wetlabsim/timeline.py) for each agent's transcript format: Claude Code, Codex,
Devin (ACP) and Jev. Same robot events for all, so the robot rows must agree."""
from wetlabsim import timeline as TL

START = 100.0


def at(t, o):
    return {**o, "_sim_time": START + t}


def robot_events():
    return [
        {"t": START + 35, "event": "command", "kind": "move_l", "seconds": 5.0},
        {"t": START + 41, "event": "command", "kind": "gripper", "position": 255},
        {"t": START + 42, "event": "command", "kind": "move_l", "seconds": 8.0},
        {"t": START + 51, "event": "command", "kind": "gripper", "position": 0},
        {"t": START + 52, "event": "camera", "camera": "wrist"},
    ]


def lane(tl, k):
    return next(l for l in tl["lanes"] if l["id"] == k)


def claude_transcript():
    def msg(mid, blocks, out_tok=100):
        return {"type": "assistant", "message": {"id": mid, "model": "claude-opus-5-5", "content": blocks,
                                                 "usage": {"input_tokens": 1000, "output_tokens": out_tok,
                                                           "cache_read_input_tokens": 5000}}}
    def result(tid, text):
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}
    return [
        at(0.1, {"type": "system", "subtype": "init", "model": "claude-opus-5-5"}),
        at(4, msg("m1", [{"type": "thinking", "thinking": "Find the apple first, then plan the grasp."}])),
        at(5, msg("m1", [{"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "/w/SITE.md"}}])),
        at(5.2, result("r1", "site sheet")),
        at(8, msg("m2", [{"type": "tool_use", "id": "l1", "name": "mcp__wetlab__look", "input": {"camera": "overhead"}}])),
        at(9, result("l1", [{"type": "image"}])),
        at(20, msg("m3", [{"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": "/w/pick.py", "content": "print(1)"}}], 2000)),
        at(20.1, result("w1", "ok")),
        at(22, msg("m4", [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "cd /w && python3 pick.py"}}])),
        at(25, result("b1", "Traceback (most recent call last):\n  File pick.py\nRobotError: target pose is unreachable")),
        at(30, msg("m5", [{"type": "tool_use", "id": "w2", "name": "Edit", "input": {"file_path": "/w/pick.py", "new_string": "x"}}])),
        at(30.1, result("w2", "ok")),
        at(31, msg("m6", [{"type": "tool_use", "id": "b2", "name": "Bash", "input": {"command": "python3 pick.py"}}])),
        at(60, result("b2", "picked and placed")),
        at(70, msg("m7", [{"type": "text", "text": "DONE. The apple is in the bowl."}])),
        at(71, {"type": "result", "total_cost_usd": 0.5, "usage": {"input_tokens": 7000, "output_tokens": 2600}}),
    ]


def test_claude_rows_spend_and_result():
    tl = TL.build(claude_transcript(), robot_events(), {"agent": "claude", "model": "opus", "sim_start": START,
                                                        "status": "finished", "cost_usd": 0.5}, end=START + 72)
    assert tl["provider"] == "Anthropic"
    assert lane(tl, "reading")["blocks"] and lane(tl, "looking")["blocks"] and lane(tl, "writing")["blocks"]
    run = [b for b in lane(tl, "running")["blocks"] if b["label"] == "pick.py"]
    assert any(abs(b["start"] - 31) < 1e-6 and abs(b["end"] - 60) < 1e-6 for b in run)
    assert lane(tl, "moving")["blocks"][0] == {"start": 35.0, "end": 40.0, "label": "", "detail": "move l"}
    assert [f["label"] for f in tl["flags"]] == ["Code error", "Gripped", "Let go", "Done"]
    assert tl["result"]["ai_done_at"] == 70 and tl["result"]["safety_stops"] == 0
    errs = lane(tl, "errors")["points"]
    assert errs and "unreachable" in errs[0]["label"]
    c = tl["cost"]
    assert c["known"] and abs(c["usd"] - 0.5) < 1e-6
    assert abs(sum(lane(tl, k)["usd"] for k in TL.AI_LANES) - 0.5) < 1e-4
    assert lane(tl, "writing")["usd"] > lane(tl, "reading")["usd"]      # the big write cost most
    usd = [p[1] for p in c["series"]]
    assert usd == sorted(usd) and usd[-1] == c["usd"]
    w = lane(tl, "waiting")
    assert 0 < w["share"] < 1 and all(b["end"] <= 35 or b["start"] >= 60 for b in w["blocks"])


def test_codex_tokens_but_no_cost():
    objs = [
        at(5, {"type": "item.completed", "item": {"type": "reasoning", "text": "Plan: write pick.py"}}),
        at(8, {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "/w/pick.py"}]}}),
        at(10, {"type": "item.started", "item": {"type": "command_execution", "command": "python pick.py"}}),
        at(60, {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "ok"}}),
        at(70, {"type": "item.completed", "item": {"type": "agent_message", "text": "DONE"}}),
        at(71, {"type": "turn.completed", "usage": {"input_tokens": 40000, "output_tokens": 3000}}),
    ]
    tl = TL.build(objs, robot_events(), {"agent": "codex", "model": "gpt-6-astra", "sim_start": START,
                                         "status": "finished"}, end=START + 72)
    assert tl["provider"] == "OpenAI" and tl["model_label"] == "GPT-6 Astra"
    assert not tl["cost"]["known"] and tl["cost"]["usd"] is None and tl["cost"]["tokens"] == 43000
    assert "Codex" in tl["cost"]["why_unknown"]
    assert lane(tl, "running")["blocks"][0]["start"] == 10
    assert tl["result"]["ai_done_at"] == 70


def test_devin_tokens_but_no_cost():
    objs = [
        at(3, {"type": "_devin_acp", "kind": "thinks", "text": "Look at the table first"}),
        at(5, {"type": "_devin_acp", "kind": "tool", "id": "a", "name": "exec", "input": {"command": "python pick.py"}}),
        at(50, {"type": "_devin_acp", "kind": "tool_result", "id": "a", "text": "ok"}),
        at(51, {"type": "_devin_acp", "kind": "usage", "model": "SWE-2 Max", "input_tokens": 9000, "output_tokens": 800}),
        at(60, {"type": "_devin_acp", "kind": "says", "text": "DONE, apple placed"}),
        at(61, {"type": "_devin_acp", "kind": "usage", "model": "SWE-2 Max", "input_tokens": 12000, "output_tokens": 900}),
    ]
    tl = TL.build(objs, robot_events(), {"agent": "devin", "model": "swe-2-max", "sim_start": START,
                                         "status": "finished"}, end=START + 62)
    assert tl["provider"] == "Cognition"
    assert not tl["cost"]["known"] and tl["cost"]["tokens"] == 12900
    assert lane(tl, "running")["blocks"][0]["start"] == 5 and lane(tl, "running")["blocks"][0]["end"] == 50


def test_jev_steps_cost_and_refusals():
    objs, events = [at(0.5, {"type": "_jev", "kind": "start", "model": "jev-1.14.0"})], []
    usd = 0.0
    for n in range(1, 6):
        cam, t = 2.0 * n, 2.0 * n + 1.5
        usd += 16000 * 0.042 / 1e6
        events.append({"t": START + cam + 1.3, "event": "command", "kind": "move_l", "seconds": 0.15})
        objs.append(at(t, {"type": "_jev", "kind": "step", "step": n, "model": "jev-1.14.0", "seconds": 1.0,
                           "answers": {"move": {"choice": "down"}}, "usage": {"input_tokens": 16000},
                           "input_tokens_total": 16000 * n, "cost_usd": round(usd, 6),
                           "camera_time": START + cam, "did": "moved" if n != 3 else "the robot refused: out of reach",
                           "ok": n != 3}))
    objs.append(at(12, {"type": "_jev", "kind": "done", "steps": 5}))
    tl = TL.build(objs, events, {"agent": "jev", "model": "jev-1.14.0", "sim_start": START, "status": "finished"},
                  end=START + 13)
    assert tl["provider"] == "TypeSafe" and tl["cost"]["known"]
    assert abs(tl["cost"]["usd"] - 5 * 16000 * 0.042 / 1e6) < 1e-6 and tl["cost"]["tokens"] == 80000
    th = lane(tl, "thinking")["blocks"]
    assert len(th) == 5 and abs(th[0]["start"] - 2.3) < 1e-6 and abs(th[0]["end"] - 3.3) < 1e-6
    assert len(lane(tl, "looking")["blocks"]) == 5 and not lane(tl, "running")["blocks"]
    assert lane(tl, "looking")["usd"] == 0 and abs(lane(tl, "thinking")["usd"] - tl["cost"]["usd"]) < 1e-9
    assert lane(tl, "errors")["count"] == 1
    assert tl["result"]["ai_done_at"] == 12


def test_safety_stop_live_run_and_empty_run():
    ev = robot_events() + [{"t": START + 45, "event": "protective_stop", "reason": "collision"}]
    tl = TL.build(claude_transcript()[:9], ev, {"agent": "claude", "model": "opus", "sim_start": START,
                                                "status": "running"}, end=START + 46, live=True)
    assert tl["live"] and tl["result"]["safety_stops"] == 1
    assert any("Safety stop" in p["label"] for p in lane(tl, "errors")["points"])
    assert tl["now"]            # something is going on at the newest moment
    assert tl["result"]["ai_done_at"] is None
    empty = TL.build([], [], {"agent": "codex", "sim_start": START, "status": "error"}, end=START + 3)
    assert empty["duration"] == 3 and empty["cost"]["tokens"] == 0 and empty["flags"] == []
