"""One-time copy of runs recorded before saving existed into the website: a runs row (and its
run_files) in the database and the run's files in private Blob, owned by one account.

    .venv/bin/modal volume get wetlab-playground-runs runs ./old-runs     # the public site's runs
    DATABASE_URL=... LAB_LINK_SECRET=... WETLAB_WEBSITE_URL=https://wetlab-playground.vercel.app \\
      .venv/bin/python scripts/copy_old_runs.py ./old-runs --owner <Clerk user id> [--dry-run]

Old runs have no workspace_start.json, so the starter kit is told apart by name: robot_model/,
datasheets/ and the docs every run is given are left out; everything else in the workspace is the
agent's. Runs already copied are skipped.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from playground import savestore as S  # noqa: E402

KIT_DIRS = {"robot_model", "datasheets"}
KIT_FILES = {"AGENTS.md", "CLAUDE.md", "COMMANDS.md", "ROBOT_MANUAL.md", "SITE.md", "GOAL.md", "cameras.json"}


def old_manifest(run_dir: pathlib.Path, run: dict) -> dict:
    """A stand-in for workspace_start.json: the kit's files by name, so ai_files skips them."""
    import hashlib
    ws, files = run_dir / "workspace", {}
    for p in ws.rglob("*") if ws.is_dir() else []:
        rel = p.relative_to(ws)
        if p.is_file() and (rel.parts[0] in KIT_DIRS or str(rel) in KIT_FILES):
            files[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"robot_type": run.get("robot"), "docs": run.get("docs"), "robot_kit_version": None, "files": files}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", help="a folder of run folders (as on the Modal volume's runs/)")
    ap.add_argument("--owner", required=True, help="the Clerk user id the runs belong to")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    S.OWNER_USER = a.owner
    done = {r["run_id"] for r in S.sql("select run_id from runs")}
    for run_dir in sorted(p for p in pathlib.Path(a.runs).iterdir() if (p / "run.json").is_file()):
        run_id = run_dir.name
        if run_id in done:
            continue
        run = json.loads((run_dir / "run.json").read_text())
        result = json.loads((run_dir / "result.json").read_text()) if (run_dir / "result.json").is_file() else {}
        if not (run_dir / "workspace_start.json").exists():
            (run_dir / "workspace_start.json").write_text(json.dumps(old_manifest(run_dir, run)))
        files = S.ai_files(run_dir)
        print(f"{run_id}: {run.get('robot')} · {run.get('model_label') or run.get('model')} · {len(files)} file(s) by the agent")
        if a.dry_run:
            continue
        folder = S.upload_run(run_dir, run_id, files)
        started = run.get("sim_start") or result.get("wall_reset")
        S.record_run({"run_id": run_id, "session_id": None, "robot_station_id": None, "robot_type": run.get("robot"),
                      "robot_kit_version": None, "started_by_user_id": a.owner, "ai_provider": run.get("agent"),
                      "ai_model": run.get("model") or run.get("model_label"), "task_prompt": run.get("task"),
                      "run_outcome": result.get("status") or run.get("status"), "started_at": started,
                      "ended_at": (started + run["wall_seconds"]) if started and run.get("wall_seconds") else None,
                      "cost_usd": result.get("cost_usd", run.get("cost_usd")), "blob_folder_path": folder})
        S.record_files(run_id, files)


if __name__ == "__main__":
    main()
