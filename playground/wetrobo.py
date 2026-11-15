"""WetRobo benchmark stations (Oikawa et al., "WetRobo: A Reproducible Robot Kit for Coding
Agents in Biological Laboratories", arXiv 2609.18435; github.com/tsudalab/WetRobo).

WetRobo ships one kit (an arm, a benchtop incubator, a capped reagent bottle and a lidded
Petri dish) to different labs, and has a coding agent do the same tasks in each. Here the kit is
the playground's own items, and there are two labs: Lab X, a stainless lab bench, and
Lab Y, a wooden packing table of another height, with the kit placed differently and
other things around it. A station is one task in one lab; scores put the labs side by side.

The AI gets what every playground run gets (the robot's manuals, its cameras and sensors);
WetRobo's teleoperated demos and AGENTS.md file are left out on purpose: the playground's
AI only gets the datasheet, the cameras and the robot's own state.

A task's check reads the kit's own joints and bodies (MuJoCo state, checked every 0.1 s during a
run);
a run passes the moment its goal holds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco
import numpy as np

PAPER = "https://arxiv.org/abs/2609.18435"
INCUBATOR, BOTTLE, DISH, LID = "lab_incubator", "screw_cap_bottle", "petri_dish_60", "petri_dish_60_lid"
KIT = (INCUBATOR, BOTTLE, DISH, LID)
DOOR_OPEN = math.radians(60)          # the incubator door: open this far or more
CAP_OFF = 0.95                        # the cap: unscrewed this share of its thread or more
LID_SEAT = 0.007                      # the lid on its dish: its bottom edge this far above the dish's
LID_DROP = 0.02                       # the dish and lid: no further below the table top than this
LID_AWAY = 0.03                       # the lid: this far from its seat or more, and not touching the dish


@dataclass(frozen=True)
class Task:
    id: str
    title: str          # short name, for chips and tables
    language: str       # what the AI is told
    goal: tuple         # the check's parts, in plain words


TASKS = {t.id: t for t in (
    Task("lid", "Lift the Petri dish lid", "Lift the lid off the Petri dish.",
         ("The lid is off the dish and not touching it", "The dish and the lid are still on the table")),
    Task("cap", "Remove the bottle cap", "Remove the cap from the reagent bottle.",
         ("The bottle's cap is unscrewed all the way",)),
    Task("incubator", "Open the incubator door", "Open the incubator door.",
         ("The incubator door is open at least 60°",)),
)}

# The two labs: (kind, label, blurb). Their tables and layouts are world.KINDS entries.
LABS = {
    "x": ("wetrobo_x", "Lab X", "A stainless lab bench; the incubator ahead, at the bench's far end."),
    "y": ("wetrobo_y", "Lab Y", "A taller wooden table; the kit in other places, other things around."),
}
KIND_LAB = {k: lab for lab, (k, _, _) in LABS.items()}


def task(task_id: str) -> Task:
    if task_id not in TASKS:
        raise KeyError(task_id)
    return TASKS[task_id]


def lab_of(kind: str) -> str:
    return KIND_LAB.get(kind, "")


def kit_joints(m: mujoco.MjModel, uids_items: list[tuple[str, str]], top: float | None = None) -> dict:
    """The kit's joints in a compiled lab, from the station's items [(uid, item), ...]:
    {"door": qpos address and range, "cap": ..., "dish": body id, "lid": body id}. Missing ones
    are left out. top: the table top's height, for the checks that need it."""
    out = {} if top is None else {"top": float(top)}
    for uid, item in uids_items:
        if item in (DISH, LID):
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"obj_{uid}")
            if b >= 0:
                out.setdefault("dish" if item == DISH else "lid", b)
            continue
        for j in range(m.njnt):
            n = m.joint(j).name
            if not n.startswith(f"obj_{uid}__"):
                continue
            if item == INCUBATOR and n.endswith("_DoorOpen") and "door" not in out:
                out["door"] = (int(m.jnt_qposadr[j]), tuple(m.jnt_range[j]))
            if item == BOTTLE and n.endswith("_cap_turn") and "cap" not in out:
                out["cap"] = (int(m.jnt_qposadr[j]), tuple(m.jnt_range[j]))
    return out


def check(t: Task, joints: dict, d: mujoco.MjData) -> list[bool]:
    """Each part of the task's goal: whether it holds now."""
    if t.id == "incubator":
        j = joints.get("door")
        return [bool(j) and abs(float(d.qpos[j[0]])) >= DOOR_OPEN]
    if t.id == "cap":
        j = joints.get("cap")
        if not j:
            return [False]
        lo, hi = j[1]
        return [bool(float(d.qpos[j[0]]) >= lo + CAP_OFF * (hi - lo))]
    if t.id == "lid":
        dish, lid = joints.get("dish"), joints.get("lid")
        if dish is None or lid is None:
            return [False, False]
        m = d.model
        touching = any({int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])} == {dish, lid} and c.dist <= 0
                       for c in d.contact[:d.ncon])
        seat = d.xpos[dish] + d.xmat[dish].reshape(3, 3) @ np.array([0.0, 0.0, LID_SEAT])
        off = not touching and float(np.linalg.norm(d.xpos[lid] - seat)) >= LID_AWAY
        # still on the table: the dish standing on it, the lid on it or held above it (not dropped off)
        top = joints.get("top")
        kept = top is not None and abs(float(d.xpos[dish][2]) - top) < LID_DROP and \
            float(d.xmat[dish].reshape(3, 3)[2, 2]) > 0.9 and float(d.xpos[lid][2]) > top - LID_DROP
        return [bool(off), bool(kept)]
    return [False] * len(t.goal)


def done_when(t: Task) -> str:
    return ", and ".join([t.goal[0], *(g[0].lower() + g[1:] for g in t.goal[1:])]) + "."


def board(rows: list[dict]) -> dict:
    """Scores, model by model: passed / tried for each task in each lab (every run counts),
    and the totals per lab."""
    by: dict[str, dict] = {}
    for r in rows:
        b = by.setdefault(r["model"], {"model": r["model"], "label": r.get("model_label") or r["model"],
                                       "cells": {}, "labs": {k: {"tried": 0, "passed": 0} for k in LABS},
                                       "seconds": [], "cost": 0.0})
        c = b["cells"].setdefault(f'{r["task"]}:{r["lab"]}', {"tried": 0, "passed": 0})
        c["tried"] += 1
        c["passed"] += bool(r["passed"])
        lab = b["labs"].setdefault(r["lab"], {"tried": 0, "passed": 0})
        lab["tried"] += 1
        lab["passed"] += bool(r["passed"])
        if r.get("seconds") is not None:
            b["seconds"].append(float(r["seconds"]))
        b["cost"] += float(r.get("cost_usd") or 0.0)
    out = []
    for b in by.values():
        s = b.pop("seconds")
        b["avg_seconds"] = round(float(np.mean(s)), 1) if s else None
        b["cost"] = round(b["cost"], 2)
        out.append(b)
    out.sort(key=lambda b: -sum(x["passed"] for x in b["labs"].values()))
    return {"tasks": [{"id": t.id, "title": t.title} for t in TASKS.values()],
            "labs": [{"id": k, "label": v[1]} for k, v in LABS.items()], "board": out}
