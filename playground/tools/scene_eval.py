"""Test the prompt-to-scene builder on a set of prompts and score each scene.

For every prompt: a fresh empty world, the v2 pick (playground/scenebrief.py), the build
(scenegen.Build, with its look-and-fix rounds), then two pictures and the list of what was placed.
A judge model (a different one from the builder) scores from the pictures and the list:
  objects  1-5  are the objects relevant to the prompt (and varied enough to look like the place)?
  layout   1-5  is the layout relevant (zones, facing, grouping, task things on the robot's table)?
plus automatic checks: nothing that didn't fit, every slot filled, the task names only things there.

    python -m playground.tools.scene_eval --prompts playground/tools/scene_prompts_110.md --out runs/scene-eval/r1
    python -m playground.tools.scene_eval ... --only 1,5,44 --jobs 4

Needs the builder's and the judge's API keys (local Settings or ANTHROPIC_API_KEY / OPENAI_API_KEY),
or --claude-plan to ask Claude through the Claude Code app's own sign-in instead (no API charges)
and, for Jev's picks, JEV_API_KEY. Writes <out>/<n>/{top.jpg,front.jpg,result.json},
<out>/results.jsonl and <out>/index.html (a gallery of every scene with its scores).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import json
import pathlib
import re
import threading
import time
import traceback

from playground import scenebrief as SB
from playground import scenegen as SG
from playground import catalog
from playground.sim import PlaygroundSim

JUDGE_SYSTEM = """You judge scenes built for a robot physics playground from a person's typed \
request. You get two pictures of the scene (from above, and from the side facing the robots), \
the list of robots and objects placed, and the task the robot will be given. Judge only what the \
request asked for; our object library is limited, so a sensible stand-in for something we don't \
have is fine and a missing thing that was asked for costs a little.

Score each from 1 to 5:
- objects: are the objects relevant to the request, and is there the variety a real place like \
that has? 5 = everything fits and it reads clearly as the requested place; 3 = right idea but \
odd picks, thin or repetitive; 1 = mostly unrelated.
- layout: is the layout relevant? Zones make sense, furniture and appliances face the room and \
the robots, things are grouped as people keep them, the task's objects are on the robot's table \
within reach, nothing absurd. 5 = looks like a real, usable place; 3 = usable but messy or odd; \
1 = makes no sense.
- task_ok: true if the task can be done with what is in the scene.

Answer with JSON only:
{"objects": 4, "layout": 3, "task_ok": true, "why": "one or two plain sentences",
 "fix": "the single most useful change to the builder for this kind of request"}"""


def read_prompts(path: str) -> list[dict]:
    out, persona = [], ""
    for line in pathlib.Path(path).read_text().splitlines():
        m = re.match(r"##\s+\d+\.\s+(.*?)\s*\(\d+\)", line)
        if m:
            persona = m.group(1)
            continue
        m = re.match(r"(\d+)\.\s+\[(\w+)\]\s+(.*)", line.strip())
        if m:
            out.append({"n": int(m.group(1)), "style": m.group(2), "persona": persona, "prompt": m.group(3)})
    return out


class _Sess:
    def __init__(self):
        self.unsent = {}


def build_one(p: dict, model: str, judge: str, out: pathlib.Path) -> dict:
    d = out / str(p["n"])
    d.mkdir(parents=True, exist_ok=True)
    res = {**p, "model": model, "judge": judge}
    t0 = time.time()
    try:
        sim = PlaygroundSim(stations=[])
        sim.pause()
        pk = SB.pick(p["prompt"], model, False)
        res["pick"] = {k: pk[k] for k in ("title", "robots", "items", "missing", "task", "ranked_by", "seconds", "slot_of") if k in pk}
        res["brief"] = pk["brief"]
        b = SG.Build(sim, _Sess(), p["prompt"], pk, model, False)
        b.start()
        while b.status()["active"]:
            time.sleep(0.3)
        st = b.status()
        res["build"] = {k: st[k] for k in ("phase", "error", "counts", "skipped", "task", "plan", "fixes")}
        res["build"]["measured"] = getattr(b, "measured", [])     # measured problems at each check round
        res["layout"] = {"raw": getattr(b, "raw_layout", None),
                         "objects": [{k: v for k, v in o.items() if k != "yaw"} for o in getattr(b, "laid", [])]}
        res["seconds"] = round(time.time() - t0, 1)
        if st["phase"] != "done":
            raise RuntimeError(f"build {st['phase']}: {st['error']}")
        imgs = b.pictures()
        for name, img in zip(("top.jpg", "front.jpg"), imgs):
            (d / name).write_bytes(img)
        placed = [catalog.item(sim.find(u).item)["label"] for u in b.objects if sim.find(u)]
        robots = [f"{sim.station(u).robot}" for u in b.stations if sim.station(u)]
        res["placed"] = placed
        user = (f"The person's request:\n{p['prompt']}\n\nRobots: {robots}\nObjects placed: {placed}\n"
                f"Things we don't have: {[m['name'] for m in pk['missing']]}\nTask: {st['task']}")
        res["score"] = SG.ask_json(judge, JUDGE_SYSTEM, user, False, effort="medium", images=imgs)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
        res["trace"] = traceback.format_exc()[-1500:]
    res["seconds_total"] = round(time.time() - t0, 1)
    (d / "result.json").write_text(json.dumps(res, indent=1))
    return res


def passed(r: dict) -> bool:
    s = r.get("score") or {}
    return (not r.get("error") and SG._int(s.get("objects"), 0) >= 4 and SG._int(s.get("layout"), 0) >= 4
            and bool(s.get("task_ok", True)) and not (r.get("build") or {}).get("skipped"))


def gallery(out: pathlib.Path, rows: list[dict]):
    e = html.escape
    cards = []
    for r in sorted(rows, key=lambda r: r["n"]):
        s = r.get("score") or {}
        ok = passed(r)
        miss = ", ".join(m["name"] for m in (r.get("pick") or {}).get("missing", []))
        skipped = ", ".join((r.get("build") or {}).get("skipped") or [])
        cards.append(f"""<article class="{'ok' if ok else 'bad'}"><header><b>#{r['n']}</b> <span>{e(r['persona'])} · {e(r['style'])}</span>
