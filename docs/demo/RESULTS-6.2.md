# Photo to scene with GPT-6.2 Astra: real end-to-end run (2026-11-18, David's Mac)

Code: branch `claude/project-thread-oh3zfl` at commit 38579c116 ("Scenes default to the strongest model; add GPT-6.2
Astra and Sol"), run locally on port 8790 from a separate worktree. Same setup as the GPT-6 Astra run
(`RESULTS.md`): David's **ChatGPT subscription** sign-in through the Codex CLI, no API keys, the same photo
`docs/demo/lab-photo.jpg`.

**GPT-6.2 Astra was already selected when the From a photo tab opened.** It was not picked by hand. Codex ran with
`--model gpt-6.2-astra`.

## Video

`photo-demo-6.2.mp4` (86 s, 1440×900), a single recording. Normal speed: opening the panel, uploading the photo,
Create scene, the end of the build, orbiting the scene, clicking the right island bench (its card), closing the card,
and Add robot opening the robot picker. **The model's ~10.5-minute wait is sped up 50×** (video 0:17 to 0:29).
Nothing was added or staged.

## Numbers

| | GPT-6.2 Astra (this run) | GPT-6 Astra (earlier run) |
| --- | --- | --- |
| Total time (Create scene to finished) | **10 min 39 s** (639 s) | 14 min 44 s (884 s) |
| Things the model listed | 38 | 40 |
| Built / tested / placed | **38 / 38 / 38** | 40 / 40 / 40 |
| Failed physics | **0** | 0 |
| Retries | **0** | 0 |
| Skipped | none | none |
| Objects with moving parts | 23 | 26 |
| Fixed (furniture) / loose | 14 / 24 | 14 / 26 |
| Scene title | "University teaching laboratory" | "Teaching wet laboratory" |

**Comparison:**
- GPT-6.2 Astra finished about **4 minutes (28%) faster**, with the same clean result: everything it listed was built,
  passed physics and was placed, with no retries.
- Both runs spent almost all their time waiting for the model. Building, testing and placing took only seconds in both.
- The scene is a little smaller (38 objects against 40), but the room is more complete. It has the open door to the
  preparation room with its counter and shelves, the windows with blinds, two writing boards, rear wall shelves,
  overhead extraction fittings over both islands, five swivel chairs, and bench glassware, bottles, racks and trays.
- Moving parts are much the same: island bench doors and drawers, cupboard doors, the preparation room door,
  sliding window blinds, laptop lids and extractor-arm joints.
- People in the photo were left out in both runs.

## Same issues as the GPT-6 Astra run

- The Thinking box stays empty and the steps stay on "Looking at the photo" for the whole ~10.5-minute model wait.
  It looks frozen.
- The model's raw answer isn't kept. `model-answer-objects.json` on the Mac has each object's label, MJCF and
  placement, taken from the session layout.
- The object card shows size, mass and "Simple shapes, made by AI" but not the doors or drawers, and Friction is blank.
- Add robot is hidden while an object card is open. This time I closed the card first, so the whole demo is one
  recording.

## Files here

`photo-demo-6.2.mp4` and the screenshots `shot-6.2-1-building.png` (1 minute in), `shot-6.2-2-placing.png`
(placing 16 of 38), `shot-6.2-3-finished-scene.png`, `shot-6.2-4-object-card.png` and `shot-6.2-5-add-robot.png`.
The raw 13.4-minute recording, the build status JSON, the parsed objects and the server log are on the Mac in
`~/wetlabsim-runs/photo-demo-6.2/`.
