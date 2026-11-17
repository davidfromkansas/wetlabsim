"""Builds the playground's lab: a speckled vinyl-tile floor like a university wet lab's, the
robot stations on it (each a robot arm on its own NVIDIA packing table, with its own overhead
and side cameras), and whatever the user has dropped in.

Every library item comes from playground/assets/<id>/ (see tools/convert_simready.py):
visual meshes with their textures, collision meshes, and the mass the asset states.
Physics settings (solver, materials) are the robot cell's own (wetlabsim/scene.py).
"""
from __future__ import annotations

import contextvars
import math
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import mujoco
import numpy as np

from wetlabsim import scene as S

from . import catalog
from . import settings as ST
from . import wetrobo as WR

# The floor: 12-inch speckled vinyl tiles (playground/tools/make_lab_floor.py draws them), a 4 x 4
# patch of tiles to the picture.
FLOOR_TEXTURE = Path(__file__).resolve().parent / "textures" / "lab_floor.png"
FLOOR_PATCH = 4 * 0.3048          # metres the picture covers
TABLE_UID = "table"     # (older saved scenes) the one table a robot stood on
# Kept clear around a robot's base when a station starts with items, or when an arm is swapped in.
BASE_CLEARANCE = 0.25
# A small arm needs less (the PiPER's base is a 10 cm square).
BASE_CLEARANCE_BY = {"piper": 0.18}
# A station's robot stands on its table, near one long edge, facing across it (+x).
ROBOT_XY = (-0.42, 0.0)
# A humanoid stands on the floor instead, its pelvis this far back from the table's near edge (m):
# close enough for its hands to work over the table, its feet clear of the table's frame.
HUMANOID_GAP = 0.15
# A wheeled humanoid (the RB-Y1) stands on the floor too: its base's centre this far back from the
# table's near edge (m), the front of its base (30 cm ahead of the centre) 6 cm clear of the edge.
MOBILE_GAP = 0.36
STATION_TABLE = "table_packing"
# A big floor-standing arm stands on the floor too, facing its table (or pallet, or car) from
# further back. Per robot: its base's centre to the table's near edge (m), the room its base and
# first joint sweep takes behind that (m), and how high above the table top its overhead camera
# hangs (m): its work area is several times a table arm's.
FLOOR_ARMS = {"n220": {"gap": 1.15, "base": 0.75, "above": 3.4, "ahead": 1.6},
              "crx30ia": {"gap": 0.55, "base": 0.35, "above": 2.3, "ahead": 0.9}}

# A table arm's steel stand, when it isn't standing right on its table (Station.stands): one box
# under each base, the size of what the base covers, as (x, y) of its middle from the robot's
# mount and its half size along the robot's own x and y (m), measured on each model.
STANDS = {"franka": [(-0.041, 0.0, 0.115, 0.095)], "ur5e": [(0.0, 0.0, 0.08, 0.08)],
          "piper": [(-0.01, 0.0, 0.05, 0.045)], "fr3_duo": [(0.0, 0.0, 0.12, 0.145)],
          "aloha": [(-0.019, 0.5, 0.1, 0.16), (-0.019, -0.5, 0.1, 0.16)]}
STAND_RGBA = [0.55, 0.57, 0.6, 1.0]     # brushed steel
STAND_MIN = 0.002        # a gap this small under a mount needs no stand
ROBOT_REACH_OFF = 1.0    # a robot moved off its table stays this near the table (m)
ROBOT_Z_MAX = 2.0        # and its mount at most this high above the floor (m)

CAR_TURN = math.pi / 2       # the car body's long side faces its robot
CAR_STAND_Y = 1.0

# The kinds of station: which table the robot stands on, how that table is turned in the
# station's frame (the robot always faces +x), where the robot stands, and what starts on it.
# The wet lab bench is a stainless lab table, turned so its long side runs beside the arm,
# with lab glassware and instruments laid out within reach (item, x, y, yaw in the
# station's frame, on the table top).
KINDS = {
    "table": {"label": "Table with arm", "table": STATION_TABLE, "turn": 0.0, "robot_xy": ROBOT_XY,
              "layout": []},
    "wetlab": {"label": "Wet lab bench", "table": "lab_bench", "turn": math.pi / 2, "robot_xy": (-0.2, 0.0),
               "layout": [
                   ("sterilising_tray", 0.12, -0.5, 0.0),
                   ("syringe", 0.17, -0.27, 0.0),
                   ("syringe_small", 0.24, -0.2, 0.0),
                   ("forceps", 0.05, -0.24, 0.0),
                   ("thermometer", -0.14, -0.33, math.pi / 2),
                   ("medicine", -0.12, -0.72, 0.0),
                   ("glass_vial", 0.24, -0.06, 0.0),
                   ("glass_vial", 0.24, 0.0, 0.0),
                   ("glass_vial", 0.24, 0.06, 0.0),
                   ("lab_bottle_small", 0.1, 0.2, 0.0),
                   ("lab_bottle_small", 0.1, 0.26, 0.0),
                   ("lab_bottle", 0.2, 0.3, 0.0),
                   ("lab_bottle_m", 0.2, 0.42, 0.0),
                   ("lab_bottle_l", 0.2, 0.56, 0.0),
                   ("lab_bottle_xl", 0.2, 0.72, 0.0),
                   ("glass_jar", -0.05, 0.5, 0.0),
                   ("disinfectant", -0.12, 0.7, 0.0),
                   ("glove_box", 0.0, 0.8, math.pi / 2),
               ]},
    # A kitchen island: the arm stands on the worktop near one long edge (its long side runs
    # beside the arm, like the lab bench), a humanoid on the floor beside it. Starts empty.
    "island": {"label": "Kitchen island", "table": "kitchen_island", "turn": 0.0, "robot_xy": (-0.17, 0.0),
               "layout": []},
    # A kitchen counter run (Tripo's worktop over cabinets whose doors and drawers open), turned
    # so its long side runs beside the arm. Starts empty.
    "counter": {"label": "Kitchen counter", "table": "countertop_2", "turn": math.pi / 2, "robot_xy": (-0.15, 0.0),
                "layout": []},
    # A LIBERO benchmark room (playground/libero.py): the whole room of one of LIBERO's tasks, as
    # LIBERO builds it, with its Franka where LIBERO mounts it. The station's place is the room's
    # centre; its task and starting layout are the station's own (Station.task, .setup).
    # A pallet on the floor: what a big floor-standing arm lifts from and stacks on. An open
    # cell (no work-box walls): its robot's cameras see the line around it.
    "pallet": {"label": "Pallet", "table": "pallet", "turn": 0.0, "robot_xy": (-0.3, 0.0), "open": True,
               "layout": []},
    # A car body on stands, side on to its robot: the robot stands level with the engine bay
    # ("stand_y": how far along the car, toward its nose). An open cell.
    "car": {"label": "Car body", "table": "car_body", "turn": CAR_TURN, "robot_xy": (-0.3, 0.0), "open": True,
            "stand_y": CAR_STAND_Y, "layout": []},
    # A roller conveyor section: parts and totes ride on its rollers. An open cell.
    "conveyor": {"label": "Roller conveyor", "table": "roller_conveyor", "turn": 0.0, "robot_xy": (-0.3, 0.0),
                 "open": True, "layout": []},
    # A steel workbench with a cupboard under it.
    "workbench": {"label": "Workbench", "table": "workbench", "turn": math.pi / 2, "robot_xy": (-0.2, 0.0),
                  "layout": []},
    "libero": {"label": "LIBERO", "table": None, "turn": 0.0, "robot_xy": (-1.16, 0.0), "layout": []},
    # WetRobo's two labs (playground/wetrobo.py): the same kit (a benchtop incubator with its
    # door facing the arm, a screw-cap reagent bottle, a Petri dish) in two different places.
    # Lab X: the stainless lab bench, the arm near one end looking along it: the incubator ahead
    # (turned a little, its handle 0.6 m from the arm, its door swinging open toward the arm's left), the dish
    # and bottle ahead on its right, clear of the door's swing.
    # The paper's own arm, the AgileX PiPER, is smaller (626 mm reach; straight down it reaches
    # no higher than 12 cm above its base), so each lab has a layout of its own for it
    # ("robot_xy_by", "layout_by"): the same kit and the same incubator spot, the arm straight
    # in front of the incubator's handle, 0.6 m from it, and the dish and bottle 0.3 to 0.45 m
    # from the arm, on its right, clear of the door's swing.
    "wetrobo_x": {"label": "WetRobo Lab X", "table": "lab_bench", "turn": 0.0, "robot_xy": (-0.6, -0.2),
                  "robot_xy_by": {"piper": (-0.607, -0.066)},
                  "layout_by": {"piper": [
                      ("lab_incubator", 0.26, 0.0, -math.pi / 2 - 0.15),
                      ("screw_cap_bottle", -0.367, -0.286, 0.0),
                      ("petri_dish_60", -0.287, -0.106, 0.0),
                      ("petri_dish_60_lid", -0.287, -0.106, 0.0, WR.LID_SEAT + 0.001),
                      ("lab_bottle", -0.85, 0.22, 0.0),
                      ("glass_vial", -0.85, 0.05, 0.0),
                  ]},
                  "layout": [
                      ("lab_incubator", 0.26, 0.0, -math.pi / 2 - 0.15),
                      ("screw_cap_bottle", -0.32, -0.29, 0.0),
                      ("petri_dish_60", -0.12, -0.3, 0.0),
                      ("petri_dish_60_lid", -0.12, -0.3, 0.0, WR.LID_SEAT + 0.001),
                      ("lab_bottle", -0.8, 0.2, 0.0),
                      ("glass_vial", -0.8, 0.02, 0.0),
                  ]},
    # Lab Y: the taller wooden packing table, the incubator ahead of the arm on its left, the
    # bottle and dish on the right (all within the arm's easy reach), and other lab things around.
    "wetrobo_y": {"label": "WetRobo Lab Y", "table": STATION_TABLE, "turn": 0.0, "robot_xy": ROBOT_XY,
                  "robot_xy_by": {"piper": (-0.40, 0.10)},
                  "layout_by": {"piper": [
                      ("lab_incubator", 0.45, 0.3, -math.pi / 2),
                      ("screw_cap_bottle", -0.18, -0.26, 0.0),
                      ("petri_dish_60", -0.10, -0.04, 0.0),
                      ("petri_dish_60_lid", -0.10, -0.04, 0.0, WR.LID_SEAT + 0.001),
                      ("sterilising_tray", 0.55, -0.42, 0.0),
                      ("reagent_bottle", 0.3, -0.12, 0.0),
                      ("glove_box", 0.68, -0.12, math.pi / 2),
                      ("disinfectant", -0.15, -0.5, 0.0),
                  ]},
                  "layout": [
                      ("lab_incubator", 0.45, 0.3, -math.pi / 2),
                      ("screw_cap_bottle", 0.05, -0.33, 0.0),
                      ("petri_dish_60", 0.08, -0.12, 0.0),
                      ("petri_dish_60_lid", 0.08, -0.12, 0.0, WR.LID_SEAT + 0.001),
                      ("sterilising_tray", 0.55, -0.42, 0.0),
                      ("reagent_bottle", 0.3, -0.12, 0.0),
                      ("glove_box", 0.68, -0.12, math.pi / 2),
                      ("disinfectant", -0.15, -0.5, 0.0),
                  ]},
}
LIBERO_ROOM = (5.0, 6.0)      # a LIBERO room's floor (m), before its task is known

