"""Scripted baselines for the task library: proof that each task can be done in this cell.

They drive the arm through the same robot API the agents use, but they read object
positions from the simulator's true state instead of from the cameras, so they show the
task is physically possible, not that it is easy to perceive. Run with the cell running:

    python examples/baselines.py            # every task
    python examples/baselines.py T1 T7      # some
"""
from __future__ import annotations

import json
import math
import sys
import time

import numpy as np

from wetlabsim import scene as S
from wetlabsim import tasks as T
from wetlabsim.robot import Robot
from wetlabsim.run_agent import ROOT, _eval_call

URL = "http://127.0.0.1:8765"
TOKEN = (ROOT / "runs" / ".eval_token").read_text().strip()
SAFE_Z = 0.22
LOW_GRIP = 0.0105      # lowest safe TCP height: the fingertips reach 8.9 mm below the TCP
READY = [0, -0.5, 0, -2.3, 0, 1.8, 0.7854]
OPEN_15 = 150          # gripper opening for a 15 ml tube or cap (~33 mm)


def truth():
    return _eval_call(URL, TOKEN, "/eval/ground_truth")


def pos(name):
    return np.array(truth()["objects"][name]["pos"])


def rotvec(R):
    a = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))
    if a < 1e-9:
        return np.zeros(3)
    if abs(a - math.pi) < 1e-6:
        w = np.sqrt(np.maximum((np.diag(R) + 1) / 2, 0))
        i = int(np.argmax(w))
        w[(i + 1) % 3] = math.copysign(w[(i + 1) % 3], R[i, (i + 1) % 3])
        w[(i + 2) % 3] = math.copysign(w[(i + 2) % 3], R[i, (i + 2) % 3])
        return a * w / np.linalg.norm(w)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return a * v / (2 * math.sin(a))


def rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def down(x, y, z, yaw=0.0):
    """Tool pointing straight down, fingers closing along base y turned by yaw."""
    return [x, y, z, *rotvec(rz(yaw) @ rx(math.pi))]


class Arm:
    def __init__(self):
        self.r = Robot(URL)

    def go(self, x, y, z, yaw=0.0, speed=0.25):
        self.r.move_l(down(x, y, z, yaw), speed=speed)

    def hop(self, x, y, z, yaw=0.0):
        """Up to a safe height, across, and down to (x, y, z)."""
        p = self.r.get_tcp_pose()
        self.r.move_l([p[0], p[1], SAFE_Z, *p[3:]], speed=0.3)
        self.r.move_j_pose(down(x, y, SAFE_Z, yaw), speed=1.0)
        self.r.move_l(down(x, y, z, yaw), speed=0.08)

    def grip(self, force=255):
        return self.r.gripper_move(255, force=force)

    def release(self, width=OPEN_15):
        g = self.r.gripper_move(width)
        for _ in range(40):                       # wait until the fingers have really opened
            g = self.r.get_gripper_status()
            if abs(g["position"] - width) < 3:
                break
            time.sleep(0.05)
        return g

    def pick_tube15(self, name, yaw=0.0):
        p = pos(name)
        self.release()
        self.hop(p[0], p[1], p[2] + S.TUBE_HALF_LEN - 0.035, yaw)
        g = self.grip()
        assert g["object_detected"], f"missed {name}"
        self.r.move_l(down(p[0], p[1], SAFE_Z, yaw), speed=0.15)
        return p

    def place_tube15(self, x, y, floor, held_from_bottom):
        """Lower a held 15 ml tube until its tip is just above `floor`, then let go."""
        self.r.move_j_pose(down(x, y, SAFE_Z), speed=1.0)
        self.r.move_l(down(x, y, floor + held_from_bottom + 0.004), speed=0.05)
        self.release()
        self.r.move_l(down(x, y, SAFE_Z), speed=0.2)


