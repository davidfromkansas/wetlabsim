"""A one-off check that Jev drives the robot for real: on Modal, with the Modal secret JEV_API_KEY,
start a robot cell (Franka on the lab bench), run Jev on a task for a minute and print what it did.
Deploys nothing (an ephemeral app).

    .venv/bin/modal run hosting/jev_check.py
    .venv/bin/modal run hosting/jev_check.py --task "Push the blue tube rack to the left." --seconds 90
"""
import json
import pathlib

import modal

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORE = [".git", ".venv", "runs", "build", "**/__pycache__", ".pytest_cache", "*.mp4", ".DS_Store",
          "playground/libero_assets/files", "hosting", "web"]
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libegl1", "libgl1", "libgles2", "libegl-mesa0", "libgl1-mesa-dri", "libglvnd0", "poppler-utils")
    .pip_install("mujoco>=4.0,<5", "numpy", "pillow", "mcp")
    .env({"MUJOCO_GL": "egl", "EGL_PLATFORM": "surfaceless", "PYTHONPATH": "/app", "PYTHONUNBUFFERED": "1"})
    .add_local_dir(str(ROOT), "/app", ignore=IGNORE)
)
app = modal.App("wetlab-jev-check", image=image)


@app.function(cpu=4.0, memory=6144, timeout=900, secrets=[modal.Secret.from_name("JEV_API_KEY")])
def check(task: str, seconds: int, site: str = "") -> dict:
    import subprocess
    import time
    import urllib.request

    cell = subprocess.Popen(["python", "-m", "wetlabsim.server", "--runs", "/tmp/runs", "--robot", "franka"], cwd="/app")
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/state", timeout=2)
            break
        except OSError:
            time.sleep(1)
    extra = []
    if site:
        pathlib.Path("/tmp/SITE.md").write_text(site)
        extra = ["--site-file", "/tmp/SITE.md"]
    out = subprocess.run(["python", "-m", "wetlabsim.run_agent", "--agent", "jev", "--model", "jev-1.14.0",
                          "--task", task, "--runs", "/tmp/runs", "--time-limit", str(seconds), *extra],
                         cwd="/app", capture_output=True, text=True)
    cell.terminate()
    runs = sorted(pathlib.Path("/tmp/runs").glob("2*"))
    lines = [json.loads(l) for l in (runs[-1] / "transcript.jsonl").read_text().splitlines()] if runs else []
    return {"runner": (out.stdout + out.stderr)[-2000:], "events": lines,
            "run": json.loads((runs[-1] / "run.json").read_text()) if runs else {}}


@app.local_entrypoint()
def main(task: str = "Pick up the red-capped tube and lift it a little.", seconds: int = 60, site_file: str = ""):
    res = check.remote(task, seconds, pathlib.Path(site_file).read_text() if site_file else "")
    print(res["runner"])
    for e in res["events"]:
        if e.get("kind") == "step":
            a = e["answers"]
            pick = lambda k: f"{(a.get(k) or {}).get('choice')} ({(a.get(k) or {}).get('confidence')})"  # noqa: E731
            print(f"step {e['step']:3d}  {e['seconds']:.2f}s  goal={pick('goal')}  move={pick('move')}  "
                  f"step={pick('step')}  done?={(a.get('task_done') or {}).get('noul')}  "
                  f"box={(a.get('target') or {}).get('box')}  -> {e['did']}")
        elif e.get("type") == "_jev":
            print(e.get("kind"), {k: v for k, v in e.items() if k not in ("questions", "type")})
    r = res["run"]
    print({k: r.get(k) for k in ("model", "model_label", "tokens", "cost_usd", "status")})
    pathlib.Path("jev_check_result.json").write_text(json.dumps(res, indent=1))
    print("Full result saved to jev_check_result.json")
