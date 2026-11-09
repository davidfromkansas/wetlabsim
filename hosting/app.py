"""The public MuJoCo Playground on Modal.

    .venv/bin/modal deploy hosting/app.py

One container runs the playground server in public mode (free play only, Claude only, runs
capped at 5 minutes and about $3, 4 at a time with a queue) behind Modal's web address. Two
more ports leave it through tunnels of their own, for the agents only:
  - the robot API (run tokens only), and
  - the model proxy (run tokens only; the Anthropic key, from the "anthropic-secret" Modal
    secret, stays in this container).
Each run's agent (Claude Code) runs in its own Modal Sandbox that can reach those two tunnels
and nothing else. Run records go to the "wetlab-playground-runs" volume, so finished runs stay
viewable (/pg/runs, /viewer?run=<id>) across restarts.
"""
import contextlib
import os
import pathlib
import subprocess
import threading
import time

import modal

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORE = [".git", ".venv", "runs", "build", "**/__pycache__", ".pytest_cache", "*.mp4", ".DS_Store",
          "playground/libero_assets/files", "hosting"]

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Mesa's software OpenGL behind EGL: MuJoCo renders with no GPU and no display.
    .apt_install("libegl1", "libgl1", "libgles2", "libegl-mesa0", "libgl1-mesa-dri", "libglvnd0")
    .pip_install("mujoco>=4.0,<5", "numpy", "pillow", "mcp", "modal")
    .env({"MUJOCO_GL": "egl", "EGL_PLATFORM": "surfaceless", "PYTHONPATH": "/app", "PYTHONUNBUFFERED": "1"})
    .add_local_dir(str(ROOT), "/app", ignore=IGNORE)
)
runs = modal.Volume.from_name("wetlab-playground-runs", create_if_missing=True)
app = modal.App("wetlab-playground", image=image)

_keep = contextlib.ExitStack()      # the agents' tunnels stay open as long as the container


@app.function(cpu=4.0, memory=6144, secrets=[modal.Secret.from_name("anthropic-secret")],
              volumes={"/data": runs}, max_containers=1, scaledown_window=1200, timeout=24 * 3600)
@modal.concurrent(max_inputs=500)
@modal.web_server(8780, startup_timeout=300)
def web():
    robot = _keep.enter_context(modal.forward(8781))
    proxy = _keep.enter_context(modal.forward(8782))
    env = dict(os.environ, WETLAB_MODEL_PROXY_URL=proxy.url, WETLAB_RUN_BUDGET_USD="3")
    subprocess.Popen(
        ["python", "-m", "playground.server", "--host", "0.0.0.0", "--port", "8780", "--no-browser",
         "--public", "--run-minutes", "5", "--max-active", "4", "--launcher", "modal",
         "--robot-port", "8781", "--agent-robot-url", robot.url, "--model-proxy-port", "8782",
         "--runs", "/data/runs"],
        cwd="/app", env=env)

    def commit_loop():               # save run records to the volume as they are written
        while True:
            time.sleep(30)
            try:
                runs.commit()
            except Exception as e:  # noqa: BLE001
                print("volume commit failed:", e)
    threading.Thread(target=commit_loop, daemon=True).start()
