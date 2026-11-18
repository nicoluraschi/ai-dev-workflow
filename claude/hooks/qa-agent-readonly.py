#!/usr/bin/env python3
"""PreToolUse guard: keep the `qa` subagent read-only when it uses Bash.

The qa agent declares `disallowedTools: Edit, Write, NotebookEdit`, which removes those
tools — but it does NOT sandbox Bash, and Bash can do everything they can and more.
`git commit`, `sed -i`, or a `>` redirection would each defeat the one rule that makes
an independent QA pass worth anything: QA reports, it never changes the thing it is
judging. A QA agent that "helpfully" fixed a bug has destroyed the evidence that the
bug shipped.

Scope: fires ONLY when `agent_type == "qa"`. Every other session, agent and subagent is
untouched — a guard that leaks into normal work would be turned off within a week.

Blocks, inside that agent only:
  - git subcommands that write (commit, add, push, checkout, reset, stash, ...)
  - file-mutating commands (rm, mv, cp, touch, chmod, ln, dd, tee, ...) unless every
    path argument is scratch (/tmp, /dev/null, the session scratchpad)
  - shell redirection into a real file, in every form: `>`, `>>`, `>|`, `&>`, `2>`
  - in-place editors: `sed -i`, `sed -Ei`, `perl -pi -e`, `--in-place`
  - downloads written to a path: `curl -o`, `wget -O`
  - interpreter one-liners that write a file: `rails runner "File.write(...)"`,
    `python3 -c "open(p,'w')"`, `node -e "fs.writeFileSync(...)"`

Reads are never blocked: git log/diff/status/show, curl, rails runner, psql selects,
tail, grep — including `grep -rn touch docs/`, because a name only counts as a command
when it is the first token of its segment.

**Writes to the development database are deliberately allowed.** The rule this enforces is
"QA does not change the thing it is judging" — the code, the repo, the git state. Creating
edge-case data in a dev database is a documented part of the job (`docs/qa.md` asks each
project to explain how), and forbidding it would break QA to protect nothing.

**Threat model: a cooperative agent, not an adversary.** This stops the realistic failure —
the model helpfully "just fixing" the bug it found, which destroys the evidence that the bug
shipped. It does not stop a model determined to evade it: `eval`, command substitution and
variable indirection all defeat static analysis of a shell string, and chasing them would
cost false positives, which is how a guard gets switched off. The agent's own instructions
are the primary control; this is the backstop for when they lose against helpfulness.

Parsing note: quoting a path is ordinary, not adversarial, so `rm -rf "app/models"` must read
as `rm -rf app/models`. The scanner below *resolves* quotes rather than deleting them, and decides what is a command by position
rather than by a word appearing somewhere in the line.

Fails OPEN on any error. A QA pass that cannot run is worse than one that could
theoretically have written a file.
"""
import json
import re
import sys

AGENT = "qa"

# git subcommands that mutate the repo or the working tree.
GIT_WRITE = {
    "commit", "add", "push", "checkout", "switch", "reset", "revert", "merge",
    "rebase", "stash", "cherry-pick", "apply", "am", "clean", "restore", "rm",
    "mv", "tag", "branch", "worktree", "config", "remote", "fetch", "pull", "init",
}

# git's own flags that consume the following token, so a subcommand is never mistaken
# for their value: `git --git-dir /x commit` still reads as `commit`.
GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

# Commands whose whole purpose is to change the filesystem. Allowed only when every path
# they are given is scratch — `mkdir /tmp/shots` is normal QA, `mv x app/` is not.
FS_WRITE = {
    "rm", "mv", "cp", "touch", "mkdir", "rmdir", "chmod", "chown", "ln", "dd",
    "truncate", "shred", "unlink", "tee",
    # Deliberately NOT here: install, patch, rsync. `npm install` and `bundle install`
    # are normal setup, and a guard that blocks those gets switched off on day one.
}

# Their first non-flag operand is a mode or an owner, not a path.
FS_NON_PATH_FIRST = {"chmod", "chown"}

INTERPRETERS = {"python", "python3", "ruby", "node", "perl", "deno", "bun", "rails"}
IN_PLACE_EDITORS = {"sed", "perl", "ruby"}

# Flags naming a file to write a download into.
DOWNLOAD_OUT = {
    "curl": {"-o", "--output"},
    "wget": {"-O", "--output-document"},
}

# Writing a file from inside a one-liner leaves no shell redirection to catch. Matched
# against the RAW command, because the payload lives inside the quotes. Every token here
# must imply a *write*: a read one-liner is normal QA work, and blocking `open(p, 'r')`
# or `pathlib` outright is exactly the false positive that
# gets a guard switched off.
FILE_WRITE_TOKENS = re.compile(
    r"File\.(?:write|delete|rename|unlink)|IO\.write|FileUtils\.|write_text|write_bytes"
    r"|fs\.(?:write|append|unlink|rm|copy|rename)|writeFileSync|appendFileSync"
    r"|os\.(?:remove|rename|unlink|rmdir|mkdir)|shutil\.|Tempfile"
    r"|open\s*\([^)]*['\"][wax]"
)

# Redirections into these are harmless scratch, not a change to the thing under test.
SCRATCH_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/")


