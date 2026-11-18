#!/usr/bin/env python3
"""Notification hook: a macOS notification when a session needs a human.

With several sessions open, a permission prompt or an idle "waiting for your input" sat unseen
until someone happened to switch to that tab. The title names the session's worktree
(`dotfiles/feat/x` under ~/worktrees, else the folder name) so you know which one to switch to.

The message comes from the payload, so it is handed to osascript as an argv item and read via
`on run argv` -- never interpolated into the AppleScript source, where a quote would let it run
`do shell script`. The `--` matters too: osascript parses a dash-led positional as another `-e`
statement. Never blocks; fails OPEN on any error.
"""
import json
import os
import subprocess
import sys

SCRIPT = ('on run argv\n'
          'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"\n'
          'end run')


def title_for(cwd):
    d = os.path.realpath(cwd or os.getcwd())
    root = os.path.realpath(os.path.expanduser("~/worktrees"))
    if d.startswith(root + os.sep):
        return os.path.relpath(d, root)
    return os.path.basename(d) or "Claude Code"


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            sys.exit(0)
        message = str(data.get("message") or "Claude needs your attention")
        subprocess.run(["osascript", "-e", SCRIPT, "--", title_for(data.get("cwd")), message],
                       capture_output=True, timeout=5)
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
