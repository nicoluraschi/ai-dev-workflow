#!/usr/bin/env python3
"""PreToolUse guard: the `qa` subagent never launches without a human saying yes.

A QA run costs about as much as implementing the feature it checks, so only the human
decides when a change earns one.

`feature-workflow` phase 5q evaluates whether the change warrants QA and presents a
recommendation. This hook is what makes the human's answer binding: the recommendation
is prose a model can forget, and this is not. It fires on every path that reaches the
agent -- phase 5q, the `/qa` command, a direct request -- so there is no route that
spends the run unasked.

Scope: fires ONLY when the tool is Task/Agent and `subagent_type == "qa"`. Every other
subagent is invisible to it. A gate that prompts where it should not gets switched
off, and then it gates nothing.

Fails CLOSED, unlike every other hook here. When it cannot tell what is being launched
it asks anyway. The usual argument for failing open -- do not wedge the session -- does
not apply to a decision whose whole purpose is to not spend 400k tokens unattended;
the worst case here is one extra prompt, and the worst case the other way is the thing
this exists to prevent.
"""
import json
import sys

AGENT = "qa"
TOOLS = ("Task", "Agent")

REASON = (
    "Launch the independent `qa` agent?\n"
    "Measured cost: ~280-430k tokens and 11-44 min per run.\n"
    "Say no to skip it -- the change ships without an independent QA pass, "
    "and you can always run it later with `/qa verify <spec>`."
)

UNVERIFIABLE = (
    "Could not read this agent launch to tell whether it is the `qa` agent, "
    "so it is asking rather than assuming. " + REASON
)


def allow():
    """Stay silent: no decision, the normal permission flow continues."""
    sys.exit(0)


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        ask(UNVERIFIABLE)  # fail closed

    if not isinstance(data, dict):
        ask(UNVERIFIABLE)  # fail closed

    tool = data.get("tool_name")
    if not tool:
        # The matcher fired, so something is launching, but the payload will not say
        # what. `Task` became `Agent` once already; a third rename must not silently
        # retire this gate.
        ask(UNVERIFIABLE)
    if tool not in TOOLS:
        allow()  # a tool we can name, and it is not ours

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        ask(UNVERIFIABLE)  # an agent launch we cannot inspect

    # Absent means the default general-purpose agent, not qa.
    if str(tool_input.get("subagent_type") or "").strip().lower() != AGENT:
        allow()

    ask(REASON)


if __name__ == "__main__":
    main()
