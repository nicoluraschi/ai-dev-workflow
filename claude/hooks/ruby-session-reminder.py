#!/usr/bin/env python3
"""PreToolUse reminder: surface `ruby-version-manager` before the first Ruby command of a session.

`ruby-version-manager` says in its own description to run "at session start, BEFORE running
ruby, bundle, gem, rake, rails, rspec" — but nothing enforced that, so it fired only when the
agent happened to notice it. Running bundler under the wrong version manager fails in ways
that look like application bugs, which is an expensive way to find out.

Never blocks: this injects context, like gh-pr-create-review-reminder.py. Fires at most once
per session so it does not repeat on every bundle call. Fails OPEN on any error.
"""
import hashlib
import json
import os
import shlex
import sys

RUBY_CMDS = {"bundle", "bundler", "ruby", "gem", "rake", "rails", "rspec", "rubocop", "irb", "pry"}
# A .tool-versions counts only when it pins ruby: ~/.tool-versions pins nodejs alone, and
# counting it made every directory under home a Ruby project.
MARKERS = ("Gemfile", ".ruby-version")


def is_ruby_cmd(cmd):
    """A Ruby command in command position: first, or after |, ;, & or ( (which covers `$(`).
    Tokenized with quotes resolved, so `grep "npm|bundle"` and `echo "bundle is a word"` do not
    count. Unbalanced quotes (an apostrophe in a heredoc body) leave only the first word
    readable."""
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        tokens = list(lx)
    except ValueError:
        tokens = cmd.split()[:1]
    return any(t in RUBY_CMDS and (i == 0 or set(tokens[i - 1]) <= set("|;&("))
               for i, t in enumerate(tokens))


def pins_ruby(path):
    with open(path, errors="replace") as f:
        return any(line.split()[:1] == ["ruby"] for line in f)


REMINDER = (
    "This is the first Ruby command of the session in a Ruby project. Before running it, invoke "
    "the `ruby-version-manager` skill and resolve which version manager this repo uses (rbenv, "
    "asdf, rvm, mise) — running bundler under the wrong one fails in ways that look like "
    "application bugs. It does not need the developer to ask for it."
)


def allow():
    sys.exit(0)


def safe_session(raw):
    """Session ids are validated before use in filenames; invalid ids are hashed so they never
    escape the state dir.

    Repeated rather than shared across hooks on purpose: each hook here is standalone so a broken
    sibling import can never stop one from running.
    """
    v = str(raw or "")
    if not v or len(v) > 128 or not all(c.isalnum() or c in "._-" for c in v) or v.strip(".") == "":
        return "unknown-" + hashlib.sha256(v.encode("utf-8", "replace")).hexdigest()[:16]
    return v


def state_dir():
    d = os.environ.get("CLAUDE_AUDIT_STATE_DIR") or os.path.expanduser("~/.claude/.audit-state")
    os.makedirs(d, exist_ok=True)
    return d


def is_ruby_project(cwd):
    d = os.path.realpath(cwd or "")
    home = os.path.realpath(os.path.expanduser("~"))
    while d and d != "/":
        if any(os.path.exists(os.path.join(d, m)) for m in MARKERS):
            return True
        tv = os.path.join(d, ".tool-versions")
        if os.path.isfile(tv) and pins_ruby(tv):
            return True
        if d == home:
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return False


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            allow()
    except SystemExit:
        raise
    except Exception:
        allow()

    try:
        if data.get("tool_name") != "Bash":
            allow()
        cmd = (data.get("tool_input") or {}).get("command") or ""
        if not is_ruby_cmd(cmd):
            allow()
        if not is_ruby_project(data.get("cwd") or os.getcwd()):
            allow()

        session = safe_session(data.get("session_id"))
        marker = os.path.join(state_dir(), f"{session}.ruby-reminded")
        if os.path.exists(marker):
            allow()
        open(marker, "w").close()

        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": REMINDER,
        }}))
    except SystemExit:
        raise
    except Exception:
        allow()
    allow()


if __name__ == "__main__":
    main()
