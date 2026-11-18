"""How real places are laid out: short notes the scene planner and layout read for the kind of
place a request names (the scene builder's own reference; the robot AI never sees them).
Each note: the words that call it up (each matches the start of a word: "medic" finds "medicine"),
then what stands next to what and which way things face."""
from __future__ import annotations

import json
import os
import re
import urllib.request

# How robot benchmark scenes and real places are laid out. The tabletop rules follow LIBERO's
# scenes (one table; the fixtures the task uses on it at its left and right ends, fronts to the
# robot; loose things in the middle in front of the robot) and RoboCasa's kitchens (the robot
# stands at a fitted counter run; the sink, stove, microwave and dishwasher it works with are
# in that run, the things it handles on the counter right beside them). Rooms follow the usual
# house plans of AI2-THOR / BEHAVIOR-style homes; work cells and labs follow real practice.
NOTES = [
    (("tabletop", "benchmark", "libero", "pick and place", "pick-and-place", "plain table", "simple",
      "test", "sort", "stack", "block", "cube", "puzzle", "chess", "clutter", "on a table", "a table with",
      "drawer cabinet", "shelf with", "everyday objects", "rearrange", "crammed"),
     "Tabletop task scene (as in LIBERO): everything is on the robot's one table. Loose things sit in "
     "a band 30 to 70 cm in front of the robot, spread across the middle, a hand's width apart. "
     "Containers they go into (bins, trays, baskets, bowls) stand open at the left and right ends of "
     "that band, all within reach, never behind the robot or past the far edge. Small fixtures the "
     "task uses (a cabinet with drawers, a stove, a microwave, a rack) stand on the same table at its "
     "left or right end, fronts turned to the robot. A plain or test request has nothing else: no "
     "room, no furniture on the floor."),
    (("kitchen", "breakfast", "cook", "galley", "pasta", "dinner", "groceries", "cupboard"),
     "Kitchen (as in RoboCasa): one fitted run along the back wall, fronts in a straight line: fridge "
     "at one end, base cabinets and counter, the sink in the counter, the dishwasher right next to "
     "the sink, then the range with the hood over it; wall cabinets hang above the counter. The robot "
     "works at that run or at an island parallel to it about 1 m in front; when the task uses the "
     "sink, stove, microwave or dishwasher, the robot's counter is right beside that one, and the "
     "things it handles sit on the counter next to it. Small appliances (kettle, toaster, coffee "
     "maker) sit on the counter, never on the floor. Fridge and oven doors need about 1 m clear in "
     "front: no table, chair or robot there. A dining table with chairs tucked in stands at one end."),
    (("dish", "dishwasher", "restaurant", "cafe", "back room", "scullery", "sink"),
     "Dish line: in the order the dishes travel: dirty dishes on the counter or a bus cart, the sink "
     "set into the counter at counter height, the robot's table, the dishwasher with its door to the "
     "robot, then the drying rack and clean shelving. The robot's table is part of that line, the sink "
     "and dishwasher at its ends within reach. A sink basin always sits in a counter, never on the "
     "floor. Mop, bucket and wet-floor sign together in one corner."),
    (("living room", "lounge", "sofa", "couch", "coffee table", "tv", "remote", "tidy", "pet", "cat ",
      "dog ", "home robot"),
     "Living room: the sofa against a wall facing the TV on its stand across the room; the coffee "
     "table between them, about 45 cm in front of the sofa; an armchair at one end of the coffee table "
     "angled towards it; side table and lamp at the sofa's arm; bookshelf flat against a wall, shelves "
     "facing the room. When the task tidies a table, that table is the robot's work surface and the "
     "clutter starts on it. Rug under the coffee table. Nothing stands in the walkway."),
    (("bedroom", "kid", "child", "toy", "bed", "nursery", "wardrobe"),
     "Bedroom: the bed with its head against a wall, a bedside table at one or both sides of the head; "
     "wardrobe and chest of drawers flat against another wall, fronts facing the room with space to "
     "open them; desk under a window with its chair tucked in. In a kid's room the toy box stands open "
     "at the foot of the bed or against a wall, toys scattered on the floor or rug in the middle and "
     "on the robot's low table. Laundry folded on the bed means the bed is the work surface, in "
     "reach, the laundry lying on the bed itself."),
    (("laundry", "washer", "washing machine", "dryer", "fold", "towel", "clothes"),
     "Laundry room: washer and dryer side by side against one wall, doors facing the room, a counter or "
     "folding table next to them; the laundry basket on the floor or table right in front of the "
     "washer. When the task loads the washer, it stands right at the robot's table, its door facing "
     "the robot and in reach. Drying rack and ironing board along another wall."),
    (("bathroom", "toilet", "shower", "bath"),
     "Bathroom: the toilet, the vanity with its basin and mirror, and the bath or shower all against "
     "walls; towels on a rail by the shower; bin under the vanity end. The robot works at the vanity "
     "counter; toiletries stand on it."),
    (("bartender", "bar counter", "cocktail", "pub", "coffee shop", "espresso", "barista", "bakery",
      "pastry", "counter service", "sushi", "vending", "making coffee", "make coffee", "latte"),
     "Bar, coffee shop or bakery: one long service counter; the robot works behind it on the staff "
     "side; the machine it uses (espresso machine, tap, ice maker) sits on the back counter right "
     "behind or beside it, in reach. Stools or the customer queue on the other side of the counter, "
     "lined up along it. Display case at one end of the counter, filled. Fridge and shelving on the "
     "back wall behind the robot. A conveyor (sushi) runs along the counter, touching it."),
    (("wet lab", "biology", "molecular", "foundry", "pcr", "pipett", "reagent", "microscope", "sample",
      "autoclave", "centrifuge", "tube", "beaker", "science", "chemistry"),
     "Wet lab: benches in parallel rows; the robot works at one bench with only its task's labware, "
     "racks and plates in a row in front of it. The instrument the task loads (centrifuge, thermal "
     "cycler, autoclave, plate sealer) sits on the robot's own bench at one end, lid or door towards "
     "the robot; a benchtop instrument never stands on the floor. Other instruments stand on a second "
     "bench behind or beside it. Tall units (fridge, freezer, cabinets, fume hood, biosafety cabinet) "
     "stand together along one wall, fronts facing the room. Sharps and waste at a bench end."),
    (("cellculture", "biosafety", "incubator", "sterile", "tissue culture"),
     "Cell culture room: the biosafety cabinet is the work place: the robot's bench stands right "
     "at it or the task happens in front of it. The CO2 incubator stands next to the cabinet, its "
     "door opening towards the work place with a full door's width clear in front. The fridge and the "
     "liquid nitrogen dewar stand together a little apart as cold storage. Centrifuge and microscope "
     "on a side bench."),
    (("cold room", "freezer", "storage shelf", "sample box", "cryo"),
     "Cold storage: the shelf or rack the task takes from stands right at one end of the robot's "
     "table, shelves facing the robot, the boxes on its lower shelves in reach; the fridge or freezer "
     "it fills stands at the other end, door facing the robot with space to swing open."),
    (("cell", "bin picking", "machine tend", "cnc", "weld", "assembly", "press", "moulding", "molding",
      "fixture", "gear", "inspection", "factory", "production"),
     "Robot work cell: the robot's table in the middle; the conveyor runs along one side of the "
     "table, touching it, its belt within reach, carrying the parts; the machine it tends stands at "
     "the other side, door facing the robot, its loading spot within reach. Parts start in a tote, "
     "tray or fixture on the table, not loose. The fence closes round the back and both sides about "
     "1 m out, in a continuous line, the door in the back; the front stays open. When the robot picks "
     "from the conveyor, the parts start on the belt itself, spaced along it within reach. Control cabinet, "
     "signal tower and e-stop just outside the fence by the door. Carts and shelving outside the fence "
     "in one tidy row."),
    (("pallet", "depallet", "end-of-line", "end of line", "packing", "stretch", "shrink"),
     "Palletizing or packing line: a straight flow: infeed conveyor ending at the robot's table, "
     "the pallet the robot builds (or unloads) on the floor right beside the table within reach, "
     "loaded boxes stacked squarely on it in layers (whatever the task takes off a pallet starts on "
     "the pallet, never on the floor or the bench), then the stretch wrapper, then finished wrapped "
     "pallets in a row. Pallet jack parked by the finished pallets. Boxes the robot packs into stand "
     "open on the conveyor's end or the table; the tape and labels on the table's near corner."),
    (("warehouse", "returns", "e-commerce", "fulfil", "sorting", "parcel", "logistics", "kitting", "tote", "payload", "onto the cart"),
     "Warehouse station: inbound on one side, outbound on the other: the conveyor (or cart) of "
     "incoming things ends at one end of the robot's table; totes or bins for sorted things stand open "
     "at the other end or along the table's far edge in a row; the roll cage or pallet for outgoing "
     "stands beside those. Shelving in a straight row behind the station, stocked. Scanner, tape and "
     "label maker together on the table's near corner. Things to pick start inside the source tote. "
     "A box the robot lifts onto a cart starts on the robot's table, the cart right beside it."),
    (("server", "data cent", "network", "cable"),
     "Server room: racks side by side in one straight row, fronts the same way; the robot's table "
     "stands right in front of the rack it works on, so the ports are within reach; the cable tray "
     "runs along the row. A small desk with tools at the end of the row. Cooling unit at the other "
     "end."),
    (("workshop", "garage", "workbench", "repair", "screw", "tool", "tire", "tyre", "car lift", "car door", "wheel"),
     "Workshop or garage: the workbench against a wall with the pegboard or tool wall directly behind "
     "it, the tool cabinet beside it; machines (drill press, grinder, lathe) in a row along another "
     "wall; small bench machines stand on a bench, not on the floor. Hand tools in a row on the bench, "
     "handles towards the robot, fasteners in a small tray. In a garage the car or lift is the centre: "
     "the robot's table and the wheel or parts stand right beside it. A pit crew: the car in the "
     "middle, each robot at its own wheel with the tyre, rim and wrench on its own table in reach."),
    (("hospital", "clinic", "pharmacy", "patient", "ward", "medic", "iv bag", "iv pole", "nurse", "syringe", "operating room", "surgical"),
     "Hospital room or pharmacy: the bed with its head against a wall, the bedside cabinet and IV "
     "pole at its head, the overbed table across it; supply cart and cabinets along the opposite "
     "wall. A medication cart stands right at the robot's table, drawers facing the robot. In a "
     "pharmacy the shelves stand in one row behind the counter and the robot works at the counter."),
    (("office", "desk", "mail", "print", "study", "book", "classroom", "school", "whiteboard"),
     "Office, study or classroom (as in LIBERO's study scenes): the desk with its chair tucked in, "
     "books, mug and desk caddy on the desk within reach of the robot; filing cabinet and bookshelf "
     "side by side against a wall behind; a whiteboard the robot writes on lies flat on its table or "
     "stands at the table's end with its writing side turned to the robot, otherwise it hangs on a "
     "wall facing the room; printer on its own stand; bin beside the desk."),
    (("shop", "store", "retail", "shelf stock", "grocery", "checkout", "restock", "supermarket"),
     "Shop: shelving units side by side in a straight aisle, stocked, labels facing the aisle; the "
     "robot works in the aisle right at the shelf it stocks, its shelves facing the robot and the gaps "
     "on shelves within reach; the stock it shelves starts in a crate or on the cart's top shelf at "
     "table height beside the robot, never low on the floor. The checkout counter near the "
     "front with the till and scanner on it, the queue lined up along it; baskets stacked by the "
     "entrance."),
    (("garden", "greenhouse", "plant", "windowsill", "potting"),
     "Plants: pots stand together on a bench, shelf or windowsill at counter height within the "
     "robot's reach, the watering can beside them; bags of soil and tools under the bench; a window or "
     "greenhouse wall right behind the pots."),
]


