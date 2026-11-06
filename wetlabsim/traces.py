"""Read an agent transcript (Claude Code stream-json or Codex --json) into a simple
list of trace steps: what the agent said, the code it ran, and what came back."""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass


@dataclass
class Step:
    t: float          # robot clock (s)
    kind: str         # "says" | "thinks" | "runs" | "output" | "looks" | "reads" | "writes" | "tool"
    text: str


def _short_path(p: str) -> str:
    return pathlib.Path(p).name if p else p


def _claude_tool(name: str, inp: dict) -> Step | None:
    if name == "Bash":
        return Step(0, "runs", inp.get("command", ""))
    if name == "Write":
        return Step(0, "writes", f"{_short_path(inp.get('file_path', ''))}\n{inp.get('content', '')}")
    if name == "Edit":
        return Step(0, "writes", f"{_short_path(inp.get('file_path', ''))} (edit)\n{inp.get('new_string', '')}")
    if name == "Read":
        f = _short_path(inp.get("file_path", ""))
        if f.lower().endswith((".png", ".jpg", ".jpeg")):
            return Step(0, "looks", f"saved image {f}")
        return Step(0, "reads", f)
    if name.endswith("__look"):
        return Step(0, "looks", f"{inp.get('camera', 'overhead')} camera")
    if name.endswith("__robot_state"):
        return Step(0, "tool", "reads the robot state")
    if name.endswith("__emergency_stop"):
        return Step(0, "tool", "EMERGENCY STOP")
    if name in ("ToolSearch", "TodoWrite"):
        return None
    return Step(0, "tool", f"{name} {json.dumps(inp)[:200]}")


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c["text"])
        elif isinstance(c, dict) and c.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


class Parser:
    """Turns transcript events into trace steps one at a time, so traces can be shown live."""

    def __init__(self):
        self.tool_kinds: dict[str, str] = {}

    def feed(self, e: dict) -> list[Step]:
        steps: list[Step] = []
        tool_kinds = self.tool_kinds
        t = float(e.get("_sim_time", 0.0))
        typ = e.get("type")
        # ---- plain text output (e.g. Devin's printed summary)
        if typ == "_raw":
            if e.get("text", "").strip():
                steps.append(Step(t, "says", e["text"].strip()))
        # ---- Devin CLI hook events (tool calls as they happen)
        elif typ == "_devin_hook":
            name, args = e.get("tool_name", ""), e.get("tool_input") or {}
            if e.get("hook_event_name") == "PreToolUse":
                st = _generic_tool(name, args if isinstance(args, dict) else {"command": str(args)})
                st.t = t
                steps.append(st)
            elif e.get("hook_event_name") == "PostToolUse":
                kind = _generic_tool(name, args if isinstance(args, dict) else {"command": str(args)}).kind
                resp = e.get("tool_response") or {}
                if kind in ("runs", "tool"):
                    txt = str(resp.get("output") or resp.get("error") or "").strip()
                    try:
                        txt = str(json.loads(txt)["result"]).strip()
                    except (ValueError, KeyError, TypeError):
                        pass
                    steps.append(Step(t, "output", txt or "(no output)"))
                elif kind == "looks":
                    steps.append(Step(t, "output", "[camera image]"))
        # ---- Claude Code stream-json
        elif typ == "assistant":
            for b in e["message"].get("content", []):
                if b.get("type") == "text" and b["text"].strip():
                    steps.append(Step(t, "says", b["text"].strip()))
                elif b.get("type") == "thinking" and b.get("thinking", "").strip():
                    steps.append(Step(t, "thinks", b["thinking"].strip()))
                elif b.get("type") == "tool_use":
                    st = _claude_tool(b["name"], b.get("input", {}))
                    if st:
                        st.t = t
                        steps.append(st)
                        tool_kinds[b["id"]] = st.kind
        elif typ == "user":
            content = e.get("message", {}).get("content", [])
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    kind = tool_kinds.get(c.get("tool_use_id"))
                    if kind in ("runs", "tool"):
                        txt = _result_text(c.get("content")).strip()
                        try:   # MCP results arrive wrapped as {"result": "..."}
                            txt = str(json.loads(txt)["result"]).strip()
                        except (ValueError, KeyError, TypeError):
                            pass
                        steps.append(Step(t, "output", txt or "(no output)"))
                    elif kind == "looks":
                        steps.append(Step(t, "output", "[camera image]"))
        # ---- Codex exec --json
        elif typ in ("item.completed", "item.started"):
            it = e.get("item", {})
            ity = it.get("type") or it.get("item_type")
            if typ == "item.started" and ity == "command_execution":
                steps.append(Step(t, "runs", it.get("command", "")))
            elif typ == "item.completed":
                if ity in ("agent_message", "assistant_message"):
                    steps.append(Step(t, "says", it.get("text", "")))
                elif ity == "reasoning" and it.get("text"):
                    steps.append(Step(t, "thinks", it["text"]))
                elif ity == "command_execution":
                    steps.append(Step(t, "output", (it.get("aggregated_output") or "(no output)").strip()))
                elif ity == "file_change":
                    for ch in it.get("changes", []):
                        steps.append(Step(t, "writes", _short_path(ch.get("path", ""))))
                elif ity == "mcp_tool_call":
                    tool = it.get("tool", "")
                    args = it.get("arguments") or {}
                    if tool == "look":
                        steps.append(Step(t, "looks", f"{args.get('camera', 'overhead')} camera"))
                    else:
                        steps.append(Step(t, "tool", tool))
        return steps


