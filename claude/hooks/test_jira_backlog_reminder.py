#!/usr/bin/env python3
"""Tests for jira-backlog-reminder.py.

Run: python3 claude/hooks/test_jira_backlog_reminder.py

The hook is what makes `jira-backlog` run without anyone remembering it: a ticket key in a
prompt, a PR opening and a /ship each hand the skill its job. It speaks only in a repo whose
AGENTS.md has a `Jira:` line, and it fails OPEN.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jira-backlog-reminder.py")

FAILED = []
TOTAL = 0


def run(stdin):
    return subprocess.run([sys.executable, HOOK], input=stdin, text=True, capture_output=True)


def repo(branch, agents="# Repo\n\nJira: example.atlassian.net MAR\n"):
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", "-b", branch, d], check=True)
    if agents is not None:
        with open(os.path.join(d, "AGENTS.md"), "w") as f:
            f.write(agents)
    return d


def prompt(cwd, text):
    return json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": cwd, "prompt": text})


def bash(cwd, command):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
                       "tool_input": {"command": command}})


def context(r):
    try:
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return ""


def check(name, ok, detail=""):
    global TOTAL
    TOTAL += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILED.append(name)


def silent(name, stdin):
    r = run(stdin)
    check(f"{name} exits 0 and prints nothing", r.returncode == 0 and r.stdout == "",
          f"rc={r.returncode} out={r.stdout!r} err={r.stderr!r}")


def main():
    jira = repo("main")
    plain = repo("main", agents="# Repo\n")
    keyed = repo("feat/mar-26-local-days")
    keyless = repo("feat/tidy-up")
    no_agents = repo("feat/MAR-26-x", agents=None)

    # H1: a ticket key in a prompt starts the ticket.
    r = run(prompt(jira, "work on MAR-26 next"))
    c = context(r)
    check("H1a. a prompt naming MAR-26 hands it to jira-backlog",
          r.returncode == 0 and "jira-backlog" in c and "MAR-26" in c, r.stdout + r.stderr)
    check("H1b. the start reminder names the site and the branch rule",
          "example.atlassian.net" in c and "branch" in c and "In Progress" in c, c)
    check("H1b2. In Progress waits for the developer's go on the plan",
          "In Progress once the developer says go on the plan" in c, c)
    check("H1c. the prompt reminder is a UserPromptSubmit context",
          '"hookEventName": "UserPromptSubmit"' in r.stdout, r.stdout)
    silent("H1d. a prompt with no Jira line", prompt(plain, "work on MAR-26"))
    silent("H1e. another project's key", prompt(jira, "look at RUN-1"))
    silent("H1f. no key at all", prompt(jira, "what changed in MAR?"))
    silent("H1g. a key glued to a word", prompt(jira, "see XMAR-26"))
    check("H1h. the start reminder applies only when asked to work on it",
          "asking to work on" in c, c)
    silent("H1i. a date-like word in a prompt is not a key", prompt(jira, "the deadline is Mar-30"))
    silent("H1j. the branch's own key mentioned again", prompt(keyed, "is MAR-26 done?"))
    c = context(run(prompt(keyed, "start MAR-40 next")))
    check("H1k. another key on a keyed branch still fires, conditionally",
          "MAR-40" in c and "asking to work on" in c, c)

    # H2: a PR opening writes back.
    c = context(run(bash(keyed, "gh pr create --title t --body-file b.md")))
    check("H2a. gh pr create on a key branch names the key, upper-cased",
          "jira-backlog" in c and "MAR-26" in c and "PR link" in c, c)
    check("H2a2. the PR reminder no longer moves the ticket to In Review", "In Review" not in c, c)
    check("H2b. the PR reminder holds until the PR is open", "Once the PR is open" in c, c)
    c = context(run(bash(keyless, "gh pr create --fill")))
    check("H2c. gh pr create with no key asks to find or create one",
          "jira-backlog" in c and "MAR" in c and "find" in c and "create" in c, c)
    silent("H2d. gh pr create where AGENTS.md has no Jira line",
           bash(repo("feat/MAR-26-x", agents="# Repo\n"), "gh pr create --fill"))
    silent("H2e. gh pr create where there is no AGENTS.md", bash(no_agents, "gh pr create --fill"))
    silent("H2f. a command that only quotes gh pr create",
           bash(keyed, 'grep -rn "gh pr create" claude/hooks'))
    c = context(run(bash(keyed, "git push -u origin HEAD && gh pr create --fill")))
    check("H2g. gh pr create after && still fires", "PR link" in c, c)
    c = context(run(bash(keyed, "git push -u origin HEAD\ngh pr create --fill")))
    check("H2h. gh pr create on a second line fires", "PR link" in c, c)
    c = context(run(bash(keyed, "gh pr create --fill --body \"Don't\n")))
    check("H2i. gh pr create with unbalanced quotes still fires", "PR link" in c, c)

    # H3: /ship moves the ticket to Done.
    c = context(run(bash(keyed, "ship")))
    check("H3a. ship on a key branch moves the key to Done",
          "jira-backlog" in c and "MAR-26" in c and "Done" in c, c)
    check("H3b. the ship reminder holds until the merge succeeds", "succeeds" in c, c)
    c = context(run(bash(keyless, "ship")))
    check("H3c. ship with no key in the branch reads the key from the PR body",
          "jira-backlog" in c and "PR body" in c and "Done" in c and "succeeds" in c, c)
    check("H3e. it names the branch, and the repo placeholder when there is no origin",
          "gh pr view feat/tidy-up -R <owner>/<repo>" in c, c)
    subprocess.run(["git", "-C", keyless, "remote", "add", "origin",
                    "git@github.com:acme/app.git"], check=True)
    c = context(run(bash(keyless, "ship")))
    check("H3f. it names the origin repo", "gh pr view feat/tidy-up -R acme/app" in c, c)
    c = context(run(bash(repo("feat/x+y"), "ship")))
    check("H3g. a branch name outside the safe set becomes a placeholder",
          "gh pr view <branch> -R" in c and "x+y" not in c, c)
    silent("H3d. a command that only mentions ship", bash(keyed, "grep ship README.md"))

    # H4: everything else is silent, and the hook fails open.
    silent("H4a. another Bash command", bash(keyed, "git status"))
    silent("H4b. another tool", json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                                            "cwd": keyed, "tool_input": {}}))
    silent("H4c. malformed stdin", "not json")
    silent("H4d. a cwd outside any git repo", bash(tempfile.mkdtemp(), "gh pr create --fill"))
    silent("H4e. a cwd that does not exist", prompt("/nonexistent/x", "MAR-26"))
    silent("H4f. JSON that is not an object", "[]")
    silent("H4g. an event it does not handle", json.dumps({"hook_event_name": "Stop", "cwd": keyed}))
    c = context(run(bash(keyed, "ship 'unbalanced")))
    check("H4h. unbalanced quotes still read the first word", "Done" in c, c)

    print(f"{TOTAL - len(FAILED)}/{TOTAL} passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