def tube_in_slot(arm, name, rack, row, col):
    p = arm.pick_tube15(name)
    grip_z = p[2] + S.TUBE_HALF_LEN - 0.035          # where we held it
    held_from_bottom = grip_z - (p[2] - S.TUBE_HALF_LEN)
    s = S.slot_center(rack, row, col)
    arm.place_tube15(s[0], s[1], S.RACK_FLOOR, held_from_bottom)


# ----------------------------------------------------------------------- tasks
def b_t1(arm):
    tube_in_slot(arm, "tube_red", "rack_b", 0, 1)


def b_t3(arm):
    tube_in_slot(arm, "tube_green", "rack_b", 1, 2)


def b_t5(arm):
    # Left to right from the robot = high y to low y: red (col 5), green (col 4), blue (col 3).
    for name, col in (("tube_red", 5), ("tube_green", 4), ("tube_blue", 3)):
        tube_in_slot(arm, name, "rack_b", 0, col)


def _axis(name):
    w, x, y, z = truth()["objects"][name]["quat"]
    return np.array([2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)])


def stand_lying_tube(arm, name, half_len, target, floor, grip_off=0.03, open_to=120):
    """Pick a tube lying along y by its body (grip_off towards the cap from its middle),
    turn the hand to horizontal so the tube hangs cap up, and lower it into target."""
    p = pos(name)
    cap_dir = 1.0 if _axis(name)[1] > 0 else -1.0
    gy = p[1] + cap_dir * grip_off
    arm.release(open_to)
    arm.hop(p[0], gy, LOW_GRIP, yaw=math.pi / 2)
    assert arm.grip()["object_detected"], f"missed {name}"
    arm.r.move_l(down(p[0], gy, 0.25, math.pi / 2), speed=0.15)
    # Turn 90 degrees about base x: the tube's cap end goes up, the hand ends horizontal.
    R = rx(cap_dir * math.pi / 2) @ rz(math.pi / 2) @ rx(math.pi)
    held = half_len + grip_off                      # grip point above the tube's tip
    z = floor + held + 0.004
    arm.r.move_j_pose([target[0], target[1], z + 0.12, *rotvec(R)], speed=0.6)
    # Where the tube really hangs relative to the TCP (its axis isn't exactly on the TCP).
    tp, tb = np.array(arm.r.get_tcp_pose()[:3]), pos(name)
    off = tb - tp
    tx, ty = target[0] - off[0], target[1] - off[1]
    z = floor + half_len + 0.004 - off[2]
    arm.r.move_l([tx, ty, z + 0.12, *rotvec(R)], speed=0.05)
    arm.r.move_l([tx, ty, z, *rotvec(R)], speed=0.04)
    target = (tx, ty)
    arm.release(open_to)
    back = -R[:, 2] * 0.06                          # straight back out along the hand
    arm.r.move_l([target[0] + back[0], target[1] + back[1], z, *rotvec(R)], speed=0.05)
    arm.r.move_l([target[0] + back[0], target[1] + back[1], z + 0.15, *rotvec(R)], speed=0.1)
    arm.r.move_j(READY, speed=0.8)


def b_t7(arm):
    # Upright, the hand points the way the cap pointed, so the wrist trails behind it: pick
    # a rack on that side so the wrist swings over the open middle of the bench.
    cap_dir = 1.0 if _axis("tube_green")[1] > 0 else -1.0
    slot = S.slot_center("rack_b", 1, 2) if cap_dir > 0 else S.slot_center("rack_a", 1, 4)
    stand_lying_tube(arm, "tube_green", S.TUBE_HALF_LEN, slot, S.RACK_FLOOR)


def b_t12(arm):
    pass   # look-and-report: nothing to move