def note(*texts: str) -> str:
    """The notes (at most two) whose words turn up in the request or the room's name."""
    t = " ".join(texts).lower().replace("cell culture", "cellculture")   # not a robot "cell"
    hits = []
    for words, text in NOTES:
        n = sum(1 for w in words if re.search(r"\b" + re.escape(w) + (r"s?\b" if w == "cell" else ""), t))
        if n:
            hits.append((n, text))
    hits.sort(key=lambda h: -h[0])
    return "\n".join(text for _, text in hits[:2])


# ------------------------------------------------------------------ looked up on the web (Exa)
WEB_FILE = os.path.expanduser("~/.wetlab/scene_web_notes.json")


def exa_key() -> str:
    """The Exa search key: EXA_API_KEY in the environment, or a line EXA_API_KEY=... in
    ~/.wetlab/exa.env. Empty: no web lookup."""
    k = os.environ.get("EXA_API_KEY", "").strip()
    if k:
        return k
    try:
        for line in open(os.path.expanduser("~/.wetlab/exa.env")):
            if line.strip().startswith("EXA_API_KEY="):
                return line.strip().split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def web_note(room: str, timeout: float = 12.0) -> str:
    """How a place of this kind is really laid out, from a web search (Exa): a few sources'
    summaries. Only the kind of place is sent (the brief's room, e.g. "restaurant dish room"),
    never the person's request. Kept per kind of place, so each is looked up once. Empty with
    no key, or when the search fails."""
    room = re.sub(r"\s+", " ", room or "").strip().lower()[:80]
    key = exa_key()
    if not room or not key:
        return ""
    try:
        kept = json.load(open(WEB_FILE))
    except (OSError, ValueError):
        kept = {}
    if room in kept:
        return kept[room]
    body = {"query": f"how a {room} is physically laid out: where the equipment and furniture stand "
                     f"relative to each other and in what order along the workflow",
            "type": "auto", "numResults": 3,
            "contents": {"summary": {"query": "In 2 or 3 plain sentences, only the physical layout: what stands "
                                              "next to what, what lines the walls, what is kept within arm's "
                                              "reach of the work spot, and the order of things along the workflow."}}}
    req = urllib.request.Request("https://api.exa.ai/search", data=json.dumps(body).encode(),
                                 headers={"x-api-key": key, "Content-Type": "application/json",
                                          "User-Agent": "scene-builder"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.load(r).get("results") or []
    except Exception:  # noqa: BLE001      no network, a bad key, Exa down: the scene is built without it
        return ""
    text = "\n".join("- " + re.sub(r"\s+", " ", str(x.get("summary") or "")).strip()[:450]
                     for x in res if x.get("summary"))[:1400]
    if text:
        kept[room] = text
        try:
            os.makedirs(os.path.dirname(WEB_FILE), exist_ok=True)
            json.dump(kept, open(WEB_FILE, "w"))
        except OSError:
            pass
    return text
