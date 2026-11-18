"""The object library: which NVIDIA SimReady assets the playground offers, in which tab.

Every item comes from AutoBio (in wetlabsim/assets/autobio; "autobio:..." items, built by
tools/build_autobio.py) or from NVIDIA's SimReady set (nvidia/simready-assets) or Tripo's SimReady
assets (VAST-AI/Tripo-Simready-Assets, folder names "tripo:...") or ForgeCAD's (ForgeCAD/simready-assets,
"forgecad:...") or NVIDIA's USDCraft-10K ("usdcraft:...", most of them listed in usdcraft_library.json)
on Hugging Face, and ships with
its own physics (mass, collision shapes, and moving parts on their joints). `hollow` items are containers:
they collide as convex pieces so things fit inside (see tools/convert_simready.py).
`fixed` items are furniture: they stand where they are dropped and don't move.
Items in SOFT are deformable: MuJoCo flexes instead of rigid bodies (see world.py and
tools/build_soft.py).
"""
from __future__ import annotations

import json
import os
import pathlib

# The converted objects. On Modal they come from the "wetlab-library" Volume at /library (hosting/app.py).
ASSETS = pathlib.Path(os.environ.get("WETLAB_ASSETS_DIR") or pathlib.Path(__file__).parent / "assets")

TABS = ["Furniture", "Lab equipment", "Lab & Medical", "Glassware", "Instruments", "PPE", "Tools", "Kitchen", "Bins & Trays", "Cleaning", "Electronics", "Toys & Basics", "Factory", "Car parts", "Garage", "Home", "Office", "Shops & Hotels", "Sports & Leisure", "Outdoor", "Soft", "LIBERO"]

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
    ("rubiks_cube", "Toys & Basics", "Puzzle cube", "mujoco:cube_3x3x3", False, False),
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
    # Nov 12 lab additions (glassware, Mecka WETLABS objects, AutoBio extras, in-house builds)
    ("beaker_500", "Glassware", "Beaker, 500 ml", "quiktech:qt_lab_000015", True, False),
    ("beaker_tall", "Glassware", "Beaker, tall form", "quiktech:qt_lab_000018", True, False),
    ("erlenmeyer", "Glassware", "Erlenmeyer flask", "quiktech:qt_lab_000016", True, False),
    ("round_flask", "Glassware", "Round-bottom flask", "quiktech:qt_lab_000017", True, False),
    ("measuring_cylinder", "Glassware", "Measuring cylinder", "quiktech:qt_lab_000013", True, False),
    ("reagent_bottle", "Glassware", "Reagent bottle", "quiktech:qt_lab_000002", False, False),
    ("beaker_50", "Glassware", "Beaker, 50 ml", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R482_glass_beaker/06_mini_50_ml_beaker", True, False),
    ("beaker_100_tall", "Glassware", "Beaker, 100 ml tall", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R482_glass_beaker/02_tall_form_100_ml_beaker", True, False),
    ("test_tube", "Glassware", "Glass test tube, capped", "inhouse:test_tube_16x150", True, False),
    ("test_tube_small", "Glassware", "Glass test tube, small", "inhouse:test_tube_13x100", True, False),
    ("stirring_rod", "Glassware", "Glass stirring rod", "inhouse:stirring_rod", False, False),
    ("stir_bar", "Glassware", "Magnetic stir bar", "inhouse:stir_bar", False, False),
    ("screw_top_jar", "Glassware", "Screw-top jar", "forgecad:screw_top_jar", False, False),
    ("rack_two_tier", "Lab & Medical", "Two-tier tube rack", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/01_two_tier_plastic_rack", True, False),
    ("rack_compact", "Lab & Medical", "Single-row tube rack", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/05_compact_single_row_rack", True, False),
    ("rack_compact_blue", "Lab & Medical", "Tube rack, blue", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/05_compact_single_row_rack", True, False),
    ("rack_compact_pink", "Lab & Medical", "Tube rack, pink", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/05_compact_single_row_rack", True, False),
    ("rack_compact_yellow", "Lab & Medical", "Tube rack, yellow", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/05_compact_single_row_rack", True, False),
    ("rack_compact_orange", "Lab & Medical", "Tube rack, orange", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/05_compact_single_row_rack", True, False),
    ("rack_compact_green", "Lab & Medical", "Tube rack, green", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/05_compact_single_row_rack", True, False),
    ("rack_wire", "Lab & Medical", "Wire tube rack", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R479_test_tube_rack/10_coated_wire_test_tube_rack_25_x_10_x_7_cm_in_whi", True, False),
    ("burette_stand", "Lab & Medical", "Burette stand", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R495_laboratory_ring_stand/04_tall_burette_stand", True, False),
    ("plate_24well", "Lab & Medical", "24-well plate", "inhouse:plate_24well", True, False),
    ("plate_24well_lid", "Lab & Medical", "24-well plate lid", "inhouse:plate_24well_lid", True, False),
    ("petri_dish_lid", "Lab & Medical", "100 mm cell dish lid", "inhouse:petri_dish_lid", True, False),
    ("petri_dish_60", "Lab & Medical", "60 mm Petri dish", "inhouse:petri_dish_60", True, False),
    ("petri_dish_60_lid", "Lab & Medical", "60 mm Petri dish lid", "inhouse:petri_dish_60_lid", True, False),
    ("target_mark", "Lab & Medical", "Target mark", "inhouse:target_mark", False, False),
    ("pipette_tip", "Lab & Medical", "Pipette tip", "autobio:pipette_tip", False, False),
    ("tip_box", "Lab & Medical", "Pipette tip box", "autobio:tip_box", True, False),
    ("pcr_plate", "Lab & Medical", "96-well PCR plate", "autobio:pcr_plate_96well", True, False),
    ("cryovial", "Lab & Medical", "Cryovial, 1.8 ml", "autobio:cryovial_1-8ml", False, False),
    ("tube_10ml", "Lab & Medical", "10 ml tube", "autobio:centrifuge_10ml", False, False),
    ("snap_tube", "Lab & Medical", "1.5 ml open tube", "autobio:centrifuge_1500ul_no_lid", False, False),
    ("otoscope", "Lab & Medical", "Otoscope", "device_otoscope_a01", False, False),
    ("bp_monitor", "Lab & Medical", "Blood pressure monitor", "device_blood_pressure_monitor_a01", False, False),
    ("vein_finder", "Lab & Medical", "Vein finder", "device_vein_finder_a01", False, False),
    ("nebulizer_mask", "Lab & Medical", "Nebulizer mask", "mask_nebulization_a01", False, False),
    ("spatula", "Instruments", "Lab spatula", "instrument_spatula_a01", False, False),
    ("electronic_scale", "Lab equipment", "Electronic scale", "quiktech:qt_lab_000008", False, False),
    ("ultrasonic_cleaner", "Lab equipment", "Ultrasonic cleaner", "quiktech:qt_lab_000004", True, False),
    ("hot_plate", "Lab equipment", "Hot plate stirrer", "inhouse:hot_plate", False, False),
    ("centrifuge_5430", "Lab equipment", "Benchtop centrifuge", "autobio:centrifuge_eppendorf_5430", False, False),
    ("mini_centrifuge", "Lab equipment", "Mini centrifuge", "autobio:centrifuge_tiangen_tgear_mini", False, False),
    ("thermal_cycler", "Lab equipment", "Thermal cycler", "autobio:thermal_cycler_biorad_c1000", False, False),
    ("thermomixer", "Lab equipment", "Thermal mixer", "autobio:thermal_mixer_eppendorf_c", False, False),
    ("vortex_mixer", "Lab equipment", "Vortex mixer", "autobio:vortex_mixer_genie_2", False, False),
    ("lab_oven", "Furniture", "Hot air oven", "quiktech:qt_lab_000005", False, True),
    ("flow_cabinet", "Furniture", "Laminar flow cabinet", "quiktech:qt_lab_000012", True, True),
    # Nov 13 articulated kitchen, lab and furniture assets (ForgeCAD, Palatial, NVIDIA): doors,
    # drawers, lids and knobs on the joints and limits their assets state
    ("chest_of_drawers", "Furniture", "Chest of drawers", "forgecad:chest_of_drawers", False, True),
    ("kitchen_base_cabinet", "Furniture", "Kitchen base cabinet", "forgecad:kitchen_base_cabinet", False, True),
    ("kitchen_wall_cabinet", "Furniture", "Kitchen wall cabinet", "forgecad:kitchen_wall_cabinet", False, True),
    ("washer", "Furniture", "Front-load washer", "forgecad:front_load_washer", False, True),
    ("range_oven", "Furniture", "Range oven", "forgecad:range_oven", False, True),
    ("french_door_fridge", "Furniture", "French-door fridge", "forgecad:refrigerator", False, True),
    ("gondola_shelf", "Furniture", "Gondola shelf", "forgecad:gondola_shelf", False, True),
    ("bakery_rack", "Furniture", "Bakery display rack", "palatial:D00326", False, True),
    ("metal_shelving", "Furniture", "Metal shelving unit", "palatial:D00661", False, True),
    ("workbench_drawers", "Furniture", "Workbench with drawers", "furniture_workbench_standard_e01", True, True),
    ("fridge_freezer", "Furniture", "Fridge freezer", "appliance_refrigerator_a01", True, True),
    ("kitchen_island", "Furniture", "Kitchen island", "fixture_island_a01", True, True),
    ("kitchenette", "Furniture", "Kitchenette module", "facilitySystem_kitchenette_module_a01", True, True),
    ("drug_cabinet_2", "Furniture", "Drug cabinet, 8 drawers", "cabinet_for_drugs_a02", True, True),
    ("lab_incubator", "Lab equipment", "Benchtop incubator", "forgecad:laboratory_incubator", False, False),
    ("plate_reader", "Lab equipment", "Microplate reader", "forgecad:microplate_reader", False, False),
    ("microplate_96", "Lab & Medical", "96-well microplate", "forgecad:microplate", False, False),
    ("air_fryer", "Kitchen", "Air fryer", "forgecad:air_fryer", False, False),
    ("microwave", "Kitchen", "Microwave oven", "forgecad:microwave_oven", False, False),
    ("stand_mixer", "Kitchen", "Stand mixer", "forgecad:stand_mixer", False, False),
    ("pop_up_toaster", "Kitchen", "Pop-up toaster", "forgecad:toaster", False, False),
    ("cookware_pot", "Kitchen", "Saucepan with lid", "forgecad:cookware_set", False, False),
    ("dish_rack", "Kitchen", "Dish drying rack", "forgecad:dish_drying_rack", False, False),
    ("food_container", "Kitchen", "Latching food container", "forgecad:latching_food_container", False, False),
    ("mug_white", "Kitchen", "Mug, white gloss", "forgecad:mug", False, False),
    ("espresso_machine", "Kitchen", "Espresso machine", "palatial:D00154", False, False),
    ("toaster_tray", "Kitchen", "Toaster with crumb tray", "palatial:D00866", False, False),
    ("camping_stove", "Kitchen", "Camping gas stove", "palatial:D00336", False, False),
    ("kitchen_scale", "Kitchen", "Kitchen scale", "palatial:D00505", False, False),
    ("knife_block", "Kitchen", "Knife block", "palatial:D00477", False, False),
    ("chef_knife", "Kitchen", "Chef's knife", "palatial:D00478", False, False),
    ("towel_holder", "Kitchen", "Paper towel holder", "palatial:D00587", False, False),
    ("paper_towel", "Kitchen", "Paper towel roll", "palatial:D00588", False, False),
    ("toast", "Kitchen", "Slice of toast", "palatial:D00865", False, False),
    # Nov 14 kitchen and wet lab showcase scenes: ForgeCAD appliances and kitchenware, NVIDIA
    # SimReady sink, tap, cookware, tableware, food, and USDCraft lab enclosures
    ("dishwasher", "Furniture", "Dishwasher", "forgecad:dishwasher", False, True),
    ("range_hood", "Furniture", "Range hood", "forgecad:range_hood", False, True),
    ("bar_stool", "Furniture", "Bar stool", "forgecad:gas_lift_bar_stool", False, True),
    ("chest_freezer", "Furniture", "Chest freezer", "forgecad:chest_freezer", False, True),
    ("sink_basin", "Kitchen", "Sink basin", "fixture_sink_basin_a01", True, False),
    ("kitchen_counter", "Furniture", "Kitchen counter", "fixture_counter_a01", False, True),
    ("countertop", "Furniture", "Countertop with cabinets", "tripo:countertop_C019", False, True),
    ("countertop_2", "Furniture", "Countertop with cabinets, 2", "tripo:countertop_C020", False, True),
    ("lab_stool", "Furniture", "Lab stool", "stool_mobile_padded_vinyl_a01", False, True),
    ("fume_hood", "Furniture", "Fume hood", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R480_fume_hood/09_fume_hood_with_a_base_cabinet_120_x_80_x_230_cm", True, True),
    ("biosafety_cabinet", "Furniture", "Biosafety cabinet", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R490_biosafety_cabinet/01_class_ii_biosafety_cabinet", True, True),
    ("faucet", "Kitchen", "Kitchen tap", "fixture_faucet_singleLever_a01", False, False),
    ("electric_kettle", "Kitchen", "Electric kettle", "forgecad:electric_kettle", False, False),
    ("drip_coffee_maker", "Kitchen", "Drip coffee maker", "forgecad:drip_coffee_maker", False, False),
    ("french_press", "Kitchen", "French press", "forgecad:french_press", False, False),
    ("rice_cooker", "Kitchen", "Rice cooker", "forgecad:rice_cooker", False, False),
    ("kitchen_tongs", "Kitchen", "Kitchen tongs", "forgecad:kitchen_tongs", False, False),
    ("pedal_bin", "Kitchen", "Pedal bin", "forgecad:pedal_trash_can", True, False),
    ("plate", "Kitchen", "Dinner plate", "forgecad:plate", False, False),
    ("cutlery_set", "Kitchen", "Cutlery set", "forgecad:cutlery_set", False, False),
    ("drinking_glass", "Kitchen", "Drinking glass", "forgecad:drinking_glass", True, False),
    ("tumbler", "Kitchen", "Glass tumbler", "dishware_glass_tumbler_a01", True, False),
    ("wine_glass", "Kitchen", "Wine glass", "dishware_glass_wine_a01", True, False),
    ("fork", "Kitchen", "Fork", "kitchenware_fork_a01", False, False),
    ("spoon", "Kitchen", "Spoon", "kitchenware_spoon_b01", False, False),
    ("table_knife", "Kitchen", "Table knife", "kitchenware_knife_a01", False, False),
    ("frying_pan", "Kitchen", "Frying pan", "kitchenware_pan_a01", True, False),
    ("spatula_kitchen", "Kitchen", "Spatula", "kitchenware_spatula_b01", False, False),
    ("egg", "Kitchen", "Egg", "food_egg_chicken_a01", False, False),
    ("bread_loaf", "Kitchen", "Bread loaf", "food_packaged_bread_loaf_a01", False, False),
    ("bagel", "Kitchen", "Bagel", "food_prepared_bagel_b01", False, False),
    ("croissant", "Kitchen", "Croissant", "food_prepared_croissant_a01", False, False),
    ("banana", "Kitchen", "Banana", "food_produce_banana_a01", False, False),
    ("orange", "Kitchen", "Orange", "food_produce_orange_a01", False, False),
    ("lemon", "Kitchen", "Lemon", "food_produce_lemon_a01", False, False),
    ("tomato", "Kitchen", "Tomato", "food_produce_tomato_a01", False, False),
    ("strawberry", "Kitchen", "Strawberry", "food_produce_strawberry_a01", False, False),
    ("spray_bottle", "Cleaning", "Trigger spray bottle", "forgecad:spray_bottle", False, False),
    ("reagent_reservoir", "Lab & Medical", "Reagent reservoir", "forgecad:reagent_reservoir", True, False),
    ("screw_cap_bottle", "Glassware", "Screw-cap bottle", "forgecad:screw_cap_bottle", False, False),
    ("sharps_box", "Lab & Medical", "Sharps box", "usdcraft:rigid/medical_outdoor_garden_transport_sports/R492_sharps_container/06_tabletop_mini_sharps_box", True, False),
    # Nov 15 the Factory and Car assembly scenes: ForgeCAD's industrial task kits and NVIDIA's
    # factory, car-part and garage assets
    ("task_board", "Factory", "Assembly task board", "forgecad:assembly_task_board", False, False),
    ("gear_kit", "Factory", "Gear meshing kit", "forgecad:gear_meshing_kit", False, False),
    ("nut_bolt_kit", "Factory", "Nut and bolt kit", "forgecad:nut_bolt_kit", False, False),
    ("peg_kit", "Factory", "Peg-in-hole kit", "forgecad:peg_in_hole_kit", False, False),
    ("planetary_gearbox", "Factory", "Planetary gearbox", "forgecad:planetary_gearbox", False, False),
    ("pulley_shaft_kit", "Factory", "Bearing, pulley and shaft kit", "forgecad:bearing_pulley_shaft_kit", False, False),
    ("toggle_clamp_plate", "Factory", "Toggle clamp fixture plate", "forgecad:toggle_clamp_fixture_plate", False, False),
    ("connector_pack", "Factory", "Data connector pack", "forgecad:data_connector_pack", False, False),
    ("breaker_board", "Factory", "DIN-rail breaker board", "forgecad:din_rail_breaker_board", False, False),
    ("ball_valve", "Factory", "Ball valve", "forgecad:ball_valve", False, False),
    ("gate_valve", "Factory", "Gate valve", "forgecad:gate_valve", False, False),
    ("bench_vise", "Factory", "Bench vise", "forgecad:bench_vise", False, False),
    ("bench_grinder", "Factory", "Bench grinder", "forgecad:bench_grinder", False, False),
    ("pegboard", "Factory", "Tool pegboard", "forgecad:pegboard", False, False),
    ("parts_cabinet", "Factory", "Parts drawer cabinet", "forgecad:parts_cabinet", False, False),
    ("load_carrier", "Factory", "Small load carrier", "forgecad:small_load_carrier", True, False),
    ("picking_bin", "Factory", "Bin of parts", "forgecad:bin_picking_bin", True, False),
    ("lid_tote", "Factory", "Attached-lid tote", "forgecad:attached_lid_tote", True, False),
    ("socket_set", "Factory", "Ratchet and socket set", "forgecad:ratchet_socket_set", False, False),
    ("wrench_set", "Factory", "Combination wrench set", "forgecad:combination_wrench_set", False, False),
    ("cantilever_toolbox", "Factory", "Cantilever toolbox", "forgecad:toolbox", False, False),
    ("test_bench", "Factory", "Controls test bench", "forgecad:articulation_test_bench", False, False),
    ("pallet_jack", "Factory", "Pallet jack", "forgecad:manual_pallet_jack", False, True),
    ("pallet_rack", "Factory", "Pallet rack bay", "forgecad:pallet_rack_bay", False, True),
    ("roller_conveyor", "Factory", "Roller conveyor", "conveyor_belt_a05", True, True),
    ("factory_workstation", "Factory", "Factory workstation", "workstation_factory_a01", False, True),
    ("modular_workbench", "Factory", "Workbench with cabinet", "furniture_workbench_modular_a01", False, True),
    ("machine_guard", "Factory", "Machine guard", "machineGuard_a01", False, False),
    ("welding_station", "Factory", "Welding power station", "powerTool_welding_station_a01", False, False),
    ("impact_wrench", "Factory", "Impact wrench", "powerTool_impact_wrench_a01", False, False),
    ("air_ratchet", "Factory", "Air ratchet", "handTool_air_ratchet_a01", False, False),
    ("shop_cart", "Factory", "Shop cart", "cart_mobile_a01", False, True),
    ("nut_m16", "Factory", "M16 nut", "factory_nut_m16_loose", False, False),
    ("nut_m8", "Factory", "M8 nut", "factory_nut_m8_loose", False, False),
    ("bolt_m8", "Factory", "M8 bolt", "factory_bolt_m8_loose", False, False),
    ("pallet", "Factory", "Pallet", "pallet_a01", False, True),
    ("cardboard_box", "Factory", "Cardboard box", "box_cardboard_a01", False, False),
    ("cardboard_box_flat", "Factory", "Cardboard box, flat", "box_cardboard_b01", False, False),
    ("safety_fence", "Factory", "Safety fence", "barrier_fence_metal_a02", False, True),
    ("forklift", "Factory", "Forklift", "vehicle_forklift_orange_a01", False, True),
    ("steel_drum", "Factory", "Steel drum", "drum_steel_a01", False, True),
    ("fire_extinguisher", "Factory", "Fire extinguisher", "fireExtinguisher_abc_a03", False, False),
    ("car_body", "Car parts", "Car body", "carFrame_car_frame_assembled_a01", False, True),
    ("car_hood", "Car parts", "Hood", "bodyPart_hood_a01", False, False),
    ("car_door", "Car parts", "Door, complete", "bodyPart_door_assembled_c01", False, False),
    ("door_panel", "Car parts", "Front door panel", "bodyPart_door_front_a01", False, False),
    ("windscreen", "Car parts", "Windscreen", "bodyPart_windscreen_a01", False, False),
    ("front_bumper", "Car parts", "Front bumper", "bodyPart_bumper_front_a01", False, False),
    ("headlight", "Car parts", "Headlight", "bodyPart_headLight_left_a01", False, False),
    ("side_mirror", "Car parts", "Side mirror", "bodyPart_car_side_mirror_a01", False, False),
    ("wiper_blades", "Car parts", "Wiper blades", "bodyPart_wiper_blades_a01", False, False),
    ("car_tire", "Car parts", "Tire", "wheelAssembly_tire_a01", False, False),
    ("wheel_rim", "Car parts", "Wheel rim", "wheelAssembly_wheel_rim_a01", False, False),
    ("brake_rotor", "Car parts", "Brake rotor", "brakeSystem_rotor_b01", False, False),
    ("brake_assembly", "Car parts", "Brake assembly", "brakeSystem_brakes_assembly_a01", False, False),
    ("brake_caliper", "Car parts", "Brake caliper", "brakeSystem_caliper_b01", False, False),
    ("brake_pad", "Car parts", "Brake pad", "brakeSystem_brake_pad_a01", False, False),
    ("wheel_hub", "Car parts", "Wheel hub", "suspension_wheelHubABS_assembly_a01", False, False),
    ("steering_wheel", "Car parts", "Steering wheel", "steeringSystem_steering_wheel_b01", False, False),
    ("car_seat", "Car parts", "Bucket seat", "interiorPart_bucket_seat_c01", False, False),
    ("gauge_cluster", "Car parts", "Gauge cluster", "interiorPart_dashboard_a01", False, False),
    ("car_battery", "Car parts", "Car battery", "electricalSystem_battery_a01", False, False),
    ("alternator", "Car parts", "Alternator", "electricalSystem_alternator_a01", False, False),
    ("spark_plug", "Car parts", "Spark plug", "engineComponent_spark_plug_b01", False, False),
    ("oil_filter", "Car parts", "Oil filter", "engineComponent_oil_filter_a01", False, False),
    ("air_filter_box", "Car parts", "Air filter box", "airSystem_air_filter_box_a01", True, False),
    ("air_filter", "Car parts", "Air filter", "airSystem_air_filter_a01", False, False),
    ("bulb_h7", "Car parts", "H7 headlight bulb", "consumable_lightBulb_h7_a01", False, False),
    ("fuse_mini", "Car parts", "Mini fuse", "consumable_fuse_mini_yellow_a01", False, False),
    ("radiator", "Car parts", "Radiator", "coolingSystem_radiator_a01", False, False),
    ("electric_motor", "Car parts", "Electric drive motor", "engineAssembly_electric_engine_a01", False, False),
    ("v8_engine", "Car parts", "V8 engine", "engineAssembly_v8_engine_a01", False, False),
    ("ev_charger", "Garage", "EV charging connector", "forgecad:ev_charging_connector", False, True),
    ("scissor_lift", "Garage", "Scissor lift", "vehicleSupport_scissor_lift_c01", False, True),
    ("floor_jack", "Garage", "Floor jack", "vehicleSupport_floor_jack_a01", False, False),
    ("jack_stand", "Garage", "Jack stand", "vehicleSupport_jack_stand_b01", False, False),
    ("car_dolly", "Garage", "Rolling car dolly", "vehicleSupport_rolling_dolly_a01", False, True),
    ("engine_stand", "Garage", "Engine stand", "serviceTool_engine_stand_a01", False, True),
    ("engine_crane", "Garage", "Engine crane", "serviceTool_engine_crane_a01", False, True),
    ("wheel_balancer", "Garage", "Wheel balancer", "testingTool_wheel_balancing_machine_a01", False, True),
    ("mechanic_cart", "Garage", "Mechanic's tool cart", "equipment_mechanic_tool_cart_g01", False, True),
    ("tool_cabinet", "Garage", "Rolling tool cabinet", "equipment_rolling_tool_cabinet_a01", False, True),
    ("tire_rack", "Garage", "Tire rack", "storage_tire_rack_a01", False, True),
    ("air_compressor", "Garage", "Air compressor", "equipment_airCompressor_a01", False, True),
    ("wheel_chock", "Garage", "Wheel chock", "vehicleSupport_wheel_chock_a01", False, False),
    ("engine_oil", "Garage", "Engine oil", "consumable_engine_oil_a01", False, False),
    # Nov 15 LIBERO's own objects and fixtures (Lifelong-Robot-Learning/LIBERO,
    # libero/libero/assets), its MuJoCo models attached as they are (tools/build_libero_objects.py)
    ("libero_alphabet_soup", "LIBERO", "Alphabet soup", "libero:stable_hope_objects/alphabet_soup/alphabet_soup.xml", False, False),
    ("libero_bbq_sauce", "LIBERO", "BBQ sauce", "libero:stable_hope_objects/bbq_sauce/bbq_sauce.xml", False, False),
    ("libero_butter", "LIBERO", "Butter", "libero:stable_hope_objects/butter/butter.xml", False, False),
    ("libero_chocolate_pudding", "LIBERO", "Chocolate pudding", "libero:stable_hope_objects/chocolate_pudding/chocolate_pudding.xml", False, False),
    ("libero_cookies", "LIBERO", "Cookies", "libero:stable_hope_objects/cookies/cookies.xml", False, False),
    ("libero_cream_cheese", "LIBERO", "Cream cheese", "libero:stable_hope_objects/cream_cheese/cream_cheese.xml", False, False),
    ("libero_ketchup", "LIBERO", "Ketchup", "libero:stable_hope_objects/ketchup/ketchup.xml", False, False),
    ("libero_macaroni_and_cheese", "LIBERO", "Macaroni and cheese", "libero:stable_hope_objects/macaroni_and_cheese/macaroni_and_cheese.xml", False, False),
    ("libero_milk", "LIBERO", "Milk", "libero:stable_hope_objects/milk/milk.xml", False, False),
    ("libero_orange_juice", "LIBERO", "Orange juice", "libero:stable_hope_objects/orange_juice/orange_juice.xml", False, False),
    ("libero_popcorn", "LIBERO", "Popcorn", "libero:stable_hope_objects/popcorn/popcorn.xml", False, False),
    ("libero_salad_dressing", "LIBERO", "Salad dressing", "libero:stable_hope_objects/salad_dressing/salad_dressing.xml", False, False),
    ("libero_new_salad_dressing", "LIBERO", "Salad dressing, new", "libero:stable_hope_objects/new_salad_dressing/new_salad_dressing.xml", False, False),
    ("libero_tomato_sauce", "LIBERO", "Tomato sauce", "libero:stable_hope_objects/tomato_sauce/tomato_sauce.xml", False, False),
    ("libero_akita_black_bowl", "LIBERO", "Black bowl", "libero:stable_scanned_objects/akita_black_bowl/akita_black_bowl.xml", False, False),
    ("libero_white_bowl", "LIBERO", "White bowl", "libero:stable_scanned_objects/white_bowl/white_bowl.xml", False, False),
    ("libero_red_bowl", "LIBERO", "Red bowl", "libero:stable_scanned_objects/red_bowl/red_bowl.xml", False, False),
    ("libero_plate", "LIBERO", "Plate", "libero:stable_scanned_objects/plate/plate.xml", False, False),
    ("libero_glazed_rim_porcelain_ramekin", "LIBERO", "Porcelain ramekin", "libero:stable_scanned_objects/glazed_rim_porcelain_ramekin/glazed_rim_porcelain_ramekin.xml", False, False),
    ("libero_chefmate_8_frypan", "LIBERO", "Frying pan", "libero:stable_scanned_objects/chefmate_8_frypan/chefmate_8_frypan.xml", False, False),
    ("libero_basket", "LIBERO", "Basket", "libero:stable_scanned_objects/basket/basket.xml", False, False),
    ("libero_simple_rack", "LIBERO", "Plate rack", "libero:stable_scanned_objects/simple_rack/simple_rack.xml", False, False),
    ("libero_red_coffee_mug", "LIBERO", "Red coffee mug", "libero:turbosquid_objects/red_coffee_mug/red_coffee_mug.xml", False, False),
    ("libero_porcelain_mug", "LIBERO", "Porcelain mug", "libero:turbosquid_objects/porcelain_mug/porcelain_mug.xml", False, False),
    ("libero_white_yellow_mug", "LIBERO", "White and yellow mug", "libero:turbosquid_objects/white_yellow_mug/white_yellow_mug.xml", False, False),
    ("libero_moka_pot", "LIBERO", "Moka pot", "libero:turbosquid_objects/moka_pot/moka_pot.xml", False, False),
    ("libero_wine_bottle", "LIBERO", "Wine bottle", "libero:turbosquid_objects/wine_bottle/wine_bottle.xml", False, False),
    ("libero_wine_rack", "LIBERO", "Wine rack", "libero:turbosquid_objects/wine_rack/wine_rack.xml", False, False),
    ("libero_black_book", "LIBERO", "Black book", "libero:turbosquid_objects/black_book/black_book.xml", False, False),
    ("libero_yellow_book", "LIBERO", "Yellow book", "libero:turbosquid_objects/yellow_book/yellow_book.xml", False, False),
    ("libero_desk_caddy", "LIBERO", "Desk caddy", "libero:turbosquid_objects/desk_caddy/desk_caddy.xml", False, False),
    ("libero_wooden_tray", "LIBERO", "Wooden tray", "libero:turbosquid_objects/wooden_tray/wooden_tray.xml", False, False),
    ("libero_white_storage_box", "LIBERO", "White storage box", "libero:turbosquid_objects/white_storage_box/white_storage_box.xml", False, False),
    ("libero_bowl_drainer", "LIBERO", "Bowl drainer", "libero:turbosquid_objects/bowl_drainer/bowl_drainer.xml", False, False),
    ("libero_dining_set_group", "LIBERO", "Dining set", "libero:turbosquid_objects/dining_set_group/dining_set_group.xml", False, False),
    ("libero_wooden_shelf", "LIBERO", "Wooden shelf", "libero:turbosquid_objects/wooden_shelf/wooden_shelf.xml", False, False),
    ("libero_wooden_two_layer_shelf", "LIBERO", "Two-layer wooden shelf", "libero:turbosquid_objects/wooden_two_layer_shelf/wooden_two_layer_shelf.xml", False, False),
    ("libero_microwave", "LIBERO", "Microwave", "libero:articulated_objects/microwave.xml", False, True),
    ("libero_flat_stove", "LIBERO", "Flat stove", "libero:articulated_objects/flat_stove.xml", False, True),
    ("libero_white_cabinet", "LIBERO", "White cabinet", "libero:articulated_objects/white_cabinet.xml", False, True),
    ("libero_wooden_cabinet", "LIBERO", "Wooden cabinet", "libero:articulated_objects/wooden_cabinet.xml", False, True),
    ("libero_short_cabinet", "LIBERO", "Short cabinet", "libero:articulated_objects/short_cabinet.xml", False, True),
    ("libero_slide_cabinet", "LIBERO", "Sliding cabinet", "libero:articulated_objects/slide_cabinet.xml", False, True),
    ("libero_short_fridge", "LIBERO", "Short fridge", "libero:articulated_objects/short_fridge.xml", False, True),
    ("libero_faucet", "LIBERO", "Faucet", "libero:articulated_objects/faucet.xml", False, True),
    ("libero_basin_faucet", "LIBERO", "Basin faucet", "libero:articulated_objects/basin_faucet.xml", False, True),
    ("libero_window", "LIBERO", "Window", "libero:articulated_objects/window.xml", False, True),
]

# NVIDIA's USDCraft-10K (Apache 2.0): one version of each of its kinds that the library didn't have
# yet, listed in usdcraft_library.json (picked by playground/tools/pick_usdcraft.py). All collide
# as convex pieces; furniture-size and larger ones stand where they are dropped.
USDCRAFT = json.loads((pathlib.Path(__file__).parent / "usdcraft_library.json").read_text())
ITEMS += [(u["id"], u["tab"], u["label"], "usdcraft:" + u["folder"], True, u["fixed"]) for u in USDCRAFT]

# The Nov 17 batch: whole SimReady sets from projectsim, Allsides, NdotLight, M-XR (Marso), Palatial,
# Yamato Protec and atech, plus NVIDIA items we hadn't added, listed in extra_library.json (picked by
# playground/tools/pick_extra.py). Items that failed to build or the drop test are left out there.
EXTRA = json.loads((pathlib.Path(__file__).parent / "extra_library.json").read_text())
ITEMS += [(u["id"], u["tab"], u["label"], (u["source"] + ":" if u["source"] != "nvidia" else "") + u["folder"],
           True, u["fixed"]) for u in EXTRA if not u.get("skip")]

# Triangles an item's visuals may keep before they are simplified (tools/convert_simready; the
# default is 60,000). Simplifying drops a texture, so items whose whole look is one texture keep
# all their detail (Palatial's are about 100,000 to 160,000 triangles).
# The Nov 17 batch (EXTRA) keeps its texture when simplified (MeshLab's texture-keeping decimation),
# so it stays at the default and the library stays small enough to ship.
_EXTRA_IDS = {u["id"] for u in EXTRA}
MAX_TRIS = {i[0]: 200_000 for i in ITEMS if i[3].startswith("palatial:") and i[0] not in _EXTRA_IDS}

# Furniture whose knobs, dials and buttons turn and press through their range (on other
# furniture they are fixed, world.part_kind): a cooker's hob knobs, a washer's programme dial
# The worktop of a counter whose backsplash stands higher than it (the asset's height is the
# backsplash's): the top of its worktop collider.
WORKTOP = {"countertop": 0.738, "countertop_2": 0.754}
# The roller conveyor carries things on its rollers, below its side rails: the top of a roller.
WORKTOP["roller_conveyor"] = 0.768

FURNITURE_CONTROLS_MOVE = {"range_oven", "washer", "kitchenette", "dishwasher", "range_hood"}

# One-part items that collide as each of the colliders their asset lays out (a shelf's boards, a
# mug's handle and walls), not one hull around them all (tools/convert_simready.convert)
PER_COLLIDER = {i[0] for i in ITEMS if i[3].startswith(("forgecad:", "palatial:"))}

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
    {"id": "piper", "label": "AgileX PiPER", "maker": "AgileX Robotics", "gripper": "AgileX gripper",
     "reach_mm": 626, "payload_kg": 1.5, "joints": 6, "thumb": "/pg/static/station_piper.png"},
    {"id": "crx30ia", "label": "FANUC CRX-30iA", "maker": "FANUC", "gripper": "Vacuum gripper",
     "reach_mm": 1756, "payload_kg": 30, "joints": 6, "thumb": "/pg/static/station_crx30ia.png"},
    {"id": "n220", "label": "Comau N-220", "maker": "Comau", "gripper": "Vacuum lifting frame",
     "reach_mm": 2670, "payload_kg": 220, "joints": 6, "thumb": "/pg/static/station_n220.png"},
    {"id": "aloha", "label": "ALOHA (two arms)", "maker": "Trossen Robotics", "gripper": "2 grippers",
     "reach_mm": 750, "payload_kg": 0.75, "joints": "2 × 6", "arms": 2, "thumb": "/pg/static/station_aloha.png"},
    {"id": "fr3_duo", "label": "FR3 Duo (two arms)", "maker": "Franka Robotics", "gripper": "2 × 2F-85",
     "reach_mm": 855, "payload_kg": 3, "joints": "2 × 7", "arms": 2, "thumb": "/pg/static/station_fr3_duo.png"},
    {"id": "g1", "label": "Unitree G1 (humanoid)", "maker": "Unitree Robotics", "gripper": "2 × Dex3-1 hands",
     "reach_mm": 500, "payload_kg": 3, "joints": "29 + 2 × 7", "arms": 2, "thumb": "/pg/static/station_g1.png"},
    {"id": "rby1", "label": "RB-Y1 (wheeled humanoid)", "maker": "Rainbow Robotics", "gripper": "2 × two-finger",
     "reach_mm": 600, "payload_kg": 3, "joints": "2 wheels + 6 + 2 × 7 + 2", "arms": 2, "thumb": "/pg/static/station_rby1.png"},
]


def robots() -> list[dict]:
    return ROBOTS


DEFAULT_TABLE = "table_packing"


# copies of one rack in the colours of the small polypropylene racks labs use (Mecka's WETLABS
# benchmark has blue, pink, yellow, orange and green ones): item -> its visuals' colour
RECOLOR = {"rack_compact_blue": [0.16, 0.45, 0.85, 1], "rack_compact_pink": [0.95, 0.5, 0.7, 1],
           "rack_compact_yellow": [0.98, 0.82, 0.2, 1], "rack_compact_orange": [0.97, 0.55, 0.15, 1],
           "rack_compact_green": [0.3, 0.75, 0.4, 1]}

# Racks: their holes need finer convex pieces to stay open (tools/convert_simready.FINE)
FINE_PIECES = {"rack_two_tier", "rack_compact", "rack_wire", *RECOLOR}
# Loose parts that sit fitted inside another part of their item, and don't collide with it (nor
# do the parts on their joints): item -> {part: the part it sits in}. The kitchenette's mini
# fridge stands in its housing's recess; our convex pieces of the housing are coarser than its
# shape and fill the recess (finer ones cost a lot of speed and still overlap the fridge by 2 cm).
FITTED_PARTS = {"kitchenette": {"refrigeratorBody_01_obj_00": "body_01_obj_00"}}

# Where each item comes from, as the library's source chip names it (by its folder's prefix).
SOURCE_NAMES = {"": "NVIDIA", "tripo": "Tripo", "quiktech": "QUIKTECH", "usdcraft": "USDCraft",
                "autobio": "AutoBio", "mujoco": "MuJoCo", "inhouse": "Built in-house",
                "forgecad": "ForgeCAD", "palatial": "Palatial", "libero": "LIBERO",
                "projectsim": "projectsim", "allsides": "Allsides", "ndotlight": "NdotLight", "mxr": "Marso",
                "yamato": "Yamato Protec", "atech": "atech"}


def source(hf: str) -> str:
    return SOURCE_NAMES[hf.rpartition(":")[0]]


def item(id_: str) -> dict:
    for i, tab, label, hf, hollow, fixed in ITEMS:
        if i == id_:
            return {"id": i, "tab": tab, "label": label, "hf": hf, "hollow": hollow, "fixed": fixed,
                    "soft": SOFT.get(i)}
    raise KeyError(id_)


def meta(id_: str) -> dict:
    return json.loads((ASSETS / id_ / "asset.json").read_text())


_AVAILABLE: list[dict] | None = None


def available() -> list[dict]:
    """Library items whose converted files are present. Read once per process: on Modal the files
    are on a Volume, where reading ~3,000 asset.json files per request would be slow."""
    global _AVAILABLE
    if _AVAILABLE is None:
        _AVAILABLE = _available()
    return _AVAILABLE


def _available() -> list[dict]:
    # index.json (written by tools/library.py push): every object's asset.json in one file, so the
    # Modal Volume is read once instead of ~3,000 times. Objects not in it are read one by one.
    idx = ASSETS / "index.json"
    index = json.loads(idx.read_text()) if idx.exists() else {}
    out = []
    for i, tab, label, hf, hollow, fixed in ITEMS:
        f = ASSETS / i / "asset.json"
        m = index.get(i)
        if m is None and f.exists():
            m = json.loads(f.read_text())
        if m is not None:
            out.append({"id": i, "tab": tab, "label": label, "fixed": fixed, "size": m["size"],
                        "mass": m["mass"], "friction": m.get("friction"),
                        "collision": m.get("collision", ""), "thumb": f"/pg/thumb/{i}.png",
                        "soft": i in SOFT, "source": source(hf)})
    return out