# Contact properties for library items, as a MuJoCo default class like the cell's
# materials. Sliding friction comes from each asset's own physics material.
PROP = dict(condim=6, friction=(1, 0.005, 0.0001), solref=(0.005, 1))
FURNITURE = dict(condim=3, friction=(1, 0.005, 0.0001), solref=(0.005, 1))

# The lab's solver options: the robot cell's own (wetlabsim/scene.py), except three, so that
# soft objects can be springy. MuJoCo 4.0 integrates flex elasticity only under its
# "discrete" integrator ("Numerical integration" in MuJoCo's Computation chapter). Under
# "discrete", MuJoCo's noslip post-processing leaves out tendon and actuator couplings (same
# chapter), and the Franka Hand closes through a tendon: with noslip its grasps slipped and
# dropped things. So noslip is off, and grasps are kept from slipping the way MuJoCo's
# documentation gives for elliptic friction cones instead: a high impratio (frictional-to-
# normal constraint impedance; "XML Reference", option/impratio), 100. Measured in the
# playground (tools: a 20 s full-strength hold of six items, both arms, both benches): every
# grasp holds, creeping 0.06-1.5 mm (a mug held by its rim, 3-19 mm), as with the cell's
# own settings. The robot cell, and with it Wet Lab and LIBERO mode, keeps its own options.
OPTION = {**S.OPTION, "integrator": "discrete", "noslip_iterations": 0, "impratio": 100}


@dataclass
class Placed:
    uid: str
    item: str
    pos: tuple            # world position of the item's bottom centre (m)
    yaw: float = 0.0      # rotation about the vertical (rad)
    quat: tuple | None = None   # full orientation when set (after physics has moved it)
    joints: dict | None = None  # a jointed item's joint positions, by joint name (kept across rebuilds)
    parts: dict | None = None   # a jointed item's loose or welded parts: body name -> (pos, quat)

    def as_dict(self):
        return {"uid": self.uid, "item": self.item, "pos": [round(float(v), 4) for v in self.pos],
                "yaw": round(float(self.yaw), 4)}


def yaw_quat(yaw: float):
    return (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))


# Rotating an object: its orientation as three angles about the world's fixed X, Y and Z axes
# (applied X first, then Y, then Z), the numbers the page shows and takes.
def euler_rot(deg) -> np.ndarray:
    x, y, z = (math.radians(float(v)) for v in deg)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def rot_euler(R: np.ndarray) -> list:
    y = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    if abs(R[2, 0]) < 0.9999:
        x, z = math.atan2(R[2, 1], R[2, 2]), math.atan2(R[1, 0], R[0, 0])
    else:                       # straight up or down about Y: X and Z turn the same way
        x, z = 0.0, math.atan2(-R[0, 1], R[1, 1])
    # every turn has a second set of angles (X + 180, 180 - Y, Z + 180): show the smaller one
    wrap = lambda a: (a + 180.0) % 360.0 - 180.0 if (a + 180.0) % 360.0 else 180.0
    a = [math.degrees(v) for v in (x, y, z)]
    b = [wrap(a[0] + 180), wrap(180 - a[1]), wrap(a[2] + 180)]
    best = min((a, b), key=lambda e: sum(abs(v) for v in e) + 1e-6 * (e is b))
    return [round(v, 1) + 0.0 for v in best]


def axis_rot(axis: str, degrees: float) -> np.ndarray:
    return euler_rot({"x": (degrees, 0, 0), "y": (0, degrees, 0), "z": (0, 0, degrees)}[axis])


def rot_quat(R: np.ndarray) -> tuple:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(R, float).ravel())
    return tuple(float(v) for v in q)


def box_points(size, n: int = 3) -> np.ndarray:
    """Points over an item's box in its own frame (bottom centre at the origin): n per side."""
    sx, sy, sz = size
    t = np.linspace(-0.5, 0.5, n)
    return np.array([(a * sx, b * sy, (c + 0.5) * sz) for a in t for b in t for c in t])


