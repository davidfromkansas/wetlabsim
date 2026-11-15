# Rainbow Robotics RB-Y1 (model A, v1.2)

`rby1a_1.2.xml` and the meshes it uses are MuJoCo Menagerie's `rainbow_robotics_rby1`
model, unchanged (google-deepmind/mujoco_menagerie, commit 370c43965323c0944b433b202aac5058b5f907a9, Apache-2.0, see
LICENSE). Menagerie derived it from Rainbow Robotics' RB-Y1 URDF
(RainbowRobotics/rby1-sdk, models/rby1a).

The RB-Y1-A: a two-wheeled mobile base, a 6-joint torso, two 7-joint arms with the standard
two-finger gripper, and a 2-joint pan-tilt head. What the playground sets on top of the file
(cameras, wrist force/torque sensors, gravity compensation, the wheel motors' gains) is in
`wetlabsim/scene.py` (`_rby1`), with MuJoCo's own settings.
