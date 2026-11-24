"""Describe a scene / a photo with each kind of connection: Anthropic and OpenAI API keys (streamed),
and a Devin key (Devin's CLI through the ACP bridge). No real model is called: the API calls are
stood in for, and Devin's CLI is a fake that answers over ACP."""
import json
import os
import sys

import pytest

from playground import photoscene as PS
from playground import scenegen as SG

# A fake `devin acp`: answers with a thought, then a reply that reports what it was sent
# (prompt length, a word from the end of the prompt, how many images) as a JSON plan.
FAKE = r'''#!{py}
import json, sys
def out(m): sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
def upd(kind, text):
    out({{"jsonrpc": "2.0", "method": "session/update", "params": {{"sessionId": "s1",
         "update": {{"sessionUpdate": kind, "content": {{"type": "text", "text": text}}}}}}}})
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "initialize":
        out({{"jsonrpc": "2.0", "id": m["id"], "result": {{}}}})
    elif m.get("method") == "session/new":
        out({{"jsonrpc": "2.0", "id": m["id"], "result": {{"sessionId": "s1"}}}})
    elif m.get("method") == "session/prompt":
        blocks = m["params"]["prompt"]
        text = blocks[0]["text"]
        imgs = [b for b in blocks if b["type"] == "image"]
        upd("agent_thought_chunk", "Thinking about the scene")
        ans = {{"n": len(text), "marker": "MARKER-END" in text, "images": len(imgs),
               "mime": imgs[0]["mimeType"] if imgs else ""}}
        upd("agent_message_chunk", "```json\n" + json.dumps(ans))
        upd("agent_message_chunk", "\n```")
        out({{"jsonrpc": "2.0", "id": m["id"], "result": {{"stopReason": "end_turn"}}}})
'''


@pytest.fixture
def fake_devin(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    f = bin_dir / "devin"
    f.write_text(FAKE.format(py=sys.executable))
    f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(SG, "WHERE", "local")


def test_devin_answers_a_prompt_too_big_for_a_command_line(fake_devin):
    big = "x" * 700_000 + " MARKER-END"         # bigger than any command-line limit
    thoughts, texts = [], []
    text = SG.devin_answer("swe-2-max", big, [], "dk_test", thoughts.append, texts.append, lambda: False, 60)
    ans = SG.parse_json(text)
    assert ans["n"] == len(big) and ans["marker"] and ans["images"] == 0
    assert any("Thinking about the scene" in t for t in thoughts)
    assert texts and texts[-1] == text


def test_devin_gets_the_photo(fake_devin):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    text = SG.devin_answer("swe-2-max", "photo please", [png], "dk_test", lambda t: None, lambda t: None,
                           lambda: False, 60)
    ans = SG.parse_json(text)
    assert ans["images"] == 1 and ans["mime"] == "image/png"


def test_no_devin_cli_is_a_plain_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(SG, "WHERE", "local")
    with pytest.raises(SG.ModelError, match="isn't installed"):
        SG.devin_answer("swe-2-max", "hi", [], "dk_test", lambda t: None, lambda t: None, lambda: False, 60)


def _creds(monkeypatch, kind="key", secret="k_test"):
    monkeypatch.setattr(SG, "_cred", lambda provider, public: (kind, secret))


def test_ask_json_routes_devin_models_to_devin(monkeypatch):
    _creds(monkeypatch)
    seen = {}

    def fake(model, prompt, images, key, on_think, on_text, stopped, timeout):
        seen.update(model=model, key=key, tail=prompt.endswith(SG.DEVIN_TAIL.strip()) or SG.DEVIN_TAIL in prompt)
        return '{"ok": 1}'
    monkeypatch.setattr(SG, "devin_answer", fake)
    assert SG.ask_json("swe-2-max", "sys", "user", public=True) == {"ok": 1}
    assert seen == {"model": "swe-2-max", "key": "k_test", "tail": True}


@pytest.mark.parametrize("model,stream", [("claude-opus-5-5", "_anthropic_stream"), ("gpt-6.2-astra", "_openai_stream")])
def test_ask_json_streams_api_keys(monkeypatch, model, stream):
    """API keys go through the streamed calls, so a long layout isn't cut off by a read timeout."""
    _creds(monkeypatch)
    seen = {}

    def fake(m, system, content, key, effort, on_think, on_text, stopped):
        seen.update(m=m, key=key, effort=effort, text=content[0]["text"])
        return 'Here it is: {"plan": 2}'
    monkeypatch.setattr(PS, stream, fake)
    assert SG.ask_json(model, "sys", "user words", public=True, effort="high") == {"plan": 2}
    assert seen == {"m": model, "key": "k_test", "effort": "high", "text": "user words"}


def test_photo_stream_routes_devin(monkeypatch):
    _creds(monkeypatch)
    got = {}

    def fake(model, prompt, images, key, on_think, on_text, stopped, timeout):
        got.update(images=images, sys=prompt.startswith("SYS"))
        return "<scene></scene>"
    monkeypatch.setattr(SG, "devin_answer", fake)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAEC"}},
               {"type": "text", "text": "a kitchen"}]
    shown = []
    out = PS.ask_stream("swe-2-high", content, True, "high", lambda t: None, shown.append, lambda: False, system="SYS")
    assert out == "<scene></scene>" and shown == ["<scene></scene>"]
    assert got == {"images": [b"\x00\x01\x02"], "sys": True}


def test_devin_is_offered_when_connected(monkeypatch):
    monkeypatch.setattr(SG.ACCT, "connected", lambda: {"cognition"})
    ms = SG.models(public=True)
    assert [m["id"] for m in ms] == ["swe-2-max", "swe-2-high", "swe-2-medium"]
    assert ms[0]["default"] and not ms[1]["default"]
    assert json.dumps(ms)          # plain data for the page
