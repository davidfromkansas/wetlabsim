"""Devin's login from an organization key: a service user's API key (DEVIN_API_KEY), written where
the Devin CLI keeps its login, so Devin runs with no browser sign-in (checked 2026-11-09 with
Devin CLI 3000.12.32: the CLI reads the key from this file, not from the environment).
"""
from __future__ import annotations

import os
import pathlib

# Devin's own servers: the only addresses the CLI needs for a run (checked in a Modal Sandbox
# allowed these three and nothing else).
HOSTS = ["server.codeium.com", "api.devin.ai", "app.devin.ai"]


def key() -> str:
    return os.environ.get("DEVIN_API_KEY", "")


def credentials(api_key: str) -> str:
    return (f'windsurf_api_key = "{api_key}"\n'
            f'api_server_url = "https://{HOSTS[0]}"\n'
            f'devin_webapp_host = "{HOSTS[2]}"\n'
            f'devin_api_url = "https://{HOSTS[1]}"\n')


def write_login(data_home: pathlib.Path, api_key: str) -> pathlib.Path:
    """The login under data_home (Devin's XDG_DATA_HOME), readable by this user only."""
    d = data_home / "devin"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "credentials.toml"
    f.touch(mode=0o600)
    f.write_text(credentials(api_key))
    return f
