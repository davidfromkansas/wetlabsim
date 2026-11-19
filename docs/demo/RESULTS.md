# Photo to scene: real end-to-end run (2026-11-18, David's Mac)

Code: branch `claude/project-thread-oh3zfl` (commit f0e5fe443), run locally on port 8790 from a separate worktree.
Model: **GPT-6 Astra** through the Codex CLI, signed in with David's **ChatGPT subscription** (no API keys:
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` unset, and the server used an account file holding only the ChatGPT sign-in).
Photo: `docs/demo/lab-photo.jpg` (a university teaching lab with benches, fume extractor arms and people).

## Video

`photo-demo.mp4` (93 s, 1440×900). These parts play at normal speed: opening the panel, uploading the photo, clicking
Create scene, the end of the build, orbiting the finished scene, clicking an object, and Add robot.
**The model's 14.5-minute wait is sped up 50×** (video 0:17 to 0:34). Nothing was added or staged.

The Add robot part (last 12 s) is a second short recording. The first recording stopped because the Add robot button
is hidden while an object card is open, so my scripted click timed out. For the second clip I loaded the same scene's
saved layout (`/pg/layout`, AI-made objects included) into a fresh session with `/pg/sessions/new`, which is how
"Copy to my sessions" works, then clicked Add robot. The robot picker opens.

## Numbers

| | |
| --- | --- |
| Total time (Create scene to finished) | **14 min 44 s** (884 s) |
| Waiting for the model's answer | ~14 min 30 s (reasoning finished after ~3 min, then ~11 min writing the answer) |
| Building + physics-testing + placing 40 objects | ~15 s |
| Things the model listed | 40 ("Teaching wet laboratory") |
| Built / tested / placed | **40 / 40 / 40** |
| Failed physics | **0** |
| Retries | **0** |
| Left out (skipped) | none |
| Objects with moving parts | 26 (doors, a drawer, sliding windows, laptop lids, bottle caps, box lids, chair swivels and casters, extractor-arm joints) |
| Fixed (furniture) / loose | 14 / 26 |

What was built: 2 lab islands (with doors and a drawer), 2 wall counters, a rear alcove counter, 4 rolling chairs,
2 laptops, pipette tip boxes, a test tube rack, flasks, beakers, wash and reagent bottles, a tray, a tissue dispenser,
2 whiteboards, open shelving, 4 fume extractor systems, windows and ceiling lights. The people in the photo were left
out, as intended.

## Things worth knowing

1. **No thinking is shown with GPT-6 Astra on a ChatGPT sign-in.** The panel's "Thinking" box stays empty
   ("The model's thinking shows here as it works…") for the whole 14.5 minutes. Codex's reasoning items came back with
   empty `summary_text`, so there was nothing to show. The steps list also stays on "Looking at the photo" with no
   counter until the answer arrives. From the user's side it looks stuck for ~14 minutes.
2. **The timeout doesn't fire while Codex writes its answer.** `_codex_local_stream` only checks
   `CODEX_TIMEOUT * 3` (15 min) when Codex prints a line, and Codex prints nothing while it writes the final message.
   This run finished at 14:44, just under the limit, but a slower answer would never be cut off.
3. **The model's raw answer isn't kept anywhere.** `PhotoBuild.answer` lives only in memory and Codex's temp
   folder is deleted. `model-answer-objects.json` is what can be recovered: each object's label, MJCF, size, mass and
   placement, taken from the session layout.
4. **The object card doesn't mention moving parts.** The "Right laboratory island" card shows size 182×450×90 cm,
   mass 228.2 kg and "Simple shapes, made by AI", but nothing about its 2 doors, drawer and 3 side doors.
   Friction is blank.
5. The scene was placed around the session's existing Robot 1 table, which stays where it was.
6. Add robot is hidden while an object card is open (see above). That may be intended.

## Files here

- `photo-demo.mp4`: the edited video
- `shot-1-building.png`: 1 minute in (thinking box empty)
- `shot-2-building-placing.png`: the last seconds, objects being placed (25 of 40)
- `shot-3-finished-scene.png`, `shot-4-object-card.png`, `shot-5-add-robot.png`

Kept on the Mac only (not in git), in `~/wetlabsim-runs/photo-demo/`: raw recordings (`raw/demo-raw.mp4`
17.8 min, `raw/tail-raw.mp4`), `build-status.json` (final `/pg/scenegen/status`), `model-answer-objects.json`,
`server.log`, `record.log`/`marks.json` (timings), and the recording scripts.
