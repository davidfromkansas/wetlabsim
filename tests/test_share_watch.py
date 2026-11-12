"""A share-link viewer's page must load in the owner's private lab: requests that name no
session (catalog, logos, thumbnails) go to the shared session, and nothing else opens up."""
import pytest

from playground import labs, server as S


class _Sess:
    def __init__(self, sid, created, tok=None):
        self.id, self.created, self.share_token = sid, created, tok
        self.sim = self.runner = self.runners = self.bench = self.wetbench = self.board = None


@pytest.fixture
def private_lab(monkeypatch):
    monkeypatch.setattr(labs, "OWNER_USER", "user1")
    monkeypatch.setattr(labs, "OWNER_KEY", "ownerkey")
    monkeypatch.setattr(S, "SESSIONS", {"own1": _Sess("own1", 1), "shr2": _Sess("shr2", 2, "TOK")})


def _bind(path, cookie=""):
    h = S.PGHandler.__new__(S.PGHandler)
    h.token, h.path, h.headers = "evaltok", path, ({"Cookie": cookie} if cookie else {})
    errs = []
    h._err = lambda msg, code: errs.append(code)
    ok = h._bind_session()
    return (h.sess.id if ok else None), errs


def test_viewer_sessionless_requests_use_shared_session(private_lab):
    for path in ("/pg/catalog", "/static/anthropic.svg", "/pg/thumb/x.png"):
        assert _bind(path, "wl_watch=shr2.TOK") == ("shr2", [])
    assert _bind("/s/shr2/pg/scene", "wl_watch=shr2.TOK") == ("shr2", [])


def test_lab_stays_private(private_lab):
    assert _bind("/s/own1/pg/scene", "wl_watch=shr2.TOK") == (None, [403])
    assert _bind("/pg/catalog") == (None, [403])
    assert _bind("/pg/catalog", "wl_watch=shr2.WRONG") == (None, [403])
