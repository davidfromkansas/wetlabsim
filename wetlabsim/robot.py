"""Robot API for agents: the robot arm, its parallel gripper and two cameras.

This is the only way to act on the lab. It talks to the robot cell over the
network, like a real robot's controller. Time keeps running while your code
thinks: the arm holds its last commanded position until you send a new command.

Coordinates: metres, in the robot base frame. x points forward over the bench,
y to the robot's left, z up; the bench top is at z = 0. Tool poses are
[x, y, z, rx, ry, rz] where (rx, ry, rz) is a rotation vector (axis * angle,
radians).
[x, y, z, 3.14159, 0, 0] means the gripper points straight down.

Example:
    from wetlabsim.robot import Robot
    r = Robot()
    print(r.get_tcp_pose())
    r.gripper_move(150)                                 # open partway
    r.move_l([0.45, 0.0, 0.20, 3.14159, 0, 0], speed=0.2)
    img = r.get_camera_image("overhead")               # numpy array, H x W x 3
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request

import numpy as np

DEFAULT_URL = os.environ.get("WETLAB_ROBOT_URL", "http://127.0.0.1:8765")


class RobotError(Exception):
    """The controller rejected a command or a motion did not finish."""


class Frame:
    """One camera frame. Pixel (u, v): u to the right, v down."""

    def __init__(self, rgb, depth, meta):
        self.rgb = rgb                      # H x W x 3 uint8
        self.depth = depth                  # H x W float32 metres along the view axis, or None
        self.time = meta["time"]
        self.intrinsics = meta["intrinsics"]   # fx, fy, cx, cy, width, height
        self.camera_position = np.array(meta["pose"]["position"])        # base frame
        self.camera_rotation = np.array(meta["pose"]["rotation"])        # base<-camera, OpenCV axes

    # --- assisted helpers (left out of the client agents get at the standard docs level)
    def pixel_to_point(self, u: float, v: float, depth: float | None = None) -> np.ndarray:
        """3D point in the robot base frame seen at pixel (u, v)."""
        if depth is None:
            if self.depth is None:
                raise ValueError("this frame has no depth; use get_camera_frame(name, depth=True)")
            depth = float(self.depth[int(round(v)), int(round(u))])
        k = self.intrinsics
        p_cam = np.array([(u - k["cx"]) / k["fx"] * depth, (v - k["cy"]) / k["fy"] * depth, depth])
        return self.camera_position + self.camera_rotation @ p_cam

    def point_to_pixel(self, p_base) -> tuple[float, float]:
        """Project a base-frame point into this image."""
        k = self.intrinsics
        pc = self.camera_rotation.T @ (np.asarray(p_base) - self.camera_position)
        return (k["fx"] * pc[0] / pc[2] + k["cx"], k["fy"] * pc[1] / pc[2] + k["cy"])
    # --- end assisted helpers

    def save(self, path: str):
        from PIL import Image
        Image.fromarray(self.rgb).save(path)
        return path


class Robot:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 120.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------ transport
    def _req(self, method, path, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                if raw:
                    return payload, resp.headers
                return json.loads(payload)
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            raise RobotError(f"{path}: {msg}") from None
        except urllib.error.URLError as e:
            raise RobotError(f"cannot reach the robot at {self.url} ({e.reason}). Is the robot cell running?") from None

    def _cmd(self, path, body):
        out = self._req("POST", path, body)
        if not out.get("ok", False):
            raise RobotError(out.get("error") or out.get("result") or str(out))
        return out

    # -------------------------------------------------------------- reading
    def get_state(self) -> dict:
        """Everything the controller reports, in one call."""
        return self._req("GET", "/state")

    def get_time(self) -> float:
        """Controller clock in seconds."""
        return self.get_state()["time"]

    def get_joint_positions(self) -> list[float]:
        """Joint angles (rad), base to wrist (see the robot manual for names and limits)."""
        return self.get_state()["joint_positions"]

    def get_tcp_pose(self) -> list[float]:
        """Tool centre point (between the fingertips) as [x, y, z, rx, ry, rz]."""
        return self.get_state()["tcp_pose"]

    def get_tcp_force(self) -> list[float]:
        """Wrist force/torque [Fx, Fy, Fz, Tx, Ty, Tz] in N and Nm, tool frame,
        gripper weight already removed. Holding a 20 g tube adds about 0.2 N."""
        return self.get_state()["tcp_force"]

    def zero_ft_sensor(self):
        """Tare the wrist force sensor at the current reading."""
        self._cmd("/zero_ft_sensor", {})

    def is_moving(self) -> bool:
        return self.get_state()["moving"]

    def is_protective_stopped(self) -> bool:
        return self.get_state()["mode"] == "protective_stop"

    # ------------------------------------------------------------- arm moves
    def move_l(self, pose, speed: float = 0.25, wait: bool = True) -> dict:
        """Move the tool in a straight line to `pose` [x, y, z, rx, ry, rz].
        speed: tool speed in m/s (max 1.0). Blocks until done unless wait=False.
        Raises RobotError if the pose is unreachable or the arm hits something
        hard enough to trigger a protective stop."""
        return self._cmd("/move_l", {"pose": list(map(float, pose)), "speed": speed, "wait": wait})

    def move_j(self, joints, speed: float = 1.0, wait: bool = True) -> dict:
        """Move in joint space to the given joint angles (rad). speed in rad/s."""
        return self._cmd("/move_j", {"joints": list(map(float, joints)), "speed": speed, "wait": wait})

    def move_j_pose(self, pose, speed: float = 1.0, wait: bool = True) -> dict:
        """Move in joint space to a tool pose. Faster than move_l for big moves,
        but the path is curved: use it only when the way is clear."""
        return self._cmd("/move_j_pose", {"pose": list(map(float, pose)), "speed": speed, "wait": wait})

    def stop(self):
        """Stop the arm now."""
        self._cmd("/stop", {})

    def unlock_protective_stop(self):
        """Clear a protective stop (after a collision) so the arm accepts commands again."""
        self._cmd("/unlock_protective_stop", {})

    # --------------------------------------------------------------- gripper
    def gripper_move(self, position: int, speed: int = 255, force: int = 150, wait: bool = True) -> dict:
        """position: 0 = fully open, 255 = fully closed (see the manual for the opening width).
        Returns gripper status; status['object_detected'] is True if the fingers
        stopped on something before reaching the requested position."""
        return self._cmd("/gripper", {"position": position, "speed": speed, "force": force, "wait": wait})["gripper"]

    def gripper_open(self, wait=True):
        return self.gripper_move(0, wait=wait)

    def gripper_close(self, force: int = 150, wait=True):
        return self.gripper_move(255, force=force, wait=wait)

    def get_gripper_status(self) -> dict:
        """position (0-255, measured), requested, moving, object_detected."""
        return self.get_state()["gripper"]

    # --------------------------------------------------------------- cameras
    def cameras(self) -> list[str]:
        return [c for c in self._req("GET", "/info")["cameras"] if c != "side"]

    def get_camera_frame(self, name: str = "overhead", depth: bool = False) -> Frame:
        """Grab a frame from 'overhead' (fixed, above the bench) or 'wrist'
        (on the gripper). depth=True also returns a depth image (metres)."""
        if name == "side":
            raise RobotError("the 'side' camera is for human viewers only")
        if depth:
            raw, hdr = self._req("GET", f"/camera/{name}.rgbd.npz", raw=True)
            z = np.load(io.BytesIO(raw))
            return Frame(z["rgb"], z["depth"], json.loads(hdr["X-Frame-Meta"]))
        png, hdr = self._req("GET", f"/camera/{name}.png", raw=True)
        from PIL import Image
        rgb = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
        return Frame(rgb, None, json.loads(hdr["X-Frame-Meta"]))

    def get_camera_image(self, name: str = "overhead") -> np.ndarray:
        return self.get_camera_frame(name).rgb

    def save_camera_image(self, name: str, path: str) -> str:
        """Save a camera frame as a PNG you can look at."""
        return self.get_camera_frame(name).save(path)