@dataclass
class Station:
    """A robot arm on its own table: the unit a lab is built from."""
    uid: str              # "st1", "st2", ...: also the prefix of the robot's names ("st1/joint1")
    robot: str            # a key of wetlabsim.scene.ROBOTS ("franka", "ur5e", "aloha", "fr3_duo")
    pos: tuple            # world (x, y) of the table's centre (m)
    yaw: float = 0.0      # rotation about the vertical (rad)
    name: str = ""        # what the user calls it ("Station 1")
    kind: str = "table"   # a key of KINDS
    task: str = ""        # a benchmark station: its task (a playground.libero or playground.wetrobo task id)
    setup: int = 0        # a LIBERO station: the official starting layout its next run starts from
    free: bool = False    # a benchmark's scene as a free station: the same room or lab, any task you
    #                       type, no goal check and no score (a LIBERO room keeps a task for its room)
    open_cell: bool = False   # no work-box walls (a ready-made scene's humanoid, among other robots)
    # Where the user has put the robot itself (its own Move / Rotate controls), apart from its table.
    # None / 0: where the station's kind puts it. robot_at: (x, y) of its base in the station's
    # frame; robot_turn: its turn about the vertical from the station's (rad); robot_z: its mount's
    # height above the floor (m). A table arm with nothing under its mount stands on a steel
    # stand (stand_height): to the floor off the table, a riser on it.
    robot_at: tuple | None = None
    robot_turn: float = 0.0
    robot_z: float | None = None

    @property
    def libero(self) -> bool:
        return self.kind == "libero"

    @property
    def wetrobo(self) -> str:
        """A WetRobo station: its lab ("x" or "y"), else ""."""
        from . import wetrobo as WR
        return WR.lab_of(self.kind)

    def room(self) -> dict | None:
        """A LIBERO station's room (playground.libero.room), or None."""
        if not (self.libero and self.task):
            return None
        from . import libero as LB
        return LB.room(self.task)

    def room_origin(self):
        """Where LIBERO's own frame sits in the station's frame (its room's centre is the station's)."""
        r = self.room()
        cx, cy = r["centre"] if r else (0.5, 0.0)
        return -cx, -cy

    @property
    def prefix(self) -> str:
        return self.uid + "/"

    @property
    def spec(self) -> dict:
        return KINDS.get(self.kind, KINDS["table"])

    @property
    def table_item(self) -> str | None:
        return self.spec["table"]

    @property
    def table_yaw(self) -> float:
        return self.yaw + self.spec["turn"]

    @property
    def standing(self) -> bool:
        """A humanoid (the G1, the wheeled RB-Y1) or a big floor arm stands on the floor at the
        table, not on it."""
        from wetlabsim import scene as WS
        P = WS.ROBOTS[self.robot]
        return bool(P.get("humanoid") or P.get("mobile") or P.get("floor"))

    @property
    def floor_arm(self) -> dict | None:
        """A big floor-standing arm's stance (FLOOR_ARMS), else None."""
        return FLOOR_ARMS.get(self.robot)

    @property
    def open(self) -> bool:
        """An open cell: no work-box walls, so its robot's cameras see what is around it. A
        robot on wheels (the RB-Y1) always has one: it drives off to the rest of the lab."""
        from wetlabsim import scene as WS
        return bool(self.open_cell or self.spec.get("open") or WS.ROBOTS[self.robot].get("mobile"))

    @property
    def stand_gap(self) -> float:
        """How far back from the table's near edge a robot on the floor stands (m)."""
        from wetlabsim import scene as WS
        if self.floor_arm:
            return self.floor_arm["gap"]
        return MOBILE_GAP if WS.ROBOTS[self.robot].get("mobile") else HUMANOID_GAP

    @property
    def robot_xy(self) -> tuple:
        if self.robot_at is not None:  # where the user put it
            return tuple(self.robot_at)
        return self.home_xy

    @property
    def home_xy(self) -> tuple:
        """Where the station's kind puts its robot (station frame)."""
        if self.robot == "aloha":     # two arms facing each other across the middle of the table
            return (0.0, 0.0)
        if self.standing:             # on the floor, facing the table's near edge, HUMANOID_GAP from it
            return (-self.footprint()[0] / 2 - self.stand_gap, self.spec.get("stand_y", 0.0))
        if self.libero and self.task:  # where LIBERO mounts its Panda
            ox, oy = self.room_origin()
            bx, by, _ = self.room()["base"]["pos"]
            return (ox + bx, oy + by)
        # a benchmark lab seats a smaller arm nearer its kit (WetRobo: the PiPER)
        return self.spec.get("robot_xy_by", {}).get(self.robot, self.spec["robot_xy"])

    def bases(self) -> list:
        """Where the robot stands on the table, in the station's frame: one base, or an ALOHA's two."""
        if self.robot == "aloha":
            return [self.from_robot(-0.019, 0.469), self.from_robot(-0.019, -0.469)]
        return [self.robot_xy]

    def from_robot(self, x: float, y: float) -> tuple:
        """A point given from the robot's mount (its own x forward, y left) in the station's frame."""
        rx, ry = self.robot_xy
        c, s = math.cos(self.robot_turn), math.sin(self.robot_turn)
        return (rx + c * x - s * y, ry + s * x + c * y)

    # ------------------------------------------------ the robot's own place (Move / Rotate)
    @property
    def moved(self) -> bool:
        """Whether the user has moved, turned or raised the robot from where its kind puts it."""
        return self.robot_at is not None or abs(self.robot_turn) > 1e-9 or self.robot_z is not None

    def fixed_why(self) -> str:
        """Why this station's robot can't be moved apart from its table ("" if it can)."""
        if self.libero:
            return "a LIBERO room keeps its Franka where LIBERO mounts it"
        if self.wetrobo and not self.free:
            return "a WetRobo station keeps its robot where it is, so every run is the same test"
        return ""

    @property
    def liftable(self) -> bool:
        """A table arm can go up and down (on a stand); a robot on the floor stays on the floor."""
        return not self.standing and not self.libero

    @property
    def home_z(self) -> float:
        return 0.0 if self.standing else self.top

    @property
    def mount_z(self) -> float:
        """How high the robot's mount is above the floor (m)."""
        if self.robot_z is not None and self.liftable:
            return float(self.robot_z)
        return self.home_z

    def foot(self) -> list:
        """What the robot's base (or bases) cover: [(x, y) of the middle in the station's frame,
        half x, half y], turned with the robot. A robot with none listed: a 10 cm square."""
        out = []
        for cx, cy, hx, hy in STANDS.get(self.robot, [(0.0, 0.0, 0.05, 0.05)]):
            out.append((self.from_robot(cx, cy), hx, hy))
        return out

    def _foot_side(self, at, hx, hy) -> str:
        """Whether a base box (middle at, half sizes, turned with the robot) is all on the table
        ("on"), all off it ("off"), or across its edge ("edge")."""
        sx, sy = self.footprint()
        c, s = math.cos(self.robot_turn), math.sin(self.robot_turn)
        ex, ey = abs(c) * hx + abs(s) * hy, abs(s) * hx + abs(c) * hy   # its box along the table's axes
        x, y = at
        if abs(x) + ex <= sx / 2 and abs(y) + ey <= sy / 2:
            return "on"
        if abs(x) - ex >= sx / 2 or abs(y) - ey >= sy / 2:
            return "off"
        return "edge"

    def robot_side(self) -> str:
        """Where the robot stands: "on" its table, "off" it (on the floor), or "edge" (across it)."""
        if self.libero:
            return "on"
        sides = {self._foot_side(*f) for f in self.foot()}
        return sides.pop() if len(sides) == 1 else "edge"

    def surface_z(self) -> float:
        """What is under the robot's mount: its table top, or the floor."""
        return self.top if self.robot_side() == "on" and not self.standing else 0.0

    def stands(self) -> list:
        """The steel stand under a table arm whose mount is above what is under it: one box per
        base, [(x, y) world middle, half x, half y, bottom z, top z]. None when it stands right on
        its table, and never for a robot on the floor."""
        if not self.liftable:
            return []
        lo, hi = self.surface_z(), self.mount_z
        if hi - lo < STAND_MIN:
            return []
        return [(self.to_world(*at)[:2], hx, hy, lo, hi) for at, hx, hy in self.foot()]

    def snap_robot(self, x: float, y: float) -> tuple:
        """The nearest place to (x, y) (station frame) where the robot stands either fully on its
        table or fully off it, never across its edge. A robot on the floor: fully off it."""
        sx, sy = self.footprint()
        old = self.robot_at
        try:
            self.robot_at = (x, y)
            want = ("off",) if self.standing else ("on", "off")
            if self.robot_side() in want:
                return (x, y)
            c, s = math.cos(self.robot_turn), math.sin(self.robot_turn)
            best = None
            for (fx, fy), hx, hy in self.foot():
                ex, ey = abs(c) * hx + abs(s) * hy, abs(s) * hx + abs(c) * hy
                moves = [(sx / 2 + ex - fx + 1e-4, 0), (-sx / 2 - ex - fx - 1e-4, 0),
                         (0, sy / 2 + ey - fy + 1e-4), (0, -sy / 2 - ey - fy - 1e-4)]
                if "on" in want:
                    moves.append((max(min(fx, sx / 2 - ex), -sx / 2 + ex) - fx,
                                  max(min(fy, sy / 2 - ey), -sy / 2 + ey) - fy))
                for dx, dy in moves:
                    self.robot_at = (x + dx, y + dy)
                    if self.robot_side() in want and (best is None or math.hypot(dx, dy) < best[0]):
                        best = (math.hypot(dx, dy), (x + dx, y + dy))
            return best[1] if best else (x, y)
        finally:
            self.robot_at = old

    def robot_far(self) -> bool:
        """Whether the robot is further from its table than a robot is let go (ROBOT_REACH_OFF)."""
        sx, sy = self.footprint()
        x, y = self.robot_xy
        return max(abs(x) - sx / 2, abs(y) - sy / 2) > ROBOT_REACH_OFF + (self.stand_gap if self.standing else 0.0)

    def near_base(self, x: float, y: float, r: float | None = None) -> bool:
        """Whether a world point is within r of the robot's base (or bases)."""
        if r is None:
            r = BASE_CLEARANCE_BY.get(self.robot, BASE_CLEARANCE)
        lx, ly = self.to_local(x, y)
        return any(math.hypot(lx - bx, ly - by) < r for bx, by in self.bases())

    @property
    def top(self) -> float:
        if self.libero:        # the robot's base height: LIBERO's table top, or the floor
            r = self.room()
            return float(r["base"]["pos"][2]) if r else 0.9
        return table_top(self.table_item)

    def to_world(self, x: float, y: float, z: float = 0.0):
        """A point given in the station's own frame (table centre, robot along -x) in the world."""
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (self.pos[0] + c * x - s * y, self.pos[1] + s * x + c * y, z)

    def to_local(self, x: float, y: float):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        dx, dy = x - self.pos[0], y - self.pos[1]
        return (c * dx + s * dy, -s * dx + c * dy)

    WALL_MARGIN = 0.1        # the work box: this far out from the table's edge
    WALL_ABOVE = 1.3         # and this high above the table top (over the overhead camera)
    ROOM = 5.0               # a humanoid's work box: a solid room this wide (m) round its table,
                             # to walk about in

    @property
    def roomy(self) -> bool:
        """A humanoid that walks (the G1): its work box is a room of solid walls, ROOM wide."""
        from wetlabsim import scene as WS
        return bool(WS.ROBOTS[self.robot].get("humanoid")) and not self.libero and not self.open

    def area(self):
        """What this station takes of the floor, (half x, half y) about its centre in its own
        frame: a walking humanoid's room, else its table."""
        if self.roomy:
            return self.ROOM / 2, self.ROOM / 2
        sx, sy = self.footprint()
        hx, hy = sx / 2, sy / 2
        if self.moved:         # a robot moved off its table: its base too
            for (x, y), fx, fy in self.foot():
                r = math.hypot(fx, fy)
                hx, hy = max(hx, abs(x) + r), max(hy, abs(y) + r)
        return hx, hy

    def claims(self, x: float, y: float, margin: float = 0.0) -> bool:
        """Whether a point is on this station's floor area (area())."""
        hx, hy = self.area()
        lx, ly = self.to_local(x, y)
        return abs(lx) <= hx + margin and abs(ly) <= hy + margin

    def area_points(self, n: int = 9):
        """Points on the edges and across this station's area (world x, y), for overlap checks."""
        hx, hy = self.area()
        f = np.linspace(-1.0, 1.0, n)
        return [self.to_world(a * hx, b * hy)[:2] for a in f for b in f]

    def work_box(self):
        """The space this station's robot works in: its table's footprint plus a margin, from
        the floor to well above its cameras. (half x, half y, height), in the station's frame,
        centred on the table."""
        sx, sy = self.footprint()
        if self.libero:        # the room itself
            return sx / 2, sy / 2, 3.0
        if self.roomy:         # a walking humanoid: its room
            return self.ROOM / 2, self.ROOM / 2, self.top + self.WALL_ABOVE
        # A humanoid stands outside the table's footprint: the box takes in where it stands too.
        mx = self.stand_gap + 0.35 if self.standing else self.WALL_MARGIN
        if self.floor_arm:     # a big arm: room for its base behind, its reach to the sides, its height
            fa = self.floor_arm
            return (sx / 2 + fa["gap"] + fa["base"], max(sy / 2 + self.WALL_MARGIN, fa["gap"] + fa["base"]),
                    self.top + fa["above"] + 0.2)
        hx, hy, h = sx / 2 + mx, sy / 2 + self.WALL_MARGIN, self.top + self.WALL_ABOVE
        if self.moved and not self.standing:   # a moved arm: the box takes in its base, and its height
            x, y = self.robot_xy
            hx, hy = max(hx, abs(x) + 0.35), max(hy, abs(y) + 0.35)
            h = max(h, self.mount_z + self.WALL_ABOVE)
        elif self.moved:
            x, y = self.robot_xy
            hx, hy = max(hx, abs(x) + 0.5), max(hy, abs(y) + 0.5)
        return hx, hy, h

    def footprint(self):
        """The table's size along the station's own x and y (a LIBERO station: its room's)."""
        if self.libero:
            r = self.room()
            return tuple(r["size"]) if r else LIBERO_ROOM
        sx, sy, _ = catalog.meta(self.table_item)["size"]
        c, s = abs(math.cos(self.spec["turn"])), abs(math.sin(self.spec["turn"]))
        return c * sx + s * sy, s * sx + c * sy

    def holds(self, x: float, y: float, margin: float = 0.0) -> bool:
        """Whether a point is over this station's table."""
        sx, sy = self.footprint()
        lx, ly = self.to_local(x, y)
        return abs(lx) <= sx / 2 + margin and abs(ly) <= sy / 2 + margin

    def as_dict(self):
        from wetlabsim import scene as WS
        P = WS.ROBOTS[self.robot]
        out = {"id": self.uid, "robot": self.robot, "name": self.name, "label": P["name"], "kind": self.kind,
               "gripper": P["gripper"], "pos": [round(float(v), 4) for v in self.pos],
               "yaw": round(float(self.yaw), 4)}
        if self.moved:
            out["mount"] = {"at": [round(float(v), 4) for v in self.robot_at or self.home_xy],
                            "turn": round(float(self.robot_turn), 4),
                            **({"z": round(float(self.robot_z), 4)} if self.robot_z is not None else {})}
        if self.free:
            out["free"] = True
        elif self.libero and self.task:
            from . import libero as LB
            t = LB.task(self.task)
            out["libero"] = {"task": t.id, "suite": t.suite, "suite_name": LB.SUITE_NAMES[t.suite],
                             "index": t.index + 1, "language": t.language, "goal": LB.goal_parts(t),
                             "setup": self.setup, "setups": t.n_setups}
        if self.wetrobo and self.task and not self.free:
            from . import wetrobo as WR
            t = WR.task(self.task)
            out["wetrobo"] = {"task": t.id, "title": t.title, "language": t.language, "goal": list(t.goal),
                              "lab": self.wetrobo, "lab_label": WR.LABS[self.wetrobo][1]}
        return out


