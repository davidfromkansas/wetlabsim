"""The robot API: the only door an agent gets to the robot.

A separate listener from the app (the web page, the audience camera, run history, files and
the evaluator). It answers only the robot's own commands, readings and the agent's two
cameras, and only with a run token: each agent run gets a fresh token, good for one robot
(one station) and only while that run lasts. Everything else is refused.

A request is checked here, then handed to the app's own handler with its path pointed at
that token's robot, so the robot code itself is shared.
"""
from __future__ import annotations

import re
import secrets
import threading
import time

# What an agent may do: the robot client's calls (wetlabsim.robot) and nothing else.
# A two-arm robot (ALOHA) has the same API for each arm, under /left and /right, and its
# four cameras (overhead, low, and a wrist camera per arm).
SIDE = r"(/(left|right))?"
GET_PATHS = re.compile(r"^" + SIDE + r"/(state|info|camera/(overhead|wrist|low|left_wrist|right_wrist)"
                       r"\.(png|jpg|rgbd\.npz|depth\.npy))$")
POST_PATHS = {"/move_l", "/move_j", "/move_j_pose", "/stop", "/unlock_protective_stop",
              "/zero_ft_sensor", "/gripper"}
POST_RE = re.compile(r"^" + SIDE + r"(" + "|".join(re.escape(x) for x in POST_PATHS) + r")$")
# The robot's commands: on the app's listener these are refused once a robot API is running.
ROBOT_COMMANDS = POST_PATHS


class RunTokens:
    """Run tokens: token -> the robot it opens (a path prefix such as /st/st2, or '' for the
    scene's one robot)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tokens: dict[str, dict] = {}

    def issue(self, prefix: str, run: str = "") -> str:
        tok = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[tok] = {"prefix": prefix.rstrip("/"), "run": run, "issued": time.time()}
        return tok

    def revoke(self, tok: str | None):
        if tok:
            with self._lock:
                self._tokens.pop(tok, None)

    def lookup(self, tok: str) -> dict | None:
        if not tok:
            return None
        with self._lock:
            for k, v in self._tokens.items():
                if secrets.compare_digest(k, tok):
                    return v
        return None


TOKENS = RunTokens()


def token_from(headers) -> str:
    auth = headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else headers.get("X-Robot-Token", "").strip()


def allowed(method: str, path: str) -> bool:
    path = path.split("?", 1)[0].rstrip("/") or "/"
    if method == "GET":
        return bool(GET_PATHS.match(path))
    return method == "POST" and bool(POST_RE.match(path))


class RobotAPIMixin:
    """Mixed into a copy of the app's handler class to serve the robot API on its own port."""

    robot_api = True

    def _gate(self, method: str) -> bool:
        grant = TOKENS.lookup(token_from(self.headers))
        if grant is None:
            self._err("a valid run token is required (Authorization: Bearer <token>)", 401)
            return False
        if not allowed(method, self.path):
            self._err("not part of the robot API", 403)
            return False
        self.path = grant["prefix"] + self.path
        return True

    def do_GET(self):
        if self._gate("GET"):
            super().do_GET()

    def do_POST(self):
        if self._gate("POST"):
            super().do_POST()
