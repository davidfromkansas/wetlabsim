"""The past-run results page (playground/runpage.py): code the AI typed straight into the
terminal is found, files fall into the right groups, and file paths can't leave the run folder."""
import hashlib
import json

from playground import runpage as RP


def test_scripts_in_terminal_commands():
    codex = '/bin/zsh -lc "python3 - <<\'PY\'\nfrom wetlabsim.robot import Robot\nprint(\\"hi\\")\nPY"'
    s = RP.scripts_in(codex)
    assert [x["kind"] for x in s] == ["inline"]
    assert 'print("hi")' in s[0]["code"]
    assert RP.scripts_in('python3 -c "import os; print(1)"')[0]["code"] == "import os; print(1)"
    w = RP.scripts_in("cat > pick.py <<'EOF'\nx = 1\nEOF\npython3 pick.py")
    assert [(x["kind"], x.get("name")) for x in w] == [("file", "pick.py"), ("ran_file", "pick.py")]


def _run(tmp_path, lines, kit=True):
    d = tmp_path / "run"
    ws = d / "workspace"
    (ws / ".devin").mkdir(parents=True)
    (ws / "GOAL.md").write_text("Pick up the cup")
    (ws / "pick.py").write_text("print(1)\n")
    (ws / ".devin" / "config.json").write_text("{}")
    if kit:
        (d / "workspace_start.json").write_text(json.dumps(
            {"files": {"GOAL.md": hashlib.sha256(b"Pick up the cup").hexdigest()}}))
    (d / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    (d / "result.json").write_text(json.dumps({"wall_seconds": 30, "output_tokens": 120}))
    (d / "events.json").write_text(json.dumps([{"event": "protective_stop", "t": 15.0, "reason": "too much force"}]))
    return d


def test_build_groups_files_and_steps(tmp_path):
    lines = [{"type": "_raw", "text": "Reading additional input from stdin...", "_sim_time": 10.5},
             {"type": "item.started", "_sim_time": 11.0,
              "item": {"id": "i1", "type": "command_execution", "command": "python3 - <<'PY'\nprint(2)\nPY"}},
             {"type": "item.completed", "_sim_time": 12.0,
              "item": {"id": "i1", "type": "command_execution", "command": "python3 - <<'PY'\nprint(2)\nPY",
                       "aggregated_output": "Traceback (most recent call last):\nValueError: no", "exit_code": 1}}]
    d = _run(tmp_path, lines)
    page = RP.build(d, {"run_id": "r1", "task": "Pick up the cup", "sim_start": 10.0, "seconds": 30, "ok": True})
    f = page["files"]
    assert [x["path"] for x in f["saved"]] == ["pick.py"]
    assert [x["path"] for x in f["tool"]] == [".devin/config.json"]
    assert [x["path"] for x in f["given"]] == ["GOAL.md"] and f["kit_known"]
    kinds = [s["kind"] for s in page["steps"]]
    assert "says" not in kinds                    # the AI tool's own log line is left out
    assert kinds == ["runs", "stop"] and page["steps"][1]["t"] == 5.0
    assert page["steps"][0].get("error") and page["errors"] == 1
    assert page["scripts"][0]["kind"] == "inline" and page["scripts"][0]["code"] == "print(2)"
    assert page["cost_usd"] is None and page["cost_why"]
    assert page["tokens"]["output"] == 120


def test_file_paths_stay_in_the_run(tmp_path):
    d = _run(tmp_path, [], kit=False)
    assert RP.file_path(d, "pick.py") is not None
    for bad in ("../result.json", "/etc/passwd", "", "a/../../result.json"):
        assert RP.file_path(d, bad) is None
    assert [x["path"] for x in RP.files(d)["given"]] == ["GOAL.md"]     # starter files by name
