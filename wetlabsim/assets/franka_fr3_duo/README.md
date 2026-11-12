# Franka FR3 Duo with the FR3 Duo Vision & Manipulation Kit

`fr3_duo.xml` is converted from Franka Robotics' SimReady USD of the kit
(Hugging Face dataset `frankarobotics/simready-assets`, folder
`fr3_duo_vision_manipulation_kit`, revision f0e831cf1d7fdc815f1c41d1365f4480c65411d1) by
`playground/tools/convert_fr3_duo.py`:

    python -m playground.tools.convert_fr3_duo <package folder> wetlabsim/assets/franka_fr3_duo

Bodies, masses and inertias, joints and their limits, armature, friction loss and position
gains, collision hulls, colours and camera poses are the kit's own. Visual meshes are
simplified. The two Robotiq 2F-85 grippers are MuJoCo Menagerie's model (`robotiq_2f85/`,
unchanged, BSD-3-Clause, see its LICENSE), attached with MJCF `<attach>` where the kit
mounts its grippers.

License of the kit's data: CC-BY-4.0, author Franka Robotics GmbH
(<https://creativecommons.org/licenses/by/4.0/>). Changes: converted to MJCF/OBJ, meshes
simplified, merged per body and colour, the kit's own grippers replaced by Menagerie's.
