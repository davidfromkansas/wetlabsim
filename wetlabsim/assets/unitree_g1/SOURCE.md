# Where this folder comes from

`g1_with_hands.xml`, `assets/`, `LICENSE`, `README.md` and `CHANGELOG.md`: MuJoCo Menagerie
`unitree_g1` (google-deepmind/mujoco_menagerie, commit 370c439), unchanged. The playground
loads `g1_with_hands.xml` and adds, through MuJoCo's own model editing (`wetlabsim/scene.py`,
`_g1`): the joint gains (SONIC's on the legs and waist, LeRobot's on the arms), the head and
wrist cameras, the lidar and IMU sites, the Dex3-1 tactile areas, and a torque input on each
arm motor (the controller's gravity feed-forward). `sonic/`: NVIDIA's GEAR-SONIC whole-body
controller (see its README; the model files are downloaded, not in git).
