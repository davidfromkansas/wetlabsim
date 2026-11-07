"""A hand-written baseline: find the red-capped tube with the overhead camera and
move it into an empty slot of the other rack. It uses only the robot API and
cameras, exactly like an agent would.

    python examples/scripted_pick_place.py
"""
import numpy as np

from wetlabsim.robot import Robot

DOWN = [np.pi, 0, 0]


def point_cloud(frame):
    """Base-frame XYZ for every pixel of a depth frame."""
    k = frame.intrinsics
    h, w = frame.depth.shape
    u, v = np.meshgrid(np.arange(w), np.arange(h))
    z = frame.depth
    pc = np.stack([(u - k["cx"]) / k["fx"] * z, (v - k["cy"]) / k["fy"] * z, z], axis=-1)
    return frame.camera_position + pc @ frame.camera_rotation.T


def find_cap(frame, rgb_target):
    """Pixel centre of the cap closest in colour to rgb_target."""
    dist = np.abs(frame.rgb.astype(int) - np.array(rgb_target)).sum(axis=2)
    v, u = np.nonzero(dist < 60)   # tight enough to skip the orange 50 ml cap
    return (float(u.mean()), float(v.mean())) if len(u) > 20 else None


def rack_slots(pts, y_side):
    """15 ml hole centres of the rack on one side of the robot, from its top plate
    (6 cm high, 205 x 96 mm) and the catalogue grid (3 x 6 holes, 36 mm apart)."""
    top = pts[(np.abs(pts[..., 2] - 0.058) < 0.004) & (np.sign(pts[..., 1]) == y_side)]
    cx, cy = (top[:, 0].min() + top[:, 0].max()) / 2, (top[:, 1].min() + top[:, 1].max()) / 2
    return [(cx + (row - 1) * 0.036, cy + (col - 2.5) * 0.036) for row in range(3) for col in range(6)]


r = Robot()
if r.is_protective_stopped():
    r.unlock_protective_stop()
r.gripper_move(150)
r.move_j_pose([0.40, 0.0, 0.30, *DOWN], speed=1.0)

f = r.get_camera_frame("overhead", depth=True)
pts = point_cloud(f)
px = find_cap(f, (215, 40, 40))
assert px, "no red cap visible"
cap = f.pixel_to_point(*px)
print("red cap top at", cap.round(3))

# Pick: approach from above, grip the body below the cap.
grasp_z = cap[2] - 0.035
r.move_l([cap[0], cap[1], 0.20, *DOWN], speed=0.3)
r.move_l([cap[0], cap[1], grasp_z, *DOWN], speed=0.08)
g = r.gripper_move(255, force=255)
assert g["object_detected"], "missed the tube"
r.move_l([cap[0], cap[1], 0.22, *DOWN], speed=0.15)
print("holding tube, wrist Fz =", r.get_tcp_force()[2])

# Place: first empty slot of the rack on the other side.
slots = rack_slots(pts, -np.sign(cap[1]))
heights = [pts[(np.hypot(pts[..., 0] - x, pts[..., 1] - y) < 0.01)][:, 2].max() for x, y in slots]
x, y = next(s for s, h in zip(slots, heights) if h < 0.08)
r.move_l([x, y, 0.22, *DOWN], speed=0.25)
r.move_l([x, y, grasp_z + 0.004, *DOWN], speed=0.06)
r.gripper_move(150)
r.move_l([x, y, 0.22, *DOWN], speed=0.2)
r.save_camera_image("overhead", "after.png")
print("placed at", round(x, 3), round(y, 3), "- see after.png")
