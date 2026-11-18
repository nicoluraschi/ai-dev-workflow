#!/usr/bin/env python3
"""Tests for gh-pr-create-review-reminder.py.

Run: python3 claude/hooks/test_gh_pr_create_review_reminder.py

The reminder is the last thing read before a PR opens, so its review commands must match
feature-workflow phase 6 exactly: a stale one ("Routine: no review gate") is followed, and the
routine review is skipped. Everything else must stay silent, and the hook fails OPEN.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh-pr-create-review-reminder.py")

FAILED = []


def run(stdin):
    return subprocess.run([sys.executable, HOOK], input=stdin, text=True, capture_output=True)


def bash(command):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": command}})


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILED.append(name)


def main():
    r = run(bash("gh pr create --title t --body-file b.md"))
    try:
        out = json.loads(r.stdout)["hookSpecificOutput"]
    except (ValueError, KeyError):
        out = {}
    context = out.get("additionalContext", "")
    check("1a. gh pr create is allowed", r.returncode == 0 and out.get("permissionDecision") == "allow",
          r.stdout + r.stderr)
    for cmd in ("/code-review medium --max-findings 5", "/code-review high --max-findings default",
                "/code-review ultra --max-findings default"):
        check(f"1b. the reminder names `{cmd}`", cmd in context, context)
    check("2. the reminder no longer says routine has no review gate", "no review gate" not in context,
          context)
    check("2b. the reminder names the light lane", "light lane" in context, context)
    check("2c. a redesign unit's review is high", "a redesign unit: /code-review high "
          "--max-findings default" in context, context)
    check("2d. the trivial lane requires only trivial-lane-check",
          "Trivial: trivial-lane-check only" in context, context)
    # 2026-10-17 audit: multi-PR sessions (one opened 5 PRs in 295 msgs) carried 200k+ context per
    # message. The moment a PR opens is the moment the session is done.
    check("2e. the reminder sends the next work to a fresh session once the PR is open",
          "Once this PR is open" in context and "goes in a fresh session" in context, context)
    check("2f. it keeps the PR's follow-ups in this session",
          "follow-ups are handled" in context, context)

    for name, stdin in (("3a. another tool", json.dumps({"tool_name": "Edit", "tool_input": {}})),
                        ("3b. a Bash command without gh pr create", bash("gh pr view 71")),
                        ("4. malformed stdin", "not json")):
        r = run(stdin)
        check(f"{name} exits 0 and prints nothing", r.returncode == 0 and r.stdout == "",
              f"rc={r.returncode} out={r.stdout!r}")

    total = 14
    print(f"{total - len(FAILED)}/{total} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
