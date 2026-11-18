#!/usr/bin/env python3
"""Hands `jira-backlog` its job at the three moments a ticket changes state, so Jira stays in
step with the work without anyone remembering to ask: a prompt naming a ticket (start: In
Progress on the plan's go), `gh pr create` (PR-link comment) and `ship` (Done).

Speaks only in a repo whose AGENTS.md has a `Jira: <site> <PROJECT>` line, and only about that
project's keys. The ticket key travels in the branch name, which the skill sets at the start;
reading it here needs no network. A key matched to a keyless branch at PR open lives only in the
PR body, so the ship reminder for a keyless branch names the branch and repo to read it from:
after `ship` the worktree is gone and git can no longer say. Never blocks -- like
gh-pr-create-review-reminder.py, this injects context. Both Bash moments fire before the command
runs, so each reminder is conditional on success. Fails OPEN on any error.
"""
import json
import os
import re
import shlex
import subprocess
import sys

JIRA_LINE = re.compile(r"^Jira:\s+([A-Za-z0-9.-]+)\s+([A-Z][A-Z0-9_]+)\s*$", re.M)
GITHUB_SLUG = re.compile(r"github\.com[:/]([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?$")
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
SEPARATORS = set("|;&(")


def allow():
    sys.exit(0)


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def board(cwd):
    """(site, project) from the AGENTS.md at the repo root, or None."""
    top = git(cwd, "rev-parse", "--show-toplevel")
    path = os.path.join(top, "AGENTS.md") if top else ""
    if not path or not os.path.isfile(path):
        return None
    with open(path, errors="replace") as f:
        m = JIRA_LINE.search(f.read())
    return m.groups() if m else None


def key_in(text, project, flags=0):
    """Branch names are often lower-case, so they match with re.I; prompts match upper-case
    only, or a date like "Mar-30" in a MAR repo would start a ticket."""
    m = re.search(rf"(?<![A-Za-z0-9]){project}-(\d+)(?!\d)", text, flags)
    return f"{project}-{m.group(1)}" if m else None


def commands(cmd):
    """The simple commands in `cmd`, as word lists, split at |, ;, &, ( and newlines. Quotes
    resolved, so `grep "gh pr create"` is one grep. Unbalanced quotes (an apostrophe in a PR
    body) fall back to a plain split at the same separators."""
    try:
        lx = shlex.shlex(cmd.replace("\n", ";"), posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        tokens = list(lx)
    except ValueError:
        return [part.split() for part in re.split(r"[|;&(\n]", cmd)]
    out = [[]]
    for t in tokens:
        if set(t) <= SEPARATORS:
            out.append([])
        else:
            out[-1].append(t)
    return out


def say(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    allow()


def on_prompt(data, site, project):
    key = key_in(data.get("prompt") or "", project)
    branch = git(data.get("cwd") or os.getcwd(), "symbolic-ref", "--short", "HEAD")
    if not key or key == key_in(branch, project, re.I):
        allow()
    say("UserPromptSubmit",
        f"This prompt names {key} on the {site} Jira board. If the developer is asking to work on "
        f"it (not just mentioning it), use the `jira-backlog` skill to start it: fetch the "
        f"ticket, make sure this work's branch name carries {key}, and move it to In Progress "
        f"once the developer says go on the plan, if it is still To Do.")


def on_bash(data, site, project):
    cmds = commands((data.get("tool_input") or {}).get("command") or "")
    is_pr = any(c[:3] == ["gh", "pr", "create"] for c in cmds)
    if not is_pr and not any(c[:1] == ["ship"] for c in cmds):
        allow()
    cwd = data.get("cwd") or os.getcwd()
    branch = git(cwd, "symbolic-ref", "--short", "HEAD")
    key = key_in(branch, project, re.I)
    if is_pr and key:
        say("PreToolUse",
            f"Once the PR is open, use the `jira-backlog` skill on {key} ({site}): comment the "
            f"PR link.")
    if is_pr:
        say("PreToolUse",
            f"Once the PR is open, use the `jira-backlog` skill: this branch names no {project} "
            f"ticket, so find the one this PR closes on {site} and confirm it with the "
            f"developer, or offer to create one; then write back as for any ticket.")
    if key:
        say("PreToolUse",
            f"If this ship succeeds, use the `jira-backlog` skill to move {key} ({site}) to Done.")
    slug = GITHUB_SLUG.search(git(cwd, "remote", "get-url", "origin"))
    view = (f"gh pr view {branch if SAFE_BRANCH.match(branch) else '<branch>'} "
            f"-R {slug.group(1) if slug else '<owner>/<repo>'} --json body")
    say("PreToolUse",
        f"If this ship succeeds, use the `jira-backlog` skill: the branch names no {project} "
        f"ticket, so read the merged PR body for its Jira link (`{view}`; the worktree will be "
        f"gone) and move that ticket ({site}) to Done; with no link, do nothing.")


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            allow()
        event = data.get("hook_event_name")
        if event == "PreToolUse" and data.get("tool_name") != "Bash":
            allow()
        if event not in ("UserPromptSubmit", "PreToolUse"):
            allow()
        found = board(data.get("cwd") or os.getcwd())
        if not found:
            allow()
        (on_prompt if event == "UserPromptSubmit" else on_bash)(data, *found)
    except SystemExit:
        raise
    except Exception:
        allow()
    allow()


if __name__ == "__main__":
    main()
