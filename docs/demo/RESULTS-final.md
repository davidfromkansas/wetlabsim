# Photo to scene: final check of PR #98 (2026-11-19, David's Mac)

Code: `claude/project-thread-oh3zfl` at **eb1eeda5e** (30 × 30 m floor, Stop ends as "stopped", demo photo removed,
latest `main` merged in). Same setup as the earlier runs: GPT-6.2 Astra (**selected by default**, not picked by
hand) through Codex on David's ChatGPT sign-in, no API keys, the same lab photo. Port 8794, 1280×800 recording.

## Video

`photo-demo-final.mp4` (89 s), one recording. Normal speed: opening the panel, uploading the photo, Create scene, a
6 s stretch of the progress panel showing **"Writing the scene · thought in 5 steps"**, the end of the build and the
room appearing beside Robot 1's table, an orbit, the Right island bench's card (with **Moving parts**), closing the
card, and **Add robot** opening the robot picker. The model wait (9 minutes) is sped up 50× in two parts.

## Numbers

| | Final (eb1eeda5e, walls) | Walls run (93e5e34ca) | 6.2 run without walls |
| --- | --- | --- | --- |
| Time | **9 min 28 s** (568 s) | 18 min 50 s, then failed | 10 min 39 s |
| Objects | **38** | 43 | 38 |
| Built / tested / placed | **38 / 38 / 38** | 43 / 43 / **0** (no floor space) | 38 / 38 / 38 |
| Retries / skipped | 0 / none | 0 / none | 0 / none |
| Thinking steps shown | 5 | 0 (counter broken) | not shown |
| Answer saved | `photos/f7565c58.answer.txt` (64 KB) | `photos/7a2096da.answer.txt` | not saved |

The room now has its **back wall (yellow) and left wall**, recessed wall shelves, a clerestory window that slides, the
two whiteboards on the back wall, the shelves and worktop of the adjoining room, 4 benches (both island benches have
doors, the right one also a drawer), 2 overhead extraction rails, 3 rolling chairs, 2 laptops and bench glassware. 15 objects are
fixed and 18 have moving parts. It was placed **beside Robot 1's table** on the bigger floor.

## The fixes, checked

- **30 × 30 m floor:** the walled room now fits next to the robot table.
- **Live progress:** the step counter counted up to 5, then "Writing the scene · thought in 5 steps" with the
  explanation in the Thinking box (`shot-final-2-writing-the-scene.png`).
- **The model's answer is saved:** `photos/f7565c58.answer.txt`.
- **Moving parts on the card:** shown, and Friction is filled in (0.52) (`shot-final-4-object-card.png`).
- **Add robot:** opens the robot picker once the card is closed.

## UI problems seen

1. **Moving parts uses internal names.** The Right island bench card says "1 ri lower a, 1 ri lower b and 1 ri
   drawer" (the model's own part names) instead of something like "2 doors and 1 drawer".
2. "Writing the scene" says "often 5 to 10 minutes"; here it took about 7 minutes, so that's accurate.

## Full test suite (eb1eeda5e, MUJOCO_GL unset, on the Mac)

**8,138 passed, 2 failed** (19.5 min). Both failures also happen, identically, on `origin/main` (a685a063a), so they
are not caused by PR #98:

- `tests/test_lab_additions.py::test_new_item_rests_on_the_floor[nv_utensil_cellarview_a01]`:
  `AssertionError: obj_a__6 fell through` (`-0.405 > -0.08` fails).
- `tests/test_showcase_scenes.py::test_moving_parts_move_both_ways[rice_cooker]`:
  `('rice_cooker', 'obj_rice_cooker_2__3_sensor_compression', 0.00026, 0.00056, 0.0025)`: the 2.5 mm
  sensor button moved 0.3 mm against the 0.45 mm needed.

(The object library on this Mac is the main checkout's copy, linked into the test worktree.)

## Files here

`photo-demo-final.mp4`, `shot-final-1-building.png` (1 min in), `shot-final-2-writing-the-scene.png`,
`shot-final-3-finished-scene.png`, `shot-final-4-object-card.png`, `shot-final-5-add-robot.png`.
The raw 15.5-minute recording, the model's answer, the build status, the test log and the server log are on the Mac
in `~/wetlabsim-runs/photo-demo-final/`.
