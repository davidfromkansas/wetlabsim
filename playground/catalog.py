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

TABS = ["Furniture", "Lab & Medical", "Kitchen", "Bins & Trays", "Toys & Basics", "Robots"]

# id, tab, label, Hugging Face folder, hollow, fixed
ITEMS = [
    ("table_packing", "Furniture", "Packing table", "table_packing_heavyduty_c01", True, True),
    ("workbench", "Furniture", "Workbench", "furniture_workbench_standard_d01", True, True),
    ("instrument_trolley", "Furniture", "Instrument trolley", "trolley_instrument_b01", True, True),
    ("lab_bottle", "Lab & Medical", "Lab bottle", "bottle_laboratory_a01", False, False),
    ("lab_bottle_tall", "Lab & Medical", "Small vial", "bottle_laboratory_b01", False, False),
    ("syringe", "Lab & Medical", "Syringe", "syringe_a01", False, False),
    ("medicine", "Lab & Medical", "Medicine box", "medicine_b01", False, False),
    ("sterilising_tray", "Lab & Medical", "Sterilising tray", "container_system_sterilising_b01", True, False),
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

# Robots: Menagerie models (wetlabsim/assets). The Franka is always in the scene.
ROBOTS = [
    {"id": "franka", "tab": "Robots", "label": "Franka Panda", "gripper": "Franka Hand"},
]

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
                        "mass": m["mass"], "thumb": f"/pg/thumb/{i}.png"})
    return out
