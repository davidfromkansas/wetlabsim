"""The public site's labs: one private lab per visitor, each its own playground server (one
Modal container), plus a front server that hands labs out and lists what is live.

Shared state lives in two Modal Dicts (so every container sees it):
  wetlab-labs       lab id -> {url, owner, started, seen, runs: [live run summaries]}
  wetlab-run-slots  slot key -> start time, one per run in progress on any lab (at most
                    MAX_ACTIVE at once; a slot older than SLOT_TTL is a run that died, ignored)

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
SLOT_TTL = 420          # s: a run is at most 5 minutes; a slot this old belongs to a dead run
MAX_LABS = int(os.environ.get("WETLAB_MAX_LABS", "10"))
LAB_STALE = 90          # s: a lab that hasn't reported this long is gone

_last_request = time.time()
_dicts: dict = {}


def touch():
    """A request came in: the lab is in use."""
    global _last_request
    _last_request = time.time()


def idle_for() -> float:
    return time.time() - _last_request


def owner_ok(headers) -> bool:
    """Whether a request may change this lab (only its owner, by the key their link carries)."""
    if not OWNER_KEY:
        return True
    return secrets.compare_digest(headers.get("X-Lab-Key", ""), OWNER_KEY)


def _dict(name: str):
    if name not in _dicts:
        import modal
        _dicts[name] = modal.Dict.from_name(name, create_if_missing=True)
    return _dicts[name]


def shared() -> bool:
    return bool(LAB_ID)


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
    labs[LAB_ID] = {**cur, "url": LAB_URL, "seen": time.time(), "runs": runs,
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
    and nothing is running (the container then ends)."""
    def loop():
        while True:
            time.sleep(5)
            try:
                report(get_runs())
            except Exception as e:  # noqa: BLE001
                print("lab report failed:", e)
            if idle_for() > idle_minutes * 60 and not busy():
                print(f"lab {LAB_ID} idle for {idle_minutes} min: shutting down")
                forget()
                os._exit(0)
    threading.Thread(target=loop, daemon=True, name="lab-report").start()


# ------------------------------------------------------------------ the front
def claim_lab(owner: str) -> dict:
    """The lab for this visitor: theirs if it is still up, else a new one (if there is room).
    Returns {url, key} when ready, {pending: True} while it starts, or {full: True}."""
    import modal
    owners, keys, labs = _dict("wetlab-owners"), _dict("wetlab-lab-keys"), _dict("wetlab-labs")
    live = live_labs()
    lab = owners.get(owner)
    if lab and lab in live:
        info = live[lab]
        return {"url": info["url"], "key": keys.get(lab)} if info.get("url") else {"pending": True}
    if len(live) >= MAX_LABS:
        return {"full": True, "open": len(live), "max": MAX_LABS}
    lab, key = secrets.token_hex(4), secrets.token_urlsafe(24)
    owners[owner], keys[lab] = lab, key
    # Counted as open while it starts (it reports itself once its server is up).
    labs[lab] = {"url": "", "seen": time.time() + 120, "started": time.time(), "runs": []}
    modal.Function.from_name(os.environ.get("WETLAB_MODAL_APP", "wetlab-playground"), "lab").spawn(lab, key)
    return {"pending": True}


def live_list() -> dict:
    labs = live_labs()
    out = [{"lab": k, "url": v.get("url"), "runs": v.get("runs", [])} for k, v in labs.items() if v.get("url")]
    return {"labs": out, "open": len(labs), "max": MAX_LABS}
