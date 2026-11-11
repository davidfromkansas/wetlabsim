"""The object library: which NVIDIA SimReady assets the playground offers, in which tab.

Every item comes from AutoBio (in wetlabsim/assets/autobio; "autobio:..." items, built by
tools/build_autobio.py) or from NVIDIA's SimReady set (nvidia/simready-assets) or Tripo's SimReady
assets (VAST-AI/Tripo-Simready-Assets, folder names "tripo:...") on Hugging Face, and ships with
its own physics (mass, collision shapes, and moving parts on their joints). `hollow` items are containers:
they collide as convex pieces so things fit inside (see tools/convert_simready.py).
`fixed` items are furniture: they stand where they are dropped and don't move.
Items in SOFT are deformable: MuJoCo flexes instead of rigid bodies (see world.py and
tools/build_soft.py).
"""
from __future__ import annotations

import json
import pathlib

ASSETS = pathlib.Path(__file__).parent / "assets"

TABS = ["Furniture", "Lab equipment", "Lab & Medical", "Instruments", "PPE", "Tools", "Kitchen", "Bins & Trays", "Cleaning", "Electronics", "Toys & Basics", "Soft"]

# id, tab, label, Hugging Face folder, hollow, fixed
ITEMS = [
    ("table_packing", "Furniture", "Packing table", "table_packing_heavyduty_c01", True, True),
    ("workbench", "Furniture", "Workbench", "furniture_workbench_standard_d01", True, True),
    ("instrument_trolley", "Furniture", "Instrument trolley", "trolley_instrument_b01", True, True),
    ("lab_bench", "Furniture", "Stainless lab bench", "table_metal_stainless_a03", True, True),
    ("co2_incubator", "Furniture", "CO2 incubator", "tripo:co2_incubator_N08", False, True),
    ("autoclave", "Furniture", "Benchtop autoclave", "tripo:benchtop_autoclave_N10", False, True),
    ("lab_fridge", "Furniture", "Double-door fridge", "tripo:double_door_fridge_N14", False, True),
    ("refrigerator", "Furniture", "Refrigerator", "refrigerator_b01", False, True),
    ("labware_cabinet", "Furniture", "Labware cabinet", "labware_cabinet_a01", False, True),
    ("optical_table", "Furniture", "Optical table", "labware_table_thorlabs_a01", False, True),
    ("eyewash_station", "Furniture", "Eyewash station", "safety_eyewashStation_stand_selfContained_a01", False, True),
    ("wash_basin", "Furniture", "Wash basin", "washBasin_a01", True, True),
    ("drug_cabinet", "Furniture", "Drug cabinet", "cabinet_for_drugs_a01", True, True),
    ("fixture_cabinet", "Furniture", "Wall cabinet", "fixture_cabinet_b01", False, True),
    ("microcentrifuge", "Lab equipment", "Microcentrifuge", "tripo:microcentrifuge_N07", False, False),
    ("microscope", "Lab equipment", "Compound microscope", "tripo:compound_microscope_N06", False, False),
    ("balance", "Lab equipment", "Analytical balance", "tripo:analytical_balance_N09", False, False),
    ("infusion_pump", "Lab equipment", "Infusion pump", "pump_infusion_a01", False, False),
    ("uvc_lamp", "Lab equipment", "UV-C lamp", "lamp_uvc_a01", False, False),
    ("task_light", "Lab equipment", "Bench task light", "lighting_taskLight_adjustableArmBench_a01", False, False),
    ("tube_15ml", "Lab & Medical", "15 ml tube", "autobio:centrifuge_tube_15ml", False, False),
    ("tube_50ml", "Lab & Medical", "50 ml tube", "autobio:centrifuge_tube_50ml", False, False),
    ("microtube", "Lab & Medical", "1.5 ml screw tube", "autobio:centrifuge_1-5ml_screw", False, False),
    ("petri_dish", "Lab & Medical", "100 mm cell dish", "autobio:cell_dish_100", True, False),
    ("pipette", "Lab & Medical", "Pipette", "autobio:pipette", False, False),
    ("pipette_stand", "Lab & Medical", "Pipette stand", "autobio:pipette_stand", False, False),
    ("tube_rack", "Lab & Medical", "Tube rack", "autobio:centrifuge_10slot", True, False),
    ("rack_60well", "Lab & Medical", "60-well rack", "autobio:centrifuge_plate_60well", True, False),
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
    ("glass_jar_gold", "Lab & Medical", "Glass jar, gold lid", "container_jar_glass_gold_a01", False, False),
    ("glass_jar_black", "Lab & Medical", "Glass jar, black lid", "container_jar_glass_black_a01", False, False),
    ("corked_bottle", "Lab & Medical", "Corked bottle", "misc_bottle_corked_a01", False, False),
    ("disinfectant_2", "Lab & Medical", "Disinfectant bottle, 2", "disinfectant_b01", False, False),
    ("medicine_bottle", "Lab & Medical", "Medicine bottle", "medicine_c01", False, False),
    ("medicine_bottle_2", "Lab & Medical", "Medicine bottle, 2", "medicine_c02", False, False),
    ("medicine_bottle_3", "Lab & Medical", "Medicine bottle, 3", "medicine_c03", False, False),
    ("syringe_small", "Lab & Medical", "Small syringe", "syringe_a03", False, False),
    ("syringe_insulin", "Lab & Medical", "Insulin syringe", "syringe_insulin_a01", False, False),
    ("syringe_a02", "Lab & Medical", "Syringe, 2", "syringe_a02", False, False),
    ("syringe_a04", "Lab & Medical", "Syringe, 4", "syringe_a04", False, False),
    ("syringe_a05", "Lab & Medical", "Syringe, 5", "syringe_a05", False, False),
    ("syringe_insulin_2", "Lab & Medical", "Insulin syringe, 2", "syringe_insulin_a02", False, False),
    ("syringe_insulin_3", "Lab & Medical", "Insulin syringe, 3", "syringe_insulin_b01", False, False),
    ("inhaler", "Lab & Medical", "Inhaler", "device_inhaler_a01", False, False),
    ("lancing_device", "Lab & Medical", "Lancing device", "device_lancing_a01", False, False),
    ("instrument_storage", "Lab & Medical", "Instrument case", "instrument_storage_a01", True, False),
    ("blood_bag", "Lab & Medical", "Blood bag", "blood_bag_a01", False, False),
    ("funnel", "Lab & Medical", "Funnel with flexible spout", "serviceTool_funnel_flexibleSpout_a01", True, False),
    ("sterilising_box", "Lab & Medical", "Sterilising box", "container_system_sterilising_a02", True, False),
    ("sterilising_tray_deep", "Lab & Medical", "Deep sterilising tray", "container_system_sterilising_b02", True, False),
    ("sterilising_basket", "Lab & Medical", "Sterilising basket", "container_system_sterilising_d01", True, False),
    ("sterilising_container", "Lab & Medical", "Sterilising container", "container_system_sterilising_e01", True, False),
    ("instrument_tray", "Lab & Medical", "Instrument tray", "tray_sterilization_instrument_c02", True, False),
    ("forceps", "Instruments", "Forceps", "instrument_forceps_a01", False, False),
    ("scissors", "Instruments", "Surgical scissors", "instrument_scissors_a01", False, False),
    ("clamp", "Instruments", "Surgical clamp", "instrument_clamp_a01", False, False),
    ("caliper", "Instruments", "Caliper", "instrument_caliper_a01", False, False),
    ("bipolar_scissors", "Instruments", "Bipolar dissecting scissors", "instrument_bipolar_dissecting_scissors_a01", False, False),
    ("artery_forceps", "Instruments", "Artery forceps", "instrument_artery_forceps_b01", False, False),
    ("artery_forceps_curved", "Instruments", "Artery forceps, curved", "instrument_artery_forceps_curved_b01", False, False),
    ("bone_forceps", "Instruments", "Bone forceps", "instrument_bone_forceps_b01", False, False),
    ("nasal_forceps", "Instruments", "Nasal forceps", "instrument_nasal_forceps_b01", False, False),
    ("retractor", "Instruments", "Self-retaining retractor", "instrument_selfretaining_retractor_a01", False, False),
    ("surgical_stapler", "Instruments", "Surgical stapler", "stapler_surgical_a01", False, False),
    ("wire_cutters", "Instruments", "Wire cutters", "instrument_wire_cutters_b01", False, False),
    ("bone_clamp", "Instruments", "Bone clamp", "instrument_bone_clamp_b01", False, False),
    ("adams_pliers", "Instruments", "Adams pliers", "instrument_adams_pliers_b01", False, False),
    ("bone_rongeurs", "Instruments", "Bone rongeurs", "instrument_bone_rongeurs_b01", False, False),
    ("scalpel", "Instruments", "Scalpel handle", "instrument_scalpel_handle_a01", False, False),
    ("ligature_needle", "Instruments", "Ligature needle", "instrument_ligature_needle_a01", False, False),
    ("surgical_needle", "Instruments", "Surgical needle", "needle_surgical_a01", False, False),
    ("chemical_gloves", "PPE", "Chemical gloves", "ppe_gloves_chemical_a01", False, False),
    ("light_gloves", "PPE", "Light-duty gloves", "ppe_gloves_lightDuty_a01", False, False),
    ("goggles", "PPE", "Safety goggles", "ppe_eyeProtection_goggles_a01", False, False),
    ("respirator", "PPE", "Half-mask respirator", "ppe_respirator_halfMask_a01", False, False),
    ("face_mask", "PPE", "Medical face mask", "facemask_medical_a01", False, False),
    ("thermometer", "Lab & Medical", "Thermometer", "thermometer_fever_a01", False, False),
    ("disinfectant", "Lab & Medical", "Disinfectant bottle", "disinfectant_a01", False, False),
    ("glove_box", "Lab & Medical", "Box of gloves", "box_glove_a01", False, False),
    ("tool_scissors", "Tools", "Scissors", "tools_scissors_a01", False, False),
    ("pliers_combination", "Tools", "Combination pliers", "handTool_pliers_combination_a01", False, False),
    ("pliers_long_nose", "Tools", "Long-nose pliers", "handTool_pliers_long_nose_a01", False, False),
    ("pliers_long_nose_curved", "Tools", "Long-nose pliers, curved", "handTool_pliers_long_nose_curved_a01", False, False),
    ("pliers_diagonal", "Tools", "Diagonal cutting pliers", "handTool_pliers_diagonal_cutting_a01", False, False),
    ("pliers_groove_joint", "Tools", "Groove-joint pliers", "handTool_pliers_groove_joint_8in_b01", False, False),
    ("pliers_locking", "Tools", "Locking pliers", "handTool_pliers_locking_a01", True, False),
    ("knife_folding", "Tools", "Folding utility knife", "handTool_knife_foldingUtility_a01", False, False),
    ("knife_retractable", "Tools", "Retractable knife", "handTool_knife_retractableBlade_a01", False, False),
    ("wrench_adjustable", "Tools", "Adjustable wrench", "handTool_wrench_adjustable_a01", False, False),
    ("wrench_monkey", "Tools", "Monkey wrench", "handTool_wrench_monkey_a01", False, False),
    ("wrench_tap", "Tools", "Tap wrench", "handTool_wrench_tap_a01", False, False),
    ("ratchet", "Tools", "Ratchet", "handTool_ratchet_b01", False, False),
    ("torque_wrench", "Tools", "Torque wrench", "handTool_torque_wrench_b01", False, False),
    ("clamp_c", "Tools", "Clamp", "tool_clamp_c01", False, False),
    ("clamp_large", "Tools", "Large clamp", "tools_clamp_large_a01", False, False),
    ("hand_drill", "Tools", "Hand drill", "instrument_hand_drill_b01", False, False),
    ("drill", "Tools", "Power drill", "powerTool_drill_a01", False, False),
    ("drill_2", "Tools", "Power drill, 2", "powerTool_drill_b01", False, False),
    ("heat_gun", "Tools", "Cordless heat gun", "powerTool_heatGun_cordless_a01", False, False),
    ("cutting_tool", "Tools", "Cutting tool", "powerTool_cutting_tool_c01", False, False),
    ("mug", "Kitchen", "Mug", "kitchenware_mug_a01", True, False),
    ("bowl", "Kitchen", "Bowl", "kitchenware_bowl_b01", True, False),
    ("cutting_board", "Kitchen", "Cutting board", "kitchenware_cuttingBoard_a01", False, False),
    ("apple", "Kitchen", "Apple", "food_produce_apple_b01", False, False),
    ("canned_food", "Kitchen", "Canned food", "food_processed_cannedFood_b01", False, False),
    ("cereal_box", "Kitchen", "Cereal box", "food_processed_boxedCereal_d01", False, False),
    ("bottled_water", "Kitchen", "Bottled water", "food_beverage_bottledWater_b01", False, False),
    ("ketchup", "Kitchen", "Ketchup", "food_processed_ketchup_a01", False, False),
    ("jam", "Kitchen", "Jam jar", "food_processed_jam_a01", False, False),
    ("milk", "Kitchen", "Milk carton", "food_processed_milk_a01", False, False),
    ("shaker", "Kitchen", "Shaker", "kitchenware_shaker_a01", False, False),
    ("kettle", "Kitchen", "Kettle", "kitchenware_kettle_n01", False, False),
    ("kettle_2", "Kitchen", "Kettle, 2", "kitchenware_kettle_d01", False, False),
    ("kettle_3", "Kitchen", "Kettle, 3", "kitchenware_kettle_c01", False, False),
    ("kettle_4", "Kitchen", "Kettle, 4", "kitchenware_kettle_y01", False, False),
    ("toaster", "Kitchen", "Toaster", "appliance_toaster_a01", False, False),
    ("kitchen_scissors", "Kitchen", "Kitchen scissors", "utensils_scissors_a01", False, False),
    ("kitchen_scissors_2", "Kitchen", "Kitchen scissors, 2", "utensils_scissors_b01", False, False),
    ("kitchen_scissors_3", "Kitchen", "Kitchen scissors, 3", "utensils_scissors_e01", False, False),
    ("crate", "Bins & Trays", "Blue crate", "crate_blue_a01", True, False),
    ("cube_box", "Bins & Trays", "Cardboard box", "box_cube_a01", False, False),
    ("waste_bin", "Bins & Trays", "Waste bin", "bin_waste_a01", True, False),
    ("basket_mini", "Bins & Trays", "Mini plastic basket", "storage_basket_plastic_mini_a01", True, False),
    ("basket", "Bins & Trays", "Plastic basket", "storage_basket_plastic_a01", True, False),
    ("pail", "Bins & Trays", "Red pail", "pail_plastic_red_a02", True, False),
    ("pail_screw_top", "Bins & Trays", "Screw-top pail", "pail_screwTop_red_a02", True, False),
    ("first_aid_kit", "Bins & Trays", "First-aid kit", "safety_firstAidKit_box_plastic_a01", True, False),
    ("toolbox", "Bins & Trays", "Hard-case toolbox", "storage_toolbox_carry_hardCase_b01", True, False),
    ("case_a", "Bins & Trays", "Case", "case_a01", True, False),
    ("case_e", "Bins & Trays", "Case, 2", "case_e01", True, False),
    ("window_spray", "Cleaning", "Window spray", "cleaning_windowSpray_a01", False, False),
    ("soap_dispenser", "Cleaning", "Soap dispenser", "cleaning_soapDispenser_d01", False, False),
    ("soap_dispenser_2", "Cleaning", "Soap dispenser, 2", "cleaning_soapDispenser_e01", False, False),
    ("solvent_spray", "Cleaning", "Solvent spray", "consumable_spray_solvent_a01", False, False),
    ("eyeglasses", "PPE", "Eyeglasses", "misc_eyeGlasses_a01", False, False),
    ("eyeglasses_2", "PPE", "Eyeglasses, 2", "accessory_eyeglasses_a01", False, False),
    ("safety_glasses", "PPE", "Safety glasses", "ppe_eyeProtection_safetyGlasses_a01", False, False),
    ("ear_muffs", "PPE", "Ear muffs", "ppe_hearingProtection_earMuffs_a01", False, False),
    ("mouse", "Electronics", "Computer mouse", "computer_mouse_office_b01", False, False),
    ("barcode_scanner", "Electronics", "Barcode scanner", "computer_scanner_barcode_c01", False, False),
    ("multimeter", "Electronics", "Digital multimeter", "testingTool_multimeter_digital_b01", False, False),
    ("pressure_gauge", "Electronics", "Digital pressure gauge", "serviceTool_gauge_pressureDigitalRemote_a01", False, False),
    ("golf_ball", "Toys & Basics", "Golf ball", "misc_golfBall_a01", False, False),
    ("rubiks_cube", "Toys & Basics", "Puzzle cube", "toys_rubiksCube_a01", False, False),
    ("pong_ball", "Toys & Basics", "Ping-pong ball", "misc_toy_pongPaddle_ball_a01", False, False),
    ("cloth", "Soft", "Cleaning cloth", "cleaning_cloth_a01", False, False),
    ("towel", "Soft", "Microfibre towel", "consumable_microfiber_towel_wrinkled_b01", False, False),
    ("drape", "Soft", "Surgical drape", "drape_surgical_a01", False, False),
    ("sample_bag", "Soft", "Sample bag", "medical_sample_bag_a01", False, False),
    ("glove", "Soft", "Cloth glove", "ppe_gloves_cloth_a01", False, False),
    ("fuel_hose", "Soft", "Fuel hose", "consumable_hose_fuel_a01", False, False),
    ("hydraulic_hose", "Soft", "Hydraulic hose", "consumable_hose_hydraulic_a01", False, False),
    ("sponge", "Soft", "Kitchen sponge", "cleaning_sponge_b01", False, False),
    ("foam_brick", "Soft", "Foam brick", "primitives_brick_foam_a01", False, False),
]

