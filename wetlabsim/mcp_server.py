"""Agent plug (MCP server) for Claude Code and Codex.

Gives agents eyes and an emergency stop. Agents move the robot by writing
Python that uses wetlabsim.robot.Robot (see the robot manual in agent/).

Run by the agent CLI, not by hand:  python -m wetlabsim.mcp_server
"""
from __future__ import annotations

import io
import json

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from .robot import Robot, RobotError

server = _Server("wetlab-robot")
robot = Robot()


@server.tool()
def look(camera: str = "overhead") -> list:
    """Take a photo with one of the robot's cameras and look at it.

    camera: "overhead" (fixed above the bench, sees the whole work area) or
    "wrist" (mounted on the gripper, looks where the fingers point). A two-arm
    robot has its own: the ALOHA "overhead", "low", "left_wrist" and "right_wrist"; the
    FR3 Duo "head", "left_wrist" and "right_wrist".
    Returns the image plus the camera's calibration so you can relate pixels
    to robot coordinates (see Frame.pixel_to_point in the robot manual).
    """
    try:
        f = robot.get_camera_frame(camera)
    except RobotError as e:
        return [f"error: {e}"]
    buf = io.BytesIO()
    from PIL import Image as PILImage
    PILImage.fromarray(f.rgb).save(buf, format="PNG")
    meta = {"camera": camera, "time": f.time, "intrinsics": f.intrinsics,
            "camera_position": f.camera_position.tolist(),
            "camera_rotation": f.camera_rotation.tolist()}
    return [Image(data=buf.getvalue(), format="png"), json.dumps(meta)]


@server.tool()
def robot_state() -> str:
    """Current controller readings: joint angles, tool pose, wrist force,
    gripper status, whether it is moving or in a protective stop, and the clock."""
    try:
        return json.dumps(robot.get_state(), indent=1)
    except RobotError as e:
        return f"error: {e}"


@server.tool()
def emergency_stop() -> str:
    """Stop the arm (both arms on a two-arm robot) immediately."""
    try:
        robot.stop()
        return "stopped"
    except RobotError as e:
        return f"error: {e}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
