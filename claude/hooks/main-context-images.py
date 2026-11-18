#!/usr/bin/env python3
"""PreToolUse guard: screenshots are looked at by a subagent, never by the main session.

An image in the main session is re-read on every later call until compaction; inside the
`ui-reviewer` subagent it dies with the subagent. Most images arrive as a `Read` of a PNG a
script just wrote, so this matches `Read` on image extensions as well as `take_screenshot`.

Scope: denies ONLY in the main session. Either `agent_id` or `agent_type` in the payload
counts as a subagent, so the agent built to look at screenshots is never blind; the price is
that a main session started with `claude --agent` is not guarded. A `take_screenshot` with a
`filePath` passes -- it returns text, not pixels -- unless that file lands in a dir below. Images under ~/Desktop and ~/Downloads stay
readable -- those are the user's own screenshots, which the user asked to be looked at.

The HUMAN silences it for one session (the refusal does not print this, and gate-state-guard.py
denies the agent writing it): touch "$STATE/<session_id>.skip.main-context-images", where
$STATE is the audit-guard state dir. Fails OPEN like the other hooks here: a broken payload
never wedges the session.
"""
import json
import os
import re
import sys

NAME = "main-context-images"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
SCREENSHOT = "mcp__chrome-devtools__take_screenshot"
USER_DIRS = tuple(os.path.realpath(os.path.expanduser(d)).lower() + os.sep
                  for d in ("~/Desktop", "~/Downloads"))

REASON = (
    "Screenshots stay out of the main session: each image here is re-read on every later "
    "turn. Delegate capture and review to the `ui-reviewer` agent (Agent tool, "
    "subagent_type \"ui-reviewer\"), which takes the screenshots itself and returns text "
    "plus the file paths. To silence this gate (main-context-images), ask the human to silence it."
)


def allow():
    sys.exit(0)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def in_user_dir(path):
    # Lower-cased because macOS volumes are case-insensitive by default.
    return os.path.realpath(os.path.expanduser(path)).lower().startswith(USER_DIRS)


def skip_path(session):
    d = os.environ.get("CLAUDE_AUDIT_STATE_DIR") or os.path.expanduser("~/.claude/.audit-state")
    # The id is interpolated into a filename; anything but a plain id never matches a skip.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(session or "")):
        return None
    return os.path.join(d, f"{session}.skip.{NAME}")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()
    if not isinstance(data, dict) or data.get("agent_id") or data.get("agent_type"):
        allow()

    tool = data.get("tool_name")
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool == "Read":
        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path.lower().endswith(IMAGE_EXT):
            allow()
        if in_user_dir(path):
            allow()
    elif tool != SCREENSHOT:
        allow()
    else:
        # Saved to a file it returns text -- unless the file lands where Read is let through.
        file_path = tool_input.get("filePath")
        if isinstance(file_path, str) and file_path and not in_user_dir(file_path):
            allow()

    skip = skip_path(data.get("session_id"))
    if skip and os.path.exists(skip):
        allow()
    deny(REASON)


if __name__ == "__main__":
    main()
