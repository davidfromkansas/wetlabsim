"""The public MuJoCo Playground on Modal: one private lab per visitor.

    .venv/bin/modal deploy hosting/app.py

web (the front, Modal's stable web address): gives each visitor (a browser cookie, no sign-in)
  their own lab, at most WETLAB_MAX_LABS open at once; lists live runs to watch (/live) and
  every finished run (/pg/runs, each opening the replay viewer: chat, files, rewind).
lab (one container per visitor): a playground server in public mode (free play only, Claude
  models only, runs capped at 5 minutes and about $3, at most 4 runs at once across all labs,
  more wait in a queue). Its page is reached through a tunnel of its own; only the owner's link
  (?key=) can change it, anyone else watches. It shuts down after 15 idle minutes. The robot
  API and the model proxy leave through tunnels of their own, for the agents only: each run's
  Claude Code runs in a Modal Sandbox that can reach those two and nothing else, and the
  Anthropic key ("anthropic-secret") stays in the lab container.
Devin: with the Modal secret "DEVIN_API_KEY" (holding DEVIN_API_KEY, a Devin organization's
service-user key), labs also offer Devin's models, each run's Devin CLI in a Sandbox that can reach
the robot and Devin's own servers only. Without that secret the site is Claude only.
Run records go to the "wetlab-playground-runs" volume, shared by every lab and the front.
"""
import os
import pathlib
import subprocess
import threading
import time

import modal

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORE = [".git", ".venv", "runs", "build", "**/__pycache__", ".pytest_cache", "*.mp4", ".DS_Store",
          "playground/libero_assets/files", "hosting"]
MAX_LABS = 10
FRONT_URL = "https://davidfromkansas--wetlab-playground-web.us-east.modal.run"

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Mesa's software OpenGL behind EGL: MuJoCo renders with no GPU and no display.
    .apt_install("libegl1", "libgl1", "libgles2", "libegl-mesa0", "libgl1-mesa-dri", "libglvnd0")
    .pip_install("mujoco>=4.0,<5", "numpy", "pillow", "mcp", "modal")
    .env({"MUJOCO_GL": "egl", "EGL_PLATFORM": "surfaceless", "PYTHONPATH": "/app", "PYTHONUNBUFFERED": "1",
          "WETLAB_MAX_LABS": str(MAX_LABS), "WETLAB_FRONT_URL": FRONT_URL, "WETLAB_MODAL_APP": "wetlab-playground"})
    .add_local_dir(str(ROOT), "/app", ignore=IGNORE)
)
runs = modal.Volume.from_name("wetlab-playground-runs", create_if_missing=True)
DEVIN_SECRET = "DEVIN_API_KEY"


def _optional_secret(name: str) -> list:
    """The secret if it exists (looked up when deploying), else none."""
    try:
        s = modal.Secret.from_name(name)
        s.hydrate()
        return [s]
    except Exception:  # noqa: BLE001
        return []


lab_secrets = [modal.Secret.from_name("anthropic-secret"), *_optional_secret(DEVIN_SECRET)]
app = modal.App("wetlab-playground", image=image)


def _commit_loop(every=30):
    """Save run records to the volume as they are written (and see other containers' runs)."""
    def loop():
        while True:
            time.sleep(every)
            try:
                runs.commit()
                runs.reload()
            except Exception as e:  # noqa: BLE001
                print("volume sync failed:", e)
    threading.Thread(target=loop, daemon=True).start()


@app.function(cpu=1.0, memory=2048, volumes={"/data": runs}, max_containers=2, scaledown_window=600)
@modal.concurrent(max_inputs=500)
@modal.web_server(8780, startup_timeout=300)
def web():
    subprocess.Popen(["python", "-m", "playground.server", "--host", "0.0.0.0", "--port", "8780", "--no-browser",
                      "--front", "--public", "--robot-port", "0", "--runs", "/data/runs"], cwd="/app",
                     env=dict(os.environ, WETLAB_SESSION_DIR="/tmp/sessions"))
    _commit_loop()


@app.function(cpu=4.0, memory=6144, secrets=lab_secrets,
              volumes={"/data": runs}, max_containers=MAX_LABS, timeout=12 * 3600)
def lab(lab_id: str, owner_key: str):
    """One visitor's lab, for as long as it is in use (its server exits after 15 idle minutes)."""
    with modal.forward(8780) as page, modal.forward(8781) as robot, modal.forward(8782) as proxy:
        env = dict(os.environ, WETLAB_SESSION_DIR="/tmp/sessions", WETLAB_LAB_ID=lab_id, WETLAB_OWNER_KEY=owner_key, WETLAB_LAB_URL=page.url,
                   WETLAB_RUN_TAG=lab_id, WETLAB_MODEL_PROXY_URL=proxy.url, WETLAB_RUN_BUDGET_USD="3")
        _commit_loop()
        proc = subprocess.Popen(
            ["python", "-m", "playground.server", "--host", "0.0.0.0", "--port", "8780", "--no-browser",
             "--public", "--run-minutes", "5", "--max-active", "4", "--idle-minutes", "15",
             "--launcher", "modal", "--robot-port", "8781", "--agent-robot-url", robot.url,
             "--model-proxy-port", "8782", "--runs", "/data/runs"],
            cwd="/app", env=env)
        proc.wait()
    runs.commit()