def table_uid(st: Station) -> str:
    return f"{st.uid}-table"


def _xml_attrs(d):
    return S._xml_attrs(d)


# The session's scene settings (playground/settings.py) while its lab is built.
_SETTINGS: contextvars.ContextVar[dict] = contextvars.ContextVar("pg_settings", default={})


def prop_class() -> dict:
    """The objects' material class, with the session's changes."""
    return ST.material(PROP, "prop", _SETTINGS.get())


def _world_xml() -> str:
    cfg = _SETTINGS.get()
    defaults = ("<default>"
                + "".join(f'<default class="{n}"><geom {_xml_attrs(ST.material(p, n, cfg))}/></default>'
                          for n, p in S.MATERIALS.items())
                + f'<default class="prop"><geom {_xml_attrs(prop_class())}/></default>'
                + f'<default class="furniture"><geom {_xml_attrs(ST.material(FURNITURE, "furniture", cfg))}/></default>'
                + "</default>")
    return f"""
<mujoco model="playground">
  <compiler angle="radian" autolimits="true"/>
  <size memory="512M"/>
  <option {_xml_attrs(ST.option_attrs(OPTION, cfg))}><flag {_xml_attrs(ST.flag_attrs(S.FLAGS, cfg))}/></option>
  {defaults}
  <visual>
    <global offwidth="1920" offheight="1200" azimuth="150" elevation="-25"/>
    <headlight ambient="0.5 0.5 0.5" diffuse="0.3 0.3 0.3" specular="0.05 0.05 0.05"/>
    <quality shadowsize="4096"/>
    <map znear="0.01" zfar="50"/>
  </visual>
  <asset>
    <texture name="floor" type="2d" file="{FLOOR_TEXTURE}"/>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.99 0.99 0.985" rgb2="0.93 0.94 0.95"
             width="256" height="1536"/>
    <material name="floor" texture="floor" texrepeat="{1 / FLOOR_PATCH:.4f} {1 / FLOOR_PATCH:.4f}" texuniform="true" reflectance="0"/>
  </asset>
  <worldbody>
    <light pos="0.5 -1.0 4" dir="-0.1 0.25 -1" diffuse="0.5 0.5 0.5" specular="0.1 0.1 0.1" castshadow="true"/>
    <light type="directional" pos="-2 2 3" dir="0.5 -0.5 -1" diffuse="0.2 0.2 0.2" castshadow="false"/>
    <geom name="floor" type="plane" size="60 60 0.1" material="floor" class="bench"/>
  </worldbody>
</mujoco>
"""


def _add_materials(world: mujoco.MjSpec, d, prefix: str, meta: dict):
    for k, v in enumerate(meta["visuals"]):
        if v.get("texture"):
            world.add_texture(name=f"{prefix}tex{k}", file=str(d / v["texture"]),
                              type=mujoco.mjtTexture.mjTEXTURE_2D)
            mat = world.add_material(name=f"{prefix}mat{k}", rgba=v["rgba"])
            mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = f"{prefix}tex{k}"
        else:
            world.add_material(name=f"{prefix}mat{k}", rgba=v["rgba"])
        world.material(f"{prefix}mat{k}").specular = 0.3 if v.get("metallic", 0) > 0.5 else 0.15
        world.material(f"{prefix}mat{k}").shininess = max(0.05, 1 - v.get("roughness", 0.6))


def _pose(pos, quat) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = _rot(quat)
    T[:3, 3] = pos
    return T


def _quat_of(T: np.ndarray) -> list:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.ascontiguousarray(T[:3, :3]).ravel())
    return [float(v) for v in q]


def restitution_dampratio(e: float) -> float:
    """The damping ratio of a spring-damper contact that bounces back with coefficient of
    restitution e: zeta = -ln(e) / sqrt(pi^2 + ln(e)^2) (a damped oscillator's half period). It
    goes in the contact's solref (time constant, damping ratio), MuJoCo's way to set how bouncy a
    contact is ("Modeling", Restitution)."""
    if e <= 0:
        return 1.0
    le = math.log(min(e, 0.99))
    return -le / math.sqrt(math.pi ** 2 + le ** 2)


# The time constant of a contact that bounces: MuJoCo's default (0.02 s). With the lab's stiffer
# 0.005 s, an under-damped resting contact chatters and light items creep 1-2 mm/s (measured on
# a task light, funnel, tap wrench, toaster and gauge); at 0.02 s they settle.
BOUNCE_TIMECONST = 0.02


def set_surface(g, c: dict, cls, friction=None):
    """A collision shape's surface, as its asset states: sliding friction (static, MuJoCo takes
    one coefficient), how bouncy it is (restitution, or the asset's own MuJoCo solref), and, for
    a thin hard wall, how stiff its contacts are and that its own stiffness is the one used
    (MuJoCo's solimp and priority: a soft fingertip pad's would let the pad sink through a wall
    1 mm thick)."""
    if "contype" in c:       # the asset's own contact filter (MuJoCo's contype/conaffinity bits)
        g.contype, g.conaffinity = c["contype"], c["conaffinity"]
    mu = c.get("friction", friction)
    if mu:
        g.friction = [mu, g.friction[1], g.friction[2]]
    if c.get("solimp"):
        g.solimp[:len(c["solimp"])] = list(c["solimp"])
    if c.get("priority") is not None:
        g.priority = c["priority"]
    if c.get("solref"):
        g.solref = list(c["solref"])
    elif c.get("restitution") is not None:
        g.solref = [BOUNCE_TIMECONST, restitution_dampratio(c["restitution"])]


