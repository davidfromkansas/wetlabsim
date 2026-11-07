"""Run Devin through its Agent Client Protocol server so the recorder sees everything live,
including its reasoning. (`devin -p` only prints the final answer, and its --export is
written at exit.)

    python -m wetlabsim.devin_acp <workspace> <prompt> [--model M] [--mcp JSON]

Prints one JSON line per trace event on stdout:
    {"type": "_devin_acp", "kind": "thinks" | "says", "text": ...}
    {"type": "_devin_acp", "kind": "tool", "id": ..., "name": ..., "input": {...}}
    {"type": "_devin_acp", "kind": "tool_result", "id": ..., "status": ..., "text": ...}
Streamed thought and message chunks are joined, so each line is one whole thought or reply.
Permission requests are answered like print mode would (nobody is there to approve them):
anything that mentions a --deny folder or a path outside the workspace is refused, and the
rest is refused too unless Devin offers a one-time allow for a workspace-only action.
Any other request from Devin gets a JSON-RPC error, so it never waits on us. If Devin goes
quiet for --idle-timeout seconds with no tool running, the turn is cancelled and the run fails.
--raw-log saves every ACP message in both directions.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _content_text(content) -> str:
    parts = []
    for c in content or []:
        inner = c.get("content") if isinstance(c, dict) else None
        if isinstance(inner, dict) and inner.get("type") == "text":
            parts.append(inner.get("text", ""))
        elif isinstance(inner, dict) and inner.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("prompt")
    ap.add_argument("--model")
    ap.add_argument("--mcp", default="[]", help="ACP mcpServers list as JSON")
    ap.add_argument("--deny", action="append", default=[], help="folder the agent may not touch")
    ap.add_argument("--idle-timeout", type=float, default=120,
                    help="fail if Devin sends nothing for this many seconds while no tool is running")
    ap.add_argument("--raw-log", help="append every ACP message here (one JSON line each)")
    args = ap.parse_args(argv)
    workspace = os.path.realpath(args.workspace)
    deny = [os.path.realpath(d) for d in args.deny] + args.deny

    def allowed(tool_call: dict) -> bool:
        # Only workspace-only actions: no denied folder, no absolute path outside the workspace.
        text = json.dumps(tool_call.get("rawInput") or {}) + " " + (tool_call.get("title") or "")
        if any(d in text for d in deny):
            return False
        for p in re.findall(r"(?<![\w.])/(?:[\w.@-]+/)*[\w.@-]+", text):
            rp = os.path.realpath(p)
            if not (rp == workspace or rp.startswith(workspace + os.sep)):
                return False
        return True

    cmd = ["devin", "acp"] + (["--model", args.model] if args.model else [])
    proc = subprocess.Popen(cmd, cwd=args.workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    write_lock = threading.Lock()
    pending: dict[int, list] = {}
    next_id = [0]
    session = [None]
    last_heard = [time.time()]
    open_tools: set[str] = set()
    raw = open(args.raw_log, "a") if args.raw_log else None

    def log_raw(direction, line):
        if raw:
            with write_lock:
                raw.write(json.dumps({"t": round(time.time(), 3), "dir": direction,
                                      "msg": line.rstrip("\n")}) + "\n")
                raw.flush()

    def send(obj):
        line = json.dumps(obj)
        log_raw("out", line)
        with write_lock:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()

    def request(method, params):
        next_id[0] += 1
        rid = next_id[0]
        pending[rid] = [threading.Event(), None]
        send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        pending[rid][0].wait()
        reply = pending.pop(rid)[1]
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error'].get('message', reply['error'])}")
        return reply["result"]

    # Streamed chunks of the same kind are joined until something else happens.
    buf = {"kind": None, "text": ""}
    tool_out: dict[str, str] = {}

    def flush():
        if buf["kind"] and buf["text"].strip():
            emit({"type": "_devin_acp", "kind": buf["kind"], "text": buf["text"].strip()})
        buf["kind"], buf["text"] = None, ""

    def on_update(u):
        what = u.get("sessionUpdate")
        if what in ("agent_thought_chunk", "agent_message_chunk"):
            kind = "thinks" if what == "agent_thought_chunk" else "says"
            if buf["kind"] != kind:
                flush()
                buf["kind"] = kind
            buf["text"] += (u.get("content") or {}).get("text", "")
        elif what == "tool_call":
            flush()
            meta = u.get("_meta") or {}
            if u.get("status") not in ("completed", "failed"):
                open_tools.add(u.get("toolCallId"))
            emit({"type": "_devin_acp", "kind": "tool", "id": u.get("toolCallId"),
                  "name": meta.get("cognition.ai/inferenceToolName") or u.get("kind") or "",
                  "title": u.get("title", ""), "input": u.get("rawInput") or {}})
        elif what == "tool_call_update":
            tid = u.get("toolCallId")
            if u.get("content"):
                tool_out[tid] = _content_text(u["content"])
            if u.get("status") in ("completed", "failed"):
                open_tools.discard(tid)
                flush()
                emit({"type": "_devin_acp", "kind": "tool_result", "id": tid, "status": u["status"],
                      "text": tool_out.pop(tid, "")})

    def reader():
        for line in proc.stdout:
            last_heard[0] = time.time()
            log_raw("in", line)
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if "id" in m and ("result" in m or "error" in m) and m["id"] in pending:
                pending[m["id"]][1] = m
                pending[m["id"]][0].set()
            elif m.get("method") == "session/request_permission":
                opts = m["params"].get("options", [])
                call = m["params"].get("toolCall") or {}
                ok = allowed(call)
                want = "allow_once" if ok else "reject"
                pick = next((o for o in opts if o.get("kind", "").startswith(want)), None)
                if pick is None:
                    ok = False
                    pick = next((o for o in opts if o.get("kind", "").startswith("reject")), None)
                outcome = {"outcome": "selected", "optionId": pick["optionId"]} if pick \
                    else {"outcome": "cancelled"}
                send({"jsonrpc": "2.0", "id": m["id"], "result": {"outcome": outcome}})
                emit({"type": "_devin_acp", "kind": "says",
                      "text": f"[permission {'allowed' if ok else 'refused'}] {call.get('title', '')}"})
            elif m.get("method") == "session/update":
                on_update(m["params"].get("update") or {})
            elif m.get("method") == "_cognition.ai/agent_stopped":
                # Devin's per-turn totals: the model it ran and the tokens it used.
                st = m["params"].get("stats") or {}
                emit({"type": "_devin_acp", "kind": "usage", "model": st.get("modelLabel", ""),
                      "input_tokens": st.get("inputTokens") or 0, "output_tokens": st.get("outputTokens") or 0})
            elif "id" in m and "method" in m:
                # A request we don't serve (we offered no fs or terminal): say so instead of
                # leaving Devin waiting for an answer that never comes.
                send({"jsonrpc": "2.0", "id": m["id"],
                      "error": {"code": -32601, "message": f"method not supported: {m['method']}"}})
                flush()
                emit({"type": "_devin_acp", "kind": "says",
                      "text": f"[unsupported ACP request refused] {m['method']}"})
        flush()
        for p in list(pending.values()):   # Devin exited: release anyone waiting
            p[1] = {"error": {"message": "devin acp exited"}}
            p[0].set()

    threading.Thread(target=reader, daemon=True).start()

    def stop(*_):
        # Ctrl-C from the recorder (time limit): ask Devin to cancel the turn.
        if session[0]:
            send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session[0]}})
    signal.signal(signal.SIGINT, stop)

    stalled = threading.Event()

    def watchdog():
        # A tool can legitimately run for a while; silence with nothing running means Devin is stuck.
        while proc.poll() is None:
            time.sleep(2)
            if open_tools:
                last_heard[0] = max(last_heard[0], time.time() - 2)
            elif session[0] and time.time() - last_heard[0] > args.idle_timeout:
                stalled.set()
                flush()
                emit({"type": "_raw", "text": f"Error: Devin sent nothing over ACP for "
                                              f"{args.idle_timeout:.0f} s; cancelling the run"})
                stop()
                time.sleep(15)
                proc.terminate()
                return
    if args.idle_timeout > 0:
        threading.Thread(target=watchdog, daemon=True).start()

    code = 0
    try:
        request("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
        session[0] = request("session/new", {"cwd": workspace,
                                             "mcpServers": json.loads(args.mcp)})["sessionId"]
        res = request("session/prompt", {"sessionId": session[0],
                                         "prompt": [{"type": "text", "text": args.prompt}]})
        flush()
        emit({"type": "_devin_acp", "kind": "end", "stop_reason": res.get("stopReason")})
        if stalled.is_set():
            code = 1
    except RuntimeError as e:
        emit({"type": "_raw", "text": f"Error: {e}"})
        code = 1
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    return code


if __name__ == "__main__":
    sys.exit(main())
