# Where this folder comes from

`g1_with_hands.xml`, `assets/`, `LICENSE`, `README.md` and `CHANGELOG.md`: MuJoCo Menagerie
`unitree_g1` (google-deepmind/mujoco_menagerie, commit 370c439), unchanged. The playground
loads `g1_with_hands.xml` and adds, through MuJoCo's own model editing (`wetlabsim/scene.py`,
`_g1`): LeRobot's joint gains, the head and wrist cameras, the lidar and IMU sites, the
Dex3-1 tactile areas, and a torque input on each arm motor (the controller's gravity
feed-forward). `locomotion/`: the balance and walking policies (see its README).