def set_inertia(body, parts: list) -> bool:
    """Give a body the mass, centre of mass and inertia its asset states for each of its parts
    (tools/convert_simready.combine_inertia), combined about their common centre: parts are
    (inertial, where the part sits in the body). False, and nothing set, if any part lacks them."""
    if not parts or any(not inr for inr, _ in parts):
        return False
    m = sum(inr["mass"] for inr, _ in parts)
    cs, Is = [], []
    for inr, at in parts:
        R = at[:3, :3] @ _rot(inr["quat"])
        cs.append(at[:3, :3] @ np.array(inr["pos"]) + at[:3, 3])
        Is.append(R @ np.diag(inr["diaginertia"]) @ R.T)
    c = sum(inr["mass"] * ci for (inr, _), ci in zip(parts, cs)) / m
    I = np.zeros((3, 3))
    for (inr, _), ci, Ii in zip(parts, cs, Is):
        d = ci - c
        I += Ii + inr["mass"] * (d @ d * np.eye(3) - np.outer(d, d))
    w, V = np.linalg.eigh((I + I.T) / 2)
    if np.linalg.det(V) < 0:
        V[:, 0] = -V[:, 0]
    T = np.eye(4)
    T[:3, :3] = V
    body.mass, body.ipos, body.iquat, body.inertia = m, list(c), _quat_of(T), list(np.maximum(w, 1e-12))
    body.explicitinertial = True
    return True


SHAPES = {"box": mujoco.mjtGeom.mjGEOM_BOX, "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER,
          "capsule": mujoco.mjtGeom.mjGEOM_CAPSULE, "sphere": mujoco.mjtGeom.mjGEOM_SPHERE}


def _part_geoms(world, body, name: str, rec: dict, prefix: str, cls, friction, at=None):
    """A part's collision shapes (its stated mass spread over them by volume) and its visuals;
    at: where the part sits in the body, for a part fixed onto another."""
    off = {} if at is None else {"pos": list(at[:3, 3]), "quat": _quat_of(at)}
    total = sum(c["volume"] for c in rec["collision_parts"]) or 1.0
    for k, c in enumerate(rec["collision_parts"]):
        if "shape" in c:          # one of MuJoCo's own shapes (a box, cylinder, capsule, sphere), as the asset states
            T = _pose(c["pos"], c["quat"]) if at is None else at @ _pose(c["pos"], c["quat"])
            g = body.add_geom(name=f"{name}_col{k}", type=SHAPES[c["shape"]], size=list(c["size"]) + [0] * (3 - len(c["size"])),
                              pos=list(T[:3, 3]), quat=_quat_of(T), default=cls, group=3, rgba=[0, 0, 0, 0])
        else:
            g = body.add_geom(name=f"{name}_col{k}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"{prefix}col{k}",
                              default=cls, group=3, rgba=[0, 0, 0, 0], **off)
        if rec.get("mass"):
            g.mass = rec["mass"] * c["volume"] / total
        set_surface(g, c, cls, friction)
    for k, _ in enumerate(rec["visuals"]):
        body.add_geom(name=f"{name}_vis{k}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"{prefix}vis{k}",
                      material=f"{prefix}mat{k}", contype=0, conaffinity=0, group=1, mass=0, **off)
    if at is None and not rec["collision_parts"]:          # a part with nothing to touch still needs a mass to move
        body.mass, body.inertia, body.explicitinertial = rec.get("mass") or 0.005, [1e-7] * 3, True


# Parts an asset glues on with a fixed joint that stay separate bodies (held by a weld), so they
# could come off later: caps, lids and stoppers. Other glued parts (labels, needles, shelves,
# straps) are fixed in place on their part, and cost nothing.
SEPARATE = re.compile(r"cap|lid|cover|cork|stopper|plug", re.I)


def part_kind(b: dict, fixed: bool, item: str = "") -> str:
    """How a part of a jointed item is built: "top" (the main body, a loose part, a welded cap),
    "joint" (on its hinge or slide) or "rigid" (fixed in place: its shapes join its parent part's
    body). Fixed too: buttons and switches of furniture (and of everything, with BUTTONS_MOVE
    off), and a free-spinning part (a hinge with no limits) whose asset gives it no damping
    (furniture's wheels and casters, a wrench's knurl): nothing would stop it, and so light a
    part spins by itself. One with damping (a drill's chuck, a ratchet's drive) turns."""
    if b.get("root") or b.get("free"):
        return "top"
    if b.get("weld"):
        caps = catalog.CAPS.get(item, ())
        return "top" if SEPARATE.search(b["name"]) or any(c in b["name"] for c in caps) else "rigid"
    if "range" not in b["joint"] and not joint_damping(b["joint"]):
        return "rigid"
    if BUTTON.search(b["name"]) and (fixed and item not in catalog.FURNITURE_CONTROLS_MOVE or not BUTTONS_MOVE):
        return "rigid"
    return "joint"


BUTTON = re.compile(r"switch|button|dial|knob", re.I)


def drive(j: dict) -> dict:
    """A joint's drive as the asset states it (USD Physics DriveAPI); a drive whose force is
    capped at zero does nothing."""
    d = j.get("drive") or {}
    return {} if d.get("max_force") == 0 else d


def joint_damping(j: dict) -> float:
    """The joint's damping: its asset's MuJoCo value, else its drive's."""
    return j.get("damping") or drive(j).get("damping") or 0.0
# A cap's weld: as quick as the lab's plastic contacts (wetlabsim.scene.MATERIALS) and nearly
# hard. With MuJoCo's defaults a light cap is pushed 3 mm (1.5 degrees) off its tube when the
# tube lies on it, and flies 10 cm off on impact.
CAP_SOLREF = [0.005, 1.0]
CAP_SOLIMP = [0.99, 0.999, 0.001, 0.5, 2.0]
# Buttons, dials and switches of hand-sized items move (a robot can press them); furniture's
# are fixed. False: fixed everywhere (each moving part costs a little speed).
BUTTONS_MOVE = True


