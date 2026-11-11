# SimReady data audit

What NVIDIA's SimReady assets (and Tripo's) actually contain, what each piece of data means, how
many assets have it, whether the playground uses it today, and which official MuJoCo feature it
maps to. Nothing in the converter changes with this document; it is for deciding what to adopt.

**How this was measured (11 November 2026).** Every NVIDIA asset on Hugging Face
(`nvidia/simready-assets`, 2,669 assets with physics) was read file by file:

- **Read for every asset:** the physics layer, the MuJoCo variant, the materials, the base layer, the MuJoCo collision layer and the packaging manifest.
- **Read for a random 300-asset sample:** the PhysX and Newton variants, the neutral collision layer, the bill of materials and the conformance record.

All 19 Tripo assets (`VAST-AI/Tripo-Simready-Assets`) were read too. Counts below are out of 2,669 unless marked "sample".

## Where each kind of data lives

Each asset ships as one root file plus layers ("payloads"). The root offers three variant sets, PhysX, Newton and MuJoCo, each either `Disabled` or `Enabled`. With all three disabled you get the neutral, engine-independent asset. Enabling one adds only that engine's settings on top. NVIDIA's guide: [Multiple Physics Solvers](https://nvidia.github.io/simready-foundation/latest/guides/multiphysics_solvers.html).

| File | What it holds |
| --- | --- |
| `sm_<asset>.usd` (root) | Variant sets, asset type, validation record (profile `Robotics-Prop 3.1.0`, pass/fail per feature) |
| `payloads/base.usda` | Hierarchy, semantic labels, a one-line description, per-part mass, centre of mass and inertia, joint authoring helpers (`ReferencePrims`), grasp lines (`Grasp`) |
| `payloads/Physics/physics.usda` | Rigid bodies, joints (type, axis, limits, break force), joint drives (springs, dampers, motors), initial joint positions, physics materials |
| `payloads/materials.usda` | Look (PBR shaders, textures) and, on the same material, physical properties: density, friction, restitution, fill ratio, wall thickness, material type, and the non-visual sensor material (base, coating, attributes) |
| `payloads/instances*.usda` | Meshes and collision setup. There is one neutral version plus one per engine (`_mujoco`, `_physx`, `_newton`), each with its own collision approximation |
| `payloads/<Engine>/enabled.usda` | The engine's own settings, applied when its variant is on |
| `.metadata/*.json`, `com.nvidia.simready.packaging.json` | Licence (CC BY 4.0), bill of materials with hashes, conformance records, which file is the root |

## The data, one row per kind

"Used today" refers to `playground/tools/convert_simready.py` as merged in PR #22.

### Physics: bodies and mass

| Data | What it is in real life | Assets | Used today? | MuJoCo equivalent |
| --- | --- | --- | --- | --- |
| Rigid bodies (`PhysicsRigidBodyAPI`) | Each separate solid part | 2,669 (1,006 have several) | **Yes**: one MuJoCo body each | `body` |
| Mass per part (`physics:mass`, base layer) | How heavy each part is | 2,669 | **Yes**, when stated; MuJoCo's default density otherwise | `geom mass` / `body mass` |
| Centre of mass and inertia per part (`physics:centerOfMass`, `diagonalInertia`, `principalAxes`) | Where the weight sits and how hard it is to spin. For example, a hammer's head end is heavy | 2,669 | **No**. MuJoCo computes these from the collision shapes, which is wrong for hollow or unevenly filled items | `body inertial` (`pos`, `diaginertia`, `quat`), explicit inertia |
| Density per material (`physics_density`) | What the material weighs per volume: steel 7,850 kg/m³, plastic about 1,000 | 2,646 | **No** | `geom density` |
| Fill ratio and wall thickness (`physics_fillRatio`, `physics_thickness`) | How hollow a part is. A bottle is a thin shell (4 mm walls, 60% full), not a solid block | 2,646 | **No**. This is why some of NVIDIA's masses look odd when computed from solid volume | Mass from shell volume × density, written as `geom mass`. MuJoCo can also compute shell inertia (`mesh inertia="shell"`) |
| Collision shape (`physics:approximation`) | The simplified shape used for contact | 2,669 | **Yes**: convex hull, or convex pieces (CoACD) where asked | `geom type="mesh"` (convex) |
| Engine-specific collision (MuJoCo layer) | NVIDIA's MuJoCo layer sets every collider to a single convex hull (`mjc:maxhullvert -1`, `mjc:inertia convex`, `mjc:group 2`) | 2,669 | We read the neutral layer instead. In the sample, 4% ask for convex decomposition there, and we honour that | `mesh maxhullvert`, `mesh inertia`, `geom group` |

### Physics: surfaces

| Data | What it is in real life | Assets | Used today? | MuJoCo equivalent |
| --- | --- | --- | --- | --- |
| Static and dynamic friction per material | How grippy each surface is: rubber 0.61, steel 0.3, plastic 0.4 | 2,668. On 1,520 the parts differ | **Partly**: one value per item (the highest) | `geom friction` per part. MuJoCo uses one sliding coefficient, so dynamic = static |
| Restitution per material | How bouncy: plastic 0.4, glass 0.05, ping-pong ball 0.8 | 2,668 | **No** | Contact `solref` with negative damping (MuJoCo's restitution recipe, [Modeling: restitution](https://mujoco.readthedocs.io/en/stable/modeling.html#restitution)) |
| Material type (`physics_type`) | A named material: plastic, steel, glass, rubber, cardboard, fabric… | 2,646 | **No** | None. Useful for picking defaults and for task text |
| Rolling and twisting friction (Newton layer) | Resistance to rolling and spinning in place. Stops a bottle rolling forever | 287 of 287 (sample); always 0.0001 and 0.005 | **No** | `geom condim="6"` with `friction` torsional and rolling terms |

### Physics: joints

| Data | What it is in real life | Assets | Used today? | MuJoCo equivalent |
| --- | --- | --- | --- | --- |
| Revolute and prismatic joints, with axis and limits | Hinges and slides: lids, doors, drawers, plungers | 678 (615 have hinges, 263 have slides) | **Yes** | `joint type="hinge"` / `"slide"`, `range` |
| Fixed joints | Parts glued on: caps, labels, needles | 544 | **Yes**: caps are separate welded parts, the rest are fixed in place | `equality weld`, or the same body |
| Spherical (ball) joints | A ball-and-socket part | 2 | **No** | `joint type="ball"` |
| Joint collision filtering (`physics:collisionEnabled`) | Whether two joined parts may touch each other | every jointed asset (1 asset turns collisions on) | **Yes** | `contact exclude` |
| Joint drives: stiffness and target position | A **spring**: a button pops back, a lid snaps shut, scissors spring open | 131 | **No**. NVIDIA's own MuJoCo layer deletes these | `joint stiffness` + `springref` |
| Joint drives: damping | Resistance proportional to speed, like a soft-close drawer or a viscous plunger | 282 | **No**. NVIDIA's MuJoCo layer deletes these | `joint damping` |
| Joint drives: target velocity and max force | A **motor**: a toaster timer, a fan, a turntable | 29 | **No** | `actuator velocity` (or `motor`) with `forcerange` |
| Joint friction (PhysX layer, `physxJoint:jointFriction`) | Stiffness of a hinge or slide, so a part stays where it's left | 21 of 287 (sample), about 7% | **No** | `joint frictionloss` |
| Joint limit softness (PhysX layer) | How hard a part stops at its end | 3 of 287 (sample) | **No** | `joint solreflimit` / `solimplimit` |
| Initial joint position (`PhysicsJointStateAPI`) | Whether a door starts open or closed | 641 | **No**: everything starts at zero. NVIDIA's MuJoCo layer deletes this too | `qpos0` / `keyframe` |
| Break force and torque | A joint snaps under too much load | 18 finite | **No** | None built in. Would need a custom rule |
| Articulation root | Marks a multi-part mechanism | 115 | Not needed | None needed: MuJoCo bodies form a tree |

### Grasping, meaning and sensors

| Data | What it is in real life | Assets | Used today? | MuJoCo equivalent |
| --- | --- | --- | --- | --- |
| Grasp line (`Grasp/grasp_identifier`, a 2-point curve) | Where and how a gripper should close on the object: the line between the two fingertips ([Graspable Vectors](https://nvidia.github.io/simready-foundation/latest/capabilities/physics_bodies/physics_graspable/requirements.html)) | 1,925 (1,780 with one, 145 with 2–3) | **No** | `site` pairs (or a capsule site) on the part. The agent could be given them as grasp suggestions |
| Semantic labels (Wikidata class and Q-code) | What the object is ("scissors", Q40847), for vision and task matching | 2,667 | **No** | None in physics. Useful for the library, search and segmentation labels |
| Description (`omni:simready:documentation`) | One plain-language line, for example "hand-operated cutting instrument" | 2,615 | **No** | None. Useful for library tooltips and agent prompts |
| Non-visual material (base, coating, attributes) | How the surface looks to lidar, radar or thermal sensors: steel, clear glass, skin, emissive, transparent | 2,646 | **No** | None. Rendering and sensor data, not physics |
| Visual materials (PBR textures, roughness, metalness, opacity) | How it looks | 2,668 | **Yes** for colour and texture, roughness and metalness. **No** for transparency (glass) | `material` (`rgba` alpha for transparency) |
| `ReferencePrims` | NVIDIA's authoring helpers that record each joint's source parameters | 2,668 | Not needed: duplicates the joints | None |

### Packaging and quality records

| Data | What it is | Assets | Used today? |
| --- | --- | --- | --- |
| Licence | CC BY 4.0 | all | **Yes** (`playground/assets/CREDITS.md`) |
| Bill of materials and hashes | Every file, with checksums | all | **No**. Could verify downloads |
| Validation record (root and engine layers) | NVIDIA's checker results against profile `Robotics-Prop 3.1.0`. The most common failures are `RB.MB.001`, `AA.001`, `VM.MDL.001` and `GSP.001`. `GSP.001` means no grasp line: 1,190 records | 2,541 | **No**. Could flag assets NVIDIA itself marks as failing |

## Tripo's assets: richer MuJoCo data

Tripo's 19 assets (6 in our library) ship a hand-tuned MuJoCo layer (`usd/runnables/physics/mujoco.usda`):

| Data | Meaning | Assets (of 19) | Used today? | MuJoCo equivalent |
| --- | --- | --- | --- | --- |
| Joint damping (`mjc:damping`) | Doors and lids move smoothly, not freely | 16 | **Yes** | `joint damping` |
| Friction and limit softness (`mjc:solreffriction`, `solimpfriction`, `solreflimit`) | How joints stop and slide | 14 | **No** | Same names on `joint` |
| Contact softness (`mjc:solref`) | Contact stiffness of each part | 16 | **No** | `geom solref` |
| Spring tendons (`MjcTendon`, `stiffness`, `springlength`) | Door closers and seals: a fridge door pulls itself shut and seals in its last few degrees | 5 | **No** | `tendon fixed`/`spatial` with `stiffness`, `springlength` |
| Sites (`MjcSiteAPI`) | Grasp and reference points, for example the microcentrifuge's `rotor_grasp` | 16 | **No** | `site` |
| Benchmarks and validation (`.metadata/*_benchmark.json`, `*_validation.json`) | Tripo's own tests in Isaac Sim (joints move, pivots, semantic labels, renders) and validation per engine | 19 | **No** | Not applicable |

## What NVIDIA's own MuJoCo layer does

NVIDIA's MuJoCo variant is minimal:

- It **sets every collider to a single convex hull**.
- It **deletes** the joint drives (springs, dampers, motors) and the initial joint positions from the joints that have them.
- It adds no MuJoCo joint or contact parameters at all: no damping, armature or friction loss.

So the springs and dampers exist in NVIDIA's neutral data, but NVIDIA doesn't carry them into MuJoCo. Adopting them means mapping the neutral drives onto MuJoCo's own joint and actuator settings, which are official features with direct equivalents.

## Recommended order to adopt

Each item uses an official MuJoCo feature and NVIDIA's or Tripo's own values. None needs a custom rule except where noted.

1. **Per-part friction and restitution** (2,668 assets). The data is complete, the effect is visible everywhere (grippy rubber, slippy glass, bouncy plastic), and it's cheap.
2. **Centre of mass and inertia, plus density, fill ratio and wall thickness** (2,646–2,669). Correct weight and balance for hollow and uneven objects. This also fixes most of the odd masses we flagged, for example jars and kettles.
3. **Joint drives as MuJoCo springs and dampers** (131 springs, 282 dampers), plus **PhysX joint friction** (about 7%) and **Tripo's joint and limit softness**. Buttons spring back, lids close, hinges hold their angle. Adding `armature` for very light parts belongs here too: it's a standard MuJoCo stabiliser, though not in the data.
4. **Initial joint positions** (641). Doors and drawers start where NVIDIA put them.
5. **Grasp lines as sites** (1,925). Tell the agent where each object is meant to be held. This improves AI runs directly.
6. **Rolling and twisting friction** (Newton's values). Round items stop rolling.
7. **Motors** (29) and **Tripo's spring tendons** (5). Toasters time out, fridge doors self-close.
8. **Semantic labels and descriptions** for library search, tooltips and agent prompts. **Transparency** for glass.
9. Not adoptable as physics: break forces (MuJoCo has no breakable joints), non-visual sensor materials (rendering only), and the validation and packaging records (useful for quality checks, not simulation).

## Sources

- SimReady Foundation spec: <https://nvidia.github.io/simready-foundation/>
  - Capabilities index: <https://nvidia.github.io/simready-foundation/latest/capabilities/capabilities.html>
  - Multiple physics solvers (variant layout, engine-specific layers): <https://nvidia.github.io/simready-foundation/latest/guides/multiphysics_solvers.html>
  - Rigid bodies, colliders and mass requirements: <https://nvidia.github.io/simready-foundation/latest/capabilities/physics_bodies/physics_rigid_bodies/requirements.html>
  - Driven joints: <https://nvidia.github.io/simready-foundation/latest/capabilities/physics_bodies/physics_driven_joints/capability-physics_driven_joints.html>
  - Physics materials: <https://nvidia.github.io/simready-foundation/latest/capabilities/physics_bodies/physics_materials/capability-physics_materials.html>
  - Graspable vectors: <https://nvidia.github.io/simready-foundation/latest/capabilities/physics_bodies/physics_graspable/requirements.html>
  - Non-visual materials: <https://nvidia.github.io/simready-foundation/latest/capabilities/nonvisual_sensors/nonvisual_materials/requirements.html>
- USD Physics schema (friction, restitution, density, drives, joint state): <https://openusd.org/release/api/usd_physics_page_front.html>
- MuJoCo XML reference: <https://mujoco.readthedocs.io/en/stable/XMLreference.html>
  - Joints: [stiffness](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-joint-stiffness), [frictionloss](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-joint-frictionloss), [armature](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-joint-armature)
  - Contact: [geom friction](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-geom-friction), [condim](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-geom-condim)
- MuJoCo modeling guide (restitution, solver parameters): <https://mujoco.readthedocs.io/en/stable/modeling.html>
- Data: <https://huggingface.co/datasets/nvidia/simready-assets>, <https://huggingface.co/datasets/VAST-AI/Tripo-Simready-Assets>