# Items kept as one rigid body although their asset has moving parts: the puzzle cube's 26
# cubies are each hinged to its centre on a single axis (they can't turn as faces, and each
# costs speed).
SOLID = {"rubiks_cube"}

# Glued-on parts kept as separate caps (on a weld) whose asset doesn't name them as a cap, lid,
# cork or stopper (world.SEPARATE finds those): item -> part names.
CAPS = {"medicine_bottle": ["body_02"], "medicine_bottle_2": ["body_02"], "medicine_bottle_3": ["body_02"],
        "disinfectant_2": ["cup_01"]}

# Friction in moving parts, added to what the asset states (most NVIDIA assets state none, so
# hinges flop and plungers slide freely): item -> {joint name or part of it: MuJoCo frictionloss
# (N for a slide, N m for a hinge)}. Empty until the values are agreed; see world._add_jointed.
JOINT_FRICTION: dict[str, dict[str, float]] = {}

# Soft items, by how MuJoCo simulates them (all with the robot cell's implicitfast integrator):
#   sheet  a single-layer cloth through the item (2D flex): it folds and drapes, and its edges
#          don't stretch (edge equality constraints); a flat bag is one too;
#   shell  the item's own surface, simplified (2D flex), the same way: a glove or a bag goes limp;
#   rope   a chain along the item's centre line (1D flex) whose links don't stretch;
#   solid  a springy block (3D flex, its shape interpolated from its box's 8 corners) with
#          MuJoCo's own elasticity: Young's modulus (Pa), Poisson's ratio and damping (s). The
#          moduli are those of soft foams (about 10 kPa): a full-strength grip squeezes them by
#          a third to a half, and they spring back when let go.
# The item's own SimReady mesh is drawn over the flex as a MuJoCo skin. `nodes` sets how fine
# the simulated shape is (each node costs speed); see tools/build_soft.py.
SOFT = {
    "cloth": {"kind": "sheet", "nodes": 36},
    "towel": {"kind": "sheet", "nodes": 42},
    "drape": {"kind": "sheet", "nodes": 36},
    "sample_bag": {"kind": "sheet", "nodes": 30},
    "glove": {"kind": "sheet", "nodes": 40},
    "fuel_hose": {"kind": "rope", "nodes": 20},
    "hydraulic_hose": {"kind": "rope", "nodes": 20},
    "sponge": {"kind": "solid", "young": 1e4, "poisson": 0.2, "damping": 0.002},
    "foam_brick": {"kind": "solid", "young": 8e3, "poisson": 0.2, "damping": 0.002},
}

