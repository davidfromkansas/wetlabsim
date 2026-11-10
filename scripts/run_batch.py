"""Run a batch of task-library runs: every task, N tries, on one or more cells.

    python scripts/run_batch.py --batch opus-group1 --model claude-opus-5-5 --tries 3 \
        --urls http://127.0.0.1:8765 http://127.0.0.1:8766

Tries go round-robin (every task's try 1, then every task's try 2, ...). Each cell takes the
next run from the queue. A run stopped by a usage limit waits 10 minutes and runs again.
Progress goes to runs/<batch>.progress.json.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import queue
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wetlabsim import tasks as T   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--tasks", nargs="*", default=list(T.TASKS))
    ap.add_argument("--urls", nargs="+", default=["http://127.0.0.1:8765"])
    ap.add_argument("--time-limit", type=float, default=900)
    a = ap.parse_args()
    runs = ROOT / "runs"
    prog_file = runs / f"{a.batch}.progress.json"
    done = []
    q: queue.Queue = queue.Queue()
    for k in range(1, a.tries + 1):
        for t in a.tasks:
            if not any(json.loads(p.read_text()).get("batch") == a.batch and
                       json.loads(p.read_text()).get("task_id") == t and
                       json.loads(p.read_text()).get("attempt") == k and
                       not str(json.loads(p.read_text()).get("status", "")).startswith("interrupted")
                       and not json.loads(p.read_text()).get("excluded")
                       for p in runs.glob("*/result.json")):
                q.put((t, k))
    total = q.qsize()
    lock = threading.Lock()

    def lane(url):
        while True:
            try:
                t, k = q.get_nowait()
            except queue.Empty:
                return
            while True:
                cmd = [sys.executable, "-m", "wetlabsim.run_agent", "--agent", a.agent, "--model", a.model,
                       "--task-id", t, "--batch", a.batch, "--try", str(k), "--url", url,
                       "--time-limit", str(a.time_limit)]
                out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                line = next((l for l in out.stdout.splitlines() if l.startswith("Done in")), "")
                rd = next((l.split("Results in ")[-1].strip() for l in out.stdout.splitlines() if "Results in" in l), "")
                res = json.loads((pathlib.Path(rd) / "result.json").read_text()) if rd else {}
                if str(res.get("status", "")).startswith("interrupted"):
                    time.sleep(600)          # usage limit: wait for it to reset, then run again
                    continue
                with lock:
                    done.append({"task": t, "try": k, "run_id": res.get("run_id"), "score": res.get("score"),
                                 "passed": res.get("passed"), "status": res.get("status"),
                                 "error": None if res else (out.stderr or out.stdout)[-800:]})
                    prog_file.write_text(json.dumps({"batch": a.batch, "total": total, "done": len(done),
                                                     "runs": done}, indent=1))
                print(f"[{len(done)}/{total}] {t} try {k}: {res.get('score')} {res.get('status')} {line}", flush=True)
                break

    threads = [threading.Thread(target=lane, args=(u,)) for u in a.urls]
    for th in threads:
        th.start()
        time.sleep(20)                       # stagger the starts
    for th in threads:
        th.join()


if __name__ == "__main__":
    main()
