# Photo to scene: faster with a leaner answer? (2026-11-19, David's Mac)

Question: can a photo scene be built faster without losing quality?

**Today:** the photo call runs at "high" thinking effort, and the model writes every object in full.
**Lean (test only):** "medium" effort, plus one paragraph added to the request:

> WRITE IT COMPACTLY: how long your answer is decides how long the person waits. Keep every object, wall and
> moving part you would build anyway, but: numbers with at most 2 decimals (3 below 5 cm); one material per colour
> per object, reused; the fewest shapes that keep each object's look and its moving parts (no hidden parts, no
> decoration nobody would notice); leave out things smaller than 3 cm.

Code: `claude/project-thread-pzs5q3` = PR #98's branch at 8de97d37e plus this test switch
(`WETLAB_PHOTOSCENE_LEAN=1`). Both runs used the same code, the same lab photo, GPT-6.2 Astra (the default), and
David's ChatGPT sign-in. They ran **at the same time** (ports 8794 and 8796), so they had the same conditions.

## Side by side

| | Today | Lean |
| --- | --- | --- |
| **Create scene → done** | **11 min 23 s** (683 s) | **5 min 56 s** (356 s): **48% less time** |
| Earlier runs of today's version on this photo | 9:02, 9:28 | n/a |
| Answer length | 77 K characters | 42 K characters |
| Objects built / passed physics / placed | 42 / 42 / 42 | 38 / 38 / 38 |
| Retries / skipped | 0 / none | 0 / none |
| Walls | 2 (back, left) | **3** (back, left, prep-room back) |
| Fixed furniture | 16 | 15 |
| Loose items (of which small, under 35 cm) | 26 (21) | 23 (18) |
| Chairs | 4 | 4 |
| Objects with moving parts | 25 | 21 |
| Hinges + slides | 28 + 13 = **41** | 32 + 9 = **41** |
| Extraction arm joints | 6 + 6 | 8 + 8 |
| Shapes (geoms) / bodies, all objects | 472 / 83 | 279 / 79 |
| Bench card | "1 drawer and 2 doors" | "2 doors and 1 drawer" |

Screenshots (today on the left, lean on the right): `lean-view-1-front.png`, `lean-view-2-overview.png`,
`lean-view-3-bench.png`, `lean-card.png`.

## Honest read

- **Faster: yes, clearly.** It took 5:56 against 11:23 in the same conditions. Even against the fastest earlier
  run of today's version (9:02) it is about 35% faster. This is one run each, though, and the model's speed varies
  from run to run.
- **Quality: mostly kept, but not identical.**
  - Kept: the walls (one more than today), all the furniture, the doors and drawers on the benches, the same number
    of moving joints in total (41), all 4 chairs, the extraction arms, and every object passed physics.
  - Lost: about 4 objects, mostly tiny bench items (sample tubes, a pipette tip box). The "under 3 cm" rule does
    exactly that. Objects use ~40% fewer shapes, so they're plainer up close: in the bench close-up, today's bench
    has flasks, beakers and labelled bottles, while the lean bench (a different bench in its scene) has a rack, a
    tray and a vial.
  - Looks: lean's chairs are boxy task chairs, closer to the grey chairs in the photo than today's round stools.
    Today's extraction arms read more clearly from the front.
- **Verdict:** about twice as fast for a small loss of small-item detail. The room, walls, furniture and moving
  parts are as good. If the tiny items matter, dropping the "smaller than 3 cm" line should keep them at some cost
  in time. That would need one more run to measure.