def b_t18(arm):
    p = pos("tube50")
    arm.release(40)
    arm.hop(p[0], p[1], p[2] + 0.0598 - 0.03)
    assert arm.grip()["object_detected"], "missed the 50 ml tube"
    arm.r.move_l(down(p[0], p[1], 0.25), speed=0.15)
    h = S.hole50_center("rack_b", 0, 2)
    held = (p[2] + 0.0598 - 0.03) - (p[2] - 0.0598)
    arm.r.move_j_pose(down(h[0], h[1], 0.25), speed=1.0)
    arm.r.move_l(down(h[0], h[1], S.RACK_FLOOR + held + 0.004), speed=0.05)
    arm.release(40)
    arm.r.move_l(down(h[0], h[1], 0.25), speed=0.2)


def move_microtube(arm, well):
    """Lift the 1.5 ml tube straight up by its body and lower it into a well."""
    p = pos("microtube")
    top = p[2] + 0.0224
    arm.release(200)
    arm.hop(p[0], p[1], top - 0.008)
    assert arm.grip(force=150)["object_detected"], "missed the 1.5 ml tube"
    arm.r.move_l(down(p[0], p[1], 0.15), speed=0.1)
    w = S.well_center(well)
    held = top - 0.008 - (p[2] - 0.0224)          # grip point above the tube's tip
    arm.r.move_j_pose(down(w[0], w[1], 0.15), speed=0.8)
    arm.r.move_l(down(w[0], w[1], held + 0.003), speed=0.03)
    arm.release(200)
    arm.r.move_l(down(w[0], w[1], 0.15), speed=0.1)


def b_t19(arm):
    move_microtube(arm, "B3")


