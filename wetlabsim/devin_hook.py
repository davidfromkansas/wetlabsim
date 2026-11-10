"""Devin CLI hook: append each tool event to a log file so the run recorder can show
Devin's steps live (Devin's own --export is only written when it exits).

    python -m wetlabsim.devin_hook <log file>      (event JSON on stdin)
"""
import json
import sys
import time


def main():
    try:
        e = json.load(sys.stdin)
    except ValueError:
        return
    e["_wall"] = time.time()
    with open(sys.argv[1], "a") as f:
        f.write(json.dumps(e) + "\n")


if __name__ == "__main__":
    main()