# Robot stations: a Menagerie arm (wetlabsim/assets) on its own packing table. Specs are the
# makers' datasheet figures.
ROBOTS = [
    {"id": "franka", "label": "Franka Panda", "maker": "Franka Robotics", "gripper": "Franka Hand",
     "reach_mm": 855, "payload_kg": 3, "joints": 7, "thumb": "/pg/static/station_franka.png"},
    {"id": "ur5e", "label": "UR5e", "maker": "Universal Robots", "gripper": "Robotiq 2F-85",
     "reach_mm": 850, "payload_kg": 5, "joints": 6, "thumb": "/pg/static/station_ur5e.png"},
    {"id": "aloha", "label": "ALOHA (two arms)", "maker": "Trossen Robotics", "gripper": "2 grippers",
     "reach_mm": 750, "payload_kg": 0.75, "joints": "2 × 6", "arms": 2, "thumb": "/pg/static/station_aloha.png"},
]


def robots() -> list[dict]:
    return ROBOTS


DEFAULT_TABLE = "table_packing"


def item(id_: str) -> dict:
    for i, tab, label, hf, hollow, fixed in ITEMS:
        if i == id_:
            return {"id": i, "tab": tab, "label": label, "hf": hf, "hollow": hollow, "fixed": fixed,
                    "soft": SOFT.get(i)}
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
                        "collision": m.get("collision", ""), "thumb": f"/pg/thumb/{i}.png",
                        "soft": i in SOFT})
    return out
