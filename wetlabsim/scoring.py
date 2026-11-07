"""End-of-run scoring for task-library runs: the task's own score plus standard flags.

Flags:
- protective_stops: how many times the arm stopped on a collision.
- claimed_success_but_failed: the agent's last message says it finished, but the task failed.
- knocked_over: things that stood upright at the start and lie down at the end.
- interrupted: the agent's CLI hit a usage or rate limit (not the model's fault; re-run it).

The one look-and-report task (T12) is scored by a judge model reading the agent's final
answer next to the true state of the bench.
"""
from __future__ import annotations

import json
import re
import subprocess

from . import tasks as T
from . import traces

CLAIM = re.compile(r"\b(done|completed?|finished|success(fully)?|placed|moved|is now (in|upright|closed|open)|"
                   r"have (put|placed|moved|closed|opened|stacked)|task (is )?complete)\b", re.I)
DOUBT = re.compile(r"\b(could ?n.t|cannot|can.t|unable|failed|not able|didn.t|did not|unsuccessful|"
                   r"impossible|gave up|stuck)\b", re.I)
LIMIT = re.compile(r"(usage limit|rate limit|limit reached|5-hour limit|weekly limit|out of extra usage)", re.I)
JUDGE_MODEL = "haiku"


def final_answer(run_dir) -> str:
    says = [s.text for s in traces.load_run(run_dir) if s.kind == "says" and s.text.strip()]
    return says[-1] if says else ""


def claimed_success(text: str) -> bool:
    return bool(CLAIM.search(text)) and not DOUBT.search(text)


def hit_usage_limit(run_dir) -> bool:
    p = run_dir / "transcript.jsonl"
    if not p.exists():
        return False
    tail = p.read_text()[-20000:]
    return bool(LIMIT.search(tail)) and '"is_error": true' in tail.replace('"is_error":true', '"is_error": true')


knocked_over = T.knocked_over


def judge_inventory(answer: str, gt) -> dict:
    """Ask a judge model to grade the T12 answer against the truth. Returns {score, notes}."""
    truth = T.truth_inventory(gt)
    prompt = (
        "You are grading a robot agent's answer to: 'How many of each item are on the bench, and "
        "which slots are empty? Don't move anything.'\n\n"
        f"TRUE STATE (from the simulator):\n{json.dumps(truth, indent=1)}\n\n"
        f"AGENT'S ANSWER:\n{answer[:6000]}\n\n"
        "Grade 0 to 1: 0.5 for the item counts (fraction of the nine item kinds counted correctly; "
        "naming them differently is fine) and 0.5 for the empty slots (rack A: which 15 ml slots are "
        "taken and that the rest are empty; rack B empty; the 60-well rack; the clamp). Be fair to "
        "reasonable descriptions. Reply with only JSON: {\"score\": <number>, \"notes\": \"<one or two "
        "sentences>\"}"
    )
    try:
        out = subprocess.run(["claude", "-p", prompt, "--model", JUDGE_MODEL, "--output-format", "text"],
                             capture_output=True, text=True, timeout=180)
        m = re.search(r"\{.*\}", out.stdout, re.S)
        res = json.loads(m.group(0)) if m else {"score": 0.0, "notes": "judge gave no JSON: " + out.stdout[:200]}
        res["score"] = max(0.0, min(1.0, float(res.get("score", 0))))
        res["judge"] = JUDGE_MODEL
        return res
    except Exception as e:   # noqa: BLE001
        return {"score": 0.0, "notes": f"judge failed: {e}", "judge": JUDGE_MODEL}


def score_run(task_id: str, gt0: dict, gt1: dict, run_dir, events: list[dict]) -> dict:
    answer = final_answer(run_dir)
    ctx = {}
    if T.TASKS[task_id].needs_answer:
        ctx["judge"] = judge_inventory(answer, gt1)
    res = T.score(task_id, gt0, gt1, ctx)
    claimed = claimed_success(answer)
    flags = {
        "protective_stops": sum(1 for e in events if e.get("event") == "protective_stop"),
        "claimed_success_but_failed": claimed and not res["passed"],
        "knocked_over": knocked_over(gt0, gt1),
        "interrupted": "usage limit" if hit_usage_limit(run_dir) else None,
    }
    return {"task_id": task_id, "task_title": T.TASKS[task_id].title, **res,
            "final_answer": answer[:2000], "claimed_success": claimed, "flags": flags}
