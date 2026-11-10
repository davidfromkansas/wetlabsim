"""Spike: the playground's simulator on Modal, headless, in a sandbox with two tunnels: the
app (the page) and the robot API (the only door an agent gets).

    WETLAB_EVAL_TOKEN=... .venv/bin/python hosting/spike_sim.py   # prints the URLs and leaves it running

Not the hosted app yet: one lab, started by hand, to check the image, headless rendering
and speed on Modal's CPUs.
"""
import os
import pathlib
import sys
import time

import modal

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORE = [".git", ".venv", "runs", "build", "**/__pycache__", ".pytest_cache", "*.mp4", ".DS_Store",
          "playground/libero_assets/files"]

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Mesa's software OpenGL behind EGL: MuJoCo renders with no GPU and no display.
    .apt_install("libegl1", "libgl1", "libgles2", "libegl-mesa0", "libgl1-mesa-dri", "libglvnd0")
    .pip_install("mujoco>=4.0,<5", "numpy", "pillow", "mcp")
    .env({"MUJOCO_GL": "egl", "EGL_PLATFORM": "surfaceless", "PYTHONPATH": "/app", "PYTHONUNBUFFERED": "1"})
    .add_local_dir(str(ROOT), "/app", ignore=IGNORE)
)


def main():
    app = modal.App.lookup("wetlab-playground-spike", create_if_missing=True)
    with modal.enable_output():
        sb = modal.Sandbox.create(
            "python", "-m", "playground.server", "--host", "0.0.0.0", "--no-browser",
            "--runs", "/tmp/runs", "--model-proxy-port", "8782",
            app=app, image=image, workdir="/app", cpu=4.0, memory=4096, timeout=3600,
            encrypted_ports=[8780, 8781, 8782],
            # The Anthropic key lives only here, for the model proxy; the evaluator's token comes
            # from whoever started the spike (a remote orchestrator needs it).
            secrets=[modal.Secret.from_name("anthropic-secret"),
                     modal.Secret.from_dict({"WETLAB_EVAL_TOKEN": os.environ["WETLAB_EVAL_TOKEN"]})],
        )
    tunnels = sb.tunnels(timeout=600)
    print("app (the page):", tunnels[8780].url)
    print("robot API     :", tunnels[8781].url)
    print("model proxy   :", tunnels[8782].url)
    print("sandbox id    :", sb.object_id)
    # Left running (up to its timeout); stop it with: modal sandbox terminate <id>, or
    # modal.Sandbox.from_id(id).terminate().


if __name__ == "__main__":
    main()
