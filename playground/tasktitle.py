"""A run's task name: a summary of its task in fewer than six words, written by Claude Haiku, for
the run tag over the robot and the Gallery. It is made once per task (in the background, so a
run never waits for it) and kept with the run, so it stays after the run ends and is replaced
when the robot's next task starts.

The key is the owner's own Anthropic key (Settings > General); on a computer of one's own,
ANTHROPIC_API_KEY too. With neither (or if the call fails) the name is the task's first words."""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request

MODEL = "claude-haiku-5-5"
_CACHE: dict[str, str] = {}
_LOCK = threading.Lock()
PROMPT = ("Name this robot task in at most 5 words, like a short title (for example: \"Stack the red blocks\"). "
          "Answer with the title only, no quotes or punctuation at the end.\n\nTask: ")


def fallback(task: str) -> str:
    words = re.sub(r"\s+", " ", task).strip().split(" ")
    return " ".join(words[:5]).rstrip(".,;:!?") + ("…" if len(words) > 5 else "")


def _clean(text: str) -> str:
    t = text.strip().splitlines()[0] if text.strip() else ""
    t = t.strip().strip('"\'“”‘’*#').strip().rstrip(".!")
    words = t.split()
    return " ".join(words[:5])


def _ask(task: str, key: str) -> str:
    body = json.dumps({"model": MODEL, "max_tokens": 30,
                       "messages": [{"role": "user", "content": PROMPT + task[:2000]}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.loads(r.read())
    return _clean("".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text"))


def make(task: str, key: str, public: bool, done) -> None:
    """Calls done(title) with the task's name: at once if it is known, else from a thread."""
    task = (task or "").strip()
    if not task:
        return
    with _LOCK:
        if task in _CACHE:
            return done(_CACHE[task])
    key = key or ("" if public else os.environ.get("ANTHROPIC_API_KEY", ""))

    def work():
        title = ""
        if key:
            try:
                title = _ask(task, key)
            except Exception as e:  # noqa: BLE001
                print("could not name the task:", e)
        if not title:
            title = fallback(task)
        else:
            with _LOCK:
                _CACHE[task] = title
        done(title)
    threading.Thread(target=work, daemon=True, name="task-title").start()
