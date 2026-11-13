"""The robot work every stand-in agent does (tests/fake_agents): written into the agent's
workspace as pick.py and run with the agent's own Python, through the real robot client.
First try reaches too far (an error, like a real first attempt); the second moves the hand down,
closes the fingers, lifts, carries and lets go."""
ROUTINE = r'''
import sys, time
from wetlabsim.robot import Robot, RobotError
r = Robot()
p = list(r.get_tcp_pose())
if "--first" in sys.argv:
    r.move_l([p[0] + 3.0, p[1], p[2], *p[3:]])      # far out of reach: raises
down = [p[0], p[1], p[2] - 0.08, *p[3:]]
r.move_l(down, speed=0.1)
r.gripper_close()
r.move_l(p, speed=0.1)
r.move_l([p[0], p[1] + 0.12, p[2], *p[3:]], speed=0.1)
r.gripper_open()
print("placed")
'''
