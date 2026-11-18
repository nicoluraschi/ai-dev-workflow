#!/usr/bin/env python3
"""Tests for main-context-images.py.

Run: python3 claude/hooks/test_main_context_images.py

Measured 2026-10-12..19: 989 of 1,153 images landed in the main Opus session and each was
re-read on ~87 later calls. The guard keeps pixels out of the main session: it denies an
image Read or an inline chrome-devtools screenshot there, and stays invisible inside any
subagent, for non-images, and for the user's own screenshots in ~/Desktop and ~/Downloads.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main-context-images.py")
HOME = os.path.expanduser("~")
SHOT = "/private/tmp/claude-501/proj/session/scratchpad/shots/home-360.png"
SCREENSHOT = "mcp__chrome-devtools__take_screenshot"
STATE = tempfile.mkdtemp()

FAILED = []


def run(payload, raw=None):
    return subprocess.run(
        [sys.executable, HOOK], input=raw if raw is not None else json.dumps(payload),
        text=True, capture_output=True, env={**os.environ, "CLAUDE_AUDIT_STATE_DIR": STATE},
    )


def pre(path=SHOT, tool="Read", session="s1", tool_input=None, **extra):
    if tool_input is None:
        tool_input = {"file_path": path} if tool == "Read" else {}
    return {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": tool,
            "tool_input": tool_input, **extra}


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILED.append(name)


def output(proc):
    try:
        return json.loads(proc.stdout)["hookSpecificOutput"]
    except Exception:
        return {}


def denies(name, **kw):
    p = run(pre(**kw))
    out = output(p)
    check(name, out.get("permissionDecision") == "deny"
          and "ui-reviewer" in out.get("permissionDecisionReason", ""),
          f"rc={p.returncode} out={p.stdout[:160]!r}")


def allows(name, payload=None, raw=None, **kw):
    p = run(payload if payload is not None else pre(**kw), raw=raw)
    check(name, p.returncode == 0 and not p.stdout.strip(), f"rc={p.returncode} out={p.stdout[:160]!r}")


print("denies — pixels entering the main session")
denies("Read of a scratchpad .png")
for ext in (".jpg", ".jpeg", ".webp", ".gif", ".PNG"):
    denies(f"Read of a {ext}", path=SHOT[:-4] + ext)
denies("Read of a .png inside a repo", path=f"{HOME}/worktrees/app/feat/x/web/public/shot.png")
denies("inline chrome-devtools take_screenshot", tool=SCREENSHOT)
denies("a Desktop path that escapes via ..", path=f"{HOME}/Desktop/../scratch/shot.png")
denies("a sibling dir that only shares the Desktop prefix", path=f"{HOME}/DesktopX/shot.png")
denies("take_screenshot saved into ~/Downloads, the readable dir", tool=SCREENSHOT,
       tool_input={"filePath": f"{HOME}/Downloads/shot.png"})

print("allows — subagents see pixels")
allows("Read of a .png from ui-reviewer", agent_id="a1", agent_type="ui-reviewer")
allows("Read of a .png with only agent_type", agent_type="general-purpose")
allows("Read of a .png with only agent_id", agent_id="a2")
allows("take_screenshot from a subagent", tool=SCREENSHOT, agent_id="a3", agent_type="ui-reviewer")

print("allows — no pixels enter context, or the user's own screenshot")
allows("take_screenshot saved to a file", tool=SCREENSHOT, tool_input={"filePath": SHOT})
allows("Read of a .md", path="/x/README.md")
allows("Read of a .pdf", path="/x/doc.pdf")
allows("Read of a .png in ~/Desktop", path=f"{HOME}/Desktop/Screenshot 2026-10-19.png")
allows("Read of a .png in ~/Downloads", path=f"{HOME}/Downloads/mock.png")
allows("Read of a .png in ~/desktop (case-insensitive volume)", path=f"{HOME}/desktop/shot.png")
allows("Read of a .png via ~", path="~/Downloads/mock.png")
allows("another tool", tool="Bash")

print("allows — silenced for this session")
open(os.path.join(STATE, "s2.skip.main-context-images"), "w").close()
allows("skip file for this session", session="s2")
denies("skip file does not leak to another session", session="s3")
denies("hostile session id is not treated as skipped", session="../s2")

print("B9 — the refusal names the gate and asks the human; it prints no recipe")
for label, sess in (("a normal session id", "s4"), ("a session id that cannot be a skip name", "../s4"),
                    ("no session id", None)):
    reason = output(run(pre(session=sess))).get("permissionDecisionReason", "")
    low = reason.lower()
    check(f"refusal text for {label}",
          "ask the human" in low and "main-context-images" in reason and "touch" not in low
          and ".skip" not in low and STATE not in reason and "cannot be silenced" not in low,
          reason[-200:])
with open(HOOK) as f:
    sites = [ln for ln in f.read().splitlines() if re.match(r"\s+(block|deny)\(", ln)]
check("exactly one refusal call site, the one driven above", len(sites) == 1, str(sites))

print("fails open — a broken payload never wedges the session")
allows("malformed stdin", raw="not json")
allows("non-object JSON", raw="[]")
allows("Read with no tool_input", payload={"tool_name": "Read"})

print()
if FAILED:
    print(f"{len(FAILED)} failing: {', '.join(FAILED)}")
    sys.exit(1)
print("all passing")
