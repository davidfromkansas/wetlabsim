"""Describe a scene / a photo with each kind of connection: Anthropic and OpenAI API keys
(streamed). Devin doesn't build scenes. No real model is called: the API calls are stood in for."""
import json

import pytest

from playground import photoscene as PS
from playground import scenegen as SG


def _creds(monkeypatch, kind="key", secret="k_test"):
    monkeypatch.setattr(SG, "_cred", lambda provider, public: (kind, secret))


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


def test_only_anthropic_and_openai_build_scenes(monkeypatch):
    monkeypatch.setattr(SG.ACCT, "connected", lambda: {"anthropic", "openai", "cognition", "typesafe"})
    ms = SG.models(public=True)
    assert {m["provider"] for m in ms} == {"anthropic", "openai"}
    assert not any(m["id"].startswith("swe-") for m in ms)
    assert json.dumps(ms)          # plain data for the page


def test_a_devin_model_is_refused(monkeypatch):
    _creds(monkeypatch)
    with pytest.raises(SG.ModelError, match="can't build scenes"):
        SG.ask_json("swe-2-max", "sys", "user", public=True)
