#!/usr/bin/env python3
"""PreToolUse reminder: right before `gh pr create` runs, inject a review-gate checklist
into Claude's own context. Never blocks -- this is a memory aid, not a gate, since a hook
cannot know a change's risk tier (that's a spec-level judgement call from feature-workflow).
Fails OPEN on any error so it can never block a PR.

Why: a long green tool chain builds momentum straight into commit/push/PR, past the review
checkpoint. This puts the checklist in front of the agent at that moment.

It also carries the one-session-per-PR rule: the 2026-10-17 usage audit found multi-PR sessions
(one opened 5 PRs in 295 messages) carrying 200k+ tokens of context per message. The sentence is
conditional on the PR actually opening, since this fires before `gh pr create` runs.
"""
import json
import sys

REMINDER = (
    "Before opening this PR: restate this change's lane and risk tier (trivial / light lane "
    "routine / Tier B / Tier A, per CLAUDE.md and the feature-workflow skill) and confirm which "
    "reviews that tier requires have already produced a citable result -- not \"will run\". "
    "Trivial: trivial-lane-check only; /code-review is optional. Light lane: /code-review medium --max-findings 5 already run (a redesign unit: "
    "/code-review high --max-findings default). Tier B: /code-review high --max-findings default already run. "
    "Tier A: /code-review ultra --max-findings default (developer-triggered "
    "-- ask if it hasn't happened) AND a Codex gate-6b spec-conformance cross-check already "
    "run against this diff. If the tier's required reviews have not actually run yet, run "
    "them (or ask the developer to) before creating the PR. Once this PR is open and its "
    "follow-ups are handled (CI, body updates"
    "), the next piece of work "
    "goes in a fresh session, not this one."
)


def allow():
    sys.exit(0)


def remind():
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": REMINDER,
        }
    }))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()
        return

    if data.get("tool_name", "") != "Bash":
        allow()
        return

    command = (data.get("tool_input", {}) or {}).get("command", "") or ""
    if "gh pr create" not in command:
        allow()
        return

    remind()


if __name__ == "__main__":
    main()