def _add_jointed(world: mujoco.MjSpec, p: Placed, meta: dict, fixed: bool, mesh_cache: set):
    """An item with moving parts (tools/convert_simready.convert_articulated): its main body, the
    parts on hinge and slide joints nested under it, and its separate parts (a cap held by a weld,
    or loose)."""
    d = catalog.ASSETS / p.item
    bodies = meta["bodies"]
    pre = [f"{p.item}__b{i}_" for i in range(len(bodies))]
    if p.item not in mesh_cache:
        mesh_cache.add(p.item)
        for i, b in enumerate(bodies):
            for k, v in enumerate(b["visuals"]):         # weightless: a flat part (a label) is fine
                world.add_mesh(name=f"{pre[i]}vis{k}", file=str(d / v["mesh"]),
                               inertia=mujoco.mjtMeshInertia.mjMESH_INERTIA_SHELL)
            _add_materials(world, d, pre[i], b)
            for k, c in enumerate(b["collision_parts"]):
                if "mesh" in c:
                    world.add_mesh(name=f"{pre[i]}col{k}", file=str(d / c["mesh"]))
    cls = world.find_default("furniture" if fixed else "prop")
    T0 = _pose(p.pos, p.quat or yaw_quat(p.yaw))
    names = [f"obj_{p.uid}" if b.get("root") else f"obj_{p.uid}__{i}" for i, b in enumerate(bodies)]
    frame = [_pose(b["frame"][:3], b["frame"][3:]) for b in bodies]
    root = next(i for i, b in enumerate(bodies) if b.get("root"))
    kind = [part_kind(b, fixed, p.item) for b in bodies]

    host = list(names)        # the MuJoCo body each part's shapes are in
    inertia: dict = {}        # MuJoCo body -> [(its parts' stated inertial, where each sits in it)]

    def add(i, parent=None):
        """parent: (the body to build in, where the parent part's frame sits in it)."""
        b = bodies[i]
        at = None
        if kind[i] == "top":                         # placed in the world
            saved = (p.parts or {}).get(names[i])     # where it lay, relative to the main body
            T = T0 @ frame[i] if b.get("root") or not saved else T0 @ frame[root] @ _pose(*saved)
            body = world.worldbody.add_body(name=names[i], pos=list(T[:3, 3]), quat=_quat_of(T))
            if not (fixed and b.get("root")):
                body.add_freejoint(name=f"{names[i]}_joint")
        elif kind[i] == "rigid":                     # its shapes join its parent's body
            body, pat = parent
            at = pat @ np.linalg.inv(frame[b["parent"]]) @ frame[i]
            host[i] = host[b["parent"]]
        else:
            pbody, pat = parent
            T = pat @ _pose(b["pos"], b["quat"])
            body = pbody.add_body(name=names[i], pos=list(T[:3, 3]), quat=_quat_of(T))
            j = b["joint"]
            jt = body.add_joint(name=f"{names[i]}_{j['name']}", pos=j["pos"], axis=j["axis"],
                                type=mujoco.mjtJoint.mjJNT_HINGE if j["type"] == "hinge" else mujoco.mjtJoint.mjJNT_SLIDE)
            if "range" in j:
                jt.range, jt.limited = j["range"], mujoco.mjtLimited.mjLIMITED_TRUE
            for k in ("frictionloss", "armature"):
                if k in j:
                    setattr(jt, k, j[k])
            for key, f in catalog.JOINT_FRICTION.get(p.item, {}).items():
                if key in j["name"]:
                    jt.frictionloss = f
            for k in ("damping", "stiffness"):     # MuJoCo's linear coefficient
                if k in j:
                    getattr(jt, k)[0] = j[k]
            dr = drive(j)            # the asset's drive: a spring toward its target, and a damper
            if "stiffness" in dr and "stiffness" not in j:
                jt.stiffness[0] = dr["stiffness"]
                jt.springref = dr.get("target", 0.0)
            if "damping" in dr and "damping" not in j:
                jt.damping[0] = dr["damping"]
            for k in ("solref_friction", "solimp_friction", "solref_limit", "solimp_limit"):
                if k.replace("_", "") in j:          # the asset's own MuJoCo joint softness (Tripo)
                    setattr(jt, k, j[k.replace("_", "")])
            if dr.get("target_velocity") and dr.get("damping") and "damping" not in j:
                # a drive toward a speed (a toaster's timer): its force is damping x (target speed -
                # speed); the joint's damping gives the second part, this the constant first
                act = world.add_actuator(name=f"{names[i]}_drive", target=jt.name, trntype=mujoco.mjtTrn.mjTRN_JOINT,
                                         gaintype=mujoco.mjtGain.mjGAIN_FIXED, biastype=mujoco.mjtBias.mjBIAS_AFFINE)
                act.gainprm[0] = 0.0
                act.biasprm[0] = dr["damping"] * dr["target_velocity"]
                if dr.get("max_force") is not None:
                    act.forcelimited, act.forcerange = mujoco.mjtLimited.mjLIMITED_TRUE, [-dr["max_force"], dr["max_force"]]
        _part_geoms(world, body, names[i], b, pre[i], cls, meta.get("friction"), at)
        inertia.setdefault(id(body), (body, []))[1].append((b.get("inertial"), np.eye(4) if at is None else at))
        for c, cb in enumerate(bodies):
            if cb.get("parent") == i and kind[c] != "top":
                add(c, (body, np.eye(4) if at is None else at))

    for i in range(len(bodies)):
        if kind[i] == "top":
            add(i)
    for body, parts in inertia.values():          # as the asset states, where it states all of it
        set_inertia(body, parts)
    joint_of = {b["joint"]["name"]: f"{names[i]}_{b['joint']['name']}" for i, b in enumerate(bodies)
                if kind[i] == "joint"}
    for t in meta.get("tendons", []):               # the asset's tendons over its joints (Tripo's door closers)
        if t["type"] != "fixed" or not all(n in joint_of for n in t["joints"]):
            continue
        tn = world.add_tendon(name=f"obj_{p.uid}__{t['name']}")
        for n, c in zip(t["joints"], t["coef"]):
            tn.wrap_joint(joint_of[n], c)
        tn.stiffness[0] = t.get("stiffness", 0.0)
        tn.damping[0] = t.get("damping", 0.0)
        if "springlength" in t:
            tn.springlength = t["springlength"]
    for sc in meta.get("screws", []):
        # a screw thread (the asset's own unscrew clip): lift = ratio x turn, written as the turn
        # following the lift. MuJoCo sizes a joint equality's softness by its joints' weights, not
        # its coefficient: written the other way (lift from turn), the light lid's thread is so
        # soft that the lid sags off it
        if sc["slide"] in joint_of and sc["hinge"] in joint_of:
            # a hinge several slides drive (a pallet jack's lever linkage): one coupling each
            many = sum(1 for o in meta["screws"] if o["hinge"] == sc["hinge"]) > 1
            nm = f"{sc['slide']}_{sc['hinge']}" if many else sc["hinge"]
            world.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name=f"obj_{p.uid}__{nm}_thread",
                               objtype=mujoco.mjtObj.mjOBJ_JOINT, name1=joint_of[sc["hinge"]], name2=joint_of[sc["slide"]],
                               data=[0, 1 / sc["ratio"], 0, 0, 0] + [0] * 7)
    fitted = catalog.FITTED_PARTS.get(p.item, {})
    for part, into in fitted.items():               # a loose part fitted inside another (catalog.FITTED_PARTS)
        k = next(i for i, b in enumerate(bodies) if b["name"] == part)
        h = host[next(i for i, b in enumerate(bodies) if b["name"] == into)]
        sub = {k}
        while True:
            more = {i for i, b in enumerate(bodies) if b.get("parent") in sub and kind[i] != "top"} - sub
            if not more:
                break
            sub |= more
        for i in {host[i] for i in sub} - {h}:
            world.add_exclude(bodyname1=h, bodyname2=i)
    for i, b in enumerate(bodies):
        if kind[i] == "rigid":
            continue
        if b.get("parent") is not None and not b.get("collide") and host[b["parent"]] != host[i]:
            world.add_exclude(bodyname1=host[b["parent"]], bodyname2=names[i])   # jointed parts pass through each other
        if kind[i] == "joint":
            # nor with the parts further up its chain (a drawer on a runner in a cabinet): our convex
            # shapes are coarser than the asset's exact ones, and overlap where it slides inside
            a = bodies[b["parent"]].get("parent") if bodies[b["parent"]].get("joint") else None
            while a is not None:
                if host[a] != host[i]:
                    world.add_exclude(bodyname1=host[a], bodyname2=names[i])
                a = bodies[a].get("parent") if bodies[a].get("joint") else None
        if b.get("weld"):                            # held to its parent as the asset lays them out
            hp = next(k for k in range(len(bodies)) if names[k] == host[b["parent"]])
            rel = np.linalg.inv(frame[i]) @ frame[hp]
            world.add_equality(type=mujoco.mjtEq.mjEQ_WELD, objtype=mujoco.mjtObj.mjOBJ_BODY,
                               name=f"{names[i]}_weld", name1=names[i], name2=host[b["parent"]],
                               data=[0, 0, 0, *rel[:3, 3], *_quat_of(rel), 1, 0],
                               solref=CAP_SOLREF, solimp=CAP_SOLIMP)


def part_bodies(m: mujoco.MjModel, uid: str) -> list[int]:
    """A jointed item's bodies besides its main one (obj_<uid>__<i>)."""
    pre = f"obj_{uid}__"
    return [b for b in range(m.nbody) if m.body(b).name.startswith(pre)]


def save_parts(m: mujoco.MjModel, d: mujoco.MjData, p: Placed, root: int):
    """Remember a jointed item's joint positions, and where its separate parts lie relative to
    its main body, so a rebuild (or a move of the item) keeps them as they are."""
    parts = part_bodies(m, p.uid)
    if not parts:
        return
    joints, loose = {}, {}
    Tr = _pose(d.xpos[root], d.xquat[root])
    meta = catalog.meta(p.item)
    if m.body_jntnum[root] and meta.get("bodies"):   # the item's place is its own frame's, not its main body's
        fr = next(b["frame"] for b in meta["bodies"] if b.get("root"))
        Ta = Tr @ np.linalg.inv(_pose(fr[:3], fr[3:]))
        p.pos, p.quat = tuple(float(v) for v in Ta[:3, 3]), tuple(_quat_of(Ta))
    for b in parts:
        for j in range(m.body_jntadr[b], m.body_jntadr[b] + m.body_jntnum[b]):
            if m.jnt_type[j] in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
                joints[m.joint(j).name] = float(d.qpos[m.jnt_qposadr[j]])
            elif m.jnt_type[j] == int(mujoco.mjtJoint.mjJNT_BALL):     # a puzzle cube's cubelet
                a = m.jnt_qposadr[j]
                joints[m.joint(j).name] = [float(v) for v in d.qpos[a:a + 4]]
        if m.body_parentid[b] == 0:
            rel = np.linalg.inv(Tr) @ _pose(d.xpos[b], d.xquat[b])
            loose[m.body(b).name] = (tuple(float(v) for v in rel[:3, 3]), tuple(_quat_of(rel)))
    p.joints, p.parts = joints, loose


def scramble_cube(m: mujoco.MjModel, d: mujoco.MjData, uid: str, turns: int = 25, rng=None):
    """Mix up a puzzle cube (MuJoCo's 3x3x3 model) as a person would: random quarter turns of
    its faces, done exactly (no physics), so it starts as a fair, solvable puzzle. Each piece's
    joint is set to the rotation the turns gave it."""
    rng = rng or np.random.default_rng()
    core = m.body(f"obj_{uid}__core").id
    pieces = [b for b in range(m.nbody) if m.body_parentid[b] == core]
    home = {b: np.round(m.geom_pos[m.body_geomadr[b]] / np.abs(m.geom_pos[m.body_geomadr[b]]).max())
            for b in pieces}
    R = {b: np.eye(3) for b in pieces}
    last = None
    for _ in range(turns):
        while True:
            k, side = int(rng.integers(3)), int(rng.choice([-1, 1]))
            if (k, side) != last:
                break
        last = (k, side)
        q, Rm = np.zeros(4), np.zeros(9)
        mujoco.mju_axisAngle2Quat(q, np.eye(3)[k], float(rng.choice([-1, 1, 2])) * np.pi / 2)
        mujoco.mju_quat2Mat(Rm, q)
        Rm = Rm.reshape(3, 3)
        for b in pieces:
            if round(float((R[b] @ home[b])[k])) == side:
                R[b] = Rm @ R[b]
    for b in pieces:
        j = m.body_jntadr[b]
        a = m.jnt_qposadr[j]
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, R[b].ravel())
        if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_BALL:
            d.qpos[a:a + 4] = q
        else:                                         # a face centre: it only spins on its own axis
            v = np.zeros(3)
            mujoco.mju_quat2Vel(v, q, 1.0)
            d.qpos[a] = float(v @ m.jnt_axis[j])


