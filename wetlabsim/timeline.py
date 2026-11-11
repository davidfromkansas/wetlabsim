"""A run's timeline, for the run popup: what the AI and the robot were doing, second by second,
what it cost, and how the run ended. Works the same for every agent (Claude Code, Codex, Devin,
Jev); only what each one reports about cost differs.

    from wetlabsim import timeline
    tl = timeline.build(transcript_objects, robot_events, run_info, end_time)

Inputs are what a run already records: the transcript (one JSON object per line, each stamped with
the robot clock in "_sim_time"), the robot's event log (commands, gripper, cameras, protective
stops, on the same clock) and the run's info (agent, model, start, status, cost). Every time in
the output is seconds from the run's start.

Rows ("lanes"):
  thinking  the AI working out what to do (and saying it)
  reading   the AI reading a document
  looking   the AI looking through a camera (its own time and the camera's)
  writing   the AI writing a file (the time it spent producing it)
  running   the AI's code running
  moving    the arm moving
  gripper   the fingers opening or closing
  waiting   the robot still while the AI works (no move, no code running)
  errors    code errors, robot refusals and protective stops (points, not spans)
"""
from __future__ import annotations

import json
import pathlib
import re

from . import prices, traces

LANES = ["thinking", "reading", "looking", "writing", "running", "moving", "gripper", "waiting", "errors"]
LABELS = {"thinking": "Thinking", "reading": "Reading docs", "looking": "Looking", "writing": "Writing code",
          "running": "Running code", "moving": "Moving", "gripper": "Gripper", "waiting": "Waiting on AI",
          "errors": "Errors"}
AI_LANES = ("thinking", "reading", "looking", "writing")      # where the AI's own time (and money) goes
GRIP_SECONDS = 0.6            # a gripper command, drawn as a short block (the fingers' travel)
CLOSED_AT = 128               # gripper command position (0 open .. 255 closed): at or above = closing
ERROR_RE = re.compile(r"(Traceback \(most recent call last\)|\b\w*Error\b:|\bprotective stop\b|\brefused\b)")
DONE_RE = re.compile(r"\bDONE\b")


def _short(text: str, n: int = 28) -> str:
    """A few words for a block's label: the first line, cut at a word."""
    line = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    line = re.sub(r"^[#>*\-\s]+", "", line)
    if len(line) <= n:
        return line
    cut = line[:n].rsplit(" ", 1)[0]
    return (cut or line[:n]).rstrip(".,:;") + "…"


def _run_label(cmd: str) -> str:
    """'cd /tmp/x && python3 pick.py --fast' -> 'pick.py'; else the command's first words."""
    m = re.findall(r"[\w./-]+\.py\b", cmd or "")
    if m:
        return pathlib.Path(m[-1]).name
    return _short(cmd, 22)


