"""Stand-in for TypeSafe's Jev API (JEV_API_URL): answers each step with the next move of a
short routine (down, close, up, left, open, done), with usage like Jev's."""
import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
MOVES = ["down", "down", "close_gripper", "up", "up", "left", "left", "open_gripper", "done"]
n, last = [0], [0.0]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if time.time() - last[0] > 20: n[0] = 0      # a new run starts the routine over
        time.sleep(0.6)
        mv = MOVES[min(n[0], len(MOVES) - 1)]; n[0] += 1; last[0] = time.time()
        body = json.dumps({"model": "jev-1.14.0", "answers": {"move": {"choice": mv, "confidence": 0.8},
                           "step": {"choice": "large", "confidence": 0.7}}, "usage": {"input_tokens": 16500}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
