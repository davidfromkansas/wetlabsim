"""The public site's labs: one private lab per visitor, each its own playground server (one
Modal container), plus a front server that hands labs out and lists what is live.

Shared state lives in two Modal Dicts (so every container sees it):
  wetlab-labs       lab id -> {url, owner, started, seen, runs: [live run summaries]}
  wetlab-run-slots  slot key -> start time, one per run in progress on any lab (at most
                    MAX_ACTIVE at once; a slot older than SLOT_TTL is a run that died, ignored)
  wetlab-build      "current" -> the build the front runs (each deploy is a new build)

A lab started by an older deploy keeps running the old code (a deploy doesn't stop running
labs), so the front never hands one out again, and the lab itself, once it sees a newer build,
tells its page to go back to the front and shuts down as soon as nothing is running in it.

Locally (no Modal) none of this is used: no owner key, no idle exit, no shared slots.
"""
from __future__ import annotations

import os
import secrets
import threading
import time

LAB_ID = os.environ.get("WETLAB_LAB_ID", "")
OWNER_KEY = os.environ.get("WETLAB_OWNER_KEY", "")
LAB_URL = os.environ.get("WETLAB_LAB_URL", "")
FRONT_URL = os.environ.get("WETLAB_FRONT_URL", "")
BUILD = os.environ.get("WETLAB_BUILD", "")
# Signed in on the website (Vercel): the lab's owner is that account, and the website and the
# labs share LAB_LINK_SECRET (the "lab for user" request, and the one-time pass into the lab).
OWNER_USER = os.environ.get("WETLAB_OWNER_USER", "")
LINK_SECRET = os.environ.get("LAB_LINK_SECRET", "")
# A second copy of the site (staging) keeps its own registry: its Modal Dicts carry this prefix.
DICT_PREFIX = os.environ.get("WETLAB_DICT_PREFIX", "")
SLOT_TTL = 420          # s: a run is at most 5 minutes; a slot this old belongs to a dead run
MAX_LABS = int(os.environ.get("WETLAB_MAX_LABS", "10"))
LAB_STALE = 90          # s: a lab that hasn't reported this long is gone

_last_request = time.time()
_dicts: dict = {}
_stale = False
_announced = False


def touch():
    """A request came in: the lab is in use."""
    global _last_request
    _last_request = time.time()


def idle_for() -> float:
    return time.time() - _last_request


# Real use: the owner clicking, dragging, typing or scrolling (the page polling doesn't count).
_last_active = time.time()
_idle_limit: float | None = None      # seconds; set on the hosted site only


def active():
    global _last_active
    _last_active = time.time()


def idle_left() -> float | None:
    """Seconds until this lab closes for lack of use (None where labs don't close)."""
    if _idle_limit is None:
        return None
    return max(0.0, _idle_limit - (time.time() - _last_active))


def owner_ok(headers) -> bool:
    """Whether a request may change this lab: only its owner, by the key their link carries or
    the cookie the one-time pass set (signed in on the website)."""
    if not OWNER_KEY:
        return True
    import http.cookies
    c = http.cookies.SimpleCookie(headers.get("Cookie", ""))
    key = headers.get("X-Lab-Key", "") or (c["wl_lab"].value if "wl_lab" in c else "")
    return secrets.compare_digest(key, OWNER_KEY)


# ------------------------------------------------------------------ signed-in owners
def link_ok(given: str) -> bool:
    """The website's request (it knows LAB_LINK_SECRET); without the secret nobody is."""
    return bool(LINK_SECRET) and secrets.compare_digest(given, LINK_SECRET)


_used_passes: set = set()