def quat_mat(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def tcp_R():
    return quat_mat_from_rotvec(Robot(URL).get_tcp_pose()[3:])


def quat_mat_from_rotvec(rv):
    rv = np.asarray(rv, float)
    a = np.linalg.norm(rv)
    if a < 1e-12:
        return np.eye(3)
    k = rv / a
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K


def stack_dishes(arm):
    """Pinch dish 2 by its rim (it is wider than the hand opens), set it on dish 1."""
    a, b = pos("petri_dish_1"), pos("petri_dish_2")
    r = -0.04266                                    # pinch the wall on the robot's side
    arm.release(190)
    arm.hop(b[0] + r, b[1], 0.012, yaw=math.pi / 2)
    g = arm.grip(force=120)
    assert g["position"] < 250, "missed the dish rim"      # the 2 mm wall is too thin to read as "object"
    arm.r.move_l(down(b[0] + r, b[1], 0.10, math.pi / 2), speed=0.1)
    arm.r.move_l(down(a[0] + r, a[1], 0.10, math.pi / 2), speed=0.15)
    arm.r.move_l(down(a[0] + r, a[1], 0.012 + 0.021, math.pi / 2), speed=0.03)
    arm.release(190)
    arm.r.move_l(down(a[0] + r, a[1], 0.12, math.pi / 2), speed=0.1)


def hang_pipette(arm):
    """Grip the lying pipette across its body, then move it so it hangs by its finger hook
    on the front of the stand's beam (hook towards +y, tip down), and let go."""
    gt = truth()["objects"]["pipette"]
    pp, Rp = np.array(gt["pos"]), quat_mat(gt["quat"])
    g_local = np.array([0.0016, 0.0, 0.061])         # grip on the shaft, low enough that the hand passes under the beam
    gp = pp + Rp @ g_local
    ax = Rp[:, 2]
    yaw = math.atan2(ax[1], ax[0])                   # fingers (base y at yaw 0) across the pipette
    arm.release(140)
    arm.hop(gp[0], gp[1], max(LOW_GRIP, gp[2]), yaw=yaw)
    assert arm.grip(force=200)["object_detected"], "missed the pipette"
    arm.r.move_l(down(gp[0], gp[1], 0.25, yaw), speed=0.1)
    # Pipette pose relative to the hand, now that it is held.
    gt = truth()["objects"]["pipette"]
    pp, Rp = np.array(gt["pos"]), quat_mat(gt["quat"])
    th = np.array(arm.r.get_tcp_pose()[:3])
    Rh = quat_mat_from_rotvec(arm.r.get_tcp_pose()[3:])
    p_rel, R_rel = Rh.T @ (pp - th), Rh.T @ Rp
    # Target: upright, hook (local -x) pointing +y, hook resting 1 cm above the beam top.
    sx, sy = S.PIPETTE_STAND
    R_goal = rz(-math.pi / 2)
    p_goal = np.array([sx - 0.06, sy - 0.022 - 0.0095, 0.2565 - 0.1665 + 0.012])
    Rh_goal = R_goal @ R_rel.T
    th_goal = p_goal - Rh_goal @ p_rel
    # Come in level from the robot's side: the hand stays under the beam while the hook,
    # 10 cm above the grip, passes over it.
    away = th_goal + np.array([0, -0.12, 0.0])
    above = away + np.array([0, 0, 0.10])
    arm.r.move_j_pose([*above, *rotvec(Rh_goal)], speed=0.4)     # turns it upright on the way
    arm.r.move_l([*away, *rotvec(Rh_goal)], speed=0.05)
    arm.r.move_l([*th_goal, *rotvec(Rh_goal)], speed=0.02)
    arm.r.move_l([*(th_goal - np.array([0, 0, 0.012])), *rotvec(Rh_goal)], speed=0.01)
    arm.release(140)
    back = -Rh_goal[:, 2] * 0.05
    arm.r.move_l([*(th_goal - np.array([0, 0, 0.012]) + back), *rotvec(Rh_goal)], speed=0.03)
    arm.r.move_j(READY, speed=0.6)


def b_t23(arm):
    """Tidy: blue tube into a rack, 50 ml tube into a 50 ml hole, dish 2 onto dish 1 (pinched
    by its rim), pipette onto its stand."""
    steps = {}
    for label, fn in [
        ("dishes", lambda: stack_dishes(arm)),
        ("tube50", lambda: stand_lying_tube(arm, "tube50", 0.0598,
                                            S.hole50_center("rack_b", 1, 2) if _axis("tube50")[1] > 0
                                            else S.hole50_center("rack_a", 1, 3), S.RACK_FLOOR,
                                            grip_off=0.03, open_to=90)),
        ("blue", lambda: stand_lying_tube(arm, "tube_blue", S.TUBE_HALF_LEN,
                                          S.slot_center("rack_a", 2, 5) if _axis("tube_blue")[1] < 0
                                          else S.slot_center("rack_b", 1, 2), S.RACK_FLOOR)),
        ("pipette", lambda: hang_pipette(arm)),
    ]:
        try:
            fn()
            steps[label] = "ok"
        except Exception as e:   # noqa: BLE001
            steps[label] = f"{type(e).__name__}: {e}"
            if arm.r.is_protective_stopped():
                arm.r.unlock_protective_stop()
            arm.release(140)
            try:
                arm.r.move_j(READY, speed=0.5)
            except Exception:   # noqa: BLE001
                pass
    print(json.dumps({"t23_steps": steps}), flush=True)


BASELINES = {"T1": b_t1, "T3": b_t3, "T5": b_t5, "T7": b_t7, "T12": b_t12, "T18": b_t18,
             "T19": b_t19, "T23": b_t23}


def run(task_id):
    _eval_call(URL, TOKEN, "/eval/reset", {"task": task_id})
    time.sleep(1.0)
    gt0 = truth()
    arm = Arm()
    t0 = time.time()
    err = None
    try:
        BASELINES[task_id](arm)
    except Exception as e:   # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    time.sleep(1.5)
    gt1 = truth()
    ctx = {"judge": {"score": 1.0}} if task_id == "T12" else {}
    res = T.score(task_id, gt0, gt1, ctx)
    stops = Robot(URL).get_state()["mode"]
    return {"task": task_id, "seconds": round(time.time() - t0, 1), "error": err, "mode": stops, **res}


if __name__ == "__main__":
    ids = sys.argv[1:] or list(BASELINES)
    for tid in ids:
        print(json.dumps(run(tid)), flush=True)
