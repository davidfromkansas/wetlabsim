"""Run records: everything a run leaves behind (task, command, transcript, robot log and
recording, results, the agent's workspace), written through one place.

local: a folder per run under the runs folder (the original layout). The folder is also the
working area while a run goes (the simulator writes its log and recording there). finish()
is where a hosted store would upload the finished record.
"""
from __future__ import annotations

import json
import pathlib
import shutil


class LocalRunStore:
    name = "local"

    def __init__(self, runs: pathlib.Path):
        self.runs = pathlib.Path(runs)

    def create(self, run_id: str) -> pathlib.Path:
        d = self.runs / run_id
        d.mkdir(parents=True)
        return d

    def dir(self, run_id: str) -> pathlib.Path:
        return self.runs / run_id

    def path(self, run_id: str, name: str) -> pathlib.Path:
        return self.dir(run_id) / name

    def open(self, run_id: str, name: str, mode: str = "w"):
        return open(self.path(run_id, name), mode)

    def write_text(self, run_id: str, name: str, text: str):
        self.path(run_id, name).write_text(text)

    def write_json(self, run_id: str, name: str, obj, indent=1):
        self.write_text(run_id, name, json.dumps(obj, indent=indent))

    def copy_tree(self, run_id: str, name: str, src: pathlib.Path):
        shutil.copytree(src, self.path(run_id, name), dirs_exist_ok=True)

    def finish(self, run_id: str):
        """The record is complete. Nothing to do for a local folder."""


STORES = {"local": LocalRunStore}


def get(name: str, runs: pathlib.Path):
    try:
        return STORES[name](runs)
    except KeyError:
        raise SystemExit(f"unknown run store {name!r}; choose from {', '.join(STORES)}") from None