def signed(token: str) -> dict | None:
    """What a pass from the website says, if it is signed with LAB_LINK_SECRET and not expired.
    Format: base64url(json).base64url(hmac-sha256)."""
    import base64
    import hashlib
    import hmac
    import json
    if not (LINK_SECRET and "." in token):
        return None
    body, sig = token.rsplit(".", 1)
    want = base64.urlsafe_b64encode(hmac.new(LINK_SECRET.encode(), body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    if not secrets.compare_digest(sig, want):
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:  # noqa: BLE001
        return None
    return d if isinstance(d, dict) and float(d.get("exp", 0)) >= time.time() else None


def pass_ok(token: str) -> bool:
    """The owner's one-time pass into this lab: for this lab and its owner, used once."""
    d = signed(token)
    if not (d and OWNER_USER) or d.get("k") or d.get("l") != LAB_ID or d.get("u") != OWNER_USER or d.get("n") in _used_passes:
        return False
    _used_passes.add(d.get("n"))
    return True


def watch_pass(token: str) -> dict | None:
    """A share link's pass into this lab (view only): {"w": session, "t": its share token}."""
    d = signed(token)
    return d if d and d.get("k") == "watch" and d.get("l") == LAB_ID and d.get("w") and d.get("t") else None


def view_pass(token: str) -> str | None:
    """A pass to replay one finished run (the owner's, or a shared one): its run id."""
    d = signed(token or "")
    return d.get("r") if d and d.get("k") == "view" and d.get("r") else None


def _dict(name: str):
    if name not in _dicts:
        import modal
        _dicts[name] = modal.Dict.from_name(DICT_PREFIX + name, create_if_missing=True)
    return _dicts[name]


def shared() -> bool:
    return bool(LAB_ID)


# ------------------------------------------------------------------ builds
def older(a: str, b: str) -> bool:
    """Build a is from an earlier deploy than b (builds are YYYYmmdd-HHMMSS-<commit>, so they sort
    by time). During a deploy the old front can still answer for a while: it must not treat the
    new build's labs as stale, nor move "current" back."""
    return bool(a and b) and a < b


def announce_build():
    """The front: this is the current build (once per front process; never an older one)."""
    global _announced
    if BUILD and not _announced:
        d = _dict("wetlab-build")
        if not older(BUILD, d.get("current", "")):
            d["current"] = BUILD
        _announced = True


def current_build() -> str:
    try:
        return _dict("wetlab-build").get("current", "")
    except Exception as e:  # noqa: BLE001
        print("current build unreadable:", e)
        return ""


def stale() -> bool:
    """This lab runs an older build than the front (as of its last report)."""
    return _stale


# ------------------------------------------------------------------ run slots
def slots_in_use() -> int:
    now = time.time()
    try:
        return sum(1 for _, t in _dict("wetlab-run-slots").items() if now - float(t) < SLOT_TTL)
    except Exception as e:  # noqa: BLE001
        print("run slots unreadable:", e)
        return 0


def take_slot() -> str:
    key = f"{LAB_ID}:{secrets.token_hex(4)}"
    _dict("wetlab-run-slots")[key] = time.time()
    return key


def free_slot(key: str | None):
    if key:
        try:
            _dict("wetlab-run-slots").pop(key, None)
        except Exception as e:  # noqa: BLE001
            print("could not free a run slot:", e)


# ------------------------------------------------------------------ lab registry
def report(runs: list[dict]):
    """This lab is alive, at LAB_URL, with these runs going (for the front's Live now list)."""
    labs = _dict("wetlab-labs")
    cur = labs.get(LAB_ID) or {}
    labs[LAB_ID] = {**cur, "url": LAB_URL, "seen": time.time(), "runs": runs, "build": BUILD, "owner_user": OWNER_USER,
                    "started": cur.get("started", time.time())}


def forget():
    try:
        _dict("wetlab-labs").pop(LAB_ID, None)
    except Exception:  # noqa: BLE001
        pass


def live_labs() -> dict:
    now = time.time()
    return {k: v for k, v in _dict("wetlab-labs").items() if now - v.get("seen", 0) < LAB_STALE}


def start_reporting(get_runs, idle_minutes: float, busy):
    """Report to the registry every few seconds; exit when nobody has looked for idle_minutes
    and nothing is running (the container then ends), or, once a newer build is out, as soon as
    nothing is running and the page has gone (it is told to, see stale())."""
    global _idle_limit
    _idle_limit = idle_minutes * 60
    active()

    def loop():
        global _stale
        while True:
            time.sleep(5)
            try:
                report(get_runs())
            except Exception as e:  # noqa: BLE001
                print("lab report failed:", e)
            cur = current_build()
            _stale = older(BUILD, cur)
            if _stale and not busy() and idle_for() > 15:
                print(f"lab {LAB_ID} is build {BUILD}, the site is on {cur}: shutting down")
                forget()
                os._exit(0)
            if busy():
                active()          # a run (or one waiting in line) counts as use
            elif idle_left() <= 0:
                print(f"lab {LAB_ID}: no activity for {idle_minutes} min: shutting down")
                forget()
                os._exit(0)
    threading.Thread(target=loop, daemon=True, name="lab-report").start()


# ------------------------------------------------------------------ the front
def claim_lab(owner: str, user: str = "") -> dict:
    """The lab for this visitor: theirs if it is still up and on this build, else a new one (if
    there is room). Returns {url, key} when ready, {pending: True} while it starts, or {full: True}."""
    import modal
    announce_build()
    owners, keys, labs = _dict("wetlab-owners"), _dict("wetlab-lab-keys"), _dict("wetlab-labs")
    live = live_labs()
    lab = owners.get(owner)
    # A lab still starting is the account's lab whichever build it was asked for (during a deploy
    # the old and new fronts both answer); once up, one from an older build is replaced.
    if lab and lab in live and (not live[lab].get("url") or not older(live[lab].get("build", ""), BUILD)):
        info = live[lab]
        return {"url": info["url"], "key": keys.get(lab), "lab": lab} if info.get("url") else {"pending": True}
    # An older build's lab with nothing running is on its way out: it doesn't take a place.
    open_labs = [k for k, v in live.items() if not older(v.get("build", ""), BUILD) or v.get("runs")]
    if len(open_labs) >= MAX_LABS:
        return {"full": True, "open": len(open_labs), "max": MAX_LABS}
    lab, key = secrets.token_hex(4), secrets.token_urlsafe(24)
    owners[owner], keys[lab] = lab, key
    # Counted as open while it starts (it reports itself once its server is up).
    labs[lab] = {"url": "", "seen": time.time() + 120, "started": time.time(), "runs": [], "build": BUILD}
    modal.Function.from_name(os.environ.get("WETLAB_MODAL_APP", "wetlab-playground"), "lab").spawn(lab, key, user)
    return {"pending": True}


def live_list(user: str | None = None) -> dict:
    """What is running now: every lab's runs, or (user) only that signed-in account's (labs are
    private; the website asks for the signed-in person's own)."""
    labs = live_labs()
    out = [{"lab": k, "url": v.get("url"), "runs": v.get("runs", [])} for k, v in labs.items()
           if v.get("url") and (user is None or v.get("owner_user") == user)]
    return {"labs": out, "open": len(labs), "max": MAX_LABS}


def lab_of_user(user: str) -> dict:
    """A signed-in account's lab if it is up (nothing is started): {url, lab} or {closed: True}."""
    lab = _dict("wetlab-owners").get("user:" + user)
    info = live_labs().get(lab) if lab else None
    return {"url": info["url"], "lab": lab} if info and info.get("url") and not older(info.get("build", ""), BUILD) else {"closed": True}
