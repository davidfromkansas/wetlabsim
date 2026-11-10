"""Saved sessions and run records in the website's database (Neon Postgres, DATABASE_URL), for a
lab owned by a signed-in account (WETLAB_OWNER_USER, see labs.py). Without both, nothing is saved
and the playground works as before (locally, or on the public site without sign-in).

Tables (web/db/schema.sql): users, sessions (a saved lab: scene_layout, unsent_tasks, save_version),
runs (one AI task on one robot: robot_type and robot_kit_version name the starter kit it was given,
which lives in the repo and is never stored per run), run_files (one row per file the AI wrote).

Neon answers SQL over HTTPS (https://api.<host>/sql, as its serverless driver does), so this needs
no database driver.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OWNER_USER = os.environ.get("WETLAB_OWNER_USER", "")
# Tests use their own schema in the same database (WETLAB_DB_SCHEMA), never the live tables.
SCHEMA = os.environ.get("WETLAB_DB_SCHEMA", "")


def enabled() -> bool:
    return bool(DATABASE_URL and OWNER_USER)


def _endpoint() -> str:
    host = urllib.parse.urlparse(DATABASE_URL).hostname or ""
    return "https://" + re.sub(r"^[^.]+\.", "api.", host) + "/sql"


def sql(query: str, params: list | None = None) -> list[dict]:
    """Run one statement; rows as dicts (json/jsonb columns already parsed)."""
    one = {"query": query, "params": params or []}
    body = ({"queries": [{"query": f'set local search_path to "{SCHEMA}"', "params": []}, one]}
            if SCHEMA and re.match(r"^\w+$", SCHEMA) else one)
    req = urllib.request.Request(_endpoint(), method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Neon-Connection-String": DATABASE_URL})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.loads(r.read())
    return (out["results"][-1] if "results" in out else out).get("rows", [])


# ------------------------------------------------------------------ sessions
def load_sessions(limit: int) -> list[dict]:
    """The owner's saved sessions, most recently saved first."""
    return sql("""select session_id::text, session_name, scene_layout, unsent_tasks, save_version
                  from sessions where owner_user_id = $1 and deleted_at is null
                  order by last_saved_at desc limit $2""", [OWNER_USER, limit])


def load_session(session_id: str) -> dict | None:
    rows = sql("""select session_id::text, session_name, scene_layout, unsent_tasks, save_version
                  from sessions where session_id = $1::uuid and owner_user_id = $2 and deleted_at is null""",
               [session_id, OWNER_USER])
    return rows[0] if rows else None


def save_session(session_id: str, name: str, layout: dict, unsent: dict) -> int:
    """Insert or update a session; returns its new save_version."""
    rows = sql("""insert into sessions (session_id, owner_user_id, session_name, scene_layout, unsent_tasks)
                  values ($1::uuid, $2, $3, $4::jsonb, $5::jsonb)
                  on conflict (session_id) do update set session_name = excluded.session_name,
                    scene_layout = excluded.scene_layout, unsent_tasks = excluded.unsent_tasks,
                    save_version = sessions.save_version + 1, last_saved_at = now()
                  where sessions.owner_user_id = excluded.owner_user_id
                  returning save_version""",
               [session_id, OWNER_USER, name, json.dumps(layout), json.dumps(unsent)])
    return int(rows[0]["save_version"]) if rows else 0


def opened(session_id: str):
    sql("update sessions set last_opened_at = now() where session_id = $1::uuid and owner_user_id = $2",
        [session_id, OWNER_USER])


class Autosaver:
    """Saves each of the owner's sessions a few seconds after it changes (and never only at the
    end: a container can stop without warning). snapshot(sess) -> (db_id, name, layout, unsent)."""

    def __init__(self, sessions, snapshot, every: float = 3.0):
        self.sessions, self.snapshot, self.every = sessions, snapshot, every
        self.last: dict[str, str] = {}

    def seed(self, db_id: str, name: str, layout: dict, unsent: dict):
        """A session just loaded from the database: it is saved as it is."""
        self.last[db_id] = json.dumps([name, layout, unsent], sort_keys=True)

    def tick(self):
        for sess in self.sessions():
            try:
                db_id, name, layout, unsent = self.snapshot(sess)
            except Exception as e:  # noqa: BLE001
                print("autosave: could not read a session:", e)
                continue
            key = json.dumps([name, layout, unsent], sort_keys=True)
            if self.last.get(db_id) == key:
                continue
            try:
                save_session(db_id, name, layout, unsent)
                self.last[db_id] = key
            except Exception as e:  # noqa: BLE001
                print("autosave failed (will retry):", e)

    def start(self):
        def loop():
            while True:
                time.sleep(self.every)
                self.tick()
        threading.Thread(target=loop, daemon=True, name="autosave").start()


# ------------------------------------------------------------------ runs
def record_run(run: dict):
    """A run's row (insert at start, update at the end): keys are the runs columns."""
    cols = ["run_id", "session_id", "robot_station_id", "robot_type", "robot_kit_version", "started_by_user_id",
            "ai_provider", "ai_model", "task_prompt", "run_outcome", "started_at", "ended_at", "cost_usd",
            "blob_folder_path"]
    vals = [run.get(c) for c in cols]
    sql(f"""insert into runs ({", ".join(cols)}) values ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10,
                to_timestamp($11), to_timestamp($12), $13, $14)
            on conflict (run_id) do update set run_outcome = excluded.run_outcome, ended_at = excluded.ended_at,
                cost_usd = excluded.cost_usd, blob_folder_path = coalesce(excluded.blob_folder_path, runs.blob_folder_path)""",
        vals)


