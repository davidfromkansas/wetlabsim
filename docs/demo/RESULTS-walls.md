# Photo to scene with walls: real run (2026-11-18, David's Mac)

Code: `claude/project-thread-oh3zfl` at 93e5e34ca (walls, live progress, saved answer, moving parts on the card).
For the step-counter check: b991a8634. Same setup as before: GPT-6.2 Astra (selected by default) through Codex on
David's ChatGPT sign-in, no API keys, the same photo `docs/demo/lab-photo.jpg`. Port 8794.

## Result: the scene was not placed

| | Walls run (93e5e34ca) | 6.2 run without walls (38579c116) |
| --- | --- | --- |
| Time | 18 min 50 s (1130 s), then it failed | 10 min 39 s |
| Objects in the answer | **43** (3 walls, a door, a window, the next room's bench) | 38 |
| Built / tested | **43 / 43** | 38 / 38 |
| Placed | **0**: "There's no free floor space big enough for this scene: remove something first." | 38 |
| Retries / skipped | 0 / none | 0 / none |

**The model did what was asked.** Its answer has a back wall, a left wall, the wall of the room beyond the door,
the lab door, the window with shelves under it, both whiteboards on the back wall, 4 benches, 2 extraction arm
rows, 4 chairs and a stool, 2 laptops and 20 small items (bottles, flasks, racks, tubes, a tray, cartons). Every object passed the physics test. The answer was saved as
`photos/7a2096da.answer.txt` (84 KB), so the "keep the model's answer" fix works.

**Why placing failed:** with walls, the scene's footprint is about 7.4 m × 7.6 m (the left wall at x = -3.66, benches
to x ≈ +3.3; chairs from y ≈ 2.5 to the next room's wall at y = 9.0). `_free_spot` only accepts spots inside
±8.3 m of the floor's centre, and the session's Robot 1 table stands at the centre (with a 0.4 m margin). No spot
beside the table fits a 7.4-7.6 m scene, so the whole build failed after 19 minutes of model time. The run without
walls was smaller and fit.

## Progress panel

- **93e5e34ca:** the step counter stayed at 0 for the whole run (`steps: 0`), so the panel said "Looking at the
  photo" for 19 minutes and "Writing the scene" never appeared. The reason: `codex exec --json` doesn't print the
  empty reasoning items; they're only in Codex's session log.
- **b991a8634 (fix):** checked for 3.5 minutes on a fresh run. Steps went 0 → 1 → … → 6 over the first ~105 s.
  After ~40 s with no news the row switched to **"Writing the scene · thought in 6 steps"**, and the Thinking box
  said "Done thinking. Now writing out every object as shapes, sizes, weights and hinges. This is the longest part,
  often 5 to 10 minutes." (screenshot `shot-walls-3-step-progress.png`). This works.

## UI problems seen

1. **Stop shows a wrong error.** Pressing Stop while Codex is writing ends the build (the Codex process is gone),
   but the panel says "Couldn't build the scene. Codex gave no answer (is the ChatGPT sign-in still good? Try
   signing in again in Settings)", with phase `error`. It should say the build was stopped, not suggest the sign-in
   is broken (`shot-walls-4-stop-message.png`).
2. **The floor-space error comes only at the end**, after the model has worked for 19 minutes, and "Try again" would
   presumably ask the model again rather than reuse the built objects. A scene that's too big could be moved into
   a bigger free area, or the error could at least say how big the scene is and what's in the way.
3. Earlier issues still open: the object card had no chance to show Moving parts in this run (nothing was placed).

## Files here

`shot-walls-1-building.png` (1 min in, 93e5e34ca, no counter), `shot-walls-2-no-floor-space.png` (the error),
`shot-walls-3-step-progress.png` (b991a8634, "Writing the scene"), `shot-walls-4-stop-message.png`.
No video: the build failed, so there was no scene to show. The raw 19-minute recording, the model's full answer
and the server logs are on the Mac in `~/wetlabsim-runs/photo-demo-walls/`.
