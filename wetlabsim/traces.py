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
                      # | "decides" (one of Jev's moves: text is the step's JSON, see jev_agent.py)
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
        # ---- Jev's loop (jev_agent.py): one step per move, with everything its API answered
        elif typ == "_jev":
            kind = e.get("kind")
            if kind == "step":
                keep = ("step", "model", "seconds", "answers", "usage", "input_tokens_total", "cost_usd",
                        "camera_time", "did", "ok")
                steps.append(Step(t, "decides", json.dumps({k: e.get(k) for k in keep})))
            elif kind == "start":
                docs = ", ".join(e.get("datasheets") or []) or "none"
                left = ", ".join(e.get("datasheets_left_out") or [])
                steps.append(Step(t, "says", f"Jev ({e.get('model')}) is starting. Each step it gets the task, "
                                             f"both cameras, the robot's readings and the datasheets ({docs})"
                                             + (f"; left out to fit Jev's limit: {left}" if left else "")
                                             + ", and picks one move."))
            elif kind == "retry":
                steps.append(Step(t, "tool", f"Jev API busy ({e.get('status')}), trying again in {e.get('wait_s')} s"))
            elif kind == "error":
                steps.append(Step(t, "says", f"Stopped: {e.get('text', '')}"))
            elif kind == "done":
                steps.append(Step(t, "says", e.get("text") or f"Jev says the task is done (after {e.get('steps')} steps)."))
        # ---- Devin through ACP (devin_acp.py)
        elif typ == "_devin_acp":
            kind = e.get("kind")
            if kind in ("thinks", "says") and e.get("text", "").strip():
                steps.append(Step(t, kind, e["text"].strip()))
            elif kind == "tool":
                args = e.get("input") or {}
                st = _generic_tool(e.get("name", ""), args if isinstance(args, dict) else {"command": str(args)})
                st.t = t
                steps.append(st)
                tool_kinds[e.get("id")] = st.kind
            elif kind == "tool_result":
                k = tool_kinds.get(e.get("id"))
                if k in ("runs", "tool"):
                    txt = (e.get("text") or "").strip()
                    try:
                        txt = str(json.loads(txt)["result"]).strip()
                    except (ValueError, KeyError, TypeError):
                        pass
                    steps.append(Step(t, "output", txt or "(no output)"))
                elif k == "looks":
                    steps.append(Step(t, "output", "[camera image]"))
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


# ------------------------------------------------------------------ run info
AGENTS = {"claude": ("Claude Code", "Anthropic"), "codex": ("Codex", "OpenAI"), "devin": ("Devin", "Cognition"),
          "jev": ("TypeSafe API", "TypeSafe")}


def provider_of(model: str, agent: str) -> str:
    """Which company makes a model, from its name (falls back to the agent's maker)."""
    m = (model or "").lower()
    if m.startswith(("claude", "opus", "sonnet", "haiku", "fable")):
        return "Anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4", "codex")):
        return "OpenAI"
    if m.startswith("swe"):
        return "Cognition"
    if m.startswith("gemini"):
        return "Google"
    if m.startswith("jev"):
        return "TypeSafe"
    return AGENTS.get(agent, (agent, ""))[1]


def model_label(model: str) -> str:
    """'claude-opus-5-5' -> 'Claude Opus 5.5', 'gpt-6-astra' -> 'GPT-6 Astra'; labels pass through."""
    if not model or " " in model:
        return model or ""
    parts = model.split("-")
    if parts[0] == "gpt" and len(parts) > 1:
        return "GPT-" + parts[1] + "".join(" " + p.capitalize() for p in parts[2:])
    if parts[0] == "swe":
        nums = [p for p in parts[1:] if p.isdigit()]
        rest = [p.capitalize() for p in parts[1 + len(nums):]]
        return " ".join(["SWE-" + ".".join(nums)] + rest)
    words, nums = [], []
    for p in parts:
        (nums if p.isdigit() else words).append(p)
    name = " ".join(w.upper() if w in ("swe",) else w.capitalize() for w in words)
    return (name + " " + ".".join(nums)).strip()


class RunMeta:
    """Follows a transcript for the model the agent reports and the tokens and cost it used."""

    def __init__(self, agent: str, model: str | None = None):
        self.agent = agent
        self.model = model or ""
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0      # part of the input read from the provider's cache
        self.cost_usd: float | None = None
        self._claude_msgs: dict[str, tuple[int, int]] = {}

    def feed(self, e: dict) -> bool:
        """Update from one transcript event. Returns True if anything changed."""
        typ = e.get("type")
        if typ == "system" and e.get("subtype") == "init" and e.get("model"):
            self.model = e["model"]
            return True
        if typ == "assistant":      # Claude Code: one usage per API message, repeated per block
            msg = e.get("message") or {}
            u = msg.get("usage") or {}
            if msg.get("id") and u:
                inp = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                    + (u.get("cache_read_input_tokens") or 0)
                self._claude_msgs[msg["id"]] = (inp, u.get("output_tokens") or 0, u.get("cache_read_input_tokens") or 0)
                self.input_tokens = sum(m[0] for m in self._claude_msgs.values())
                self.output_tokens = sum(m[1] for m in self._claude_msgs.values())
                self.cached_tokens = sum(m[2] for m in self._claude_msgs.values())
                return True
        if typ == "result":         # Claude Code's final totals (the per-message counts above are partial)
            u = e.get("usage") or {}
            if u:
                self.cached_tokens = u.get("cache_read_input_tokens") or 0
                self.input_tokens = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                    + self.cached_tokens
                self.output_tokens = u.get("output_tokens") or 0
            if e.get("total_cost_usd") is not None:
                self.cost_usd = float(e["total_cost_usd"])
            return True
        if typ == "turn.completed":  # Codex
            u = e.get("usage") or {}
            self.input_tokens += u.get("input_tokens") or 0
            self.cached_tokens += u.get("cached_input_tokens") or 0
            self.output_tokens += (u.get("output_tokens") or 0)
            return True
        if typ == "_jev" and e.get("kind") == "step":
            self.model = e.get("model") or self.model
            self.input_tokens = e.get("input_tokens_total") or self.input_tokens
            self.output_tokens += (e.get("usage") or {}).get("output_tokens") or 0
            self.cost_usd = e.get("cost_usd")
            return True
        if typ == "_devin_acp" and e.get("kind") == "usage":
            self.model = e.get("model") or self.model
            self.input_tokens = e.get("input_tokens") or self.input_tokens
            self.output_tokens = e.get("output_tokens") or self.output_tokens
            self.cached_tokens = e.get("cached_tokens") or self.cached_tokens
            return True
        return False

    def info(self) -> dict:
        agent_label, _ = AGENTS.get(self.agent, (self.agent, ""))
        return {
            "agent": self.agent, "agent_label": agent_label,
            "model": self.model, "model_label": model_label(self.model),
            "provider": provider_of(self.model, self.agent),
            "tokens": self.input_tokens + self.output_tokens,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_usd": self.cost_usd,
        }