def restore_joints(m: mujoco.MjModel, d: mujoco.MjData, p: Placed):
    """Joint positions as they were, or for a new item where its asset says they start (a puzzle
    cube starts mixed up, ready to be solved)."""
    if p.joints is None:
        meta = catalog.meta(p.item)
        if meta.get("scramble"):
            scramble_cube(m, d, p.uid)
            return
        for i, b in enumerate(meta.get("bodies") or []):
            if b.get("joint", {}).get("initial"):
                jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"obj_{p.uid}__{i}_{b['joint']['name']}")
                if jid >= 0:
                    d.qpos[m.jnt_qposadr[jid]] = b["joint"]["initial"]
        return
    for name, q in (p.joints or {}).items():
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
        if j >= 0:
            a = m.jnt_qposadr[j]
            if isinstance(q, (list, tuple)):
                d.qpos[a:a + len(q)] = q
            else:
                d.qpos[a] = q


def _add_mjcf(world: mujoco.MjSpec, p: Placed, meta: dict, fixed: bool = False):
    """An item that is a MuJoCo model of its own (asset.json "mjcf": the puzzle cube from MuJoCo's
    model gallery, LIBERO's objects), attached as it is: a body "obj_<uid>" at the item's place
    (free unless the item is fixed), the model's bodies inside it, named "obj_<uid>__<its body
    name>", with their own joints, shapes and materials. The item's place is its bottom centre;
    the model sits where asset.json "frame" puts it (LIBERO's turned upright), else centred on it.
    "free_damping" is the free joint's damping the model's source gives it (LIBERO's 0.0005), and
    "hide_collision" draws the model's collision shapes (group 0) only when debugging, as its
    source does."""
    child = mujoco.MjSpec.from_file(str(catalog.ASSETS / p.item / meta["mjcf"]))
    if meta.get("hide_collision"):
        for g in child.geoms:
            if g.group == 0 and (g.contype or g.conaffinity):
                g.group = 3
    body = world.worldbody.add_body(name=f"obj_{p.uid}", pos=list(p.pos), quat=list(p.quat or yaw_quat(p.yaw)))
    if not fixed:
        j = body.add_freejoint(name=f"obj_{p.uid}_joint")
        if meta.get("free_damping"):
            j.damping = [meta["free_damping"], 0, 0]      # as XML damping="..." sets it
    fr = meta.get("frame") or {"pos": [0, 0, meta["size"][2] / 2]}
    frame = body.add_frame(pos=fr["pos"], quat=fr.get("quat", [1, 0, 0, 0]))
    world.attach(child, frame=frame, prefix=f"obj_{p.uid}__")


def _add_item(world: mujoco.MjSpec, p: Placed, meta: dict, fixed: bool, mesh_cache: set):
    if meta.get("mjcf"):
        return _add_mjcf(world, p, meta, fixed)
    if meta.get("bodies"):
        return _add_jointed(world, p, meta, fixed, mesh_cache)
    d = catalog.ASSETS / p.item
    prefix = f"{p.item}__"
    if p.item not in mesh_cache:
        mesh_cache.add(p.item)
        for k, v in enumerate(meta["visuals"]):         # weightless: a flat part (a scale's display) is fine
            world.add_mesh(name=f"{prefix}vis{k}", file=str(d / v["mesh"]),
                           inertia=mujoco.mjtMeshInertia.mjMESH_INERTIA_SHELL)
        _add_materials(world, d, prefix, meta)
        for k, c in enumerate(meta["collision_parts"]):
            world.add_mesh(name=f"{prefix}col{k}", file=str(d / c["mesh"]))
    quat = p.quat or yaw_quat(p.yaw)
    body = world.worldbody.add_body(name=f"obj_{p.uid}", pos=list(p.pos), quat=list(quat))
    if not fixed:
        body.add_freejoint(name=f"obj_{p.uid}_joint")
    cls = world.find_default("furniture" if fixed else "prop")
    total_vol = sum(c["volume"] for c in meta["collision_parts"]) or 1.0
    mass = meta.get("mass") or 0.1
    for k, c in enumerate(meta["collision_parts"]):
        g = body.add_geom(name=f"obj_{p.uid}_col{k}", type=mujoco.mjtGeom.mjGEOM_MESH,
                          meshname=f"{prefix}col{k}", default=cls, group=3, rgba=[0, 0, 0, 0])
        g.mass = mass * c["volume"] / total_vol
        set_surface(g, c, cls, meta.get("friction"))
    for k, _ in enumerate(meta["visuals"]):
        body.add_geom(name=f"obj_{p.uid}_vis{k}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"{prefix}vis{k}",
                      material=f"{prefix}mat{k}", contype=0, conaffinity=0, group=1, mass=0)
    set_inertia(body, [(meta.get("inertial"), np.eye(4))])


def table_top(item: str) -> float:
    """Where a station's robot and objects stand: the item's height, or its worktop when a
    backsplash rises above it (catalog.WORKTOP)."""
    return float(catalog.WORKTOP.get(item, catalog.meta(item)["size"][2]))


def _quat_mul(a, b):
    q = np.zeros(4)
    mujoco.mju_mulQuat(q, np.asarray(a, float), np.asarray(b, float))
    return q


def _camera(world, name, pos, target, fovy, up=(0, 0, 1)):
    cam = world.worldbody.add_camera(name=name, pos=list(pos), fovy=fovy)
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [float(v) for v in S._look_at_axes(pos, target, up=up).split()]


OVERHEAD_FOVY = 55         # degrees (vertical); the picture is 640 x 480
OVERHEAD_IN_FRONT = 0.75   # how far in front of the robot the overhead camera hangs, room allowing
OVERHEAD_ABOVE = 1.0       # its least height above the table top
OVERHEAD_EDGE = 0.05       # kept this far in from the table's edge and below the walls' top


def overhead_pose(st: Station) -> tuple:
    """Where a one-arm robot's overhead camera hangs, worked out from its table's size: (x over
    the table, height above the top), in the station's frame. It looks down at the table's
    centre line. It hangs in front of the robot but always over the table, so it stays inside
    the station's work box (outside it, it would see the box's walls); and high enough that
    the table's whole length fits across the picture, but below the walls' top."""
    sx, sy = st.footprint()
    rx, _ = st.robot_xy
    if st.floor_arm:           # a big arm's: high over the middle of what it reaches
        return rx + st.floor_arm["ahead"], st.floor_arm["above"]
    x = min(rx + OVERHEAD_IN_FRONT, sx / 2 - OVERHEAD_EDGE)
    half_w = math.tan(math.radians(OVERHEAD_FOVY) / 2) * 640 / 480   # half width per metre away
    above = min(max(OVERHEAD_ABOVE, (sy / 2) / half_w), st.WALL_ABOVE - OVERHEAD_EDGE)
    return x, above


def _add_libero(world: mujoco.MjSpec, st: Station):
    """A LIBERO station: its task's whole room (playground.libero.room_spec) at the station's
    place and turn, LIBERO's Franka where LIBERO mounts it, and LIBERO's cameras as the robot's
    overhead and side cameras. Everything in the room is named "<station>/<LIBERO's name>"."""
    from . import libero as LB
    t = LB.task(st.task)
    ox, oy = st.room_origin()
    origin = st.to_world(ox, oy, 0.0)
    q0 = yaw_quat(st.yaw)
    frame = world.worldbody.add_frame(pos=list(origin), quat=list(q0))
    world.attach(LB.room_spec(t), frame=frame, prefix=st.prefix)
    c, s_ = math.cos(st.yaw), math.sin(st.yaw)
    for name, cam in LB.cameras(t).items():
        x, y, z = cam["pos"]
        world.worldbody.add_camera(name=st.prefix + name, pos=[origin[0] + c * x - s_ * y, origin[1] + s_ * x + c * y, z],
                                   quat=list(_quat_mul(q0, cam["quat"])), fovy=cam["fovy"])
    S.add_robot(world, st.robot, st.prefix + "robot_mount", st.prefix)


def libero_origin(st: Station):
    """Where a LIBERO station's room frame is in the world: (origin, yaw)."""
    ox, oy = st.room_origin()
    return st.to_world(ox, oy, 0.0), st.yaw


def add_station(world: mujoco.MjSpec, st: Station, cache: set):
    """A station's table, its robot on it, and the robot's overhead and side cameras."""
    if st.libero:
        return _add_libero(world, st)
    tmeta = catalog.meta(st.table_item)
    top = table_top(st.table_item)
    _add_item(world, Placed(table_uid(st), st.table_item, (st.pos[0], st.pos[1], 0.0), st.table_yaw),
              tmeta, True, cache)
    rx, ry = st.robot_xy
    mount = _quat_mul(yaw_quat(st.yaw + st.robot_turn), [float(v) for v in S.ROBOTS[st.robot]["mount_quat"].split()])
    world.worldbody.add_site(name=st.prefix + "robot_mount", pos=list(st.to_world(rx, ry, st.mount_z)),
                             quat=list(mount))
    _add_stands(world, st)
    c, s_ = math.cos(st.yaw), math.sin(st.yaw)
    if not S.ROBOTS[st.robot].get("sides"):   # a two-arm robot brings its own (ALOHA's four, the Duo's head)
        cx, above = overhead_pose(st)
        _camera(world, st.prefix + "overhead", st.to_world(cx, ry, top + above),
                st.to_world(cx if st.floor_arm else 0.0, ry, top), OVERHEAD_FOVY, up=(-c, -s_, 0))
    if st.floor_arm:           # the audience's side view stands back to take the whole arm in
        k = st.floor_arm["gap"] / 0.55
        _camera(world, st.prefix + "side", st.to_world(rx + 1.2 * k, ry - 3.0 * k, 1.1 * k + 0.6),
                st.to_world(rx + 0.6 * k, ry, 0.5 * k + 0.4), 45)
    else:
        mz = st.mount_z        # the robot's own height (its table top, unless it was raised)
        _camera(world, st.prefix + "side", st.to_world(rx + 1.75, ry - 1.3, mz + 0.8),
                st.to_world(rx + 0.4, ry, mz + 0.1), 45)
    S.add_robot(world, st.robot, st.prefix + "robot_mount", st.prefix)
    if not st.open:
        _add_walls(world, st)


