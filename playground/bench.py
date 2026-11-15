"""LIBERO scores: every run on a LIBERO station, graded by LIBERO's own success check.

A run passes the moment the goal holds (LIBERO ends an episode on success) and fails if the
AI finishes, errors or reaches the time limit without it. Results are kept in
runs/playground/libero_results.jsonl (the same file, and rows, as the old LIBERO test mode's)
and summed up on the scoreboard.
"""
from __future__ import annotations

import json
import pathlib
import threading

from . import libero as LB

_LOCK = threading.Lock()


class LiberoScores:
    def __init__(self, results: pathlib.Path, suites: bool = True):
        self.results = results
        self.suites = suites        # LIBERO's rows carry their suite (WetRobo's file has none)

    def record(self, row: dict):
        """One finished run (a stopped one doesn't count)."""
        self.results.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, open(self.results, "a") as f:
            f.write(json.dumps(row) + "\n")

    def rows(self) -> list[dict]:
        if not self.results.exists():
            return []
        out = []
        for line in self.results.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if self.suites and "suite" not in r:          # rows from before the other suites existed
                try:
                    r["suite"] = LB.task(r["task"]).suite
                except KeyError:
                    continue
            out.append(r)
        return out

    def suite_board(self, study: bool = True) -> dict:
        """Passed / tried per model and suite. study=True counts only setups 1-5 (Anthropic's
        study set); the latest result for each (task, setup) counts."""
        latest: dict = {}
        for r in self.rows():
            if study and r["setup"] > LB.STUDY_SETUPS:
                continue
            latest[(r["model"], r["task"], r["setup"])] = r
        by: dict[str, dict] = {}
        for (model, _, _), r in latest.items():
            b = by.setdefault(model, {"model": model, "label": r.get("model_label") or model,
                                      "suites": {k: {"tried": 0, "passed": 0} for k, _, _ in LB.SUITES},
                                      "secs": [], "costs": []})
            c = b["suites"].setdefault(r["suite"], {"tried": 0, "passed": 0})
            c["tried"] += 1
            c["passed"] += int(r["passed"])
            if r["passed"]:
                b["secs"].append(r["seconds"])
            if r.get("cost_usd") is not None:
                b["costs"].append(r["cost_usd"])
        board = []
        per_suite = LB.STUDY_SETUPS if study else None
        for b in by.values():
            tried = sum(c["tried"] for c in b["suites"].values())
            passed = sum(c["passed"] for c in b["suites"].values())
            board.append({"model": b["model"], "label": b["label"], "suites": b["suites"],
                          "tried": tried, "passed": passed, "rate": round(passed / tried, 3) if tried else 0,
                          "avg_seconds": round(sum(b["secs"]) / len(b["secs"]), 1) if b["secs"] else None,
                          "total_cost": round(sum(b["costs"]), 2) if b["costs"] else None})
        board.sort(key=lambda b: -b["rate"])
        sizes = {k: len(LB.tasks(k)) * (per_suite or 50) for k, _, _ in LB.SUITES}
        return {"board": board, "sizes": sizes, "study": study}

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