LANGUAGES = {".py": "python", ".md": "markdown", ".txt": "text", ".json": "json", ".jsonl": "json", ".sh": "shell",
             ".js": "javascript", ".ts": "typescript", ".yaml": "yaml", ".yml": "yaml", ".csv": "csv", ".toml": "toml",
             ".png": "image", ".jpg": "image", ".jpeg": "image"}
CODE_TEXT_MAX = 100_000


def ai_files(run_dir) -> list[dict]:
    """What the agent wrote or changed in its workspace: every file that wasn't in its starting
    kit (workspace_start.json) or differs from it, saved images included. Text files under
    100 KB carry their text (code_text), so code can be searched across runs."""
    import hashlib
    import pathlib
    run_dir = pathlib.Path(run_dir)
    ws = run_dir / "workspace"
    try:
        start = json.loads((run_dir / "workspace_start.json").read_text()).get("files", {})
    except (OSError, ValueError):
        start = {}
    out = []
    for p in sorted(ws.rglob("*")) if ws.is_dir() else []:
        if not p.is_file():
            continue
        rel = str(p.relative_to(ws))
        data = p.read_bytes()
        if start.get(rel) == hashlib.sha256(data).hexdigest():
            continue                  # part of the starter kit, as given
        text = None
        if len(data) <= CODE_TEXT_MAX and LANGUAGES.get(p.suffix.lower()) != "image":
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
        out.append({"file_path": rel, "language": LANGUAGES.get(p.suffix.lower(), p.suffix.lower().lstrip(".") or None),
                    "size_bytes": len(data), "line_count": text.count("\n") + (1 if text and not text.endswith("\n") else 0)
                    if text is not None else None, "code_text": text, "blob_file_path": None})
    return out


# The run's own record, uploaded with the agent's files (the replay viewer and the website read
# them). Text records are gzipped: the robot's states compress about tenfold.
RUN_RECORD_FILES = ["task.txt", "run.json", "result.json", "events.json", "command.json", "model.ref",
                    "workspace_start.json", "transcript.jsonl", "states.jsonl", "replay.npz"]
UPLOAD_MAX = 4_000_000          # the website takes at most 4.5 MB a request
WEBSITE_URL = os.environ.get("WETLAB_WEBSITE_URL", "")


def blob_enabled() -> bool:
    return bool(WEBSITE_URL and os.environ.get("LAB_LINK_SECRET"))


def _upload(run_id: str, path: str, data: bytes, content_type: str) -> bool:
    q = urllib.parse.urlencode({"run": run_id, "path": path})
    req = urllib.request.Request(f"{WEBSITE_URL}/api/internal/run-file?{q}", data=data, method="POST",
                                 headers={"Content-Type": content_type, "X-Link-Secret": os.environ["LAB_LINK_SECRET"]})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status == 200


def upload_run(run_dir, run_id: str, files: list[dict]) -> str | None:
    """A finished run's files into private Blob (through the website) at runs/<run id>/: its
    record (text gzipped) and workspace/<path> for each file the agent wrote or changed. Sets
    each file's blob_file_path; returns the run's folder, or None when nothing could be sent."""
    import gzip
    import mimetypes
    import pathlib
    if not blob_enabled():
        return None
    run_dir, sent = pathlib.Path(run_dir), 0
    for name in RUN_RECORD_FILES:
        p = run_dir / name
        if not p.is_file():
            continue
        data, path, ctype = p.read_bytes(), name, "application/octet-stream"
        if not name.endswith(".npz"):
            data, path, ctype = gzip.compress(data), name + ".gz", "application/gzip"
        if len(data) > UPLOAD_MAX:
            print(f"run {run_id}: {name} is too big to upload ({len(data)} bytes)")
            continue
        try:
            sent += _upload(run_id, path, data, ctype)
        except Exception as e:  # noqa: BLE001
            print(f"run {run_id}: could not upload {name}:", e)
    for f in files:
        p = run_dir / "workspace" / f["file_path"]
        data = p.read_bytes()
        if len(data) > UPLOAD_MAX:
            print(f"run {run_id}: {f['file_path']} is too big to upload ({len(data)} bytes)")
            continue
        try:
            if _upload(run_id, f"workspace/{f['file_path']}", data,
                       mimetypes.guess_type(p.name)[0] or "application/octet-stream"):
                f["blob_file_path"] = f"runs/{run_id}/workspace/{f['file_path']}"
                sent += 1
        except Exception as e:  # noqa: BLE001
            print(f"run {run_id}: could not upload {f['file_path']}:", e)
    return f"runs/{run_id}/" if sent else None


def record_files(run_id: str, files: list[dict]):
    """run_files rows for what the AI wrote: file_path, language, size_bytes, line_count, code_text, blob_file_path."""
    sql("delete from run_files where run_id = $1", [run_id])
    for f in files:
        sql("""insert into run_files (run_id, file_path, language, size_bytes, line_count, code_text, blob_file_path)
               values ($1, $2, $3, $4, $5, $6, $7)""",
            [run_id, f["file_path"], f.get("language"), f.get("size_bytes"), f.get("line_count"), f.get("code_text"),
             f.get("blob_file_path")])
