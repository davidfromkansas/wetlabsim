"""How real places are laid out: short notes the scene planner and layout read for the kind of
place a request names (the scene builder's own reference; the robot AI never sees them).
Each note: the words that call it up, then what stands next to what and which way things face."""
from __future__ import annotations

import json
import os
import re
import urllib.request

NOTES = [
    (("kitchen", "breakfast", "cook", "galley"),
     "Kitchen: one fitted run along a wall: fridge at one end, then counter with the sink, then the "
     "range with its hood over it; wall cabinets belong over the counter. Small appliances (kettle, "
     "toaster, coffee maker) sit on that counter, not on the robot's. The robot's island or counter "
     "stands parallel to the run, about 1 m in front of it. A dining table with its chairs tucked in "
     "stands at one end, clear of the walkway. The bin stands at the end of the run."),
    (("dish", "restaurant", "cafe", "back room", "scullery"),
     "Dish room: one line in the order the dishes travel: bus cart with dirty dishes, the sink, "
     "the robot's table, the dishwasher, then the drying rack and clean shelving. The robot's table is "
     "part of that line, right beside the sink and dishwasher. Mop, bucket and wet-floor sign together "
     "in one corner."),
    (("wet lab", "biology", "molecular", "foundry", "pcr", "pipett", "reagent", "microscope", "sample"),
     "Wet lab: benches in parallel rows; the robot works at one bench with only its task's labware. A "
     "second bench right behind or beside it holds the instruments (centrifuge, vortex, balance, thermal "
     "cycler) in a row at its back edge. Tall units (fridge, freezer, cabinets, fume hood, biosafety "
     "cabinet) stand together along one wall. Sharps and waste containers go on a bench end or beside "
     "a bench leg, never out on the open floor. A stool is tucked under a bench."),
    (("cellculture", "biosafety", "incubator", "sterile", "tissue culture"),
     "Cell culture room: the biosafety cabinet is the work place: the robot's bench stands right "
     "at it or the task happens in front of it. The CO2 incubator stands next to the cabinet, its "
     "door opening towards the work place with a full door's width clear in front. The fridge and the "
     "liquid nitrogen dewar stand together a little apart as cold storage. Centrifuge and microscope "
     "on a side bench."),
    (("cell", "bin picking", "machine tend", "cnc", "weld", "assembly"),
     "Robot work cell: the robot's table in the middle; the conveyor runs along one side of the "
     "table, touching it, so the robot can reach the belt; the machine it tends stands on the other "
     "side with its door facing the robot. The fence stands round the back and sides about 1 m out, "
     "the door in the back. The control cabinet, signal tower and e-stop stand together just outside "
     "the fence by the door. Pallets, carts and shelving stand outside the fence in one tidy row."),
    (("pallet", "depallet", "end-of-line", "end of line", "packing", "stretch", "shrink"),
     "Palletizing or packing line: a straight flow: infeed conveyor ending at the robot's table, "
     "the pallet the robot builds (or unloads) on the floor right beside the table within reach, then "
     "the stretch wrapper, then finished wrapped pallets in a row. Pallet jack or forklift parked by "
     "the finished pallets. Boxes the robot handles are on the conveyor's end or the table, upright, "
     "all the same way round."),
    (("warehouse", "returns", "e-commerce", "fulfil", "sorting", "parcel", "logistics", "kitting"),
     "Warehouse station: inbound on one side, outbound on the other: the conveyor (or cart) of "
     "incoming things ends at one end of the robot's table; totes or bins for sorted things stand at "
     "the other end or on the table's far edge in a row; the roll cage or pallet for outgoing stands "
     "beside those. Shelving in a straight row behind the station, stocked. Scanner, tape and label "
     "maker together on the table's near corner."),
    (("server", "data cent", "rack", "network", "cable"),
     "Server room: racks side by side in one straight row, fronts the same way; the robot's table "
     "stands right in front of the rack it works on, so the ports are within reach; the cable tray "
     "runs along the row. A small desk with tools at the end of the row. Cooling unit at the other "
     "end."),
    (("workshop", "garage", "workbench", "repair", "screw", "tool"),
     "Workshop: the workbench against a wall with the pegboard or tool wall directly behind it, "
     "the tool cabinet beside it; machines (drill press, grinder, lathe) in a row along another wall; "
     "small bench machines stand on a bench, not on the floor. Hand tools laid out in a row on the "
     "bench, handles towards the robot, fasteners in a small tray."),
    (("hospital", "clinic", "pharmacy", "patient", "ward", "medic"),
     "Hospital room or pharmacy: the bed with its head against a wall, the bedside cabinet and IV "
     "pole at its head, the overbed table across it; supply cart and cabinets along the opposite "
     "wall. In a pharmacy the shelves stand in one row behind the counter and the robot works at the "
     "counter."),
    (("office", "desk", "mail", "print"),
     "Office: the desk with its chair tucked in, monitor and keyboard at the back of the desk; "
     "filing cabinet and bookshelf side by side against a wall behind; printer on its own stand next "
     "to them; the bin beside the desk."),
    (("shop", "store", "retail", "shelf stock", "grocery", "checkout"),
     "Shop: shelving units side by side in a straight aisle, stocked, labels facing the aisle; the "
     "checkout counter near the front with the till on it; baskets stacked by the entrance. The robot "
     "works in the aisle right at the shelf it stocks."),
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