def _add_stands(world: mujoco.MjSpec, st: Station):
    """A table arm's steel stand (Station.stands): a solid box under each base, from the table top
    or the floor up to the robot's mount, in a body of its own fixed to the world."""
    for k, ((x, y), hx, hy, lo, hi) in enumerate(st.stands()):
        body = world.worldbody.add_body(name=f"{st.prefix}stand{k}", pos=[x, y, (lo + hi) / 2],
                                        quat=list(yaw_quat(st.yaw + st.robot_turn)))
        body.add_geom(name=f"{st.prefix}stand{k}", type=mujoco.mjtGeom.mjGEOM_BOX,
                      size=[hx, hy, (hi - lo) / 2], rgba=STAND_RGBA, group=1)


WALL_GROUP = 5          # MuJoCo geom group of the work box's walls: hidden in MuJoCo's default
                        # view (groups 0-2) and in the page's 3D view; the robots' own cameras show it
WALL_RGBA = [0.86, 0.87, 0.89, 1.0]


def _add_walls(world: mujoco.MjSpec, st: Station):
    """The four walls of a station's work box: seen only by its robots' cameras and lidar (geom
    group WALL_GROUP), so a robot sees its own table and not the stations around it. A table
    arm's walls are not part of the physics (contype and conaffinity 0); a walking humanoid's
    room has solid walls, so what it sees is what stops it."""
    hx, hy, h = st.work_box()
    solid = st.roomy
    t = 0.05 if solid else 0.005
    for k, (lx, ly, ax, ay) in enumerate(((hx, 0, t, hy), (-hx, 0, t, hy), (0, hy, hx, t), (0, -hy, hx, t))):
        x, y, _ = st.to_world(lx, ly)
        world.worldbody.add_geom(name=f"{st.prefix}wall{k}", type=mujoco.mjtGeom.mjGEOM_BOX,
                                 size=[ax, ay, h / 2], pos=[x, y, h / 2], quat=list(yaw_quat(st.yaw)),
                                 group=WALL_GROUP, contype=int(solid), conaffinity=int(solid),
                                 rgba=WALL_RGBA)


def read_obj(path):
    """Our OBJs (tools/convert_simready.write_obj): v, vt with the same indices, triangles."""
    V, UV, F = [], [], []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                V.append(line.split()[1:4])
            elif line.startswith("vt "):
                UV.append(line.split()[1:3])
            elif line.startswith("f "):
                F.append([c.split("/")[0] for c in line.split()[1:4]])
    return (np.array(V, float).reshape(-1, 3), np.array(UV, float) if UV else None,
            np.array(F, int).reshape(-1, 3) - 1)


def _rot(quat):
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(quat, float))
    return R.reshape(3, 3)


def _add_soft(world: mujoco.MjSpec, p: Placed, meta: dict, mat_cache: set):
    """A soft item (catalog.SOFT): a MuJoCo flex, its own mesh drawn over it as a skin.

    The flex sits in a body "obj_<uid>" at the item's place; its vertices (a solid's 8 corner
    nodes, "obj_<uid>_<ix>_<iy>_<iz>") are bodies "obj_<uid>_<i>" that slide freely. Sheets and
    shells are 2D flexes (tools/build_soft.py's sim.obj), ropes 1D chains; in both the edges
    keep their length (edge equality constraints), so cloth folds but doesn't stretch. Solids
    are 3D flexes with MuJoCo's own elasticity, so they squash and spring back. Contact with everything else uses the
    item's own friction, as rigid items do; the flex doesn't collide with itself."""
    d = catalog.ASSETS / p.item
    soft = meta["soft"]
    quat = yaw_quat(p.yaw)
    R, pos = _rot(quat), np.asarray(p.pos, float)
    simV, _, simF = read_obj(d / soft["sim"])
    pts = " ".join(f"{v:.6f}" for v in simV.ravel())
    if soft["kind"] == "solid":
        lo, hi = simV.min(0), simV.max(0)
        c, size = (lo + hi) / 2, hi - lo
        shape = (f'type="grid" dim="3" count="2 2 2" spacing="{size[0]:.6f} {size[1]:.6f} {size[2]:.6f}" '
                 f'pos="{c[0]:.6f} {c[1]:.6f} {c[2]:.6f}" dof="trilinear"')
    elif soft["kind"] == "rope":
        elems = " ".join(f"{i} {i + 1}" for i in range(len(simV) - 1))
        shape = f'type="direct" dim="1" point="{pts}" element="{elems}"'
    else:
        shape = f'type="direct" dim="2" point="{pts}" element="{" ".join(str(i) for i in simF.ravel())}"'
    prop = prop_class()
    mu = meta.get("friction") or prop["friction"][0]
    material = (f'<elasticity young="{soft["young"]}" poisson="{soft["poisson"]}" damping="{soft["damping"]}"/>'
                if soft["kind"] == "solid" else '<edge equality="true"/>')
    child = mujoco.MjSpec.from_string(f"""<mujoco><worldbody>
      <body name="{p.uid}" pos="{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}" quat="{' '.join(f'{q:.8f}' for q in quat)}">
        <flexcomp name="{p.uid}" {shape} radius="{soft['radius']}" mass="{meta.get('mass') or 0.1}" group="3"
                  rgba="0.6 0.6 0.6 1">
          {material}
          <contact condim="3" friction="{mu} {prop['friction'][1]} {prop['friction'][2]}"
                   solref="{prop['solref'][0]} {prop['solref'][1]}" selfcollide="none"/>
        </flexcomp>
      </body></worldbody></mujoco>""")
    world.attach(child, frame=world.worldbody.add_frame(), prefix="obj_")
    prefix = f"{p.item}__"
    if p.item not in mat_cache:
        mat_cache.add(p.item)
        _add_materials(world, d, prefix, meta)
    simW = simV @ R.T + pos
    for k, v in enumerate(meta["visuals"]):
        V, UV, F = read_obj(d / v["mesh"])
        b = np.load(d / v["bind"])
        idx, w = b["idx"], b["w"]
        bones = np.unique(idx[w > 1e-6])
        vertid, vertweight = [], []
        for i in bones:
            rows, cols = np.nonzero((idx == i) & (w > 1e-6))
            vertid.append(rows.tolist())
            vertweight.append(w[rows, cols].tolist())
        names = ([f"obj_{p.uid}_{i >> 2}_{(i >> 1) & 1}_{i & 1}" for i in bones] if soft["kind"] == "solid"
                 else [f"obj_{p.uid}_{i}" for i in bones])
        world.add_skin(
            name=f"obj_{p.uid}_skin{k}", material=f"{prefix}mat{k}", group=1,
            vert=(V @ R.T + pos).ravel().tolist(), face=F.ravel().tolist(),
            texcoord=(np.c_[UV[:, 0], 1 - UV[:, 1]].ravel().tolist() if UV is not None else []),
            bodyname=names, bindpos=simW[bones].ravel().tolist(),
            bindquat=np.tile(quat, len(bones)).tolist(), vertid=vertid, vertweight=vertweight)


def soft_count(placed: list[Placed]) -> int:
    return sum(1 for p in placed if catalog.item(p.item)["soft"])


def build(placed: list[Placed], stations: list[Station], settings: dict | None = None) -> mujoco.MjModel:
    """Compile the lab: every station (table, robot, cameras) and every placed item, with the
    session's scene settings (playground/settings.py; none: the lab's defaults)."""
    cfg = settings or {}
    tok = _SETTINGS.set(cfg)
    tok2 = S.MATERIAL_CHANGES.set(cfg.get("materials") or {})
    try:
        return _build(placed, stations)
    finally:
        _SETTINGS.reset(tok)
        S.MATERIAL_CHANGES.reset(tok2)


def _build(placed: list[Placed], stations: list[Station]) -> mujoco.MjModel:
    world = mujoco.MjSpec.from_string(_world_xml())
    cache: set = set()
    for st in stations:
        add_station(world, st, cache)
    for p in placed:
        it = catalog.item(p.item)
        if it["soft"]:
            _add_soft(world, p, catalog.meta(p.item), cache)
        else:
            _add_item(world, p, catalog.meta(p.item), it["fixed"], cache)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return world.compile()


def default_scene() -> list[Placed]:
    return []


def default_stations() -> list[Station]:
    return [Station("st1", "franka", (0.0, 0.0), 0.0, "Robot 1")]