def load(path: str | pathlib.Path) -> list[Step]:
    parser, steps = Parser(), []
    for line in pathlib.Path(path).read_text().splitlines():
        try:
            steps += parser.feed(json.loads(line))
        except json.JSONDecodeError:
            continue
    return steps


def _iso_to_epoch(ts) -> float | None:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _generic_tool(name: str, args: dict) -> Step:
    """Map a tool call from an unknown harness (e.g. Devin) onto a trace step by its arguments."""
    n = name.lower()
    if n.endswith("look") or n.endswith("__look"):
        return Step(0, "looks", f"{args.get('camera', 'overhead')} camera")
    if n.endswith("robot_state"):
        return Step(0, "tool", "reads the robot state")
    if n.endswith("emergency_stop"):
        return Step(0, "tool", "EMERGENCY STOP")
    if "command" in args or "cmd" in args:
        return Step(0, "runs", str(args.get("command") or args.get("cmd")))
    path = args.get("file_path") or args.get("path") or ""
    if "content" in args or "new_string" in args or "write" in n or "edit" in n:
        return Step(0, "writes", f"{_short_path(path)}\n{args.get('content') or args.get('new_string') or ''}")
    if "read" in n and path:
        f = _short_path(path)
        return Step(0, "looks", f"saved image {f}") if f.lower().endswith((".png", ".jpg", ".jpeg")) \
            else Step(0, "reads", f)
    return Step(0, "tool", f"{name} {json.dumps(args)[:200]}")


def load_atif(path, wall_reset: float, sim_reset: float) -> list[Step]:
    """Read an ATIF trajectory (Devin CLI --export). Step timestamps are wall-clock, so they are
    shifted onto the robot clock with the run's reset times."""
    data = json.loads(pathlib.Path(path).read_text())
    steps: list[Step] = []
    for s in data.get("steps", []):
        if s.get("source") != "agent":
            continue
        epoch = _iso_to_epoch(s.get("timestamp"))
        t = sim_reset + (epoch - wall_reset) if epoch else 0.0
        if (s.get("reasoning_content") or "").strip():
            steps.append(Step(t, "thinks", s["reasoning_content"].strip()))
        msg = s.get("message")
        if isinstance(msg, list):
            msg = "\n".join(p.get("text", "") for p in msg if isinstance(p, dict))
        if (msg or "").strip():
            steps.append(Step(t, "says", msg.strip()))
        kinds = {}
        for c in s.get("tool_calls") or []:
            args = c.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            st = _generic_tool(c.get("function_name", ""), args)
            st.t = t
            steps.append(st)
            kinds[c.get("tool_call_id")] = st.kind
        for r in (s.get("observation") or {}).get("results", []):
            kind = kinds.get(r.get("source_call_id"))
            if kind in ("runs", "tool"):
                txt = _result_text(r.get("content")).strip()
                steps.append(Step(t, "output", txt or "(no output)"))
            elif kind == "looks":
                steps.append(Step(t, "output", "[camera image]"))
    return steps


def load_run(run_dir) -> list[Step]:
    """Trace steps for a run folder, whichever agent made it."""
    run = pathlib.Path(run_dir)
    if (run / "devin_trajectory.json").exists():
        res = json.loads((run / "result.json").read_text())
        return load_atif(run / "devin_trajectory.json", res["wall_reset"], res["sim_reset"])
    if (run / "transcript.jsonl").exists():
        return load(run / "transcript.jsonl")
    return []
