"""LIBERO test runs: one setup or all 50, each graded by LIBERO's own success check.

A run passes the moment the goal holds (LIBERO ends an episode on success) and fails if the
AI finishes, errors or reaches the time limit without it. Results are kept in
runs/playground/libero_results.jsonl and summed up on the scoreboard.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

from . import libero as LB


class Bench:
    def __init__(self, sim, runner, handler_cls, results: pathlib.Path):
        self.sim, self.runner, self.H = sim, runner, handler_cls
        self.results = results
        self.thread: threading.Thread | None = None
        self.cancel = threading.Event()
        self.state: dict = {}

    def active(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, model_id: str, setups: list[int], time_limit: float):
        if self.active() or self.runner.active():
            raise RuntimeError("a run is already going")
        task = self.sim.libero_task
        self.cancel.clear()
        self.state = {"task": task.id, "model": model_id, "queue": setups, "done": 0, "passed": 0,
                      "current": None, "last": None}
        self.thread = threading.Thread(target=self._loop, args=(task, model_id, setups, time_limit), daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()
        self.runner.stop()

    def _loop(self, task: LB.Task, model_id: str, setups: list[int], time_limit: float):
        for k in setups:
            if self.cancel.is_set():
                break
            self.state["current"] = k
            self.sim.set_libero(task.id, k)
            self.sim.play()
            self.runner.start(task.language, model_id, LB.site_sheet(), time_limit)
            t0 = time.time()
            passed, how = False, ""
            while True:
                if self.sim.goal_met():
                    passed, how = True, "goal reached"
                    break
                if not self.runner.active():
                    st = self.runner.status()
                    how = {"finished": "the AI stopped without reaching the goal",
                           "stopped": "stopped"}.get(st.get("status"), "the AI stopped with an error")
                    if time.time() - t0 >= time_limit - 1:
                        how = "time limit"
                    break
                if self.cancel.is_set():
                    how = "stopped"
                    break
                time.sleep(0.1)
            secs = round(time.time() - t0, 1)
            # Let the agent's last messages arrive before it's stopped (the run's cost comes last).
            if passed:
                time.sleep(1.0)
                self.runner.stop()
            for _ in range(50):
                if not self.runner.active():
                    break
                time.sleep(0.1)
            time.sleep(0.5)
            self.sim.pause()
            info = dict(self.H.run)
            row = {"task": task.id, "language": task.language, "setup": k + 1, "model": model_id,
                   "model_label": info.get("model_label") or model_id, "passed": passed, "how": how,
                   "seconds": secs, "cost_usd": info.get("cost_usd"), "tokens": info.get("tokens"),
                   "run_id": info.get("run_id"), "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            if how != "stopped":
                with open(self.results, "a") as f:
                    f.write(json.dumps(row) + "\n")
                self.state["done"] += 1
                self.state["passed"] += int(passed)
            self.state["last"] = row
        self.state["current"] = None

    def status(self) -> dict:
        return {**self.state, "active": self.active()}

    def rows(self) -> list[dict]:
        if not self.results.exists():
            return []
        out = []
        for line in self.results.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def scoreboard(self, task_id: str | None) -> dict:
        rows = [r for r in self.rows() if task_id is None or r["task"] == task_id]
        by: dict[str, dict] = {}
        for r in rows:
            b = by.setdefault(r["model"], {"model": r["model"], "label": r.get("model_label") or r["model"],
                                           "tried": 0, "passed": 0, "secs": [], "costs": [], "setups": {}})
            b["tried"] += 1
            b["passed"] += int(r["passed"])
            if r["passed"]:
                b["secs"].append(r["seconds"])
            if r.get("cost_usd") is not None:
                b["costs"].append(r["cost_usd"])
            b["setups"][r["setup"]] = r["passed"]     # the latest result for each setup
            b["label"] = r.get("model_label") or b["label"]
        board = []
        for b in by.values():
            board.append({"model": b["model"], "label": b["label"], "tried": b["tried"], "passed": b["passed"],
                          "rate": round(b["passed"] / b["tried"], 3) if b["tried"] else 0,
                          "avg_seconds": round(sum(b["secs"]) / len(b["secs"]), 1) if b["secs"] else None,
                          "avg_cost": round(sum(b["costs"]) / len(b["costs"]), 3) if b["costs"] else None,
                          "setups": b["setups"]})
        board.sort(key=lambda b: -b["rate"])
        return {"board": board, "recent": rows[-10:][::-1]}
