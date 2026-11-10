"""The object library: which NVIDIA SimReady assets the playground offers, in which tab.

Every item comes from NVIDIA's SimReady set on Hugging Face (nvidia/simready-assets) and
ships with its own MuJoCo physics (mass and collision shape). `hollow` items are containers:
they collide as convex pieces so things fit inside (see tools/convert_simready.py).
`fixed` items are furniture: they stand where they are dropped and don't move.
"""
from __future__ import annotations

import json
import pathlib

ASSETS = pathlib.Path(__file__).parent / "assets"

TABS = ["Furniture", "Lab & Medical", "Kitchen", "Bins & Trays", "Toys & Basics"]

# id, tab, label, Hugging Face folder, hollow, fixed
ITEMS = [
    ("table_packing", "Furniture", "Packing table", "table_packing_heavyduty_c01", True, True),
    ("workbench", "Furniture", "Workbench", "furniture_workbench_standard_d01", True, True),
    ("instrument_trolley", "Furniture", "Instrument trolley", "trolley_instrument_b01", True, True),
    ("lab_bench", "Furniture", "Stainless lab bench", "table_metal_stainless_a03", True, True),
    ("lab_bottle", "Lab & Medical", "Lab bottle", "bottle_laboratory_a01", False, False),
    ("lab_bottle_tall", "Lab & Medical", "Small vial", "bottle_laboratory_b01", False, False),
    ("syringe", "Lab & Medical", "Syringe", "syringe_a01", False, False),
    ("medicine", "Lab & Medical", "Medicine box", "medicine_b01", False, False),
    ("sterilising_tray", "Lab & Medical", "Sterilising tray", "container_system_sterilising_b01", True, False),
    ("kidney_dish", "Lab & Medical", "Kidney dish", "container_system_sterilising_c01", True, False),
    ("lab_bottle_small", "Lab & Medical", "Small lab bottle", "bottle_laboratory_c01", False, False),
    ("lab_bottle_m", "Lab & Medical", "Lab bottle, medium", "bottle_laboratory_a02", False, False),
    ("lab_bottle_l", "Lab & Medical", "Lab bottle, large", "bottle_laboratory_a03", False, False),
    ("lab_bottle_xl", "Lab & Medical", "Lab bottle, extra large", "bottle_laboratory_a04", False, False),
    ("glass_vial", "Lab & Medical", "Glass vial", "container_vial_glass_a01", False, False),
    ("glass_jar", "Lab & Medical", "Glass jar with lid", "container_jar_glass_silver_a01", False, False),
    ("syringe_small", "Lab & Medical", "Small syringe", "syringe_a03", False, False),
    ("forceps", "Lab & Medical", "Forceps", "instrument_forceps_a01", False, False),
    ("thermometer", "Lab & Medical", "Thermometer", "thermometer_fever_a01", False, False),
    ("disinfectant", "Lab & Medical", "Disinfectant bottle", "disinfectant_a01", False, False),
    ("glove_box", "Lab & Medical", "Box of gloves", "box_glove_a01", False, False),
    ("mug", "Kitchen", "Mug", "kitchenware_mug_a01", True, False),
    ("bowl", "Kitchen", "Bowl", "kitchenware_bowl_b01", True, False),
    ("cutting_board", "Kitchen", "Cutting board", "kitchenware_cuttingBoard_a01", False, False),
    ("apple", "Kitchen", "Apple", "food_produce_apple_b01", False, False),
    ("canned_food", "Kitchen", "Canned food", "food_processed_cannedFood_b01", False, False),
    ("cereal_box", "Kitchen", "Cereal box", "food_processed_boxedCereal_d01", False, False),
    ("crate", "Bins & Trays", "Blue crate", "crate_blue_a01", True, False),
    ("cube_box", "Bins & Trays", "Cardboard box", "box_cube_a01", False, False),
    ("waste_bin", "Bins & Trays", "Waste bin", "bin_waste_a01", True, False),
    ("golf_ball", "Toys & Basics", "Golf ball", "misc_golfBall_a01", False, False),
    ("rubiks_cube", "Toys & Basics", "Puzzle cube", "toys_rubiksCube_a01", False, False),
    ("pong_ball", "Toys & Basics", "Ping-pong ball", "misc_toy_pongPaddle_ball_a01", False, False),
]

# Robot stations: a Menagerie arm (wetlabsim/assets) on its own packing table. Specs are the
# makers' datasheet figures.
ROBOTS = [
    {"id": "franka", "label": "Franka Panda", "maker": "Franka Robotics", "gripper": "Franka Hand",
     "reach_mm": 855, "payload_kg": 3, "joints": 7, "thumb": "/pg/static/station_franka.png"},
    {"id": "ur5e", "label": "UR5e", "maker": "Universal Robots", "gripper": "Robotiq 2F-85",
     "reach_mm": 850, "payload_kg": 5, "joints": 6, "thumb": "/pg/static/station_ur5e.png"},
]


def robots() -> list[dict]:
    return ROBOTS


DEFAULT_TABLE = "table_packing"


def item(id_: str) -> dict:
    for i, tab, label, hf, hollow, fixed in ITEMS:
        if i == id_:
            return {"id": i, "tab": tab, "label": label, "hf": hf, "hollow": hollow, "fixed": fixed}
    raise KeyError(id_)


def meta(id_: str) -> dict:
    return json.loads((ASSETS / id_ / "asset.json").read_text())


def available() -> list[dict]:
    """Library items whose converted files are present."""
    out = []
    for i, tab, label, hf, hollow, fixed in ITEMS:
        f = ASSETS / i / "asset.json"
        if f.exists():
            m = json.loads(f.read_text())
            out.append({"id": i, "tab": tab, "label": label, "fixed": fixed, "size": m["size"],
                        "mass": m["mass"], "friction": m.get("friction"),
                        "collision": m.get("collision", ""), "thumb": f"/pg/thumb/{i}.png"})
    return out
