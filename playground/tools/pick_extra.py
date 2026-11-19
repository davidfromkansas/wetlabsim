"""List the Nov 17 batch of SimReady objects for the library and write playground/extra_library.json.

    python -m playground.tools.pick_extra

Sources (all CC BY 4.0, NVIDIA SimReady packaging):
- projectsim (Kaedim): household items, many with screw caps, triggers and lids
- Allsides: 3D scans of real objects with weighed masses
- NdotLight: factory, tools and safety equipment
- M-XR (Marso): textured everyday objects, some with moving parts
- Palatial: the whole NV asset library (mostly kitchen), not only the 11 we had
- Yamato Protec: the maker's own fire extinguisher
- atech: small electronics modules
- NVIDIA SimReady: the items added since our Nov 11 scan, plus the loaded pallets, the small
  load carrier (KLT) and the cables we hadn't added

Every item in a set is kept, except folders the library already has. The library tab comes from
the source's own category where it has one (projectsim, Palatial), else from words in the name.
Whether an item is fixed in place is decided after the build from its size (tools/finish_extra.py).
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import urllib.request

from .. import catalog
from .fetch_simready import REPOS

OUT = pathlib.Path(catalog.__file__).parent / "extra_library.json"
PREFIX = {"projectsim": "ps", "allsides": "as", "ndotlight": "nd", "mxr": "mx", "palatial": "pl",
          "yamato": "ym", "atech": "at", "nvidia": "nv"}

# Words in an item's name -> library tab, first match wins
WORDS = [
    (r"placemat|place_?mat|cutting_?board|tableware|dishware|cookware|utensil|grocery", "Kitchen"),
    (r"pallet|klt|load_carrier|crate|warehouse|drum|barrier|bollard|cone|scaffold|conveyor|signal_tower|"
     r"gas_cylinder|jerrycan|anvil|cart|trolley|dolly|handtruck|wheelbarrow|rack|machine_guard|pegboard|"
     r"industrial|gear|bolt|nut|bracket|hinge|pipe|valve|coupling|anchor|housing|pump|lancable|cable|cord", "Factory"),
    (r"respirator|goggles|helmet|welding_shield|mask|extinguisher", "PPE"),
    (r"hammer|pliers|wrench|spanner|screwdriver|drill|saw|chisel|clamp|caliper|square|crowbar|pry_bar|"
     r"scraper|file|grinder|grinding|torch|tool|multimeter|caulking|ratchet|socket|pincers|cutter|level", "Tools"),
    (r"carburetor|brake|steering|tire|wheel|oil|antifreeze|degreaser|brake_fluid|motor", "Car parts"),
    (r"cleaner|bleach|detergent|cleaning|squeegee|brush|sponge|soap|disinfect|polish|stain|scouring|"
     r"descaler|drain|towel|cloth|napkin|bathproduct|spray|trash|waste|bin_", "Cleaning"),
    (r"atech_board|sensor|button|encoder|speaker|microphone|screen|camera|stepper|neopixel|usb|sd_card|"
     r"power_jack|aht20|icm|scd40|pir|load_cell|integrator|speaker|headphones|phone|mouse|printer|"
     r"disc_drive|preamplifier|noise_machine|amplifier", "Electronics"),
    (r"ball|racket|bat|skate|dumbbell|kickboard|dartboard|chessboard|guitar|drum|boot|shoe|sandal|"
     r"balance_board|boxing", "Sports & Leisure"),
    (r"toy|figurine|dollhouse|model_car|block|primitives|cube|skull", "Toys & Basics"),
    (r"garden|trowel|hoe|cultivator|flowerpot|planter|hose|watering|bird_feeder|shovel|shears|wagon|"
     r"water_timer|rock|geode|stone", "Outdoor"),
    (r"stool|chair|table|shelf|shelving|cabinet|couch|stand|desk|bookend|coat_rack|footstool|chest|"
     r"refrigerator|dishwasher|stove|hood|faucet|sink|lamp|socket|switch|mirror", "Furniture"),
    (r"book|frame|vase|candle|clock|painting|rug|doormat|decor|lantern|diya|plant|jewelry|cosmetic|"
     r"perfume|nail_polish|hair|face_cream|shampoo|bubble|massager|hat|sticker|eyeglasses", "Home"),
    (r"box|case|tray|basket|caddy|container|organizer|bucket|crate", "Bins & Trays"),
]

PROJECTSIM_TAB = {
    "food container": "Kitchen", "fruit": "Kitchen", "household chemical container": "Cleaning",
    "personal care container": "Home", "kitchen utensil": "Kitchen", "kitchen appliance": "Kitchen",
    "tableware": "Kitchen", "storage container": "Bins & Trays", "vegetable": "Kitchen",
    "food packaging": "Kitchen", "hand tool": "Tools", "furniture": "Furniture", "packaging": "Bins & Trays",
    "hardware": "Factory", "tool storage": "Tools", "home decor": "Home", "toy": "Toys & Basics",
    "garden tool": "Outdoor", "household": "Home", "industrial equipment": "Factory", "lighting": "Home",
    "musical instrument": "Sports & Leisure", "plumbing fixture": "Home"}

# Palatial's own class labels -> tab (everything else of theirs is kitchen)
PALATIAL_TAB = {"furniture": "Furniture", "book": "Home", "magazine": "Home", "frame": "Home",
                "work of art": "Home", "figurine": "Toys & Basics", "plant": "Home", "lamp": "Home",
                "candle": "Home", "clock": "Home", "pen": "Office", "paper": "Office", "textile": "Home",
                "physical tool": "Tools", "spherical body": "Toys & Basics", "bell": "Home"}

# NVIDIA folders we hadn't added: the loaded pallets, KLT, cables (plus everything new since Nov 11)
NVIDIA_WORDS = re.compile(r"^(pallet_assembly|pallet_composition|warehouse_klt|electrical_cable|equipment_extensionCord|"
                          r"equipment_cord_reel)")
NVIDIA_SINCE = "wuhanlanqi/simready-assets"   # a copy of NVIDIA's set as it was on Nov 11 (2,677 items)
SKIP_NVIDIA = re.compile(r"^modular_warehouse_")   # building walls, not objects

# Items the word rules put in the wrong tab
TAB_FIX = {"as_mask_9da2uznfyx": "Home", "ps_wheeled_trash_bin_green": "Cleaning", "mx_coiled_rope": "Garage"}

# Names that read badly when made from the folder name
LABELS = {"lancable": "LAN cable", "klt": "KLT", "tv": "TV", "usb": "USB", "pcr": "PCR", "led": "LED",
          "aht20": "AHT20", "icm40608": "ICM40608", "scd40": "SCD40", "tft": "TFT", "pir": "PIR",
          "st7735": "ST7735", "n20": "N20", "dc": "DC", "sd": "SD", "ya": "YA", "nx": "NX", "m4": "M4"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def _dirs(repo: str) -> list[str]:
    out, url = [], f"https://huggingface.co/api/datasets/{repo}/tree/main"
    while url:
        with urllib.request.urlopen(url, timeout=120) as r:
            out += json.load(r)
            m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
            url = m.group(1) if m else None
    return [x["path"] for x in out if x["type"] == "directory" and not x["path"].startswith(".")]


def _label(name: str) -> str:
    name = re.sub(r"_[A-Z0-9]{10}$", "", name)                 # Allsides' item id
    name = re.sub(r"^\d+_atech_", "", name)
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)           # camelCase
    words = [w for w in re.split(r"[_\-\s]+", name) if w]
    words = [w for w in words if not re.fullmatch(r"[a-z]\d\d", w.lower())]   # NVIDIA's variant code
    words = [LABELS.get(w.lower(), w.lower()) for w in words]
    s = " ".join(words)
    return s[:1].upper() + s[1:]


def _tab(name: str) -> str:
    n = name.lower()
    for pat, tab in WORDS:
        if re.search(pat, n):
            return tab
    return "Kitchen"


def _nvidia_label(folder: str) -> str:
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", folder).split("_")
    if len(words) > 2 and words[0].lower() in ("dishware", "utensil", "cookware", "grocery", "decor", "cleaning",
                                               "fixture", "furniture", "appliance", "misc", "hardware",
                                               "storage", "warehouse", "textileDecor", "food", "primitives",
                                               "signage", "equipment", "electrical"):
        words = words[1:]
    return _label("_".join(words))


def projectsim_categories() -> dict:
    text = _get(f"https://huggingface.co/datasets/{REPOS['projectsim']}/resolve/main/README.md").decode()
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\| `([^`]+)` \| ([^|]+) \|", text, re.M)}


def main(argv=None):
    extra = {u["id"] for u in catalog.EXTRA}       # this list itself, from an earlier run
    have = {i[3] for i in catalog.ITEMS if i[0] not in extra}
    labels = {i[2] for i in catalog.ITEMS if i[0] not in extra}
    rows = []

    def add(src: str, folder: str, label: str, tab: str):
        hf = f"{src}:{folder}" if src != "nvidia" else folder
        if hf in have:
            return
        have.add(hf)
        base, n = label, 2
        while label in labels:
            label, n = f"{base}, {n}", n + 1
        labels.add(label)
        id_ = PREFIX[src] + "_" + re.sub(r"[^a-z0-9]+", "_", folder.lower()).strip("_")
        rows.append({"id": id_, "source": src, "folder": folder, "label": label, "tab": TAB_FIX.get(id_, tab), "fixed": False})

    cats = projectsim_categories()
    for f in _dirs(REPOS["projectsim"]):
        add("projectsim", f, _label(f), PROJECTSIM_TAB.get(cats.get(f, ""), _tab(f)))
    for src in ("allsides", "ndotlight", "yamato", "atech"):
        for f in _dirs(REPOS[src]):
            if f in ("videos", "images"):
                continue
            label = "Fire extinguisher YA-10NX" if src == "yamato" else _label(f)
            add(src, f, label, "PPE" if src == "yamato" else ("Electronics" if src == "atech" else _tab(f)))
    import csv
    for r in csv.DictReader(io.StringIO(_get(f"https://huggingface.co/datasets/{REPOS['mxr']}/resolve/main/catalog/all.csv").decode())):
        add("mxr", r["asset"], r["name"][:1] + r["name"][1:].lower(), _tab(r["asset"]))
    import pyarrow.parquet as pq     # Palatial's catalog table
    pal = pq.read_table(io.BytesIO(_get(f"https://huggingface.co/datasets/{REPOS['palatial']}/resolve/main/data/catalog.parquet"))).to_pylist()
    for r in sorted(pal, key=lambda r: r["asset_id"]):
        tab = PALATIAL_TAB.get(r["class_label"], "Kitchen")
        add("palatial", r["asset_id"], r["name"][:1].upper() + r["name"][1:].lower(), tab)
    before = set(_dirs(NVIDIA_SINCE))
    for f in _dirs(REPOS["nvidia"]):
        if SKIP_NVIDIA.match(f):
            continue
        if f not in before or NVIDIA_WORDS.match(f):
            add("nvidia", f, _nvidia_label(f), _tab(f))
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    import collections
    print(len(rows), "items;", dict(collections.Counter(r["source"] for r in rows)))
    print(dict(collections.Counter(r["tab"] for r in rows)))


if __name__ == "__main__":
    main()
