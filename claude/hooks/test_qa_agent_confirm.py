#!/usr/bin/env python3
"""Tests for qa-agent-confirm.py.

Run: python3 claude/hooks/test_qa_agent_confirm.py

The `qa` agent costs ~360k tokens and 11-44 minutes per run (measured, 2026-09).
Nothing may spend that without a human saying yes, so this guard turns every launch
into a permission prompt. Two properties matter: it asks on every path that can reach
the qa agent, and it is completely invisible for every other subagent — a gate that
fires where it should not gets disabled, and then it gates nothing.

Unlike the other hooks here it fails CLOSED: when it cannot tell what is being
launched, it asks. Failing open would mean spending the run without permission, which
is the exact thing it exists to prevent.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa-agent-confirm.py")

FAILED = []


def run(payload):
    return subprocess.run(
        [sys.executable, HOOK], input=json.dumps(payload), text=True, capture_output=True
    )


def pre(subagent="qa", tool="Agent", tool_input=...):
    if tool_input is ...:
        tool_input = {"description": "d", "prompt": "p"}
        if subagent is not None:
            tool_input["subagent_type"] = subagent
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILED.append(name)


def decision(proc):
    """The permissionDecision the hook emitted, or None if it stayed silent."""
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return None


def asks(name, **kw):
    p = run(pre(**kw))
    d = decision(p)
    reason = ""
    try:
        reason = json.loads(p.stdout)["hookSpecificOutput"].get("permissionDecisionReason", "")
    except Exception:
        pass
    check(name, d == "ask" and len(reason) > 20, f"rc={p.returncode} decision={d!r} out={p.stdout[:160]!r}")


def allows(name, **kw):
    p = run(pre(**kw))
    d = decision(p)
    check(name, p.returncode == 0 and d is None, f"rc={p.returncode} decision={d!r}")


print("asks — every path that reaches the qa agent")
asks("Agent tool, qa")
asks("Task tool, qa (legacy tool name)", tool="Task")

print("allows — every other subagent (the guard must be invisible)")
allows("Explore subagent", subagent="Explore")
allows("general-purpose subagent", subagent="general-purpose")
allows("claude subagent", subagent="claude")
allows("no subagent_type (defaults to general-purpose)", subagent=None)
allows("a subagent whose name merely contains qa", subagent="qa-methodology-writer")

print("allows — outside the Agent/Task tools")
allows("Bash", tool="Bash", tool_input={"command": "ls"})
allows("Read", tool="Read", tool_input={"file_path": "/x"})

print("fails closed — cannot verify means ask")
p = subprocess.run([sys.executable, HOOK], input="not json", text=True, capture_output=True)
check("malformed stdin asks", decision(p) == "ask", f"rc={p.returncode} out={p.stdout[:120]!r}")
p = run({"hook_event_name": "PreToolUse", "tool_name": "Agent"})
check("Agent call with no tool_input asks", decision(p) == "ask", f"rc={p.returncode}")
for payload in ("[]", "null", '"x"', "3"):
    p = subprocess.run([sys.executable, HOOK], input=payload, text=True, capture_output=True)
    check(f"non-object JSON ({payload}) asks", decision(p) == "ask", f"rc={p.returncode}")
p = run({"hook_event_name": "PreToolUse", "tool_input": {"subagent_type": "qa"}})
check("qa launch with no tool_name asks", decision(p) == "ask", f"rc={p.returncode}")

print()
if FAILED:
    print(f"{len(FAILED)} failing: {', '.join(FAILED)}")
    sys.exit(1)
print("all passing")
