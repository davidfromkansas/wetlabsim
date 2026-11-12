"""The makers' own documents for each robot, as the agent gets them.

The files are the makers', unchanged. Their sources and checksums are in
agent/datasheets/sources.json (Franka), agent/aloha/datasheets/sources.json (ALOHA) and
agent/fr3_duo/datasheets/sources.json (FR3 Duo);
this fetches any that are missing and checks them:

    python -m wetlabsim.datasheets
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.request

AGENT = pathlib.Path(__file__).resolve().parent.parent / "agent"
DIRS = {"franka": AGENT / "datasheets", "aloha": AGENT / "aloha" / "datasheets",
        "fr3_duo": AGENT / "fr3_duo" / "datasheets"}
DIR = DIRS["franka"]


def sources(robot: str = "franka") -> list[dict]:
    return json.loads((DIRS[robot] / "sources.json").read_text())


def fetch(strict: bool = True, robot: str = "franka") -> list[pathlib.Path]:
    """Make sure every document is present. A PDF whose checksum doesn't match is an error;
    web pages are live, so a changed checksum there is only reported."""
    out = []
    for s in sources(robot):
        path = DIRS[robot] / s["file"]
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
    for robot in DIRS:
        for p in fetch(robot=robot):
            print("ok", robot, p.name)
