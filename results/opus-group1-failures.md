# Why the failed runs failed: opus-group1

Claude Opus 5.5 in Claude Code, standard docs, 15-minute limit. These are the 10 official runs that didn't
pass (20/30 passed). Times are seconds from the start of the run. Each run has a frame of the decisive
moment, room camera on the left and wrist camera on the right, in `failure-frames/<run>.png`.
Sources: the transcript, the command and stop log, the replay, and the final true state.

Root-cause labels:
- **MODEL**: a wrong belief, perception, planning or time management.
- **SIM**: a physics artifact.
- **TASK**: wording, an impossible part, or the scoring.
- **HARNESS**: tooling or limits.

None of the 10 failed runs claimed success ("done") falsely. In one (T25 try 1) Opus believed it had
failed when the cap was in fact on.

## Run by run

| Run | Score | Decisive moment | What Opus believed | Cause | Real Franka would fail the same way? |
|---|---|---|---|---|---|
| T19 try 2 (`214642`) | 0 | **214 s.** Opus released the 1.5 ml tube over B3 and lifted the hand. The tube stayed stuck to one finger while the gripper was open at 22 mm, then tipped over onto the rack. The replay shows its cap 0.5 mm deep inside the left finger's collision shape, held up with nothing on the other side. After that, re-gripping the lying tube took 10 minutes, including a transposed-rotation bug and its own IK. Time ran out over B3. | "Even partly opened, it stayed lodged between the fingers… stuck against one finger." | **SIM** (a sticky finger), then MODEL (slow recovery) | **No.** A tube can't hang off one open finger. |
| T23 try 1 (`212725`) | 0.75 | **466 s.** The arm bumped the pipette stand's beam, causing a safety stop. It then finished the tubes and the dishes, and was still studying the pipette hook when time ran out (842 s). | "The arm (not the hand) bumped the pipette stand's beam." | **TASK** (pipette item) + HARNESS (4 jobs in 15 min) | **Yes**, for the pipette: this stand has no notch, and our scripted baseline couldn't hang it either. |
| T23 try 2 (`220329`) | 0.75 | **758 s.** Tubes and dishes were done by 557 s. It spent the rest of the time planning the pipette grasp, including modelling the stand for clearance, and never moved it. | Planned a low grip "so the hand stays under the beam" (the same plan our baseline used). | **TASK** + HARNESS | **Yes** (same as try 1). |
| T23 try 3 (`224531`) | 0.5 | **491 s.** Backing away knocked the blue tube over in rack B, and fixing it took 2 minutes. **861 s:** the top dish "stuck to the fingers on release" and ended wedged on the fingers, so the dishes weren't stacked. | "The dish is actually still hanging on the fingers, wedged on them." | MODEL (clearance) + **SIM, suspected** (the dish sticking to open fingers; same pattern as T19) + TASK | **Unsure.** Knocking the tube: yes. A dish wedging on open fingers: unlikely. |
| T24 try 1 (`231317`) | 0.5 | **226 s.** It turned the wrist 2.6 turns, then lifted, but the cap hadn't fully come off: the cap slips in the fingers, so it turns less than the wrist. The lift pulled on the tube and hit a −50 N stop. It got the cap off by 503 s, but the cap fell into a neighbouring clamp slot. Retrieving it, the hand bumped the tube (Fx stop) and tilted it out of the clamp. Time ran out. | "Unscrewing ran 2.6 turns… the cap still isn't free." | **MODEL** (lifting before the cap was free; handling) | **Yes.** Pulling on a still-threaded cap and dropping it into a slot both happen in real life. |
| T24 try 2 (`214828`) | 0.5 | **192 s.** Same as try 1: it lifted while the cap was still threaded and hit the −50 N stop, which drew the tube up. By 467 s the cap was off and set down open side down. It spent the last 5 minutes trying to flip the cap open side up: IK refusals, joint limits, writing its own IK. | "Joint 4 hits its limit when the hand is horizontal this close to the base." | **MODEL** (lifting too early) + **TASK** (open side up is very hard for a parallel gripper; our baseline needed a tip-off trick) | **Yes** for the flip difficulty. |
| T24 try 3 (`223029`) | 0 | **520–548 s.** A force check fired falsely, so it let go of the cap with the cap still on the thread. The whole tube came out of the clamp with the cap on, wedged under the hand. **809–840 s:** it zeroed the force sensor while the fingers were pressing on rack B, which left a 125 N bias and caused repeated stops. | "The whole tube (cap still on) came out of the clamp… The force reading carried a ~125 N offset because I zeroed it while… pressing." | **MODEL** (misused the force sensor; lifted while threaded) | **Yes.** Zeroing a force sensor under load is a classic real-robot mistake. |
| T25 try 1 (`231713`) | 0.75 | **354 s.** The thread had caught at 250 s (3 mm/turn). Then it zeroed the force sensor while pressing down, so the hand drifted 30 mm down and the fingers slid off the cap onto the tube. The cap did end fully closed (0.53 N·m), but the tube was lifted out of the clamp. Opus concluded the cap "was never threaded". | "The cap lifted off with no resistance, so it was never threaded." In fact the tube came up with the closed cap. | **MODEL** (force-sensor zeroing, a wrong belief) | **Yes.** |
| T25 try 2 (`233214`) | 0.75 | **409–468 s.** It screwed 1.65 turns well. Then the fingers lost the cap and it kept turning an empty gripper. The twisting had tilted the tube 25° in the clamp. Its reorientation moves then hit the pipette stand (2 stops), and a re-grip knocked the tube out at 775 s. The cap ended closed, but the tube was on the bench. | "The arm's wrist/elbow is pressing against the pipette stand — the joint configuration drifted into an awkward pose during the screwing." | **MODEL** (didn't check the grip between strokes) + **TASK/layout** (the stand crowds the clamp) | **Yes, mostly.** The stand placement is our choice, though. |
| T25 try 3 (`233707`) | 0 | **413 s.** It set the cap on the rim and turned it, but the cap never caught. The wrist felt no torque, the hand dropped 10 mm and the cap slid off into the clamp. Its depth readings of the rim height disagreed by 14 mm, so the cap was probably off-centre beyond the strict 1 mm rule. It then found the tube sitting 35 mm high, re-seated it, fetched the cap again, and time ran out just as it lowered the cap. | "Depth readings of the rim height disagree (0.127 vs 0.141 m)… The turn didn't behave as expected." | **MODEL** (alignment, perception) + **TASK, unsure** (whether a 1 mm catch tolerance is stricter than a real chamfered cap) | **Probably.** A real cap 1–2 mm off-centre often still catches, so our rule may be a bit harsh. |

## Patterns

1. **Almost every failure is a timeout.** 9 of 10 hit the 15-minute limit. None ran out of ideas or gave up.
   The time goes on long recovery loops after a slip: writing its own kinematics and IK, re-measuring.
   T23 asks for four jobs in 15 minutes.
2. **Caps: "lift while still threaded" pulls the tube out of the clamp** (all 3 T24 runs and 2 T25 runs). Opus
   counts wrist turns, but the cap slips in the fingers, so it turns less. It then lifts, and the clamp's grip loses
   to the arm. With the hand rigid, every misalignment turns into a large force.
3. **Force-sensor misuse:** in 2 runs it zeroed the force reading while pressing on something, then trusted
   the biased value. That's a real-world mistake and a fair one to penalise.
4. **The pipette stand gets in the way:** 3 safety stops in T23 try 1 and T25 try 2. Its spot near the clamp
   crowds the wrist during cap work.
5. **Sticky release of light objects:** a simulator artifact. Twice an open gripper kept holding a light
   object. T19: the 1.5 ml tube's cap was trapped 0.5 mm inside the finger's collision shape. T23 try 3: a dish
   stayed wedged on the fingers. This is a side effect of the hard contacts we added for light objects.
6. **No false "done":** in all 10 failures Opus reported honestly what it saw. Its one wrong belief went the
   cautious way.

## The 3 most useful fixes (fairer, not easier)

1. **SIM: fix the sticky release.** Give light objects firm contact against things pressing *into* them, but no "trapped
   inside" stickiness. Use the finger pads' own collision boxes for the tube and dish contacts rather than the coarse
   finger hull, and add a test: open the gripper on a held 1.5 ml tube, a 15 ml tube and a dish, and each must fall
   within 0.2 s. This would likely have saved T19 try 2 and maybe T23 try 3.
2. **SIM + DOCS: realistic cap and clamp behaviour.**
   - Measure, or look up, the pull-out force of a real spring-grip rack and a real cap's catch tolerance with its
     lead-in chamfer. Set our clamp (currently about 28 N) and the 1 mm catch rule to match.
   - Add the compliant (spring-like) arm from the plan, so a slightly misaligned cap doesn't produce huge forces.
   - In the site sheet, say what any lab user knows: "the clamp stops a tube turning, not being pulled out;
     check the cap is free before lifting".
3. **TASK: remove things the benchmark shouldn't be testing.**
   - Move the pipette stand away from the clamp.
   - Either replace the stand with one that has a real pipette notch, as real stands do, or drop "pipette on its
     stand" from T23.
   - Give T23, which has four sub-jobs, a longer limit (for example 25 minutes), or score it per item, as now, but
     report time per item.

Uncertain: whether the 1 mm catch tolerance is too strict (T25 try 3), and whether a dish wedging on open
fingers (T23 try 3) is the same artifact as T19. Both need a quick test before we call them SIM.
