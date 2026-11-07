"""Franka's official documents for the robot, as the agent gets them.

The PDFs are Franka's, unchanged. Their sources and checksums are in
agent/datasheets/sources.json; this fetches any that are missing and checks them:

    python -m wetlabsim.datasheets
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.request

DIR = pathlib.Path(__file__).resolve().parent.parent / "agent" / "datasheets"


def sources() -> list[dict]:
    return json.loads((DIR / "sources.json").read_text())


def fetch(strict: bool = True) -> list[pathlib.Path]:
    """Make sure every document is present. A PDF whose checksum doesn't match is an error;
    the FCI page is a live web page, so a changed checksum there is only reported."""
    out = []
    for s in sources():
        path = DIR / s["file"]
        if not path.exists():
            req = urllib.request.Request(s["url"], headers={"User-Agent": "wetlabsim"})
            with urllib.request.urlopen(req, timeout=60) as r:
                path.write_bytes(r.read())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != s["sha256"]:
            msg = f"{s['file']}: checksum {digest} differs from the recorded {s['sha256']}"
            if strict and path.suffix == ".pdf":
                raise RuntimeError(msg + f" (source: {s['url']})")
            print("note:", msg)
        out.append(path)
    return out


if __name__ == "__main__":
    for p in fetch():
        print("ok", p.name)
