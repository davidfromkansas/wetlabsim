# Photo to scene: one-shot vs split mode (2026-11-19, David's Mac)

Code: `claude/project-thread-oh3zfl` at **7f7615efd** (adds `WETLAB_PHOTOSCENE_SPLIT=1`: one call plans the room,
then up to 6 Codex calls build their share of the objects at the same time). Both runs used the same lab photo,
GPT-6.2 Astra (**selected by default**), David's ChatGPT sign-in through Codex, no API keys, port 8794, a fresh
server and a fresh browser session each, one after the other.

- **A** = `WETLAB_PHOTOSCENE_SPLIT=0` (today's one-shot)
- **B** = `WETLAB_PHOTOSCENE_SPLIT=1` (split)

## Side by side

| | A: one-shot | B: split |
| --- | --- | --- |
| **Create scene → done** | **9 min 2 s** (542 s) | **12 min 42 s** (762 s): **41% slower** |
| Model answer(s) in | ~9 min (about 534 s) | plan at 2 min 33 s (153 s); last builder at 10 min 52 s (652 s) |
| Physics test + placing | ~8 s | 1 min 50 s (110 s), incl. one fix call to the model |
| Model calls | 1 | 8 (1 plan + 6 builders + 1 fix) |
| Answer text written | 58 K characters | 273 K characters |
| Objects listed | 43 | 42 (plan) |
| Built / passed physics / placed | **43 / 43 / 43** | **42 / 42 / 42** |
| Retries | 0 | 1 ("Left windows and blinds": too detailed, over 40 bodies / 160 geoms / 24 joints; fixed on the 2nd try) |
| Skipped | none | none |
| Walls built | 3 (back, left, prep-room back) | 3 (back, left, prep-room back) |
| Fixed / loose objects | 19 / 24 | 18 / 24 |
| Objects with moving parts | 24 | 22 |
| Hinges / slides (all objects) | **28 / 13** | **125 / 24** |
| Shapes (geoms) / bodies, all objects | 406 / 84 | **1,260 / 191** |
| Errors | none | none |

Where B's extra joints are: each of its 4 chairs has 11 joints, the extraction arms have
24 and 16 (articulated booms and hoods), the windows and blinds 17, the prep-room counter 12.
A's most-jointed objects are the two island benches (doors + drawer, 5 each) and the extraction rails (4 each).

## Quality read (honest)

- **Not faster.** On this photo split mode was **3 min 40 s slower**. The plan came back quickly (2.5 min), but the
  six builders then wrote almost 5× as much as the one-shot answer, and the slowest one took over 8 minutes after
  the plan. Testing was also slower (heavier objects, plus one fix call). So the speed-up idea didn't hold here.
- **No objects lost.** 42 vs 43, every planned object was built, passed physics and was placed; walls are the same.
- **More detailed objects.** B's objects have 3× the shapes and far more moving parts. In the close-up
  (`split-view-3-bench.png`) B's glassware is more lifelike (a graduated bottle, a labelled reagent bottle, a banded
  jar) and its extraction arms are articulated with clear hoods, closer to the photo. A's room reads equally well
  as a whole (`split-view-1-front.png`, `split-view-2-overview.png`); its office-style chairs are arguably closer
  to the grey task chairs in the photo than B's round stools.
- **More risk per object.** One of B's objects went over the size limits and needed a fix; heavy, many-jointed
  objects (11-joint chairs, 24-joint arms) are slower to simulate and more for a robot to deal with.
- **The object card** (same object, Right island bench): A lists "1 ri far left, 1 ri far right, 1 ri middle door,
  1 ri near door and 1 ri near drawer"; B "1 island front door, 1 island middle door, 1 island front drawer and 1
  island middle drawer". Both work; both show the model's own part names.

**Verdict:** split mode is at least as good in completeness and better in object detail, but **it is slower, not
faster**, on this photo, and uses 8 model calls instead of 1.

## UI notes (split mode)

1. "Building objects **0 of 42**" sits at 0 for about 8 minutes, then jumps, because Codex hands each builder's
   answer back only when it's finished.
2. While building, the Thinking box still says "Working through the photo: 5 thinking steps so far", which is left
   over from the planning step.
3. Testing showed "Fixing the left windows and blinds: the object is too detailed …", which is clear.

## Method notes

- Camera views were set exactly (`V3.glideTo`) from each scene's own extent: 1 front (azimuth 90°, the photo's
  direction), 2 high overview, 3 close-up of the Right island bench. Screenshots are cropped to the 3D view; A on
  the left, B on the right.
- My first script picked the wrong object for A's close-up and card, so for A only, views 3 and the card were taken
  by loading run A's saved scene (its layout, with the same AI-made objects and positions) into a fresh session and
  selecting the bench there.
- Video `photo-demo-split.mp4` (92 s) is run B only: normal speed at the start, when the plan comes back (builders
  start), the start of testing, and the end (placing, the 3 views, the card, Add robot); the model wait is sped up
  50× and testing 20×.
