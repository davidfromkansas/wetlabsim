"""The Devin ACP bridge answers every request and gives up on a silent Devin."""
import json
import os
import pathlib
import subprocess
import sys

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "wetlabsim" / "devin_acp.py"

FAKE = r'''#!{py}
import json, sys, time
def out(m): sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "initialize":
        out({{"jsonrpc": "2.0", "id": m["id"], "result": {{}}}})
    elif m.get("method") == "session/new":
        out({{"jsonrpc": "2.0", "id": m["id"], "result": {{"sessionId": "s1"}}}})
    elif m.get("method") == "session/prompt":
        prompt_id = m["id"]
        out({{"jsonrpc": "2.0", "id": 99, "method": "terminal/create", "params": {{}}}})
    elif m.get("id") == 99:
        sys.stderr.write("got reply\n")
        if "{mode}" == "answer":
            out({{"jsonrpc": "2.0", "id": prompt_id, "result": {{"stopReason": "end_turn"}}}})
        # "hang": say nothing more until cancelled
    elif m.get("method") == "session/cancel":
        out({{"jsonrpc": "2.0", "id": prompt_id, "result": {{"stopReason": "cancelled"}}}})
'''


def _run(tmp_path, mode, *extra):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "devin"
    fake.write_text(FAKE.format(py=sys.executable, mode=mode))
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    raw = tmp_path / "raw.jsonl"
    p = subprocess.run([sys.executable, str(BRIDGE), str(tmp_path), "hi", "--raw-log", str(raw), *extra],
                       env=env, capture_output=True, text=True, timeout=60)
    events = [json.loads(l) for l in p.stdout.splitlines()]
    return p.returncode, events, [json.loads(l) for l in raw.read_text().splitlines()]


def test_unknown_request_gets_an_error_reply(tmp_path):
    code, events, raw = _run(tmp_path, "answer")
    assert code == 0
    assert events[-1] == {"type": "_devin_acp", "kind": "end", "stop_reason": "end_turn"}
    replies = [json.loads(r["msg"]) for r in raw if r["dir"] == "out"]
    assert any(r.get("id") == 99 and r["error"]["code"] == -32601 for r in replies)


def test_silent_devin_is_cancelled_and_fails(tmp_path):
    code, events, _ = _run(tmp_path, "hang", "--idle-timeout", "3")
    assert code == 1
    assert any("sent nothing over ACP" in e.get("text", "") for e in events)
    assert events[-1]["stop_reason"] == "cancelled"
