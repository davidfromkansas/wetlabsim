import json, os, pathlib, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from routine import ROUTINE  # noqa: E402

def out(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()

def write_pick(cwd="."):
    pathlib.Path(cwd, "pick.py").write_text(ROUTINE)

def run_pick(first=False, cwd="."):
    p = subprocess.run([sys.executable, "pick.py"] + (["--first"] if first else []), cwd=cwd,
                       capture_output=True, text=True, timeout=300)
    return (p.stdout + p.stderr).strip(), p.returncode

def think(s=float(os.environ.get("FAKE_THINK", "2"))):
    time.sleep(s)
