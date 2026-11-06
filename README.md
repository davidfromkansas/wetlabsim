# Wet Lab Sim

![Live viewer](docs/viewer.png)

A realistic, real-time robot cell for testing how well AI agents (Claude Code,
Codex, Devin) can control a robot arm in a wet lab.

A simulated **Franka Emika Panda arm** with its **Franka Hand gripper** stands on a lab bench with
tube racks and 15 ml tubes. Physics runs in [MuJoCo](https://mujoco.org) and never
pauses. Agents control the arm by writing Python against a robot API that mirrors
real hardware. They only get what a real robot would have: camera images (with
depth), joint readings, wrist force, and gripper status. Nobody tells them where the
tubes are.

## Quick start (Mac or Linux)

```bash
git clone https://github.com/davidfromkansas/wetlabsim && cd wetlabsim
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 1. Start the robot cell, then open http://localhost:8765 to watch it live
python -m wetlabsim.server

# 2. In a second terminal, give an agent a task
python -m wetlabsim.run_agent --agent claude --task "Move the tube with the red cap into an empty slot of the other rack."
python -m wetlabsim.run_agent --agent codex  --task "Move the tube with the red cap into an empty slot of the other rack."
```

Claude Code and Codex use your existing logins, so no API keys are needed. Install
them first if you haven't: `npm i -g @anthropic-ai/claude-code @openai/codex`.

Devin works the same way through the Devin CLI (`--agent devin`). Install it with
`curl -fsSL https://cli.devin.ai/install.sh | bash` (or `brew install --cask devin-cli`),
then run `devin auth login` once. Devin is only allowed to run Python, edit files in its
own workspace and use the robot tools.

By default agents get what a lab would hand over with a real Franka: Franka's own
documents unchanged (copies in `agent/datasheets/`, see `SOURCES.md` there), a short site sheet and
camera calibration, the robot-only MuJoCo model, and a command reference without tips
(`agent/franka/`). `--docs assisted` gives them our hand-written manual with tips and
pixel/point helpers instead. The simulator's speed, acceleration, force-sensing and
protective-stop limits follow Franka's published numbers (sources in
`agent/datasheets/SOURCES.md`). `python -m wetlabsim.datasheets` checks Franka's files
against their recorded checksums and re-downloads any that are missing.

The arm is a Franka Panda by default. To run the earlier UR5e + Robotiq 2F-85 cell
instead, start the server with `--robot ur5e` (or set `WETLAB_ROBOT=ur5e`); agents
automatically get that robot's manual.

On a Linux machine with no screen, add `MUJOCO_GL=egl` (NVIDIA GPU) or
`MUJOCO_GL=osmesa` (CPU only) before the server command.

There's also a hand-written baseline that solves the same task using only the
cameras: `python examples/scripted_pick_place.py`.

## How it fits together

| Part | File | What it does |
| --- | --- | --- |
| Scene | `wetlabsim/scene.py` | Bench, racks, tubes, cameras, the arm and gripper (models from [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie)). |
| Robot cell | `wetlabsim/sim.py`, `wetlabsim/server.py` | Real-time physics, the arm's motion controller, sensors, safety stops, cameras, and the live viewer. |
| Robot API | `wetlabsim/robot.py` | What agents' code imports: `move_l`, `gripper_move`, `get_camera_frame`, and so on. |
| Agent plug | `wetlabsim/mcp_server.py` | MCP tools so agents can look through the cameras, read the robot state, and hit stop. |
| Robot manual | `agent/ROBOT_MANUAL_<robot>.md` | What agents read first, like a manual a lab tech would hand you. |
| Run recorder | `wetlabsim/run_agent.py` | Resets the cell, runs one agent on one task, saves everything. |

### What makes it realistic

- **Time never stops.** While the model thinks, the arm holds its last position.
- **No hidden knowledge.** Agents get cameras (overhead and wrist, colour and depth, calibrated), joint angles, wrist force/torque with ~0.3 N noise, and gripper status, including "object detected".
- **Real controller behaviour.** Straight-line moves, joint moves, unreachable poses are rejected, and a hard bump triggers a protective stop that has to be cleared.
- **Real physics.** Tubes can slip, tip over or get knocked out of their racks.

### What each run saves

Each run creates `runs/<date>-<agent>/` with:

- `task.txt`
- `transcript.jsonl` (everything the agent said and did)
- `states.jsonl` (the robot's readings and the true object positions, 20 times a second, plus every command)
- `result.json` (time taken, commands sent, protective stops, final object positions)
- `workspace/` (the code the agent wrote)

Scoring rules per task come next.

## Notes

- The true object positions are only available to the run recorder, via a token saved in `runs/.eval_token`. Agents aren't given it, but they run on your machine as you, so a determined agent could find it. Check transcripts when results look too good.
- Agents run with permission to execute code. Run them on a machine you're comfortable with (the cloud machine is a good choice).
- Robot models are © their authors under their own licences: see `wetlabsim/assets/*/LICENSE`.
