# AutoBio lab items

These 3D models come from **AutoBio** and are used here with credit to its authors:

> Zhiqian Lan, Yuxuan Jiang, Ruiqi Wang, Xuanbing Xie, Rongkui Zhang, Yicheng Zhu,
> Peihang Li, Tianshuo Yang, Tianxing Chen, Haoyu Gao, Xiaokang Yang, Xuelong Li,
> Hongyuan Zhang, Yao Mu, Ping Luo. *AutoBio: A Simulation and Benchmark for Robotic
> Automation in Digital Biology Laboratory.* arXiv:2505.14030, 2025.

- Source: https://github.com/autobio-bench/AutoBio, commit
  `08504213356cbfe9a82bcd33a43cd282945a45df` (28 May 2025), folder `autobio/assets/`.
- The AutoBio repository has no licence file. We use these files with credit to the
  authors. All rights stay with them.

## Files

| Here | AutoBio original |
| --- | --- |
| `centrifuge_tube_15ml_body.STL`, `centrifuge_tube_15ml_cap.STL` | `container/centrifuge_15ml_screw_vis/` |
| `centrifuge_tube_50ml_body.STL`, `centrifuge_tube_50ml_cap.STL` | `container/centrifuge_50ml_screw_vis/` |
| `centrifuge_1-5ml_screw_body.STL`, `centrifuge_1-5ml_screw_cap.STL` | `container/centrifuge_1-5ml_screw_vis/` |
| `rack_upper_plane_visual.obj`, `rack_lower_plane_visual.obj`, `rack_pillars_visual.obj` | `rack/centrifuge_10slot_vis/` |
| `rack_plate_60well.obj` | `rack/centrifuge_plate_60well_vis/visual.obj` |
| `cell_dish_100.obj` | `container/cell_dish_100_vis/visual.obj` |
| `pipette/*.obj` | `tool/pipette/*.obj` |
| `pipette_stand/beam_visual.obj`, `legs_visual.obj` | `rack/pipette_rack_tri_vis/` |
| `pipette_stand/*_collision_0.obj` | `rack/pipette_rack_tri_col/` |

The files are unchanged; only the rack meshes were renamed.

## What we changed in how they're used (`wetlabsim/scene.py`)

- **Tubes:** collision is the convex hull of the body mesh (AutoBio's own tube collision
  has a flat bottom, which lets a dropped conical tube stand on its tip). The 1.5 ml tube
  collides as a 10.5 mm capsule, because its hull (11.4 mm, it includes the lip under the
  thread) is wider than the rack's wells.
- **15 ml caps** screw on and off: each cap is its own body, held on by a weld that
  `wetlabsim/threads.py` moves along a 3 mm-pitch thread as the cap is twisted. AutoBio's
  screw-thread plugin isn't used (it ships only as a Linux binary). The 50 ml and 1.5 ml
  caps are fixed to their tubes.
- **Racks and petri dish:** AutoBio's box collision proxies, as in its `*.gen.xml` models.
  The tube rack's proxies are resized for 18 mm (15 ml) and 30 mm (50 ml) holes, from a
  catalogue rack (Bel-Art Poxygrid F18722-0000 and F18794); AutoBio's holes are 17 mm.
- **Pipette and stand:** rigid (the plunger and ejector don't move), with AutoBio's
  convex collision pieces. The pipette's mass is our estimate (100 g).
- **Masses:** mesh plastic volume x density. Polypropylene (0.90 g/cm3) for tube
  bodies, HDPE (0.95) for caps, polystyrene (1.05) for the dish.
  - 15 ml tube: 6.4 g
  - 50 ml tube: 12.7 g
  - 1.5 ml tube: 1.25 g
  - dish: 23 g
  - 60-well rack: estimated at 45 g, because its mesh is a solid block. The two
    centrifuge-tube racks are fixed to the bench.
