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

from wetlabsim import scene as WS
from wetlabsim import tasks as WT
from wetlabsim.sim import Arm, RobotError, Sim, TwoArm

from . import catalog
from . import libero as LB
from . import tron
from . import world as W

VIEW_W, VIEW_H = 1280, 800      # default size of the main view
MAX_W, MAX_H = 1920, 1200        # the scene's offscreen buffer (offwidth/offheight)
SOFT_MAX = 3       # soft objects a lab may hold: each is many bodies and contacts (see world._add_soft)
# How far from a robot's base centre nothing may be dropped: its base (a Franka's is 0.2 m across,
# a UR5e's 0.15 m) stands there. Objects nearer than that would sit inside it.
BASE_RADIUS = 0.11
FOVY = 45.0        # the free camera's vertical field of view (MuJoCo's default)


def _ray_flex(m, d, f: int, p0, dn):
    """Where a ray (unit direction) first meets a flex: its triangles (2D), or within a few mm
    of its segments (1D). None if it misses."""
    a, n = int(m.flex_vertadr[f]), int(m.flex_vertnum[f])
    dim, ea, en = int(m.flex_dim[f]), int(m.flex_elemdataadr[f]), int(m.flex_elemnum[f])
    V = d.flexvert_xpos[a:a + n]
    E = m.flex_elem[ea:ea + en * (dim + 1)].reshape(en, dim + 1)
    if dim == 3:   # a solid: the faces of its tetrahedra
        E = np.vstack([E[:, [0, 1, 2]], E[:, [0, 1, 3]], E[:, [0, 2, 3]], E[:, [1, 2, 3]]])
        dim = 2
    if dim == 2:   # Moller-Trumbore, all triangles at once
        A, B, C = V[E[:, 0]], V[E[:, 1]], V[E[:, 2]]
        e1, e2 = B - A, C - A
        h = np.cross(dn, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
        sv = p0 - A
        u = np.einsum("ij,ij->i", sv, h) * inv
        q = np.cross(sv, e1)
        v = (q @ dn) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
        return float(t[hit].min()) if hit.any() else None
    A, B = V[E[:, 0]], V[E[:, -1]]
    ts = np.linspace(0, 1, 9)[:, None, None]
    P = A[None] + ts * (B - A)[None] - p0          # points along each segment
    t = P @ dn
    r = np.linalg.norm(P - t[..., None] * dn, axis=2)
    near = (t > 0) & (r < m.flex_radius[f] + 0.005)
    return float(t[near].min()) if near.any() else None


class PlaygroundSim(Sim):
    def __init__(self, placed: list[W.Placed] | None = None, robot: str = "franka",
                 stations: list[W.Station] | None = None, settings: dict | None = None, **kw):
        self.settings = settings or {}           # the session's scene settings (playground/settings.py)
        self.placed = placed if placed is not None else W.default_scene()
        self.stations = stations if stations is not None else W.default_stations()
        self._uid = 0
        self.scene_mode = "free"                      # or "libero" or "wetlab"
        self.wetlab_task: str | None = None     # Wet Lab: the bench task (wetlabsim.tasks) laid out
        self.libero_task: LB.Task | None = None
        self.setup = 0                          # which of the task's 50 starting setups
        self.checker: LB.Checker | None = None
        self.active_station = self.stations[0].uid if self.stations else None   # the station the page is looking at
        super().__init__(robot=robot, **kw)
        self.paused = False                     # the world plays unless someone pauses it
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = [0.0, 0.0, 0.85]
        cam.distance, cam.azimuth, cam.elevation = 2.8, 145.0, -28.0
        self.view = cam
        self._glide: dict | None = None         # where the camera is gliding to
        self.view_size = (VIEW_W, VIEW_H)
        self.overlay: list[dict] = []           # ghost and highlight shapes for the main view
        self.selected: str | None = None        # uid of the selected object
        self._frame = (0, b"")                  # (sequence, jpeg) of the latest main view
        self._frame_cv = threading.Condition()
        self._viewers = 0
        self._last_view_req = 0.0

    # ------------------------------------------------------------- scene
    def _make_model(self) -> mujoco.MjModel:
        if self.scene_mode == "libero":
            return LB.build(self.libero_task, self.robot)
        if self.scene_mode == "wetlab":
            m = WS.build_model(self.robot)          # the robot cell's own bench
            # Room for the main view's largest size (offscreen buffer only; physics unchanged).
            m.vis.global_.offwidth = max(m.vis.global_.offwidth, MAX_W)
            m.vis.global_.offheight = max(m.vis.global_.offheight, MAX_H)
            return m
        return W.build(self.placed, self.stations, self.settings)

    def _make_arms(self) -> dict[str, Arm]:
        if self.scene_mode == "free":
            return {st.uid: (TwoArm if WS.ROBOTS[st.robot].get("sides") else Arm)(self, st.robot, st.prefix, st.uid)
                    for st in self.stations}
        return {"robot": Arm(self, self.robot)}

    def station(self, uid: str | None = None) -> W.Station | None:
        uid = uid or self.active_station
        return next((s for s in self.stations if s.uid == uid), None)

    def arm_of(self, uid: str | None) -> Arm:
        """A station's robot (free play), or the scene's one robot (LIBERO, Wet Lab)."""
        if self.scene_mode != "free":
            return self.arm
        a = self.arms.get(uid or self.active_station)
        if a is None:
            raise RobotError(f"no station {uid!r}")
        return a

    def _index(self):
        super()._index()
        m = self.m
        self.robot_bodies = set().union(*(a.bodies for a in self.arms.values()))
        self.body_station = {}
        for uid, a in self.arms.items():
            for b in a.bodies:
                self.body_station[b] = uid
        self.body_uid = {}
        self.checker = None
        if self.scene_mode == "wetlab":
            return
        if self.scene_mode == "libero":
            self.checker = LB.Checker(m, self.libero_task)
            # A stove's burner glows only while the stove is on (LIBERO's visual cue).
            self._burners = {}
            for n in self.checker.lit_burners(self.d):
                sid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, n + "_burner")
                if sid >= 0:
                    self._burners[n] = sid
                    m.site_rgba[sid, 3] = 0.0
            return
        for st in self.stations:
            self.body_station[m.body(f"obj_{W.table_uid(st)}").id] = st.uid
        self.flex_uid = {}
        for p in self.placed:
            self.body_uid[m.body(f"obj_{p.uid}").id] = p.uid
            for b in W.part_bodies(m, p.uid):         # a jointed item's other parts
                self.body_uid[b] = p.uid
            f = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_FLEX, f"obj_{p.uid}")
            if f >= 0:
                self.flex_uid[f] = p.uid

    def _swap_model(self):
        """Build the scene for the current mode from scratch and start it over."""
        with self.lock:
            self.m = self._make_model()
            self.d = mujoco.MjData(self.m)
            self._cap_rgba0 = {}                # a fresh model has its own colours
            self._index()
            self.selected = None
            self._model_ver += 1
            self.reset()
            self.paused = True

    def apply_settings(self, settings: dict):
        """New scene settings: the lab is compiled with them (first, so a combination MuJoCo
        refuses changes nothing) and starts over from where everything started."""
        if self.scene_mode != "free":
            raise RobotError("scene settings are for free play")
        m = W.build(self.placed, self.stations, settings)      # raises if MuJoCo refuses them
        with self.lock:
            was = self.paused
            self.settings = settings
            self.m = m
            self.d = mujoco.MjData(m)
            self._cap_rgba0 = {}
            self._index()
            self.selected = None
            self._model_ver += 1
            self.reset()
            self.paused = was

    # ------------------------------------------- one station, back to a moment
    def station_snapshot(self, uid: str) -> dict:
        """This station's robot and every loose object on its table, as they are now (for
        repeat runs: each run starts from here; the rest of the lab carries on)."""
        with self.lock:
            m, d = self.m, self.d
            st, arm = self.station(uid), self.arm_of(uid)
            roots = {int(m.body_rootid[b]) for b in arm.bodies}
            for p in self.placed:
                b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{p.uid}")
                if b >= 0 and st.holds(float(d.xpos[b][0]), float(d.xpos[b][1]), 0.05):
                    pre = f"obj_{p.uid}"
                    roots |= {int(m.body_rootid[k]) for k in range(m.nbody)
                              if (m.body(k).name == pre or m.body(k).name.startswith(pre + "__"))}
            qpos, qvel = [], []
            for j in range(m.njnt):
                if int(m.body_rootid[m.jnt_bodyid[j]]) not in roots:
                    continue
                t = m.jnt_type[j]
                nq = 7 if t == mujoco.mjtJoint.mjJNT_FREE else 4 if t == mujoco.mjtJoint.mjJNT_BALL else 1
                nv = 6 if t == mujoco.mjtJoint.mjJNT_FREE else 3 if t == mujoco.mjtJoint.mjJNT_BALL else 1
                qpos += list(range(m.jnt_qposadr[j], m.jnt_qposadr[j] + nq))
                qvel += list(range(m.jnt_dofadr[j], m.jnt_dofadr[j] + nv))
            # Soft objects: their flex vertices' bodies (in the same trees) are covered above.
            return {"ver": self._model_ver, "uid": uid, "qpos_i": qpos, "qpos": d.qpos[qpos].copy(),
                    "qvel_i": qvel, "qvel": d.qvel[qvel].copy(), "arm": arm.snapshot()}

    def restore_station(self, snap: dict) -> bool:
        """Put a station back as station_snapshot saw it. False if the lab has been rebuilt
        since (its numbering may have changed)."""
        with self.lock:
            if snap["ver"] != self._model_ver or self.arms.get(snap["uid"]) is None:
                return False
            m, d = self.m, self.d
            d.qpos[snap["qpos_i"]] = snap["qpos"]
            d.qvel[snap["qvel_i"]] = 0.0
            arm = self.arms[snap["uid"]]
            arm.restore(snap["arm"])
            arm.reset_state()
            arm.motion = None
            mujoco.mj_forward(m, d)
            return True

    def set_libero(self, task_id: str, setup: int = 0):
        t = LB.task(task_id)
        if not 0 <= setup < len(t.states):
            raise RobotError(f"setup must be 1..{len(t.states)}")
        with self.lock:
            switching = self.scene_mode != "libero" or self.libero_task is None or self.libero_task.id != t.id
            self.scene_mode, self.libero_task, self.setup = "libero", t, setup
            if switching:
                self._swap_model()
            else:
                self.reset()
                self.paused = True

    def set_free(self):
        with self.lock:
            if self.scene_mode != "free":
                self.scene_mode, self.libero_task, self.wetlab_task = "free", None, None
                self._swap_model()

    def set_wetlab(self, task_id: str):
        if task_id not in WT.TASKS:
            raise RobotError(f"unknown wet lab task {task_id!r}")
        with self.lock:
            switching = self.scene_mode != "wetlab"
            self.scene_mode, self.libero_task, self.wetlab_task = "wetlab", None, task_id
            if switching:
                self._swap_model()
            else:
                self.reset()
                self.paused = True

    def goal_met(self) -> bool:
        if self.scene_mode != "libero" or self.checker is None:
            return False
        with self.lock:
            ok = self.checker.check(self.d)
            lit = self.checker.lit_burners(self.d)
            for n, sid in self._burners.items():
                self.m.site_rgba[sid, 3] = 1.0 if lit.get(n) else 0.0
        return ok

    def _lay_out(self, task):
        """Free play: nothing to do, every object starts where the user put it (the model's own
        pose). LIBERO: the task's official starting setup."""
        if self.scene_mode == "wetlab":
            # The bench laid out for its task, as in the robot cell's evals. An eval reset names
            # the task itself; a plain reset keeps the chosen one.
            super()._lay_out(task or self.wetlab_task)
            return
        if self.scene_mode == "libero" and self.libero_task is not None:
            arm = LB.apply_setup(self.m, self.d, self.libero_task, self.setup, self.arm.arm_qadr)
            self.d.ctrl[self.arm.arm_act] = arm

    def new_uid(self, item: str) -> str:
        self._uid += 1
        return f"{item}_{self._uid}"

    def find(self, uid) -> W.Placed | None:
        return next((p for p in self.placed if p.uid == uid), None)

    def _sync_placed(self):
        """Remember where every free object is now, so a rebuild keeps them there. A soft
        object is remembered by where its shape lies now (a rebuild lays it out flat again)."""
        m, d = self.m, self.d
        for p in self.placed:
            f = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_FLEX, f"obj_{p.uid}")
            if f >= 0:
                a, n = int(m.flex_vertadr[f]), int(m.flex_vertnum[f])
                V = d.flexvert_xpos[a:a + n]
                # its body sits _soft_lift below its shape's lowest vertex (the vertex's own radius
                # is already in where it rests)
                p.pos = (float(V[:, 0].mean()), float(V[:, 1].mean()), float(V[:, 2].min()) - self._soft_lift(p))
                p.quat = None
                continue
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{p.uid}")
            if b >= 0 and m.body_jntnum[b]:
                p.pos = tuple(float(v) for v in d.xpos[b])
                p.quat = tuple(float(v) for v in d.xquat[b])
            if b >= 0:
                W.save_parts(m, d, p, b)

    def _soft_lift(self, p: W.Placed) -> float:
        """How far above a soft object's place its simulated shape starts (a sheet lies through
        the middle of the item), so remembering it by its lowest point doesn't lift it."""
        meta = catalog.meta(p.item)
        V, _, _ = W.read_obj(catalog.ASSETS / p.item / meta["soft"]["sim"])
        return float(V[:, 2].min())

    def rebuild(self, sync: bool = True):
        """Recompile the lab after an edit. Every robot keeps its pose and controller state;
        objects stay put (sync=False: where self.placed now says, for an edit that moved them)."""
        if self.scene_mode != "free":
            raise RobotError("this scene can't be edited")
        with self.lock:
            if sync:
                self._sync_placed()
            old_d = self.d
            snaps = {uid: a.snapshot() for uid, a in self.arms.items()}
            m = W.build(self.placed, self.stations, self.settings)
            d = mujoco.MjData(m)
            self.m, self.d = m, d
            self._index()
            for p in self.placed:
                W.restore_joints(m, d, p)
            for uid, a in self.arms.items():
                if uid in snaps:
                    a.restore(snaps[uid])
                else:                       # a new station: arm ready, gripper open
                    a.reset_pose()
                    a.reset_state()
                a.motion = None
            d.time = old_d.time
            mujoco.mj_forward(m, d)
            self._wall0, self._sim0 = time.perf_counter(), d.time
            self._model_ver += 1

    def add(self, item: str, pos, yaw: float = 0.0) -> str:
        if catalog.item(item)["soft"] and W.soft_count(self.placed) >= SOFT_MAX:
            raise RobotError(f"a lab holds at most {SOFT_MAX} soft objects (each takes a lot of the "
                             "physics' time); remove one first")
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
            if yaw is not None:          # turned about the vertical; any tilt it has stays
                if p.quat is not None:
                    p.quat = W.rot_quat(W.axis_rot("z", math.degrees(yaw - p.yaw)) @ W._rot(p.quat))
                p.yaw = yaw
            self.rebuild(sync=False)     # synced above; its new place stands

    def _obj_mid(self, p: W.Placed, R) -> np.ndarray:
        """The middle of an object's box, in the world (where its rotate rings sit)."""
        b = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{p.uid}")
        o = self.d.xpos[b] if b >= 0 and not catalog.item(p.item)["soft"] else np.asarray(p.pos, float)
        return o + R @ np.array([0.0, 0.0, catalog.meta(p.item)["size"][2] / 2])

    def can_tilt(self, uid: str) -> str:
        """Why an object can only turn about the vertical ("" if it can rotate every way)."""
        it = catalog.item(self.find(uid).item)
        if it["fixed"]:
            return "furniture stays level"
        if it["soft"]:
            return "soft objects lie flat"
        return ""

    def orient(self, uid: str, euler=None, axis: str | None = None, degrees: float = 0.0):
        """Rotate an object: to the angles euler (degrees about the world's X, Y, Z), or by
        degrees about one world axis. It turns about its middle, then comes to rest on whatever
        is under it (so it can't end up inside the table)."""
        with self.lock:
            p = self.find(uid)
            if p is None:
                raise RobotError("no such object")
            self._sync_placed()
            R0 = self.obj_rot(uid)
            R = W.euler_rot(euler) if euler is not None else W.axis_rot(axis, float(degrees)) @ R0
            why = self.can_tilt(uid)
            if why:
                if abs(R[2, 2] - 1) > 1e-6:
                    raise RobotError(f"only Z: {why}")
                yaw = math.atan2(R[1, 0], R[0, 0])
                if catalog.item(p.item)["fixed"]:
                    p.yaw, p.quat = yaw, None
                else:                    # a soft object turns about its middle, flat as it lies
                    p.yaw = yaw
                self.rebuild(sync=False)
                return
            meta = catalog.meta(p.item)
            mid = np.asarray(p.pos, float) + R0 @ np.array([0.0, 0.0, meta["size"][2] / 2])
        spot = self.support(p.item, float(mid[0]), float(mid[1]), exclude_uid=uid, rot=R)
        if not spot["valid"]:
            raise RobotError(spot["reason"])
        with self.lock:
            p.pos, p.quat = tuple(spot["pos"]), W.rot_quat(R)
            p.yaw = math.atan2(R[1, 0], R[0, 0])
            self.rebuild(sync=False)

    def remove(self, uid: str):
        with self.lock:
            if self.find(uid) is None:
                raise RobotError("no such object")
            self.placed = [p for p in self.placed if p.uid != uid]
            if self.selected == uid:
                self.selected = None
            self.rebuild()

    def clear(self):
        """Take every object away (the stations stay)."""
        with self.lock:
            self.placed = []
            self.selected = None
            self.rebuild()
            self.reset()

    # ---------------------------------------------------------- stations
    def _new_station_uid(self) -> str:
        n = 1
        while any(s.uid == f"st{n}" for s in self.stations):
            n += 1
        return f"st{n}"

    def _on_table(self, st: W.Station) -> list[W.Placed]:
        """Objects resting on a station's table (they move with it)."""
        top = st.top
        return [p for p in self.placed if not catalog.item(p.item)["fixed"]
                and st.holds(p.pos[0], p.pos[1]) and p.pos[2] > top - 0.05]

    def add_station(self, robot: str, pos, yaw: float = 0.0, kind: str = "table") -> str:
        if robot not in WS.ROBOTS:
            raise RobotError(f"unknown robot {robot!r}")
        if kind not in W.KINDS:
            raise RobotError(f"unknown kind of station {kind!r}")
        with self.lock:
            self._sync_placed()
            uid = self._new_station_uid()
            n = int(uid[2:])
            st = W.Station(uid, robot, (float(pos[0]), float(pos[1])), float(yaw), f"Robot {n}", kind)
            self.stations.append(st)
            top = st.top
            for item, lx, ly, iyaw in st.spec["layout"]:     # what the station starts with
                x, y, _ = st.to_world(lx, ly)
                if st.near_base(x, y):        # where another robot's base stands (an ALOHA's two)
                    continue
                self.placed.append(W.Placed(self.new_uid(item), item, (x, y, top), st.yaw + iyaw))
            self.rebuild()
            self.active_station = uid
        return uid

    def move_station(self, uid: str, pos, yaw: float | None = None):
        with self.lock:
            st = self.station(uid)
            if st is None:
                raise RobotError("no such station")
            self._sync_placed()
            riders = self._on_table(st)
            yaw = st.yaw if yaw is None else float(yaw)
            dyaw = yaw - st.yaw
            locs = [(p, st.to_local(p.pos[0], p.pos[1])) for p in riders]
            st.pos, st.yaw = (float(pos[0]), float(pos[1])), yaw
            for p, (lx, ly) in locs:    # what was on the table rides along
                x, y, _ = st.to_world(lx, ly)
                p.pos = (x, y, p.pos[2])
                p.yaw = p.yaw + dyaw
                if p.quat is not None:
                    q = np.zeros(4)
                    mujoco.mju_mulQuat(q, np.array(W.yaw_quat(dyaw)), np.array(p.quat))
                    p.quat = tuple(q)
            self.rebuild(sync=False)     # synced above; the riders' new places stand

    def remove_station(self, uid: str, keep_table: bool = True):
        """Remove a robot. A station is only a starting template, so by default its table
        (and whatever is on it) stays in the lab as an ordinary object."""
        with self.lock:
            if self.station(uid) is None:
                raise RobotError("no such station")
            self._sync_placed()
            st = self.station(uid)
            if keep_table:
                self.placed.append(W.Placed(self.new_uid(st.table_item), st.table_item,
                                            (st.pos[0], st.pos[1], 0.0), st.table_yaw))
            else:
                riders = {p.uid for p in self._on_table(st)}
                self.placed = [p for p in self.placed if p.uid not in riders]
            self.stations = [s for s in self.stations if s.uid != uid]
            self.arms.pop(uid, None)
            if self.active_station == uid:
                self.active_station = self.stations[0].uid if self.stations else None
            self.rebuild()

    def duplicate_station(self, uid: str) -> str:
        """Copy a station (robot, table and what is on the table) into the nearest free spot
        beside it. The copy becomes the active station."""
        with self.lock:
            st = self.station(uid)
            if st is None:
                raise RobotError("no such station")
            self._sync_placed()
            sx, sy = st.footprint()
            c, s = float(np.cos(st.yaw)), float(np.sin(st.yaw))
            spot = None
            for k in (1, 2, 3, 4):
                # beside it first (along the table's long side), then in front / behind
                for lx, ly in ((k * (sx + 0.4), 0), (-k * (sx + 0.4), 0),
                               (0, -k * (sy + 0.5)), (0, k * (sy + 0.5))):
                    dx, dy = c * lx - s * ly, s * lx + c * ly
                    out = self.station_spot(st.pos[0] + dx, st.pos[1] + dy, st.yaw, kind=st.kind)
                    if out["valid"]:
                        spot = (dx, dy)
                        break
                if spot:
                    break
            if spot is None:
                raise RobotError("no free space next to this station")
            dx, dy = spot
            riders = self._on_table(st)
            soft = sum(1 for p in riders if catalog.item(p.item)["soft"])
            if soft and W.soft_count(self.placed) + soft > SOFT_MAX:
                raise RobotError(f"the copy would bring the lab over {SOFT_MAX} soft objects; remove one first")
            new = self._new_station_uid()
            base = (st.name or f"Robot {uid[2:]}").strip()
            self.stations.append(W.Station(new, st.robot, (st.pos[0] + dx, st.pos[1] + dy), st.yaw,
                                           f"{base} copy"[:40], st.kind))
            for p in riders:
                self.placed.append(W.Placed(self.new_uid(p.item), p.item,
                                            (p.pos[0] + dx, p.pos[1] + dy, p.pos[2]), p.yaw, p.quat))
            self.rebuild()
            self.active_station = new
        return new

    def swap_robot(self, uid: str, robot: str):
        """Put a different robot arm on a station's table. The table and objects stay put."""
        if robot not in WS.ROBOTS:
            raise RobotError(f"unknown robot {robot!r}")
        with self.lock:
            st = self.station(uid)
            if st is None:
                raise RobotError("no such station")
            if st.robot == robot:
                return
            self._sync_placed()
            new = W.Station(st.uid, robot, st.pos, st.yaw, st.name, st.kind)
            if any(new.holds(p.pos[0], p.pos[1]) and new.near_base(p.pos[0], p.pos[1]) for p in self.placed):
                raise RobotError(f"there are things where the {WS.ROBOTS[robot]['name']} would stand: "
                                 "move them away from where its base goes first")
            st.robot = robot
            self.arms.pop(uid, None)
            self.rebuild()

    def rename_station(self, uid: str, name: str):
        st = self.station(uid)
        if st is None:
            raise RobotError("no such station")
        st.name = name.strip()[:40] or st.name

    def station_spot(self, x: float, y: float, yaw: float = 0.0, exclude: str | None = None,
                     kind: str | None = None) -> dict:
        """Whether a station's table fits with its centre at (x, y): on the floor, clear of
        the other stations and of furniture. The kind is the moved station's own (else a table)."""
        if kind is None:
            kind = self.station(exclude).kind if exclude and self.station(exclude) else "table"
        probe = W.Station("probe", "franka", (x, y), yaw, kind=kind)
        sx, sy = probe.footprint()
        pts = [probe.to_world(fx * sx / 2, fy * sy / 2) for fx in (-1, -0.5, 0, 0.5, 1) for fy in (-1, 0, 1)]
        for st in self.stations:
            if st.uid == exclude:
                continue
            if any(st.holds(px, py, 0.15) for px, py, _ in pts) or probe.holds(st.pos[0], st.pos[1], 0.15):
                return {"pos": [round(x, 4), round(y, 4)], "yaw": yaw, "valid": False,
                        "reason": f"too close to {st.name or st.uid}"}
        for p in self.placed:
            if catalog.item(p.item)["fixed"]:
                fx, fy, _ = catalog.meta(p.item)["size"]
                if probe.holds(p.pos[0], p.pos[1], max(fx, fy) / 2):
                    return {"pos": [round(x, 4), round(y, 4)], "yaw": yaw, "valid": False,
                            "reason": "furniture is in the way"}
        if max(abs(x), abs(y)) > 8.5:
            return {"pos": [round(x, 4), round(y, 4)], "yaw": yaw, "valid": False, "reason": "off the floor"}
        return {"pos": [round(x, 4), round(y, 4)], "yaw": yaw, "valid": True, "reason": ""}

    def probe_station(self, u: float, v: float, yaw: float = 0.0, exclude: str | None = None,
                      kind: str | None = None) -> dict:
        """Where a station dragged over the view at (u, v) would stand (on the floor)."""
        p0, d = self.pixel_ray(u, v)
        if d[2] >= -1e-6:
            self.overlay = []
            return {"valid": False, "reason": "off the floor"}
        if kind is None:
            kind = self.station(exclude).kind if exclude and self.station(exclude) else "table"
        hit = p0 + (-p0[2] / d[2]) * d
        out = self.station_spot(float(hit[0]), float(hit[1]), yaw, exclude, kind)
        ghost = W.Station("probe", "franka", tuple(out["pos"]), yaw, kind=kind)
        sx, sy = ghost.footprint()
        top = ghost.top
        col = [0.25, 0.55, 1.0] if out["valid"] else [1.0, 0.3, 0.25]
        rx, ry, _ = ghost.to_world(*ghost.robot_xy)
        self.overlay = [
            {"type": "box", "size": [sx / 2 + 0.03, sy / 2 + 0.03, 0.002], "pos": [hit[0], hit[1], 0.002],
             "yaw": yaw, "rgba": [*col, 0.45]},
            {"type": "box", "size": [sx / 2, sy / 2, top / 2], "pos": [hit[0], hit[1], top / 2], "yaw": yaw,
             "rgba": [*col, 0.16]},
            {"type": "cylinder", "size": [0.09, 0.35, 0], "pos": [rx, ry, top + 0.35], "yaw": 0.0,
             "rgba": [*col, 0.25]},
        ]
        return out

    def frame_station(self, uid: str | None = None, glide: bool = True):
        """Point the main view at a station (its table, from the front corner)."""
        st = self.station(uid)
        if st is None:
            return
        top = st.top
        cx, cy, _ = st.to_world(0.0, 0.0)
        target = {"lookat": [cx, cy, top - 0.15], "distance": 2.8,
                  "azimuth": (145.0 + np.degrees(st.yaw)) % 360, "elevation": -28.0}
        self._set_view(target, glide)

    def frame_lab(self, glide: bool = True):
        """Pull back to show every station."""
        xs = [st.pos[0] for st in self.stations] or [0.0]
        ys = [st.pos[1] for st in self.stations] or [0.0]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        span = max(max(xs) - min(xs), max(ys) - min(ys), 2.0)
        target = {"lookat": [cx, cy, 0.5], "distance": 2.2 + 1.3 * span, "azimuth": 145.0, "elevation": -35.0}
        self._set_view(target, glide)

    def _set_view(self, target: dict, glide: bool):
        if not glide:
            c = self.view
            c.lookat[:] = target["lookat"]
            c.distance, c.azimuth, c.elevation = target["distance"], target["azimuth"], target["elevation"]
            self._glide = None
            return
        self._glide = {**target, "t0": time.time()}

    def _glide_step(self):
        """Ease the main view towards where it is gliding (half a second or so). Called by
        both the video and the pose stream: at most one step per frame time."""
        g = self._glide
        if g is None:
            return
        now = time.time()
        if now - getattr(self, "_glide_t", 0.0) < 0.03:
            return
        self._glide_t = now
        c = self.view
        k = 0.22
        c.lookat[:] = np.array(c.lookat) + k * (np.array(g["lookat"]) - np.array(c.lookat))
        c.distance += k * (g["distance"] - c.distance)
        daz = (g["azimuth"] - c.azimuth + 540) % 360 - 180
        c.azimuth = (c.azimuth + k * daz) % 360
        c.elevation += k * (g["elevation"] - c.elevation)
        if (np.linalg.norm(np.array(g["lookat"]) - np.array(c.lookat)) < 0.002 and abs(daz) < 0.2
                and abs(g["distance"] - c.distance) < 0.005) or time.time() - g["t0"] > 2.0:
            self._set_view(g, False)

    def scene_info(self) -> dict:
        if self.scene_mode == "wetlab":
            t = WT.TASKS[self.wetlab_task]
            return {"mode": "wetlab", "objects": [], "paused": self.paused, "selected": self.selected,
                    "time": round(self.d.time, 3), "realtime_factor": round(self.rt_factor, 3),
                    "task": t.id, "title": t.title, "language": t.prompt, "active": "robot",
                    "robots": [{"id": "robot", "robot": self.robot, "name": "Robot", "label": self.P["name"],
                                "gripper": self.P["gripper"]}]}
        if self.scene_mode == "libero":
            t = self.libero_task
            return {"mode": "libero", "objects": [], "paused": self.paused, "selected": self.selected,
                    "time": round(self.d.time, 3), "realtime_factor": round(self.rt_factor, 3),
                    "task": t.id, "suite": t.suite, "language": t.language, "setup": self.setup, "setups": len(t.states),
                    "goal_met": self.goal_met(), "active": "robot",
                    "robots": [{"id": "robot", "robot": self.robot, "name": "Robot", "label": self.P["name"],
                                "gripper": self.P["gripper"]}]}
        with self.lock:
            self._sync_placed()
            items = []
            for p in self.placed:
                it = catalog.item(p.item)
                R = self.obj_rot(p.uid)
                items.append({**p.as_dict(), "label": it["label"], "fixed": it["fixed"], "removable": True,
                              "euler": W.rot_euler(R), "tilt": self.can_tilt(p.uid) == "",
                              "tilt_why": self.can_tilt(p.uid),
                              "mid": [round(float(v), 4) for v in self._obj_mid(p, R)],
                              "bodies": sorted(b for b, u in self.body_uid.items() if u == p.uid)})
            return {"mode": "free", "objects": items, "paused": self.paused, "selected": self.selected,
                    "time": round(self.d.time, 3), "realtime_factor": round(self.rt_factor, 3),
                    "active": self.active_station,
                    "robots": [{**st.as_dict(),
                                **({"base": [round(float(v), 3) for v in self._base_mid(self.arms[st.uid])]}
                                   if st.uid in self.arms else {})} for st in self.stations]}

    @staticmethod
    def _base_mid(arm):
        """Where a robot's tag hangs: its base, or the middle of a two-arm robot's two bases."""
        sides = getattr(arm, "sides", None)
        if sides:
            return sum(a.base_tf()[0] for a in sides.values()) / len(sides)
        return arm.base_tf()[0]

    # ---------------------------------------------------- pause / play
    def play(self):
        with self.lock:
            self._wall0, self._sim0 = time.perf_counter(), self.d.time
            self.paused = False

    def pause(self):
        with self.lock:
            self.paused = True

    # ------------------------------------------------------ the camera
    # A request from a page that draws the view itself names its own camera (thread-local, for the
    # length of that request): picking and placing then follow what that page shows.
    _req = threading.local()

    def _cam_frame(self):
        c = getattr(self._req, "cam", None) or self.view
        az, el = math.radians(c.azimuth), math.radians(c.elevation)
        fwd = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        pos = np.array(c.lookat) - c.distance * fwd
        right = np.cross(fwd, [0, 0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        return pos, fwd, right, up

    def set_view_aspect(self, aspect: float):
        """Match the main view's shape to the page's box, so it fills it (about a megapixel)."""
        aspect = float(np.clip(aspect, 0.5, 4.0))
        h = math.sqrt(VIEW_W * VIEW_H / aspect)
        w = h * aspect
        k = min(1.0, MAX_W / w, MAX_H / h)
        self.view_size = (int(w * k) // 2 * 2, int(h * k) // 2 * 2)

    def pixel_ray(self, u: float, v: float, aspect: float | None = None):
        """World ray through a point of the main view (u, v in 0..1 from the top left)."""
        if aspect is None:
            aspect = getattr(self._req, "aspect", None) or self.view_size[0] / self.view_size[1]
        pos, fwd, right, up = self._cam_frame()
        t = math.tan(math.radians(FOVY) / 2)
        d = fwd + (2 * u - 1) * t * aspect * right + (1 - 2 * v) * t * up
        return pos, d / np.linalg.norm(d)

    def use_camera(self, cam: dict | None):
        """For this request: pick and place through the camera the page drew (or the shared one)."""
        if not cam:
            self._req.cam = self._req.aspect = None
            return
        c = mujoco.MjvCamera()
        c.type = mujoco.mjtCamera.mjCAMERA_FREE
        c.lookat[:] = [float(v) for v in cam["lookat"]]
        c.distance, c.azimuth, c.elevation = float(cam["distance"]), float(cam["azimuth"]), float(cam["elevation"])
        self._req.cam, self._req.aspect = c, float(cam.get("aspect") or 0) or None

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

    def move_camera(self, right=0.0, forward=0.0, up=0.0):
        """Slide the main view's camera over the floor (right/forward, keeping its angle) or
        raise/lower it, in metres. Only the audience view moves; the robot's cameras don't."""
        c = self.view
        _, fwd, r, _ = self._cam_frame()
        flat = np.array([fwd[0], fwd[1], 0.0])
        flat /= max(np.linalg.norm(flat), 1e-9)
        p = np.array(c.lookat) + right * r + forward * flat
        p[2] = float(np.clip(p[2] + up, -0.5, 3.0))
        c.lookat[:] = p

    def focus(self, target):
        self.view.lookat[:] = target

    # ---------------------------------------------------- picking, placing
    def _ray(self, p0, d, exclude_body=-1):
        gid = np.zeros(1, np.int32)
        with self.lock:
            dist = mujoco.mj_ray(self.m, self.d, np.asarray(p0, float), np.asarray(d, float),
                                 np.array([1, 1, 1, 0, 0, 0], np.uint8), 1, exclude_body, gid)
            body = int(self.m.geom_bodyid[gid[0]]) if dist >= 0 else -1
            # the excluded object's other parts (a lid, a door) don't count either
            own = getattr(self, "body_uid", {}).get(exclude_body)
            skipped = 0.0
            while own is not None and dist >= 0 and self.body_uid.get(body) == own:
                skipped += dist + 1e-4
                dist = mujoco.mj_ray(self.m, self.d, np.asarray(p0, float) + skipped * np.asarray(d, float),
                                     np.asarray(d, float), np.array([1, 1, 1, 0, 0, 0], np.uint8), 1, body, gid)
                body = int(self.m.geom_bodyid[gid[0]]) if dist >= 0 else -1
            if dist >= 0:
                dist += skipped
            # mj_ray sees geoms only; a soft object is hit where the ray passes close to its shape.
            dn = np.asarray(d, float) / np.linalg.norm(d)
            for f, uid in getattr(self, "flex_uid", {}).items():
                fb = self.m.body(f"obj_{uid}").id
                if fb == exclude_body:
                    continue
                tf = _ray_flex(self.m, self.d, f, np.asarray(p0, float), dn)
                if tf is not None:
                    tf /= float(np.linalg.norm(d))
                    if dist < 0 or tf < dist:
                        dist, body = tf, fb
        return (dist if dist >= 0 else None), body

    def _owner(self, body: int):
        """What a body is: ("robot", station), ("table", station), ("object", uid) or
        ("floor", None). In LIBERO and Wet Lab the station is "robot"."""
        if body in self.robot_bodies:
            return "robot", self.body_station.get(body, "robot")
        if body in self.body_station:
            return "table", self.body_station[body]
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
        if kind in ("robot", "table"):
            out["station"] = uid
        if kind == "object":
            p = self.find(uid)
            out["item"] = p.item
            out["label"] = catalog.item(p.item)["label"]
            out["removable"] = True
        return out

    def _ray_past_robots(self, p0, d, exclude_body=-1):
        """A ray that goes on through robots: (distance to the first thing that isn't a robot,
        body, distance to the first robot it passed or None)."""
        p0, d = np.asarray(p0, float), np.asarray(d, float)
        robot_at, skipped, excl = None, 0.0, exclude_body
        for _ in range(40):
            dist, body = self._ray(p0 + skipped * d, d, excl)
            if dist is None or body not in self.robot_bodies:
                return (None if dist is None else dist + skipped), body, robot_at
            if robot_at is None:
                robot_at = skipped + dist
            skipped += dist + 1e-4
            excl = body
        return None, -1, robot_at

    def obj_rot(self, uid: str) -> np.ndarray:
        """An object's orientation now (from the physics), as a rotation matrix."""
        p = self.find(uid)
        b = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{uid}")
        if b >= 0 and self.m.body_jntnum[b] and not catalog.item(p.item)["soft"]:
            return W._rot(self.d.xquat[b])
        return W._rot(p.quat or W.yaw_quat(p.yaw))

    def support(self, item: str, x: float, y: float, yaw: float = 0.0, top: float = 3.0,
                exclude_uid: str | None = None, rot=None) -> dict:
        """Where an item dropped with its middle over (x, y) comes to rest: on the highest surface
        under it (it stacks on whatever is there), turned by yaw, or by the rotation rot (a 3x3
        matrix) when given. A robot arm above that surface is fine as long as the item fits
        under it; a robot's base, or an arm lower than the item's top, is in the way."""
        meta = catalog.meta(item)
        R = W.euler_rot((0, 0, math.degrees(yaw))) if rot is None else np.asarray(rot, float)
        pts = W.box_points(meta["size"]) @ R.T
        mid = R @ np.array([0.0, 0.0, meta["size"][2] / 2])
        ox, oy = x - mid[0], y - mid[1]          # the item's own origin (its bottom centre)
        bottom, height = pts[:, 2].min(), pts[:, 2].max() - pts[:, 2].min()
        excl = -1
        if exclude_uid:
            with self.lock:
                excl = self.m.body(f"obj_{exclude_uid}").id
        zs, owners, robot_low = [], set(), None
        for px, py in {(round(float(a), 5), round(float(b), 5)) for a, b in pts[:, :2]}:
            dist, body, robot_at = self._ray_past_robots((ox + px, oy + py, top), (0, 0, -1.0), excl)
            if robot_at is not None:
                robot_low = top - robot_at if robot_low is None else min(robot_low, top - robot_at)
            if dist is None:
                zs.append(0.0)
                owners.add(("floor", None))
                continue
            zs.append(top - dist)
            owners.add(self._owner(body))
        z = max(zs)
        reason = ""
        feet = [(ox + px, oy + py) for px, py in pts[:, :2]]
        if any(st.near_base(fx, fy, BASE_RADIUS) for st in self.stations for fx, fy in feet):
            reason = "a robot's base is there"
        elif robot_low is not None and robot_low < z + height + 0.005:
            reason = ("a robot is in the way" if robot_low < z + 0.03 else
                      f"the robot arm is in the way: it hangs {100 * (robot_low - z):.0f} cm above here "
                      f"and this is {100 * height:.0f} cm tall")
        on = sorted({catalog.item(self.find(u).item)["label"] for k, u in owners if k == "object" and self.find(u)}
                    | {f"the table of {self.station(u).name}" for k, u in owners if k == "table" and self.station(u)})
        level = max(zs) - min(zs) < 0.03
        surface = on[0] if len(on) == 1 else ("the floor" if not on else " / ".join(on))
        return {"pos": [round(ox, 4), round(oy, 4), round(z - bottom + 0.0005, 4)], "surface": surface,
                "valid": not reason, "level": level, "reason": reason,
                "box": self._ghost_box(meta["size"], R, (x, y, z + height / 2 + 0.0005), pts)}

    @staticmethod
    def _ghost_box(size, R, mid, pts):
        """The space an item takes, as a box: its own box turned about the vertical if it stands
        upright, else the upright box around it."""
        upright = abs(R[2, 2] - 1) < 1e-6
        half = [s / 2 for s in size] if upright else list((pts.max(0) - pts.min(0)) / 2)
        return {"mid": [round(float(v), 4) for v in mid], "half": [round(float(v), 4) for v in half],
                "yaw": round(math.atan2(R[1, 0], R[0, 0]), 4) if upright else 0.0}

    def probe(self, item: str, u: float, v: float, yaw: float = 0.0, exclude_uid: str | None = None) -> dict:
        """Where an item being dragged over the view at (u, v) would land."""
        p0, d = self.pixel_ray(u, v)
        excl = -1
        if exclude_uid:
            with self.lock:
                excl = self.m.body(f"obj_{exclude_uid}").id
        # through a robot arm, to the surface under it (what's under the arm can be reached)
        dist, body, _ = self._ray_past_robots(p0, d, excl)
        if dist is None:
            if d[2] >= -1e-6:
                return {"valid": False, "reason": "off the floor"}
            dist = -p0[2] / d[2]
        hit = p0 + dist * d
        # Over a container (bowl, crate, tray...) big enough to hold it: drop it in the middle.
        kind, uid = self._owner(body) if dist is not None else ("floor", None)
        if kind == "object" and uid != exclude_uid:
            it = catalog.item(self.find(uid).item)
            mine, theirs = catalog.meta(item)["size"], catalog.meta(it["id"])["size"]
            if it["hollow"] and not it["fixed"] and max(mine[:2]) < min(theirs[:2]):
                with self.lock:
                    c = self.d.xpos[self.m.body(f"obj_{uid}").id]
                hit = np.array([c[0], c[1], hit[2]])
        if abs(hit[0]) > 9.5 or abs(hit[1]) > 9.5:
            return {"valid": False, "reason": "off the floor"}
        rot = None
        if exclude_uid:                 # a moved object keeps how it's turned
            with self.lock:
                rot = self.obj_rot(exclude_uid)
            if yaw:
                rot = W.axis_rot("z", math.degrees(yaw)) @ rot
        out = self.support(item, float(hit[0]), float(hit[1]), yaw, exclude_uid=exclude_uid, rot=rot)
        self.set_ghost(item, out, yaw)
        return out

    def set_ghost(self, item, spot, yaw=0.0):
        ok = spot.get("valid", False)
        col = [0.25, 0.55, 1.0] if ok else [1.0, 0.3, 0.25]
        if "box" not in spot:
            self.overlay = []
            return
        (x, y, zm), (hx, hy, hz) = spot["box"]["mid"], spot["box"]["half"]
        self.overlay = [
            # the drop spot, glowing on the surface it lands on
            {"type": "box", "size": [hx + 0.02, hy + 0.02, 0.0015], "pos": [x, y, zm - hz + 0.001],
             "yaw": spot["box"]["yaw"], "rgba": [*col, 0.45]},
            # the space the item will take
            {"type": "box", "size": [hx, hy, hz], "pos": [x, y, zm], "yaw": spot["box"]["yaw"], "rgba": [*col, 0.18]},
        ]

    def clear_ghost(self):
        self.overlay = []

    def _selection_overlay(self):
        out = []
        with self.lock:
            if self.scene_mode == "free" and len(self.stations) > 1:
                a = self.arms.get(self.active_station)
                if a is not None:    # the station the page is looking at: a ring at its robot's foot
                    bp = self.d.xpos[a.base_body]
                    out.append({"type": "cylinder", "size": [0.17, 0.002, 0], "pos": [bp[0], bp[1], bp[2] + 0.002],
                                "yaw": 0.0, "rgba": [0.15, 0.45, 0.95, 0.55]})
            sel = self.selected
            p = self.find(sel) if sel else None
            if p is None:
                return out
            b = self.m.body(f"obj_{sel}").id
            pos = self.d.xpos[b].copy()
            q = self.d.xquat[b]
        yaw = math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
        sx, sy, _ = catalog.meta(p.item)["size"]
        return out + [{"type": "box", "size": [sx / 2 + 0.015, sy / 2 + 0.015, 0.001], "pos": [pos[0], pos[1], pos[2] + 0.001],
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
        ver, r, rd, size = None, None, None, None
        types = {"box": mujoco.mjtGeom.mjGEOM_BOX, "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER}
        opt = mujoco.MjvOption()
        seq = 0
        while self._running:
            if time.time() - self._last_view_req > 3.0:   # nobody is watching
                time.sleep(0.05)
                continue
            t0 = time.perf_counter()
            self._glide_step()
            with self.lock:
                if ver != self._model_ver or size != self.view_size:
                    if ver != self._model_ver:
                        rd = mujoco.MjData(self.m)
                    ver, m, size = self._model_ver, self.m, self.view_size
                    if r is not None:
                        r.close()
                    r = mujoco.Renderer(m, size[1], size[0])
                rd.qpos[:] = self.d.qpos
                rd.time = self.d.time
            mujoco.mj_kinematics(m, rd)
            mujoco.mj_camlight(m, rd)
            r.update_scene(rd, camera=self.view, scene_option=opt)
            sc = r.scene
            if self.scene_mode == "free":
                tron.draw(sc, time.time())
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
