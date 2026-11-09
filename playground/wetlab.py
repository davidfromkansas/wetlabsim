"""Wet Lab test runs: the robot cell's own bench and its eight tasks (wetlabsim.tasks), each
scored at the end of the run by the task's own check, exactly as in the robot cell's evals.

The run is wetlabsim.run_agent with --task-id: it lays out the bench for the task, gives the
agent the bench's own site sheet, and scores the end state (positions, wells, what fell
over; T12 by a judge model reading the agent's answer). Results are kept in
runs/playground/wetlab_results.jsonl and summed up on the scoreboard.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

from wetlabsim import tasks as WT

TIME_LIMIT = 900.0     # seconds, as in the robot cell's evals
ORDER = list(WT.TASKS)


class WetBench:
    def __init__(self, sim, runner, handler_cls, results: pathlib.Path):
        self.sim, self.runner, self.H = sim, runner, handler_cls
        self.results = results
        self.thread: threading.Thread | None = None
        self.cancel = threading.Event()
        self.state: dict = {}

    def active(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, model_id: str, task_ids: list[str], time_limit: float = TIME_LIMIT):
        if self.active() or self.runner.active():
            raise RuntimeError("a run is already going")
        self.cancel.clear()
        self.state = {"model": model_id, "total": len(task_ids), "done": 0, "passed": 0,
                      "current": None, "last": None}
        self.thread = threading.Thread(target=self._loop, args=(model_id, task_ids, time_limit), daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()
        self.runner.stop()

    def _loop(self, model_id: str, task_ids: list[str], time_limit: float):
        for tid in task_ids:
            if self.cancel.is_set():
                break
            self.state["current"] = tid
            self.sim.set_wetlab(tid)
            self.sim.play()
            t0 = time.time()
            self.runner.start(WT.TASKS[tid].prompt, model_id, None, time_limit, extra=["--task-id", tid])
            while self.runner.active() and not self.cancel.is_set():
                time.sleep(0.2)
            if self.cancel.is_set():
                self.runner.stop()
            for _ in range(100):          # run_agent scores the run as it exits
                if not self.runner.active():
                    break
                time.sleep(0.1)
            self.sim.pause()
            secs = round(time.time() - t0, 1)
            info = dict(self.H.run)
            res = {}
            rid = info.get("run_id")
            if rid and (self.runner.runs / rid / "result.json").exists():
                res = json.loads((self.runner.runs / rid / "result.json").read_text())
            stopped = self.cancel.is_set() or self.runner.status().get("status") == "stopped"
            row = {"task": tid, "title": WT.TASKS[tid].title, "model": model_id,
                   "model_label": info.get("model_label") or model_id,
                   "passed": bool(res.get("passed")), "score": res.get("score"),
                   "how": res.get("status") or ("stopped" if stopped else "no result"),
                   "detail": res.get("detail"), "flags": res.get("flags"),
                   "seconds": res.get("wall_seconds") or secs, "cost_usd": res.get("cost_usd"),
                   "tokens": res.get("tokens"), "run_id": rid, "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            if not stopped and res:
                with open(self.results, "a") as f:
                    f.write(json.dumps(row) + "\n")
                self.state["done"] += 1
                self.state["passed"] += int(row["passed"])
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

    def scoreboard(self) -> dict:
        """Per model: tasks passed out of tasks tried (the latest result for each task counts),
        and each task's latest result."""
        latest: dict = {}
        for r in self.rows():
            latest[(r["model"], r["task"])] = r
        by: dict[str, dict] = {}
        for (model, tid), r in latest.items():
            b = by.setdefault(model, {"model": model, "label": r.get("model_label") or model, "tried": 0,
                                      "passed": 0, "costs": [], "tasks": {}})
            b["tried"] += 1
            b["passed"] += int(r["passed"])
            if r.get("cost_usd") is not None:
                b["costs"].append(r["cost_usd"])
            b["tasks"][tid] = r["passed"]
        board = [{"model": b["model"], "label": b["label"], "tried": b["tried"], "passed": b["passed"],
                  "total_cost": round(sum(b["costs"]), 2) if b["costs"] else None, "tasks": b["tasks"]}
                 for b in by.values()]
        board.sort(key=lambda b: -b["passed"])
        return {"board": board, "total": len(ORDER), "recent": self.rows()[-10:][::-1]}