def _error_line(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    for l in reversed(lines):
        if ERROR_RE.search(l):
            return _short(re.sub(r"^(?:[\w]+\.)+(\w+(?:Error|Exception))", r"\1", l), 60)
    return _short(lines[-1] if lines else "error", 60)


class _Lanes:
    def __init__(self):
        self.blocks = {k: [] for k in LANES}

    def add(self, lane: str, a: float, b: float, label: str = "", detail: str = ""):
        if b - a < 0.05 or lane not in self.blocks:
            return
        self.blocks[lane].append({"start": round(a, 3), "end": round(b, 3), "label": label,
                                  "detail": detail[:300]})


def _ai_spans(steps: list, lanes: _Lanes, start: float, end: float) -> list:
    """The AI's own time, from its trace steps (any agent but Jev): the stretch before each step
    is the AI producing it, and a tool's run lasts until its output comes back. Returns the AI's
    time spans [(a, b, lane)] for cost attribution."""
    spans, cursor = [], start
    open_tool = None          # (kind, start, label, detail) of a tool still running

    def ai(a, b, lane, label="", detail=""):
        if b > a:
            lanes.add(lane, a, b, label, detail)
            spans.append((a, b, lane))

    for st in steps:
        t = min(max(st.t, start), end)
        k = st.kind
        if k == "output":
            if open_tool:
                kind, a, label, detail = open_tool
                lane = {"runs": "running", "looks": "looking"}.get(kind)
                if lane:
                    lanes.add(lane, a, t, label, detail)
                open_tool = None
            cursor = max(cursor, t)
            continue
        if open_tool and k != "output":     # a step with no output of its own (or parallel calls)
            kind, a, label, detail = open_tool
            lane = {"runs": "running", "looks": "looking"}.get(kind)
            if lane:
                lanes.add(lane, a, t, label, detail)
            open_tool, cursor = None, max(cursor, t)
        lane = {"writes": "writing", "reads": "reading", "looks": "looking"}.get(k, "thinking")
        label = {"writes": _short(st.text.split("\n", 1)[0], 24), "reads": _short(st.text, 24),
                 "looks": _short(st.text, 24), "runs": "", "tool": ""}.get(k, _short(st.text))
        ai(cursor, t, lane, label, st.text[:300])
        cursor = max(cursor, t)
        if k in ("runs", "looks", "tool"):
            open_tool = (k, t, _run_label(st.text) if k == "runs" else _short(st.text, 24), st.text[:300])
    if open_tool:
        kind, a, label, detail = open_tool
        lane = {"runs": "running", "looks": "looking"}.get(kind)
        if lane:
            lanes.add(lane, a, end, label, detail)
    elif end > cursor:
        ai(cursor, end, "thinking")
    return spans


def _jev_spans(objs: list, events: list, lanes: _Lanes, start: float, end: float) -> list:
    """Jev writes no code: each step it reads the robot and both cameras (Looking), waits for its
    API's answer (Thinking), then its move is carried out (the robot's own events)."""
    spans = []
    cmds = sorted(e["t"] for e in events if e.get("event") == "command")
    for o in objs:
        if o.get("type") != "_jev" or o.get("kind") != "step":
            continue
        t = float(o.get("_sim_time", start))
        cam = float(o.get("camera_time") or t)
        secs = float(o.get("seconds") or 0.0)
        nxt = next((c for c in cmds if cam <= c <= t + 1e-6), None)
        ask_end = nxt if nxt is not None else t
        ask_start = max(cam, ask_end - secs)
        move = ((o.get("answers") or {}).get("move") or {}).get("choice", "")
        lanes.add("looking", cam, ask_start, "Cameras", "read the robot and both cameras")
        lanes.add("thinking", ask_start, ask_end, move.replace("_", " "), f"Jev picked: {move}")
        spans += [(cam, ask_start, "looking"), (ask_start, ask_end, "thinking")]
        if o.get("ok") is False:
            lanes.blocks["errors"].append({"t": round(t, 3), "label": _short(o.get("did") or "robot refused", 60)})
    return spans


def _robot(events: list, lanes: _Lanes, start: float, end: float) -> tuple[list, list]:
    """Moving and Gripper rows, protective stops and the gripper flags, from the robot's events."""
    flags, stops = [], []
    cmds = sorted((e for e in events if e.get("event") == "command"), key=lambda e: e["t"])
    tries = 0
    for i, e in enumerate(cmds):
        t = e["t"]
        kind = e.get("kind", "")
        nxt = next((c["t"] for c in cmds[i + 1:] if c.get("kind") != "gripper"), end) if kind != "gripper" else end
        if kind.startswith("move"):
            dur = e.get("seconds")
            b = min(t + float(dur), nxt) if dur is not None else nxt
            lanes.add("moving", t, min(b, end), "", kind.replace("_", " "))
        elif kind == "gripper":
            closing = float(e.get("position", 0)) >= CLOSED_AT
            lanes.add("gripper", t, min(t + GRIP_SECONDS, end), "", "close" if closing else "open")
            if closing:
                tries += 1
                flags.append({"t": round(t, 3), "kind": "grip", "label": "Gripped" if tries == 1 else f"Gripped (try {tries})"})
            else:
                flags.append({"t": round(t, 3), "kind": "release", "label": "Let go"})
    for e in events:
        if e.get("event") == "protective_stop":
            stops.append(e)
            lanes.blocks["errors"].append({"t": round(e["t"], 3), "label": "Safety stop: " + str(e.get("reason", ""))[:50]})
    return flags, stops


def _spend(objs: list, agent: str, model: str, final_cost: float | None) -> list[dict]:
    """The calls that cost something, in order: [{t, usd (None if unknown), tokens}] (deltas)."""
    calls: list[dict] = []
    if agent == "claude":
        msgs: dict[str, dict] = {}
        mdl = model
        for o in objs:
            if o.get("type") == "system" and o.get("subtype") == "init" and o.get("model"):
                mdl = o["model"]
            if o.get("type") != "assistant":
                continue
            m = o.get("message") or {}
            u = m.get("usage") or {}
            if not (m.get("id") and u):
                continue
            # One API call's usage is repeated on each of its content blocks: keep its last.
            msgs[m["id"]] = {"t": float(o.get("_sim_time", 0)), "usage": u, "model": m.get("model") or mdl}
        for m in msgs.values():
            u = m["usage"]
            tok = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                     "cache_creation_input_tokens"))
            calls.append({"t": m["t"], "usd": prices.anthropic_cost(m["model"], u), "tokens": tok})
        total = sum(c["usd"] for c in calls)
        if final_cost is not None and total > 0:       # match Claude Code's own total
            for c in calls:
                c["usd"] *= final_cost / total
    elif agent == "codex":
        for o in objs:
            if o.get("type") == "turn.completed":
                u = o.get("usage") or {}
                calls.append({"t": float(o.get("_sim_time", 0)), "usd": None,
                              "tokens": int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)})
    elif agent == "devin":
        last = 0
        for o in objs:
            if o.get("type") == "_devin_acp" and o.get("kind") == "usage":
                tot = int(o.get("input_tokens") or 0) + int(o.get("output_tokens") or 0)
                if tot > last:
                    calls.append({"t": float(o.get("_sim_time", 0)), "usd": None, "tokens": tot - last})
                    last = tot
    elif agent == "jev":
        usd_last = 0.0
        for o in objs:
            if o.get("type") == "_jev" and o.get("kind") == "step":
                u = o.get("usage") or {}
                usd = float(o.get("cost_usd") or 0.0)
                calls.append({"t": float(o.get("_sim_time", 0)), "usd": max(0.0, usd - usd_last), "lane": "thinking",
                              "tokens": int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)})
                usd_last = usd
    return sorted(calls, key=lambda c: c["t"])


