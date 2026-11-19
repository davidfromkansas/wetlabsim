"""A signed-in account's container answers once its newest saved session is open; the others
open in the background (listed as loading, kept out of "Older sessions", and waited for, not
opened twice, when asked for meanwhile). Big text replies go gzipped."""
import gzip
import threading
import time

import playground.server as srv


class FakeSim:
    stations, placed = [], []


class FakeSess:
    def __init__(self, row):
        self.db_id, self.sim = row["session_id"], FakeSim()
        self.used = self.created = time.time()


def test_newest_first_rest_in_background(monkeypatch):
    rows = [{"session_id": c * 36, "session_name": c} for c in "abcd"]
    gate = threading.Event()
    built = []

    def from_row(row):
        if row["session_id"] != rows[0]["session_id"]:
            gate.wait(5)
        s = FakeSess(row)
        srv.SESSIONS[row["session_id"][:6]] = s
        built.append(row["session_id"])
        return s

    class Auto:
        started = False

        def __init__(self, *a):
            pass

        def start(self):
            Auto.started = True
    monkeypatch.setattr(srv.SAVE, "load_sessions", lambda n: rows)
    monkeypatch.setattr(srv.SAVE, "Autosaver", Auto)
    monkeypatch.setattr(srv, "_from_row", from_row)
    monkeypatch.setattr(srv, "SESSIONS", {})
    assert srv._load_saved() == 1
    assert built == ["a" * 36] and set(srv._LOADING) == {c * 36 for c in "bcd"} and not Auto.started
    # Older sessions leave out the ones still loading.
    monkeypatch.setattr(srv.SAVE, "enabled", lambda: True)
    monkeypatch.setattr(srv.SAVE, "list_sessions", lambda n: [{**r, "saved": 0} for r in rows])
    srv._OLDER["t"] = 0.0
    assert srv._older_sessions({"a" * 36}) == []
    # Asking for one still loading waits for it instead of building a second copy.
    got = {}
    t = threading.Thread(target=lambda: got.setdefault("s", srv.open_saved("c" * 36)))
    t.start()
    time.sleep(0.2)
    assert "s" not in got
    gate.set()
    t.join(5)
    assert got["s"].db_id == "c" * 36 and built.count("c" * 36) == 1
    for _ in range(50):
        if Auto.started:
            break
        time.sleep(0.05)
    assert Auto.started and not srv._LOADING
    # Listed under the newest one, in saved order.
    by = {s.db_id: s.used for s in srv.SESSIONS.values()}
    assert by["a" * 36] > by["b" * 36] > by["c" * 36] > by["d" * 36]


def test_big_text_is_gzipped():
    sent = {}

    class H(srv.PGHandler):
        def __init__(self, enc):
            self.headers = {"Accept-Encoding": enc}

        def send_response(self, code):
            sent["code"] = code

        def send_header(self, k, v):
            sent[k] = v

        def end_headers(self):
            pass

        class wfile:
            @staticmethod
            def write(b):
                sent["body"] = b
    body = b'{"x": "' + b"a" * 20000 + b'"}'
    H("gzip, br")._send(200, body)
    assert sent["Content-Encoding"] == "gzip" and gzip.decompress(sent["body"]) == body
    sent.clear()
    H("")._send(200, body)
    assert "Content-Encoding" not in sent and sent["body"] == body
    sent.clear()
    H("gzip")._send(200, b"x" * 20000, "image/png")
    assert "Content-Encoding" not in sent
