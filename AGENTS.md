# AGENTS.md: start here (for coding agents working on this repo)

This file is for **you, the coding agent changing this repo**. It is not given to the robot AIs.
The `AGENTS.md` / `CLAUDE.md` files under `agent/` are the opposite: they are the starter kit the
*robot-controlling* AI gets in its run workspace. Don't mix the two up (see "Rules" below).

The owner is David. He is not a programmer by trade: talk to him in plain words, keep replies short.

## 1. What the product is

**Playground** (https://wetlab-playground.vercel.app): a web app where a signed-in user builds a
MuJoCo scene (robots on stations, objects dragged in from a library), types a task for a robot,
picks an AI model, and presses Play. The AI (Claude Code, Codex, Devin or Jev) controls the robot
in real time and its chat, code and camera views stream live. Runs are recorded and can be replayed
and shared.

Core principle: the AI gets **only what a real robot owner would have**: the maker's datasheets and
manuals, the robot's camera feeds, and the robot's own physical state (joints, gripper, wrist
force). Nobody tells it what or where the objects are; it has to find them with its cameras.
Physics never pauses while the AI thinks.

Older parts still in the repo (code kept, mostly hidden in the UI):
- `wetlabsim/` started as a single "wet lab robot cell" eval (Franka on a bench with tubes, 8 tasks
  in `wetlabsim/tasks.py`, `python -m wetlabsim.server` on port 8765). The Playground reuses its
  robot controller, sensors, robot API and agent runner.
- Benchmark packs inside the Playground: LIBERO (full LIBERO rooms, Franka only) and WetRobo
  (3 tasks in Lab X / Lab Y, Franka or AgileX PiPER). The same rooms/labs are also offered as free
  starter stations with no pass/fail.

## 2. Architecture

```
Browser ──> Vercel website (web/, Next.js 16)          https://wetlab-playground.vercel.app
              • Clerk: Google sign-in
              • Neon Postgres: users, sessions, runs, run_files, user_api_keys (web/db/schema.sql)
              • Vercel Blob (private store "wetlab-runs"): run files, replays, videos
              • API keys users paste are AES-256 encrypted (Vercel secret API_KEYS_ENCRYPTION_KEY)
              │  asks Modal for the user's container, hands the browser a one-time pass
              ▼
           Modal app "wetlab-playground" (hosting/app.py)
              • web(): the "front" (playground.server --front): hands out containers, live list
              • lab(): ONE Modal container per signed-in account (max 30 at once), running
                playground.server --public: physics, 3D stream, robot API, model proxy.
                Closes after 5 min with no real activity ("Still there?" at 4 min).
              • Each AI run (max 15 at once per account) runs its CLI in its own Modal Sandbox that can reach
                only the robot API tunnel + the model proxy (or Devin's servers). The user's own
                API key stays in the container; the proxy adds it. (wetlabsim/launchers.py,
                playground/model_proxy.py)
              • Volume "wetlab-playground-runs": run records; finished runs also uploaded to Blob
```

Secrets: Modal secrets `wetlab-link` (LAB_LINK_SECRET, shared with Vercel) and `wetlab-db`
(DATABASE_URL). Users bring their own OpenAI / Anthropic / Devin / Jev keys
(Settings > General > Connections, `playground/accounts.py`); the site has no AI keys of its own.

**Deploys are automatic on merge to `main`:**
- Vercel deploys `web/` itself.
- `.github/workflows/deploy-labs.yml` runs `modal deploy hosting/app.py` (skipped when only
  `web/**`, `docs/**` or `*.md` change). Running containers keep old code; containers from an older
  build stop being handed out and close once idle (`playground/labs.py`).
- A test copy exists: `WETLAB_APP=wetlab-playground-staging modal deploy hosting/app.py`.

## 3. Repo layout

| Path | What's there |
| --- | --- |
| `playground/server.py` | The Playground HTTP server (pages, `/pg/*` API, sessions, runs, front mode). Big file; start here. |
| `playground/sim.py` | `PlaygroundSim`: one session's world, stations, arms, runs. |
| `playground/world.py` | Builds the MuJoCo model with `MjSpec`: `Station`, station `KINDS` (table, wetlab, island, LIBERO rooms, WetRobo labs, pallet, car, conveyor...), placing items, jointed parts, soft items, cameras, work-box walls. |
| `playground/catalog.py` | Object library (`TABS`, `ITEMS`, `SOFT`) and robot picker list (`ROBOTS`). |
| `playground/site.py` | The per-station "site sheet" (SITE.md) the AI gets: table, cameras, tool. **Must not list objects.** |
| `playground/scenegen.py` | AI scene generator + one-click preset scenes (`PRESETS`: Factory, Car assembly, kitchen, wet lab...). |
| `playground/libero.py`, `playground/libero_assets/` | LIBERO suites, rooms, success checker. Meshes (~200 MB) download on first use. |
| `playground/wetrobo.py` | WetRobo tasks, live success checks, scoreboard. |
| `playground/accounts.py`, `savestore.py`, `labs.py` | User keys, saving sessions/runs to Neon/Blob, container bookkeeping on Modal. |
| `playground/settings.py` | Scene settings panel (MuJoCo option/flag/material values by their MuJoCo names). |
| `playground/static/` | Front end: `index.html` (main app, one big file), `view3d.js` (three.js view), `runpanel.js`, `scenegen.js`, `scenesettings.js`, `results.js`, `gallery.js`, robot/station thumbnails. |
| `playground/assets/` | Converted SimReady/Tripo/ForgeCAD/AutoBio/LIBERO objects. Not in git (only `CREDITS.md` is): they live in the Modal Volume `wetlab-library` (`python -m playground.tools.library pull` / `push`). |
| `playground/tools/` | One-off build/convert/render scripts (assets, robots, thumbnails). |
| `wetlabsim/scene.py` | Robot definitions (`ROBOTS` dict: franka, ur5e, aloha, fr3_duo, g1, piper, n220, crx30ia, rby1), materials, `OPTION`/`FLAGS`. |
| `wetlabsim/sim.py` | Robot controllers: `Arm`, `TwoArm`, `Humanoid`, `Mobile`; IK, protective stops, sensors, cameras. |
| `wetlabsim/robot.py` | The Python client the AI's code imports (`move_l`, `gripper_move`, `get_camera_frame`...). |
| `wetlabsim/robot_api.py`, `mcp_server.py` | Robot API gate (run tokens) and the MCP tools (look, robot_state, emergency_stop). |
| `wetlabsim/run_agent.py` | Runs one agent on one task: builds its workspace (`prepare_workspace`), CLI command, records the run. |
| `wetlabsim/launchers.py` | Where agents run: local process, or Modal Sandbox. |
| `wetlabsim/datasheets.py` | Fetches/checks makers' datasheets per robot. |
| `wetlabsim/assets/` | Robot models (MuJoCo Menagerie etc., each with its LICENSE) and AutoBio lab items. |
| `agent/<robot>/` | What the robot AI gets: `AGENTS.md`, `CLAUDE.md`, `COMMANDS.md`, `SITE.md`, `datasheets/` (maker docs unchanged + `sources.json`). |
| `hosting/app.py` | The Modal app (image, `web`, `lab`). |
| `web/` | Vercel website (Next.js, Clerk, Neon, Blob). `web/db/schema.sql` + `npm run db:migrate`. |
| `tests/` | pytest suite. `tests/fake_agents/` are stand-in `claude`/`codex`/`devin` CLIs for run tests. |
| `docs/` | Physics settings page, SimReady data audit, screenshots. |

## 4. Run it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e . pytest modal
python -m playground.tools.library pull   # the object library (~8 GB, from Modal; needs `modal token new`)
python -m playground.server          # http://localhost:8780 (robot API on 8781)
```

- On Linux with no screen: `export MUJOCO_GL=egl EGL_PLATFORM=surfaceless` (needs `libegl1
  libgl1 libegl-mesa0 libgl1-mesa-dri`, as in the Modal image). macOS needs nothing extra.
- Locally (no `--public`) runs use the Claude Code / Codex / Devin CLIs you're logged into. Keys
  saved in local Settings go to `~/.wetlab/account.json`.
- Local run records: `runs/playground/` (gitignored).
- Website: `cd web && npm install && npm run dev`; it needs the Vercel env vars (Clerk keys,
  `DATABASE_URL`, `LAB_LINK_SECRET`, `MODAL_FRONT_URL`, `API_KEYS_ENCRYPTION_KEY`), e.g. via
  `vercel env pull`. Most changes don't need the website running.

## 5. Tests

```bash
MUJOCO_GL=egl EGL_PLATFORM=surfaceless python -m pytest -q tests/test_piper.py   # one file
python -m pytest -q                                                               # everything
```

- Physics tests are slow (a single robot file takes a couple of minutes). Run the files for what
  you changed; run the full suite once before asking for review. Full runs normally go on David's
  Mac (repo at `/Users/david_lietjauw/wetlabsim`) via Remote Control.
- Each robot has its own test file (`test_<robot>.py`); there are also files per feature
  (`test_scenegen.py`, `test_side_by_side.py`, `test_libero.py`, `test_wetrobo.py`, ...).
- For UI changes, also check the page in a headless browser (Playwright) against
  `http://localhost:8780` and look at screenshots.
- `scripts/physics_checks.py` measures grip creep, release, sinking and speed after physics changes.

## 6. How things are added

**A robot** (follow a recent one, e.g. the RB-Y1 commit `09acea2d` or the PiPER):
1. Model in `wetlabsim/assets/<model>/` (Menagerie or maker's package; keep its LICENSE).
   Converters: `playground/tools/convert_simready_arm.py`, `convert_fr3_duo.py`.
2. Entry in `ROBOTS` in `wetlabsim/scene.py` (limits from the maker's datasheet, ready pose,
   gripper, cameras; `sides` = two arms, `humanoid`, `mobile` pick the controller class).
3. AI kit in `agent/<robot>/`: `AGENTS.md`, `CLAUDE.md`, `COMMANDS.md`, `SITE.md`,
   `datasheets/` (maker's documents unchanged + `sources.json` + `SOURCES.md`). Register in
   `wetlabsim/datasheets.py` (`DIRS`) and `wetlabsim/run_agent.py` (`STANDARD_KITS`).
4. Playground: `ROBOTS` in `playground/catalog.py`; standard-docs list in `playground/server.py`;
   controller choice in `playground/sim.py`; placement in `playground/world.py`; site sheet text
   in `playground/site.py`; front end maps in `static/index.html` (`STATION_IMG`, `ROBOT_PIC`,
   camera names, gripper width), `static/runpanel.js`, `static/scenegen.js`; thumbnails via a
   `playground/tools/render_*_pictures.py` script.
5. `tests/test_<robot>.py`.

**An object**: add a row to `ITEMS` in `playground/catalog.py` (id, tab, label, source folder,
hollow, fixed), build it with `python -m playground.tools.build_assets` (or `build_autobio`,
`build_inhouse`, `build_libero_objects`, `build_soft`), upload it with
`python -m playground.tools.library push <id>` (the site reads its files from the Modal Volume;
the catalog row ships with the code as usual), and credit it in `playground/assets/CREDITS.md`. Objects keep their source's own physics data (mass, inertia,
joints, friction); see `docs/simready-data-audit.md`.

**A station type**: an entry in `KINDS` in `playground/world.py` (table item, turn, robot spot,
starting layout; `robot_xy_by` / `layout_by` for per-robot layouts), plus a card and picture in
`static/index.html`.

**A benchmark pack**: a module with tasks + a live success check + scoreboard (see
`playground/wetrobo.py`, `playground/libero.py`), station kinds in `world.py`, wiring in
`server.py` / `index.html`, results to `runs/playground/<pack>_results.jsonl`.

**A preset scene**: `PRESETS` in `playground/scenegen.py`.

**A model/provider**: `MODELS` in `playground/server.py`, provider in `playground/accounts.py`,
CLI command in `wetlabsim/run_agent.py` (`build_command`), sandbox setup in `wetlabsim/launchers.py`.

## 7. Rules (David's standing rules; follow them)

- **No sim workarounds or custom patches.** Use official MuJoCo features and documented settings
  only. If something can't be done that way, say so instead of hacking around it.
- **The AI gets only:** the maker's datasheets/manuals, its camera feeds, and the robot's physical
  state. **No document the AI reads may list scene objects** (site sheets, `agent/` files, LIBERO
  sheet, etc.). It finds objects with its cameras. Grasp hints and true object positions are for
  testing/grading only.
- **Only add robots; never remove existing ones.**
- **Pull/merge the latest `main` into your branch before a PR is merged** (merge commit, re-run
  the tests). **Never merge a PR without David's OK.** Merging to `main` deploys to production.
- **Never stop the Modal app** (it takes the whole site down). To restart your own container, close
  the tab and let it idle out.
- Two Playground tabs on one account share one browser connection limit; test with one tab, or
  expect the second to stall.
- **Keep local and public in sync**: a feature should behave the same on localhost and on the site.
- **Never reuse an API key someone pasted in chat.** Never commit secrets.
- **Don't start extra work that wasn't asked for.** Suggest it in one line instead.
- When David says **"mock up"**, he means a Claude Design canvas built from this codebase (the
  source of truth), not from screenshots.
- When talking to David, use the real infrastructure names (Modal container / Modal app / Modal
  Sandbox, Vercel website, Neon, Blob), not the code's word "lab".
- Credit every third-party asset (`playground/assets/CREDITS.md`, model LICENSE files).

## 8. Gotchas

- The robot AI's workspace is a temp folder outside the repo; Claude Code runs with repo reads
  denied and `run_agent.workspace_leaks` refuses a workspace that names the repo path. Keep it that way.
- The playground uses MuJoCo's `discrete` integrator (`OPTION` in `playground/world.py`); the
  older wet lab cell uses `implicitfast`. Contact properties are per material class.
- `playground/libero_assets/files/` and the G1's GEAR-SONIC `.onnx` files are downloaded, not in git.
- `*.png` is gitignored except listed folders; add a `!` rule in `.gitignore` for new image folders.
- Sessions on a Modal container live in memory and autosave to Neon for signed-in users.