def _lane_at(spans: list, t: float) -> str:
    """The AI lane a call that finished at t belongs to: the span it ends (or is in)."""
    best, gap = "thinking", None
    for a, b, lane in spans:
        if a - 1e-6 <= t <= b + 1e-6:
            return lane
        d = t - b
        if d >= 0 and (gap is None or d < gap):
            best, gap = lane, d
    return best


def _union(blocks: list) -> list[tuple[float, float]]:
    out = []
    for a, b in sorted((x["start"], x["end"]) for x in blocks):
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def build(objs: list[dict], events: list[dict], run: dict, end: float | None = None, live: bool = False) -> dict:
    """The timeline for one run. objs: the transcript's objects; events: the robot's events;
    run: the run's info (agent, model, sim_start, status, cost_usd, tokens, ...); end: the robot
    clock now (live) or at the run's end. All times out are seconds from the run's start."""
    agent = run.get("agent") or ""
    start = float(run.get("sim_start") or 0.0)
    ts = [float(o.get("_sim_time", start)) for o in objs] + [float(e.get("t", start)) for e in events]
    if end is None:
        end = start + float(run["wall_seconds"]) if run.get("wall_seconds") else max(ts + [start])
    end = max(end, start)
    events = [e for e in events if start - 1e-6 <= float(e.get("t", 0)) <= end + 1e-6]
    lanes = _Lanes()

    parser, steps = traces.Parser(), []
    for o in objs:
        steps += parser.feed(o)
    if agent == "jev":
        spans = _jev_spans(objs, events, lanes, start, end)
    else:
        spans = _ai_spans(steps, lanes, start, end)
    flags, stops = _robot(events, lanes, start, end)

    # Code errors: an output that is a traceback or an error message.
    for st in steps:
        if st.kind == "output" and ERROR_RE.search(st.text or "") and "protective stop" not in st.text:
            lanes.blocks["errors"].append({"t": round(min(max(st.t, start), end), 3), "label": _error_line(st.text)})
            flags.append({"t": round(min(max(st.t, start), end), 3), "kind": "error", "label": "Code error"})

    # Waiting on AI: the robot still and no code running.
    busy = _union(lanes.blocks["moving"] + lanes.blocks["gripper"] + lanes.blocks["running"])
    cur = start
    for a, b in busy + [(end, end)]:
        if a - cur >= 1.0:
            lanes.add("waiting", cur, a, "Robot still, AI working")
        cur = max(cur, b)

    # When the AI said it was done.
    done_t = None
    for st in steps:
        if st.kind == "says" and (DONE_RE.search(st.text) or st.text.startswith("Jev says the task is done")):
            done_t = st.t
    if done_t is not None:
        flags.append({"t": round(done_t, 3), "kind": "done", "label": "Done"})

    # Spend: each call's cost and tokens, and the AI lane it went to.
    calls = _spend(objs, agent, run.get("model") or "", run.get("cost_usd") if not live else None)
    cost_known = agent in ("claude", "jev") and bool(calls)
    if agent in ("claude", "jev") and not calls and run.get("cost_usd") is not None:
        cost_known = True
    by_lane = {k: {"usd": 0.0 if cost_known else None, "tokens": 0} for k in AI_LANES}
    series, usd, tok = [[0.0, 0.0 if cost_known else None, 0]], 0.0, 0
    for c in calls:
        lane = c.get("lane") or _lane_at(spans, c["t"])
        by_lane[lane]["tokens"] += c["tokens"]
        tok += c["tokens"]
        if cost_known and c["usd"] is not None:
            by_lane[lane]["usd"] += c["usd"]
            usd += c["usd"]
        series.append([round(min(max(c["t"], start), end) - start, 3), round(usd, 6) if cost_known else None, tok])
    total_usd = usd if cost_known else None
    if cost_known and run.get("cost_usd") is not None and not calls:
        total_usd = float(run["cost_usd"])
    total_tokens = tok or int(run.get("tokens") or 0)
    series.append([round(end - start, 3), round(total_usd, 6) if total_usd is not None else None, total_tokens])

    # Time spent per lane (overlaps inside a lane counted once).
    rel = lambda x: round(x - start, 3)  # noqa: E731
    lanes_out = []
    for k in LANES:
        bl = lanes.blocks[k]
        if k == "errors":
            items = sorted(({"t": rel(b["t"]), "label": b["label"]} for b in bl), key=lambda b: b["t"])
            lanes_out.append({"id": k, "label": LABELS[k], "points": items, "count": len(items)})
            continue
        secs = sum(b - a for a, b in _union(bl))
        lane = {"id": k, "label": LABELS[k], "seconds": round(secs, 2),
                "blocks": [{**b, "start": rel(b["start"]), "end": rel(b["end"])} for b in sorted(bl, key=lambda b: b["start"])]}
        if k in by_lane:
            lane["usd"] = round(by_lane[k]["usd"], 6) if by_lane[k]["usd"] is not None else None
            lane["tokens"] = by_lane[k]["tokens"]
        lanes_out.append(lane)
    duration = end - start
    waiting = next(l for l in lanes_out if l["id"] == "waiting")
    waiting["share"] = round(waiting["seconds"] / duration, 3) if duration > 0 else 0.0

    # What was happening: the AI's words, for the line under the pictures.
    notes = [{"t": rel(min(max(s.t, start), end)), "kind": s.kind, "text": _short(s.text, 160)}
             for s in steps if s.kind in ("says", "thinks") and s.text.strip()]
    # Now (live): the lane the newest block of each row ends in.
    now = []
    for k in ("thinking", "reading", "looking", "writing", "running", "moving", "gripper"):
        bl = lanes.blocks[k]
        if bl and bl[-1]["end"] >= end - 0.25:
            now.append(k)
    status = run.get("status") or ("running" if live else "finished")
    result = {"status": status, "ai_done_at": rel(done_t) if done_t is not None else None,
              "safety_stops": len(stops), "passed": run.get("passed"), "score": run.get("score")}
    return {
        "agent": agent, "model": run.get("model") or "", "model_label": run.get("model_label") or traces.model_label(run.get("model") or ""),
        "provider": run.get("provider") or traces.provider_of(run.get("model") or "", agent),
        "task": run.get("task") or "", "duration": round(duration, 3), "live": live,
        "time_limit": run.get("time_limit"),
        "cost": {"known": cost_known, "usd": round(total_usd, 6) if total_usd is not None else None,
                 "tokens": total_tokens, "series": series,
                 "why_unknown": None if cost_known else f"{traces.AGENTS.get(agent, (agent,))[0]} doesn't report cost"},
        "lanes": lanes_out, "flags": sorted(({**f, "t": rel(f["t"])} for f in flags), key=lambda f: f["t"]),
        "result": result, "notes": notes[-400:], "now": now,
    }


def read_transcript(path) -> list[dict]:
    out = []
    p = pathlib.Path(path)
    if not p.exists():
        return out
    for line in p.read_text(errors="ignore").splitlines():
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def for_run_dir(run_dir, events: list | None = None, run: dict | None = None, end: float | None = None,
                live: bool = False) -> dict:
    """The timeline of a run folder (finished, or still going: pass live and the clock now)."""
    d = pathlib.Path(run_dir)
    def j(name, default):
        try:
            return json.loads((d / name).read_text())
        except (OSError, ValueError):
            return default
    info = {**j("run.json", {}), **(run or {})}
    res = j("result.json", {})
    for k in ("cost_usd", "tokens", "passed", "score", "status", "agent", "model"):
        if info.get(k) is None and res.get(k) is not None:
            info[k] = res[k]
    if events is None:
        events = j("events.json", [])
    return build(read_transcript(d / "transcript.jsonl"), events, info, end, live)
