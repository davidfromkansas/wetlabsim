"""The results summary: one table of task x try for a batch of task-library runs.

Served live at /results?batch=<name> by the cell's server (each run links to its replay at
/?run=<id>), and exported as one self-contained HTML file with each run's key frames:

    python -m wetlabsim.results --batch opus-group1 --out results.html
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import pathlib

from . import tasks as T

COST_LABEL = "API-equivalent cost (not billed)"


def collect(runs_dir: pathlib.Path, batch: str | None = None) -> list[dict]:
    rows = []
    for d in sorted(pathlib.Path(runs_dir).iterdir()):
        f = d / "result.json"
        if not f.exists():
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        if not r.get("task_id") or (batch and r.get("batch") != batch):
            continue
        if r.get("excluded"):
            continue
        rows.append({
            "run_id": d.name, "task_id": r["task_id"], "task_title": r.get("task_title", ""),
            "attempt": r.get("attempt"), "batch": r.get("batch"), "score": r.get("score", 0.0),
            "passed": r.get("passed", False), "status": r.get("status"), "seconds": r.get("wall_seconds"),
            "cost_usd": r.get("cost_usd"), "tokens": r.get("tokens"), "model": r.get("model_reported"),
            "flags": r.get("flags", {}), "fair": r.get("fair", True), "detail": r.get("detail", {}),
            "final_answer": r.get("final_answer", ""), "commands": r.get("commands"),
            "sim_start": r.get("sim_reset"), "prompt": T.TASKS[r["task_id"]].prompt if r["task_id"] in T.TASKS else "",
        })
    return rows


def excluded(runs_dir: pathlib.Path, batch: str | None = None) -> list[dict]:
    """Runs left out of the table (e.g. "harness leak"), each replaced by a clean re-run."""
    out = []
    for f in sorted(pathlib.Path(runs_dir).glob("*/result.json")):
        r = json.loads(f.read_text())
        if r.get("excluded") and (not batch or r.get("batch") == batch):
            out.append({"run_id": f.parent.name, "task_id": r.get("task_id"), "attempt": r.get("attempt"),
                        "score": r.get("score"), "passed": r.get("passed"), "why": r["excluded"]})
    return out


def _flag_list(row) -> list[str]:
    f = row["flags"] or {}
    out = []
    if f.get("interrupted"):
        out.append("interrupted: " + f["interrupted"])
    if row["status"] == "time_limit":
        out.append("hit time limit")
    if f.get("claimed_success_but_failed"):
        out.append("said done, but failed")
    if f.get("protective_stops"):
        out.append(f"{f['protective_stops']} safety stop{'s' if f['protective_stops'] > 1 else ''}")
    if f.get("knocked_over"):
        out.append("knocked over: " + ", ".join(f["knocked_over"]))
    if not row["fair"]:
        out.append("looked at simulator code")
    if row["status"] == "agent_error":
        out.append("agent error")
    return out


def _verdict(row):
    if (row["flags"] or {}).get("interrupted"):
        return "int", "Interrupted"
    if row["passed"]:
        return "pass", "Pass"
    if row["score"] and row["score"] > 0:
        return "part", "Partial"
    return "fail", "Fail"


def render(rows: list[dict], batch: str | None, live: bool, images: dict | None = None,
           left_out: list[dict] | None = None) -> str:
    order = [t for t in T.TASKS if any(r["task_id"] == t for r in rows)] or list(T.TASKS)
    by_task: dict[str, list[dict]] = {t: [] for t in order}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r)
    tries = max([len(v) for v in by_task.values()] + [3])
    counted = [r for r in rows if not (r["flags"] or {}).get("interrupted")]
    n_pass = sum(r["passed"] for r in counted)
    cost = sum(r["cost_usd"] or 0 for r in rows)
    secs = sum(r["seconds"] or 0 for r in rows)
    from .traces import model_label
    model = model_label(next((r["model"] for r in rows if r["model"]), "") or "")
    e = html.escape

    def link(r):
        return f"/?run={r['run_id']}" if live else f"runs/{r['run_id']}"

    body = []
    for t in order:
        rs = sorted(by_task.get(t, []), key=lambda r: (r["attempt"] or 0, r["run_id"]))
        task = T.TASKS.get(t)
        cnt = [r for r in rs if not (r["flags"] or {}).get("interrupted")]
        rate = f"{sum(r['passed'] for r in cnt)}/{len(cnt)}" if cnt else "–"
        cells = []
        for i in range(tries):
            if i >= len(rs):
                cells.append(f'<td class="cell empty" data-try="Try {i + 1}">not run yet</td>')
                continue
            r = rs[i]
            cls, word = _verdict(r)
            flags = "".join(f'<li>{e(x)}</li>' for x in _flag_list(r))
            img = ""
            if images and r["run_id"] in images:
                img = "".join(f'<img src="data:image/jpeg;base64,{b}" alt="{e(lbl)}" title="{e(lbl)}">'
                              for lbl, b in images[r["run_id"]])
                img = f'<div class="frames">{img}</div>'
            cost_s = f"${r['cost_usd']:.2f}" if r["cost_usd"] is not None else "–"
            time_s = f"{(r['seconds'] or 0) / 60:.1f} min"
            anchor = (f'<a href="{link(r)}">open run</a>' if live
                      else f'<span class="rid">{e(r["run_id"])}</span>')
            cells.append(
                f'<td class="cell" data-try="Try {i + 1}"><div class="v {cls}">{word}<span class="sc">{r["score"]:.2f}</span></div>'
                f'<div class="meta">{time_s} · {cost_s}</div>{img}'
                f'{"<ul class=flags>" + flags + "</ul>" if flags else ""}<div class="lk">{anchor}</div></td>')
        body.append(f'<tr><th class="task"><div class="tid">{e(t)}</div><div class="tt">{e(task.title if task else "")}'
                    f'</div><div class="tp">{e(task.prompt if task else "")}</div></th>{"".join(cells)}'
                    f'<td class="rate" data-try="Pass rate">{rate}</td></tr>')
    head = "".join(f"<th>Try {i + 1}</th>" for i in range(tries))
    note = ("Live: each run opens in the replay viewer." if live else
            "Snapshot. Pictures are each run's start and end, from the room camera. On the Mac, open "
            "http://127.0.0.1:8765/?run=&lt;run id&gt; to replay a run.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Task results</title>
<style>
:root {{ --bg:#fafaf8; --card:#fff; --ink:#1d1d1f; --mute:#6e6e73; --line:#e3e3e0; --pass:#1f8a4c; --part:#b7791f;
  --fail:#c0392b; --int:#6e6e73; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:24px 16px 48px }}
h1 {{ font-size:22px; margin:0 0 4px }}
.sub {{ color:var(--mute); margin-bottom:18px }}
.kpis {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:18px }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:140px }}
.kpi b {{ display:block; font-size:20px }} .kpi span {{ color:var(--mute); font-size:12px }}
.wrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px }}
table {{ border-collapse:collapse; width:100%; min-width:760px }}
th, td {{ border-bottom:1px solid var(--line); vertical-align:top; text-align:left; padding:10px 12px }}
thead th {{ font-size:12px; color:var(--mute); font-weight:600; background:#f4f4f1 }}
th.task {{ width:280px; font-weight:400 }} .tid {{ font-weight:700 }} .tt {{ font-weight:600 }}
.tp {{ color:var(--mute); font-size:12px; margin-top:2px }}
.v {{ display:inline-flex; gap:8px; align-items:baseline; font-weight:700; padding:2px 8px; border-radius:6px; color:#fff }}
.v.pass {{ background:var(--pass) }} .v.part {{ background:var(--part) }} .v.fail {{ background:var(--fail) }} .v.int {{ background:var(--int) }}
.sc {{ font-weight:500; opacity:.9; font-size:12px }}
.meta {{ color:var(--mute); font-size:12px; margin-top:4px }}
.flags {{ margin:6px 0 0; padding-left:16px; font-size:12px; color:#8a3b12 }}
.lk {{ margin-top:6px; font-size:12px }} .lk a {{ color:#0b63c5 }} .rid {{ color:var(--mute); font-family:ui-monospace,monospace; font-size:11px }}
.frames {{ display:flex; gap:4px; margin-top:6px }} .frames img {{ width:110px; border-radius:4px; border:1px solid var(--line) }}
td.empty {{ color:var(--mute); font-style:italic }}
td.rate {{ font-weight:700; text-align:center; white-space:nowrap }}
.foot {{ color:var(--mute); font-size:12px; margin-top:12px }}
@media (max-width: 700px) {{
  table, tbody, tr, th, td {{ display:block; min-width:0; width:auto }}
  thead {{ display:none }}
  tr {{ border-bottom:6px solid var(--bg) }}
  th.task {{ width:auto; border-bottom:none; padding-bottom:4px }}
  td {{ border-bottom:none; padding-top:6px }}
  td[data-try]::before {{ content:attr(data-try); display:block; font-size:11px; color:var(--mute); font-weight:600; margin-bottom:2px }}
  td.rate {{ text-align:left }}
  .frames img {{ width:46% }}
}}
</style></head><body><main>
<h1>Task results{(" · " + e(batch)) if batch else ""}</h1>
<div class="sub">{e(model or "")} · Claude Code · {len(rows)} runs · {note}</div>
<div class="kpis">
<div class="kpi"><b>{n_pass}/{len(counted)}</b><span>runs passed</span></div>
<div class="kpi"><b>{sum(1 for t in order if any(r['passed'] for r in by_task.get(t, [])))}/{len(order)}</b><span>tasks passed at least once</span></div>
<div class="kpi"><b>{secs / 3600:.1f} h</b><span>total run time</span></div>
<div class="kpi"><b>${cost:.2f}</b><span>{COST_LABEL}</span></div>
</div>
<div class="wrap"><table><thead><tr><th>Task</th>{head}<th>Pass rate</th></tr></thead><tbody>
{"".join(body)}
</tbody></table></div>
{_left_out_html(left_out, live)}
<div class="foot">Pass/partial comes from the simulator's true state at the end of each run (T12's answer
is graded by a judge model against it). Partial = some credit. Flags: safety stops, "said done but failed"
(the agent's last message claims success), knocked-over items, runs stopped by a usage limit (re-run, not
counted). Costs are {COST_LABEL.lower()}: these runs use a subscription.</div>
</main></body></html>"""


