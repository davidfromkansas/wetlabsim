"""One past run, for its results page (the Results tab: click a run).

Everything the page shows comes from what the run already saved in its folder:

    result.json / run.json   model, tokens, cost, time, status, safety stops
    transcript.jsonl         what the AI said, thought, ran and looked at (every agent's own
                             format, read through wetlabsim.traces), each line on the robot clock
    events.json              the robot's own log: moves, gripper, cameras, safety stops
    workspace/ + workspace_start.json
                             the files we gave the AI, and what it saved or changed

The AI often runs code it never saves as a file (a script typed straight into the terminal,
`python3 - <<'PY' ... PY` or `python3 -c "..."`): every Codex run works that way. So the page
lists "Code it ran" from the transcript too, not only the files left in the folder.

    from playground import runpage
    page = runpage.build(run_dir, entry)     # entry: the run's Results-list entry
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import re

from wetlabsim import traces

# Files the AI is given in every starter kit, when a run has no workspace_start.json (older runs).
KIT_NAMES = {"AGENTS.md", "CLAUDE.md", "COMMANDS.md", "GOAL.md", "SITE.md", "cameras.json", "LIBERO.md"}
KIT_DIRS = ("datasheets/", "robot_model/")
TOOL_DIRS = (".devin/", ".codex/", ".claude/")       # the AI tool's own settings, not the AI's work
TEXT_EXT = {".py", ".md", ".txt", ".json", ".jsonl", ".sh", ".js", ".ts", ".yaml", ".yml", ".csv", ".toml",
            ".xml", ".html", ".cfg", ".ini", ".log"}
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
TEXT_MAX = 400_000              # bigger text files: download only
STEP_TEXT_MAX = 6_000           # each transcript step's full text (the page opens it on click)
MAX_STEPS = 1500
ERROR_RE = re.compile(r"(Traceback \(most recent call last\)|\b\w*Error\b:|command not found|"
                      r"Exit code [1-9]\d*|\bexit code [1-9]\d*|\brefused\b)", re.I)
HEREDOC_RE = re.compile(r"python3?\s+(?:-u\s+)?-\s*(?:-u\s+)?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\b", re.S)
DASH_C_RE = re.compile(r"python3?\s+(?:-u\s+)?-c\s+(['\"])(.*?)(?<!\\)\1", re.S)
WRITE_FILE_RE = re.compile(r"cat\s+>{1,2}\s*['\"]?([\w./-]+\.py)['\"]?\s*<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\2\b", re.S)
RUN_FILE_RE = re.compile(r"python3?\s+(?:-u\s+)?([\w./-]+\.py)\b")
# The AI tool's own log lines that land in the transcript (Codex prints these on start): not the AI.
TOOL_NOISE_RE = re.compile(r"^(Reading additional input from stdin|\d{4}-\d\d-\d\dT[\d:.]+Z\s+(ERROR|WARN|INFO|DEBUG|TRACE)\b)")


def _j(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _clock(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def _unwrap_shell(cmd: str) -> str:
    """Codex wraps each command: /bin/zsh -lc "python3 - <<'PY' ... PY". The code inside, unquoted."""
    m = re.match(r"^\s*/bin/(?:ba|z)?sh\s+-lc\s+(['\"])(.*)\1\s*$", cmd or "", re.S)
    if not m:
        return cmd or ""
    inner = m.group(2)
    if m.group(1) == '"':
        inner = inner.replace('\\"', '"').replace("\\$", "$").replace("\\`", "`").replace("\\\\", "\\")
    return inner


def scripts_in(cmd: str) -> list[dict]:
    """The Python code in one terminal command: inline scripts (heredoc or -c), files it wrote
    with cat > x.py, and files it ran by name."""
    c = _unwrap_shell(cmd)
    out = []
    for m in WRITE_FILE_RE.finditer(c):
        out.append({"kind": "file", "name": pathlib.Path(m.group(1)).name, "code": m.group(3)})
    for m in HEREDOC_RE.finditer(c):
        out.append({"kind": "inline", "code": m.group(2)})
    for m in DASH_C_RE.finditer(c):
        code = m.group(2)
        if m.group(1) == '"':
            code = code.replace('\\"', '"')
        out.append({"kind": "inline", "code": code})
    stripped = HEREDOC_RE.sub("", WRITE_FILE_RE.sub("", c))
    for m in RUN_FILE_RE.finditer(stripped):
        out.append({"kind": "ran_file", "name": pathlib.Path(m.group(1)).name})
    return out


def _images_in(o: dict) -> list[tuple[str, str]]:
    """(media type, base64) of every picture in one transcript line: Claude tool results, Codex
    MCP results."""
    found = []
    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "image":
                src = x.get("source") if isinstance(x.get("source"), dict) else x
                data = src.get("data")
                if isinstance(data, str) and len(data) > 100:
                    found.append((src.get("media_type") or x.get("mimeType") or "image/png", data))
                    return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    typ = o.get("type")
    if typ == "user":
        walk(o.get("message", {}).get("content"))
    elif typ == "item.completed" and (o.get("item") or {}).get("type") == "mcp_tool_call":
        walk((o.get("item") or {}).get("result"))
    return found


def _read_lines(path: pathlib.Path):
    if not path.exists():
        return
    with path.open(errors="ignore") as f:
        for line in f:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict):
                yield o


def image(run_dir, n: int) -> tuple[str, bytes] | None:
    """The n-th picture (from 0) the AI looked at in its transcript."""
    i = 0
    for o in _read_lines(pathlib.Path(run_dir) / "transcript.jsonl"):
        for mt, data in _images_in(o):
            if i == n:
                try:
                    return mt, base64.b64decode(data)
                except ValueError:
                    return None
            i += 1
    return None


def transcript(run_dir, start: float, end: float | None, events: list) -> tuple[list[dict], list[dict]]:
    """The run as steps for the page, and every script the AI ran. Times are seconds from start."""
    parser = traces.Parser()
    steps: list[dict] = []
    scripts: list[dict] = []
    n_img = 0
    pending_look: list[dict] = []
    rel = lambda t: round(max(0.0, float(t) - start), 2)  # noqa: E731
    for o in _read_lines(pathlib.Path(run_dir) / "transcript.jsonl"):
        if o.get("type") == "_raw" and TOOL_NOISE_RE.match(str(o.get("text", "")).strip()):
            continue
        for st in parser.feed(o):
            text = (st.text or "").strip()
            if st.kind == "output":
                prev = next((s for s in reversed(steps) if s["kind"] in ("runs", "tool", "looks")), None)
                if prev is not None and "out" not in prev:
                    if text != "[camera image]":
                        prev["out"] = text[-STEP_TEXT_MAX:]
                        if ERROR_RE.search(text[-3000:]) and prev["kind"] == "runs":
                            prev["error"] = True
                continue
            if st.kind == "thinks" and not text:
                continue
            step = {"t": rel(st.t), "kind": st.kind, "text": text[:STEP_TEXT_MAX]}
            if st.kind == "runs":
                found = scripts_in(text)
                ids = []
                for s in found:
                    if s["kind"] == "ran_file" and any(x.get("name") == s["name"] and x["kind"] == "file" for x in scripts):
                        f = next(x for x in scripts if x.get("name") == s["name"] and x["kind"] == "file")
                        f["runs"] += 1
                        ids.append(f["id"])
                        continue
                    if s["kind"] == "ran_file":
                        s = {"kind": "file", "name": s["name"], "code": None}
                    if s["kind"] == "file":
                        old = next((x for x in scripts if x["kind"] == "file" and x["name"] == s["name"]), None)
                        if old is not None:          # written again: keep the newest version
                            old["code"] = s["code"] or old["code"]
                            old["runs"] += 1
                            ids.append(old["id"])
                            continue
                    sc = {"id": len(scripts), "kind": s["kind"], "name": s.get("name"), "code": (s.get("code") or "")[:60_000] or None,
                          "t": step["t"], "runs": 1}
                    scripts.append(sc)
                    ids.append(sc["id"])
                if ids:
                    step["scripts"] = ids
            if st.kind == "writes":
                name, _, body = text.partition("\n")
                step["text"] = name
                if name.endswith(".py") and body:
                    nm = pathlib.Path(name.replace(" (edit)", "")).name
                    old = next((x for x in scripts if x["kind"] == "file" and x["name"] == nm), None)
                    if old is None:
                        scripts.append({"id": len(scripts), "kind": "file", "name": nm, "code": body[:60_000] if "(edit)" not in name else None,
                                        "t": step["t"], "runs": 0})
            if st.kind == "looks":
                pending_look.append(step)
            steps.append(step)
        for _ in _images_in(o):
            if pending_look:
                pending_look.pop(0)["image"] = n_img
            n_img += 1
        if len(steps) > MAX_STEPS:
            break
    # The robot's safety stops, from its own log, in time order with the AI's steps.
    for e in events:
        if e.get("event") == "protective_stop":
            steps.append({"t": rel(e.get("t", start)), "kind": "stop", "text": str(e.get("reason") or "protective stop")})
    steps.sort(key=lambda s: s["t"])
    if end is not None:
        cap = round(max(0.0, end - start), 2)
        for s in steps:
            s["t"] = min(s["t"], cap)
    return steps, scripts


def files(run_dir) -> dict:
    """The AI's folder at the end of the run, in three groups: what it saved or changed, the AI
    tool's own files, and what we gave it."""
    d = pathlib.Path(run_dir)
    ws = d / "workspace"
    start = _j(d / "workspace_start.json", {}).get("files")
    saved, tool, given = [], [], []
    for p in sorted(ws.rglob("*")) if ws.is_dir() else []:
        if not p.is_file() or p.is_symlink():
            continue
        rel = str(p.relative_to(ws))
        size = p.stat().st_size
        item = {"path": rel, "size": size, "type": _ftype(p)}
        if rel.startswith(TOOL_DIRS):
            tool.append(item)
            continue
        if start is not None:
            if rel in start:
                same = size < 50_000_000 and start[rel] == hashlib.sha256(p.read_bytes()).hexdigest()
                (given if same else saved).append(item if same else {**item, "changed": True})
            else:
                saved.append(item)
        else:
            (given if rel in KIT_NAMES or rel.startswith(KIT_DIRS) else saved).append(item)
    return {"saved": saved, "tool": tool, "given": given, "kit_known": start is not None}