def allow():
    sys.exit(0)


def block(what, detail):
    print(
        f"Blocked: the `qa` agent tried to {what}.\n"
        f"  {detail}\n"
        "QA reports; it never changes what it is judging — not through Edit/Write "
        "(which it does not have) and not through Bash. If this needs to change, it is "
        "a finding for the report, and the main session makes the change through "
        "test-driven-development: failing regression test first, then the fix.",
        file=sys.stderr,
    )
    sys.exit(2)  # exit 2 = PreToolUse block; stderr is shown to the agent


def scan(cmd):
    """Split a command line into segments of resolved tokens, plus its redirect targets.

    Quotes are resolved, not removed: `rm -rf "app/models"` yields the token `app/models`.
    A segment ends at a top-level shell operator, so the first token of each segment is
    the command actually being run — which is what makes `grep -rn touch docs/` safe.
    Returns (segments, redirect_targets).
    """
    segments, targets = [], []
    tokens, token, quote = [], "", None
    pending_redirect = False
    i, n = 0, len(cmd)

    def end_token():
        nonlocal token, pending_redirect
        if token:
            if pending_redirect:
                targets.append(token)
                pending_redirect = False
            else:
                tokens.append(token)
            token = ""

    def end_segment():
        nonlocal tokens
        end_token()
        if tokens:
            segments.append(tokens)
        tokens = []

    while i < n:
        ch = cmd[i]
        if quote:
            if ch == quote:
                quote = None
            else:
                token += ch
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            token += cmd[i + 1]
            i += 2
            continue
        if ch.isspace():
            end_token()
            i += 1
            continue
        if ch == ">" or (ch == "&" and cmd[i + 1 : i + 2] == ">"):
            # In `2>` / `1>>` the descriptor belongs to the operator, not to a token.
            if ch == ">" and token.isdigit():
                token = ""
            end_token()
            while i < n and cmd[i] in ">&|":
                i += 1
            while i < n and cmd[i] == " ":
                i += 1
            # `2>&1` and `>&2` duplicate a descriptor; no file is written.
            if i < n and cmd[i].isdigit() and (i + 1 >= n or not cmd[i + 1].isalnum()):
                i += 1
                continue
            pending_redirect = True
            continue
        if ch == "<":
            end_token()
            i += 1
            continue
        if cmd.startswith("&&", i) or cmd.startswith("||", i):
            end_segment()
            i += 2
            continue
        if ch in (";", "|", "&", "(", ")", "\n"):
            end_segment()
            i += 1
            continue
        token += ch
        i += 1
    end_segment()
    return segments, targets


def git_subcommand(tokens):
    args, i = tokens[1:], 0
    while i < len(args):
        a = args[i]
        if a in GIT_VALUE_FLAGS:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def fs_operands(name, tokens):
    """Path arguments of a filesystem command, skipping flags and non-path operands."""
    args = [a for a in tokens[1:] if not a.startswith("-")]
    if name == "dd":
        return [a.split("=", 1)[1] for a in args if a.startswith("of=")]
    if name in FS_NON_PATH_FIRST and args:
        args = args[1:]  # the mode or the owner
    return args


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()

    if data.get("agent_type") != AGENT:
        allow()
    if data.get("tool_name") != "Bash":
        allow()

    raw = (data.get("tool_input") or {}).get("command") or ""
    if not raw.strip():
        allow()

    scratch = data.get("scratchpad_dir") or ""

    def is_scratch(tok):
        return (
            tok == "/dev/null"
            or tok.startswith(SCRATCH_PREFIXES)
            or bool(scratch and tok.startswith(scratch))
        )

    def shown():
        return f"command: {raw.strip()[:200]}"

    try:
        segments, targets = scan(raw)
    except Exception:
        allow()

    for target in targets:
        if not is_scratch(target):
            block(
                f"write to `{target}` by redirection",
                f"{shown()} — /tmp and the scratchpad are allowed.",
            )

    for tokens in segments:
        name = tokens[0].rsplit("/", 1)[-1]
        flags = [a for a in tokens[1:] if a.startswith("-")]

        if name == "git":
            sub = git_subcommand(tokens)
            if sub in GIT_WRITE:
                block(f"run `git {sub}`", shown())

        if name in FS_WRITE:
            paths = fs_operands(name, tokens)
            if paths and not all(is_scratch(p) for p in paths):
                block(f"run `{name}`", f"{shown()} — only scratch paths are allowed.")

        if name in IN_PLACE_EDITORS:
            for f in flags:
                if f.startswith("--in-place") or (not f.startswith("--") and "i" in f[1:]):
                    block("edit a file in place", shown())

        if name in DOWNLOAD_OUT:
            wanted = DOWNLOAD_OUT[name]
            for idx, a in enumerate(tokens):
                if a in wanted and idx + 1 < len(tokens):
                    out = tokens[idx + 1]
                    if not is_scratch(out):
                        block(f"download into `{out}`", shown())

        if name in INTERPRETERS and FILE_WRITE_TOKENS.search(raw):
            block("write a file from an interpreter one-liner", shown())

    allow()


if __name__ == "__main__":
    main()