def _left_out_html(left_out, live) -> str:
    if not left_out:
        return ""
    items = "".join(
        f'<li>{html.escape(r["task_id"] or "")} try {r["attempt"]}: score {r["score"]} '
        f'({"pass" if r["passed"] else "fail"}), excluded: {html.escape(r["why"])} · '
        + (f'<a href="/?run={r["run_id"]}">open run</a>' if live else html.escape(r["run_id"])) + "</li>"
        for r in left_out)
    return (f'<h2 style="font-size:15px;margin:22px 0 6px">Excluded runs ({len(left_out)})</h2>'
            f'<div class="sub">Replaced by clean re-runs in the table above.</div><ul class="ex">{items}</ul>')


def key_frames(runs_dir: pathlib.Path, rows: list[dict]) -> dict:
    """Start and end frames (room camera) for each run, as base64 JPEGs, from its replay."""
    import mujoco
    import numpy as np
    from PIL import Image
    out, models = {}, {}
    for r in rows:
        d = pathlib.Path(runs_dir) / r["run_id"]
        ref = d / "model.ref"
        if not (ref.exists() and (d / "replay.npz").exists()):
            continue
        name = ref.read_text().strip()
        if name not in models:
            m = mujoco.MjModel.from_binary_path(str(pathlib.Path(runs_dir) / "_models" / name))
            models[name] = (m, mujoco.MjData(m), mujoco.Renderer(m, 240, 320))
        m, dd, rr = models[name]
        rec = np.load(d / "replay.npz")
        frames = []
        for label, i in (("start", 0), ("end", -1)):
            dd.qpos[:] = rec["qpos"][i]
            mujoco.mj_forward(m, dd)
            rr.update_scene(dd, camera="side")
            buf = io.BytesIO()
            Image.fromarray(rr.render()).save(buf, "JPEG", quality=70)
            frames.append((label, base64.b64encode(buf.getvalue()).decode()))
        out[r["run_id"]] = frames
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="results.html")
    a = ap.parse_args(argv)
    rows = collect(pathlib.Path(a.runs), a.batch)
    page = render(rows, a.batch, live=False, images=key_frames(pathlib.Path(a.runs), rows),
                  left_out=excluded(pathlib.Path(a.runs), a.batch))
    pathlib.Path(a.out).write_text(page)
    summary = {"batch": a.batch, "runs": len(rows), "passed": sum(r["passed"] for r in rows),
               "by_task": {t: [round(r["score"], 2) for r in rows if r["task_id"] == t] for t in T.TASKS}}
    pathlib.Path(a.out).with_suffix(".json").write_text(json.dumps({"summary": summary, "runs": rows}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
