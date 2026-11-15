"""Sessions still open somewhere else (another lab, e.g. an older build's) stay out of "Older
sessions", and an older build's lab closes soon after a newer one is out even if a tab polls it."""
import time

import playground.labs as LABS
import playground.server as srv


def test_recently_saved_session_is_hidden(monkeypatch):
    now = time.time()
    rows = [{"session_id": "a" * 36, "session_name": "Fresh", "saved": now - 5},
            {"session_id": "b" * 36, "session_name": "Old", "saved": now - 3600},
            {"session_id": "c" * 36, "session_name": "Open here", "saved": now - 3600}]
    monkeypatch.setattr(srv.SAVE, "enabled", lambda: True)
    monkeypatch.setattr(srv.SAVE, "list_sessions", lambda n: rows)
    srv._OLDER["t"] = 0.0
    out = srv._older_sessions({"c" * 36})
    assert [o["name"] for o in out] == ["Old"]


def test_stale_lab_closes_after_grace_even_while_polled(monkeypatch):
    exits, saved = [], []

    class Done(Exception):
        pass

    def fake_exit(code):
        exits.append(code)
        raise Done

    clock = {"t": 1000.0}
    monkeypatch.setattr(LABS.time, "time", lambda: clock["t"])
    monkeypatch.setattr(LABS.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(LABS, "report", lambda runs: None)
    monkeypatch.setattr(LABS, "forget", lambda: None)
    monkeypatch.setattr(LABS, "current_build", lambda: "20991231-000000-new")
    monkeypatch.setattr(LABS, "BUILD", "20260101-000000-old")
    monkeypatch.setattr(LABS, "idle_for", lambda: 0.0)       # a tab keeps polling
    monkeypatch.setattr(LABS.os, "_exit", fake_exit)
    started = {}

    class T:
        def __init__(self, target, **kw):
            started["f"] = target

        def start(self):
            pass
    monkeypatch.setattr(LABS.threading, "Thread", T)
    LABS.start_reporting(lambda: [], 5.0, lambda: False, before_exit=lambda: saved.append(clock["t"]))
    t0 = clock["t"]
    try:
        started["f"]()
    except Done:
        pass
    assert exits == [0] and saved
    assert LABS.STALE_GRACE <= clock["t"] - t0 <= LABS.STALE_GRACE + 15