<em>{'pass' if ok else 'fail'}</em></header><p class="pr">{e(r['prompt'])}</p>
<div class="im"><img loading="lazy" src="{r['n']}/top.jpg"><img loading="lazy" src="{r['n']}/front.jpg"></div>
<p><b>Objects {e(str(s.get('objects', '-')))}/5 · Layout {e(str(s.get('layout', '-')))}/5{'' if s.get('task_ok', True) else ' · task not doable'}</b> {e(str(s.get('why', '')))}</p>
<p class="sm">Task: {e((r.get('build') or {}).get('task') or '')}</p>
<p class="sm">Placed: {e(', '.join(r.get('placed') or []))}</p>
{f'<p class="sm">Not in library: {e(miss)}</p>' if miss else ''}{f'<p class="sm warn">Did not fit: {e(skipped)}</p>' if skipped else ''}
{f'<p class="sm warn">{e(r["error"])}</p>' if r.get('error') else ''}
<p class="sm">Fixes: {e('; '.join((r.get('build') or {}).get('fixes') or []) or 'none')} · picked by {e(str((r.get('pick') or {}).get('ranked_by', '')))} · {r.get('seconds_total', '')} s</p></article>""")
    n_ok = sum(passed(r) for r in rows)
    (out / "index.html").write_text(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scene test round</title><style>
body{{font:14px/1.45 system-ui;margin:0;padding:16px;background:#f6f7f9;color:#111}}h1{{font-size:20px}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}}
article{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:12px}}article.bad{{border-color:#fca5a5}}
header{{display:flex;gap:8px;align-items:baseline}}header span{{color:#6b7280;flex:1}}header em{{font-style:normal;font-weight:600}}
.ok header em{{color:#16a34a}}.bad header em{{color:#dc2626}}.pr{{font-weight:500}}.im{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
img{{width:100%;border-radius:8px;background:#eee}}.sm{{color:#4b5563;font-size:12.5px;margin:4px 0}}.warn{{color:#b45309}}
</style><h1>{n_ok} of {len(rows)} scenes pass</h1><main>{''.join(cards)}</main>""")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="claude-fable-5-2")
    ap.add_argument("--judge", default="gpt-6-astra")
    ap.add_argument("--only", default="", help="prompt numbers, e.g. 1,5,44 or 1-10")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--claude-plan", action="store_true",
                    help="ask Claude through the Claude Code app's sign-in (a Claude plan), not an API key")
    ap.add_argument("--grid", action="store_true", help="lay out by square (playground/scenegrid.py)")
    a = ap.parse_args(argv)
    if a.grid:
        import os
        os.environ["WETLAB_SCENE_GRID"] = "1"
    if a.claude_plan:
        import os
        os.environ["WETLAB_SCENE_CLAUDE_PLAN"] = "1"
    ps = read_prompts(a.prompts)
    if a.only:
        want = set()
        for part in a.only.split(","):
            lo, _, hi = part.partition("-")
            want |= set(range(int(lo), int(hi or lo) + 1))
        ps = [p for p in ps if p["n"] in want]
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, lock = [], threading.Lock()
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(lambda p: build_one(p, a.model, a.judge, out), ps):
            with lock:
                rows.append(r)
                with open(out / "results.jsonl", "a") as f:
                    f.write(json.dumps({k: v for k, v in r.items() if k != "trace"}) + "\n")
            s = r.get("score") or {}
            print(f"#{r['n']:>3} {'PASS' if passed(r) else 'fail'} obj {s.get('objects', '-')} lay {s.get('layout', '-')} "
                  f"{r.get('seconds_total')}s {r.get('error', '')[:120]}", flush=True)
    gallery(out, rows)
    usage = {m: {"in": u[0], "out": u[1]} for m, u in SG.USAGE.items()}
    (out / "usage.json").write_text(json.dumps(usage, indent=1))
    print(f"{sum(passed(r) for r in rows)} of {len(rows)} pass. Tokens: {usage}")


if __name__ == "__main__":
    main()
