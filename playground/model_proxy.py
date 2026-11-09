"""The model proxy: how an agent in a sandbox reaches Anthropic without ever holding the key.

The agent's CLI is pointed here (ANTHROPIC_BASE_URL) with its run token where an API key
would go. A request with a live run token is forwarded to Anthropic with the real key (from
this process's ANTHROPIC_API_KEY); anything else is refused. Responses, streamed or not, are
passed back as they arrive. Tokens and the dollars they cost are counted per run token, and a
run over its budget is refused further calls.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wetlabsim import robot_api as RA

UPSTREAM = "api.anthropic.com"
BUDGET_USD = float(os.environ.get("WETLAB_RUN_BUDGET_USD", "3"))
# Dollars per million tokens (input, output, cache read, cache write), by model family: Anthropic's
# list prices for the current models (Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1). Cache writes are
# taken as 1.25x input (5-minute cache); Haiku's cache read as 0.1x input.
PRICES = {"opus": (4.0, 20.0, 0.20, 5.0), "sonnet": (2.0, 10.0, 0.20, 2.5), "haiku": (0.10, 0.50, 0.01, 0.125),
          "fable": (10.0, 50.0, 0.25, 12.5)}
_spent: dict[str, float] = {}
_lock = threading.Lock()


def spent(tok: str) -> float:
    with _lock:
        return _spent.get(tok, 0.0)


def _charge(tok: str, model: str, usage: dict):
    p = next((v for k, v in PRICES.items() if k in (model or "")), PRICES["opus"])
    usd = (usage.get("input_tokens", 0) * p[0] + usage.get("output_tokens", 0) * p[1]
           + usage.get("cache_read_input_tokens", 0) * p[2]
           + usage.get("cache_creation_input_tokens", 0) * p[3]) / 1e6
    with _lock:
        _spent[tok] = _spent.get(tok, 0.0) + usd


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _deny(self, code, msg):
        body = json.dumps({"type": "error", "error": {"type": "permission_error", "message": msg}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, method):
        tok = self.headers.get("x-api-key") or RA.token_from(self.headers)
        if RA.TOKENS.lookup(tok) is None:
            return self._deny(401, "this endpoint takes a live run token")
        if spent(tok) >= BUDGET_USD:
            return self._deny(429, f"this run has used its ${BUDGET_USD:.2f} model budget")
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return self._deny(503, "the proxy has no Anthropic key")
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "x-api-key", "authorization", "content-length", "connection",
                                        "accept-encoding")}
        headers["x-api-key"] = key
        conn = http.client.HTTPSConnection(UPSTREAM, timeout=600)
        conn.request(method, self.path, body=body, headers=headers)
        r = conn.getresponse()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        model, usage, buf = "", {}, b""
        try:
            while True:
                chunk = r.read1(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
                buf = (buf + chunk)[-200000:]
            self.wfile.write(b"0\r\n\r\n")
        finally:
            conn.close()
        # Count what this call cost: the usage blocks of a JSON reply or of a stream's events.
        text = buf.decode(errors="ignore")
        for part in [text] + [l[5:].strip() for l in text.splitlines() if l.startswith("data:")]:
            try:
                o = json.loads(part)
            except ValueError:
                continue
            msg = o.get("message", o) if isinstance(o, dict) else {}
            model = msg.get("model", model) if isinstance(msg, dict) else model
            u = (msg.get("usage") if isinstance(msg, dict) else None) or (o.get("usage") if isinstance(o, dict) else None)
            if u:
                for k, v in u.items():
                    if isinstance(v, int):
                        usage[k] = max(usage.get(k, 0), v)
        if usage:
            _charge(tok, model, usage)

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        self._forward("GET")


def serve(host: str, port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), ProxyHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="model-proxy").start()
    return srv
