"""The playground's world: the robot cell's simulator (wetlabsim.sim.Sim) with a scene the
user builds, a pause button, and a free camera for the main view.

Physics, the robot controller, its sensors and cameras are the robot cell's own, so an
agent drives the Franka here exactly as it does in the wet lab evals.
"""
from __future__ import annotations

import io
import math
import threading
import time

import mujoco
import numpy as np
from PIL import Image

from wetlabsim.sim import RobotError, Sim

from . import catalog
from . import world as W

VIEW_W, VIEW_H = 1280, 800
FOVY = 45.0        # the free camera's vertical field of view (MuJoCo's default)


class PlaygroundSim(Sim):
    def __init__(self, placed: list[W.Placed] | None = None, robot: str = "franka", **kw):
        self.placed = placed or W.default_scene()
        self._uid = 0
        super().__init__(robot=robot, **kw)
        self.paused = True                      # start in build mode
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = [0.0, 0.0, 0.85]
        cam.distance, cam.azimuth, cam.elevation = 2.8, 145.0, -28.0
        self.view = cam
        self.overlay: list[dict] = []           # ghost and highlight shapes for the main view
        self.selected: str | None = None        # uid of the selected object, or "robot"
        self._frame = (0, b"")                  # (sequence, jpeg) of the latest main view
        self._frame_cv = threading.Condition()
        self._viewers = 0
        self._last_view_req = 0.0

    # ------------------------------------------------------------- scene
    def _make_model(self) -> mujoco.MjModel:
        return W.build(self.placed, self.robot)

    def _index(self):
        super()._index()
        m = self.m
        root = self.base_body
        self.robot_bodies = {b for b in range(m.nbody) if self._in_subtree(b, root)}
        self.body_uid = {}
        for p in self.placed:
            self.body_uid[m.body(f"obj_{p.uid}").id] = p.uid

    def _in_subtree(self, b, root):
        m = self.m
        while b > 0:
            if b == root:
                return True
            b = m.body_parentid[b]
        return False

    def _lay_out(self, task):
        """Nothing to do: every object starts where the user put it (the model's own pose)."""

    def new_uid(self, item: str) -> str:
        self._uid += 1
        return f"{item}_{self._uid}"

    def find(self, uid) -> W.Placed | None:
        return next((p for p in self.placed if p.uid == uid), None)

    def _sync_placed(self):
        """Remember where every free object is now, so a rebuild keeps them there."""
        m, d = self.m, self.d
        for p in self.placed:
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{p.uid}")
            if b >= 0 and m.body_jntnum[b]:
                p.pos = tuple(float(v) for v in d.xpos[b])
                p.quat = tuple(float(v) for v in d.xquat[b])

    def rebuild(self):
        """Recompile the scene after an edit. The robot keeps its pose; objects stay put."""
        with self.lock:
            self._sync_placed()
            old_m, old_d = self.m, self.d
            arm_q = old_d.qpos[self.arm_qadr].copy()
            arm_ctrl = old_d.ctrl[self.arm_act].copy()
            grip_q = old_d.qpos[self.grip_qadr]
            grip_ctrl = old_d.ctrl[self.grip_act]
            fingers = {old_m.joint(j).name: old_d.qpos[old_m.jnt_qposadr[j]]
                       for j in range(old_m.njnt) if old_m.joint(j).name.startswith("finger_joint")}
            m = W.build(self.placed, self.robot)
            d = mujoco.MjData(m)
            self.m, self.d = m, d
            self._index()
            d.qpos[self.arm_qadr] = arm_q
            d.ctrl[self.arm_act] = arm_ctrl
            d.qpos[self.grip_qadr] = grip_q
            for name, q in fingers.items():
                d.qpos[m.joint(name).qposadr[0]] = q
            d.ctrl[self.grip_act] = grip_ctrl
            d.time = old_d.time
            mujoco.mj_forward(m, d)
            self.motion = None
            self._wall0, self._sim0 = time.perf_counter(), d.time
            self._model_ver += 1

    def add(self, item: str, pos, yaw: float = 0.0) -> str:
        catalog.item(item)
        with self.lock:
            uid = self.new_uid(item)
            self.placed.append(W.Placed(uid, item, tuple(pos), yaw))
            self.rebuild()
        return uid

    def move(self, uid: str, pos, yaw: float | None = None):
        with self.lock:
            p = self.find(uid)
            if p is None:
                raise RobotError("no such object")
            self._sync_placed()
            p.pos = tuple(pos)
            if yaw is not None:
                p.yaw = yaw
            p.quat = None if yaw is not None or p.quat is None else W.yaw_quat(p.yaw)
            self.rebuild()

    def remove(self, uid: str):
        with self.lock:
            if uid == W.TABLE_UID:
                raise RobotError("the table stays")
            self.placed = [p for p in self.placed if p.uid != uid]
            if self.selected == uid:
                self.selected = None
            self.rebuild()

    def clear(self):
        with self.lock:
            self.placed = [p for p in self.placed if p.uid == W.TABLE_UID]
            self.selected = None
            self.rebuild()
            self.reset()

    def scene_info(self) -> dict:
        with self.lock:
            self._sync_placed()
            items = []
            for p in self.placed:
                it = catalog.item(p.item)
                items.append({**p.as_dict(), "label": it["label"], "fixed": it["fixed"],
                              "removable": p.uid != W.TABLE_UID})
            return {"objects": items, "paused": self.paused, "selected": self.selected,
                    "time": round(self.d.time, 3), "realtime_factor": round(self.rt_factor, 3),
                    "robots": [{"id": "robot", "label": self.P["name"], "gripper": self.P["gripper"]}]}

    # ---------------------------------------------------- pause / play
    def play(self):
        with self.lock:
            self._wall0, self._sim0 = time.perf_counter(), self.d.time
            self.paused = False

    def pause(self):
        with self.lock:
            self.paused = True

    # ------------------------------------------------------ the camera
    def _cam_frame(self):
        c = self.view
        az, el = math.radians(c.azimuth), math.radians(c.elevation)
        fwd = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        pos = np.array(c.lookat) - c.distance * fwd
        right = np.cross(fwd, [0, 0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        return pos, fwd, right, up

    def pixel_ray(self, u: float, v: float, aspect: float = VIEW_W / VIEW_H):
        """World ray through a point of the main view (u, v in 0..1 from the top left)."""
        pos, fwd, right, up = self._cam_frame()
        t = math.tan(math.radians(FOVY) / 2)
        d = fwd + (2 * u - 1) * t * aspect * right + (1 - 2 * v) * t * up
        return pos, d / np.linalg.norm(d)

    def orbit(self, d_az=0.0, d_el=0.0, zoom=1.0, pan=(0.0, 0.0)):
        c = self.view
        c.azimuth = (c.azimuth + d_az) % 360
        c.elevation = float(np.clip(c.elevation + d_el, -89, -3))
        c.distance = float(np.clip(c.distance * zoom, 0.4, 8.0))
        if pan != (0.0, 0.0):
            _, fwd, right, _ = self._cam_frame()
            flat = np.array([fwd[0], fwd[1], 0.0])
            flat /= max(np.linalg.norm(flat), 1e-9)
            c.lookat[:] = np.array(c.lookat) + c.distance * (pan[0] * right + pan[1] * flat)

    def focus(self, target):
        self.view.lookat[:] = target

    # ---------------------------------------------------- picking, placing
    def _ray(self, p0, d, exclude_body=-1):
        gid = np.zeros(1, np.int32)
        with self.lock:
            dist = mujoco.mj_ray(self.m, self.d, np.asarray(p0, float), np.asarray(d, float),
                                 np.array([1, 1, 1, 0, 0, 0], np.uint8), 1, exclude_body, gid)
            body = int(self.m.geom_bodyid[gid[0]]) if dist >= 0 else -1
        return (dist if dist >= 0 else None), body

    def _owner(self, body: int):
        """What a body is: ("robot", None), ("object", uid) or ("floor", None)."""
        if body in self.robot_bodies:
            return "robot", None
        while body > 0:
            if body in self.body_uid:
                return "object", self.body_uid[body]
            body = self.m.body_parentid[body]
        return "floor", None

    def pick(self, u, v) -> dict:
        p0, d = self.pixel_ray(u, v)
        dist, body = self._ray(p0, d)
        if dist is None:
            return {"kind": "none"}
        kind, uid = self._owner(body)
        hit = (p0 + dist * d).round(4).tolist()
        out = {"kind": kind, "uid": uid, "point": hit}
        if kind == "object":
            p = self.find(uid)
            out["item"] = p.item
            out["label"] = catalog.item(p.item)["label"]
            out["removable"] = uid != W.TABLE_UID
        return out

    def support(self, item: str, x: float, y: float, yaw: float = 0.0, top: float = 3.0,
                exclude_uid: str | None = None) -> dict:
        """Where an item dropped at (x, y) comes to rest: on the highest surface under its
        footprint (it stacks on whatever is there)."""
        meta = catalog.meta(item)
        sx, sy, _ = meta["size"]
        c, s = math.cos(yaw), math.sin(yaw)
        excl = -1
        if exclude_uid:
            with self.lock:
                excl = self.m.body(f"obj_{exclude_uid}").id
        zs, owners = [], set()
        for fx in (-0.45, 0.0, 0.45):
            for fy in (-0.45, 0.0, 0.45):
                lx, ly = fx * sx, fy * sy
                px, py = x + c * lx - s * ly, y + s * lx + c * ly
                dist, body = self._ray((px, py, top), (0, 0, -1.0), excl)
                if dist is None:
                    zs.append(0.0)
                    owners.add(("floor", None))
                    continue
                zs.append(top - dist)
                owners.add(self._owner(body))
        z = max(zs)
        robot = any(k == "robot" for k, _ in owners)
        on = sorted({catalog.item(self.find(u).item)["label"] for k, u in owners if k == "object" and self.find(u)})
        level = max(zs) - min(zs) < 0.03
        surface = on[0] if len(on) == 1 else ("the floor" if not on else " / ".join(on))
        return {"pos": [round(x, 4), round(y, 4), round(z + 0.0005, 4)], "surface": surface,
                "valid": not robot, "level": level, "reason": "too close to the robot" if robot else ""}

    def probe(self, item: str, u: float, v: float, yaw: float = 0.0, exclude_uid: str | None = None) -> dict:
        """Where an item being dragged over the view at (u, v) would land."""
        p0, d = self.pixel_ray(u, v)
        excl = -1
        if exclude_uid:
            with self.lock:
                excl = self.m.body(f"obj_{exclude_uid}").id
        dist, body = self._ray(p0, d, excl)
        if dist is None:
            if d[2] >= -1e-6:
                return {"valid": False, "reason": "off the floor"}
            dist = -p0[2] / d[2]
        hit = p0 + dist * d
        # Over a container (bowl, crate, tray...) big enough to hold it: drop it in the middle.
        kind, uid = self._owner(body) if dist is not None else ("floor", None)
        if kind == "object" and uid != W.TABLE_UID and uid != exclude_uid:
            it = catalog.item(self.find(uid).item)
            mine, theirs = catalog.meta(item)["size"], catalog.meta(it["id"])["size"]
            if it["hollow"] and not it["fixed"] and max(mine[:2]) < min(theirs[:2]):
                with self.lock:
                    c = self.d.xpos[self.m.body(f"obj_{uid}").id]
                hit = np.array([c[0], c[1], hit[2]])
        if abs(hit[0]) > 9.5 or abs(hit[1]) > 9.5:
            return {"valid": False, "reason": "off the floor"}
        out = self.support(item, float(hit[0]), float(hit[1]), yaw, exclude_uid=exclude_uid)
        self.set_ghost(item, out, yaw)
        return out

    def set_ghost(self, item, spot, yaw=0.0):
        meta = catalog.meta(item)
        sx, sy, sz = meta["size"]
        x, y, z = spot["pos"]
        ok = spot.get("valid", False)
        col = [0.25, 0.55, 1.0] if ok else [1.0, 0.3, 0.25]
        self.overlay = [
            # the drop spot, glowing on the surface it lands on
            {"type": "box", "size": [sx / 2 + 0.02, sy / 2 + 0.02, 0.0015], "pos": [x, y, z + 0.0015],
             "yaw": yaw, "rgba": [*col, 0.45]},
            # the item's outline where it will sit
            {"type": "box", "size": [sx / 2, sy / 2, sz / 2], "pos": [x, y, z + sz / 2], "yaw": yaw,
             "rgba": [*col, 0.18]},
        ]

    def clear_ghost(self):
        self.overlay = []

    def _selection_overlay(self):
        sel = self.selected
        if not sel:
            return []
        with self.lock:
            if sel == "robot":
                bp = self.d.xpos[self.base_body]
                return [{"type": "cylinder", "size": [0.16, 0.002, 0], "pos": [bp[0], bp[1], bp[2] + 0.002],
                         "yaw": 0.0, "rgba": [0.95, 0.55, 0.15, 0.5]}]
            p = self.find(sel)
            if p is None:
                return []
            b = self.m.body(f"obj_{sel}").id
            pos = self.d.xpos[b].copy()
            q = self.d.xquat[b]
        yaw = math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
        sx, sy, _ = catalog.meta(p.item)["size"]
        return [{"type": "box", "size": [sx / 2 + 0.015, sy / 2 + 0.015, 0.001], "pos": [pos[0], pos[1], pos[2] + 0.001],
                 "yaw": yaw, "rgba": [0.95, 0.55, 0.15, 0.55]}]

    # ---------------------------------------------------- main view
    def start(self):
        super().start()
        threading.Thread(target=self._view_loop, daemon=True, name="view").start()

    def want_frames(self):
        self._last_view_req = time.time()

    def latest_frame(self, after: int, timeout=1.0):
        self.want_frames()
        with self._frame_cv:
            self._frame_cv.wait_for(lambda: self._frame[0] > after, timeout)
            return self._frame

    def _view_loop(self):
        ver, r, rd = None, None, None
        types = {"box": mujoco.mjtGeom.mjGEOM_BOX, "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER}
        opt = mujoco.MjvOption()
        seq = 0
        while self._running:
            if time.time() - self._last_view_req > 3.0:   # nobody is watching
                time.sleep(0.05)
                continue
            t0 = time.perf_counter()
            with self.lock:
                if ver != self._model_ver:
                    ver, m = self._model_ver, self.m
                    rd = mujoco.MjData(m)
                    if r is not None:
                        r.close()
                    r = mujoco.Renderer(m, VIEW_H, VIEW_W)
                rd.qpos[:] = self.d.qpos
                rd.time = self.d.time
            mujoco.mj_kinematics(m, rd)
            mujoco.mj_camlight(m, rd)
            r.update_scene(rd, camera=self.view, scene_option=opt)
            sc = r.scene
            for g in self.overlay + self._selection_overlay():
                if sc.ngeom >= sc.maxgeom:
                    break
                mat = np.zeros(9)
                mujoco.mju_quat2Mat(mat, np.array(W.yaw_quat(g["yaw"])))
                mujoco.mjv_initGeom(sc.geoms[sc.ngeom], types[g["type"]], np.array(g["size"], float),
                                    np.array(g["pos"], float), mat, np.array(g["rgba"], np.float32))
                sc.ngeom += 1
            img = r.render()
            buf = io.BytesIO()
            Image.fromarray(img).save(buf, format="JPEG", quality=82)
            seq += 1
            with self._frame_cv:
                self._frame = (seq, buf.getvalue())
                self._frame_cv.notify_all()
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - t0)))