def _ftype(p: pathlib.Path) -> str:
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT_EXT or p.name in KIT_NAMES:
        return "text"
    return "other"


def file_path(run_dir, rel: str) -> pathlib.Path | None:
    """A file in the run's folder by its path there; None for anything outside it."""
    if not rel or rel.startswith(("/", "\\")) or ".." in pathlib.PurePosixPath(rel).parts:
        return None
    ws = (pathlib.Path(run_dir) / "workspace").resolve()
    p = (ws / rel).resolve()
    try:
        p.relative_to(ws)
    except ValueError:
        return None
    return p if p.is_file() else None


def content_type(p: pathlib.Path) -> str:
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        return IMAGE_EXT[ext]
    if ext == ".pdf":
        return "application/pdf"
    if ext in TEXT_EXT or p.name in KIT_NAMES:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def build(run_dir, entry: dict) -> dict:
    """Everything the results page shows for one run."""
    d = pathlib.Path(run_dir)
    res, info = _j(d / "result.json", {}), _j(d / "run.json", {})
    run = {**info, **(entry.get("run") or {})}
    start = float(run.get("sim_start") or entry.get("sim_start") or res.get("sim_reset") or 0.0)
    seconds = float(entry.get("seconds") or res.get("wall_seconds") or run.get("wall_seconds") or 0.0)
    events = _j(d / "events.json", [])
    end = start + seconds if seconds else None
    steps, scripts = transcript(d, start, end, events if isinstance(events, list) else [])
    model = res.get("model_reported") or run.get("model") or entry.get("model") or res.get("model") or ""
    agent = run.get("agent") or res.get("agent") or ""
    label = entry.get("model_label") or run.get("model_label") or traces.model_label(model)
    out_tok, tot_tok = res.get("output_tokens"), res.get("tokens") or entry.get("tokens") or run.get("tokens")
    cost = entry.get("cost_usd") if entry.get("cost_usd") is not None else res.get("cost_usd")
    stops = res.get("protective_stops")
    if stops is None and isinstance(events, list):
        stops = sum(1 for e in events if e.get("event") == "protective_stop")
    moves = []
    for e in events if isinstance(events, list) else []:
        if e.get("event") == "command":
            moves.append({"t": round(max(0.0, float(e.get("t", start)) - start), 2),
                          "kind": "gripper" if e.get("kind") == "gripper" else "move"})
    return {
        "ok": True, "run_id": entry.get("run_id") or res.get("run_id"),
        "task": entry.get("task") or run.get("task") or res.get("task") or "",
        "status": entry.get("status") or res.get("status") or run.get("status"),
        "ok_run": bool(entry.get("ok")), "reason": entry.get("reason"), "ai_done": entry.get("ai_done"),
        "error_text": entry.get("error_text"),
        "model": model, "model_label": label or "Model not recorded",
        "provider": res.get("provider") or run.get("provider") or traces.provider_of(model, agent),
        "provider_id": entry.get("provider"), "agent": agent,
        "robot_label": run.get("robot_label") or res.get("robot"),
        "started": entry.get("started"), "seconds": round(seconds, 1),
        "time_limit": run.get("time_limit") or res.get("time_limit"),
        "tokens": {"output": out_tok, "total": tot_tok, "cached": res.get("cached_tokens"),
                   "input": res.get("input_tokens")},
        "cost_usd": cost, "cost_why": None if cost is not None else
        f"{traces.AGENTS.get(agent, (agent or 'This AI tool',))[0]} doesn't report a price",
        "safety_stops": stops or 0, "errors": sum(1 for s in steps if s.get("error")),
        "batch": entry.get("batch"), "index": entry.get("index"), "of": entry.get("of"),
        "steps": steps, "scripts": scripts, "files": files(d), "moves": moves,
        "replay": (d / "replay.npz").exists() and (d / "model.ref").exists(),
        "video_start": _video_start(d, start),
    }


def _video_start(d: pathlib.Path, start: float) -> float:
    """Where the run's video starts, in seconds from the run's start (the recording can begin a
    moment before or after it)."""
    try:
        import numpy as np
        with np.load(d / "replay.npz") as rec:
            return round(float(rec["time"][0]) - start, 2)
    except Exception:  # noqa: BLE001
        return 0.0
