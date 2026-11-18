#!/usr/bin/env python3
"""PreToolUse gate: refuse `git commit` while the test suite was last seen RED.

WHY IT READS OUTPUT INSTEAD OF EXIT CODES. The obvious design is to trust the shell's
exit status. It does not work here, and the transcripts say why: the habit in this setup is
`bundle exec rspec 2>&1 | tail -12`, and a pipe makes the exit status that of `tail`. Real
runs in this corpus therefore carry `is_error: false` whether the suite passed or failed. So
the gate parses the summary line — the thing a human reads — and ignores the exit code.

WHAT IT BLOCKS. Only a verdict it has actually seen: the most recent test run in the session
transcript that produced a parseable summary. Silence is not red. If no suite ran, the commit
goes through — "you never ran the tests" is a different gate, deliberately not this one, because
it would fire on every docs and config commit and a gate that cries wolf gets turned off.
One exception to "most recent": a red FULL run is held until a green full run clears it, so a
green related-tests run (a review-fix round's subset) cannot release it. A red related run
still blocks on its own.

ESCAPE HATCH: CLAUDE_RED_SUITE_SKIP=1 in the environment. Deliberately an env var and NOT a
state file: a `.skip` file was measured silencing security-audit for twelve hours because a
session is not a unit of time. An env var dies with the shell, so it cannot be left on and
forgotten.

It cannot trap you in a loop: it gates one command, so re-running the suite (or doing anything
else) is always available. Fails OPEN on any error, like every other hook here.
"""
import json
import os
import re
import sys

# `git commit`, `git -C <path> commit`, `git add -A && git commit`. Anchored to the start of a
# line or to a shell separator so that a mention inside a quoted string is not a commit.
GIT_COMMIT = re.compile(
    r"(?:^|[;&|]\s*)\s*git\s+(?:-C\s+\S+\s+|--?\S+\s+)*commit\b", re.MULTILINE)

# A command that plausibly runs a suite. This is only a pre-filter — the verdict parser below
# is what actually decides, so `rspec --version` matches here and is then discarded for having
# no summary to read. `lefthook run pre-push` is how Verify runs a suite in repos whose
# pre-push queues it through suite-queue; its command name (`test`) need not name a runner.
TEST_CMD = re.compile(
    r"\b(?:rspec|jest|vitest|pytest|bin/rails\s+test|lefthook\s+run\s+pre-push|"
    r"(?:npm|yarn|pnpm)\s+(?:run\s+)?test)\b")

# Quoted text is removed before the pre-filter looks at a command, because a command that
# *mentions* a runner is not a command that *runs* it. Real false positive from the corpus:
#   echo "=== what a red rspec summary looks like ===" && grep -rhoE "[0-9]+ examples?, ..."
# matched on `rspec` inside the echo, and its output — literal summary lines it was grepping
# for — was then read as a verdict. Env vars like DATABASE_URL="..." are quoted too, and
# stripping them leaves `bundle exec rspec` intact, which is the case that must keep working.
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def runs_tests(command):
    return bool(TEST_CMD.search(QUOTED.sub(" ", command)))

# FULL OR RELATED. Review-fix rounds run only the tests for the touched files (`rspec <spec
# files>`, `jest --findRelatedTests <files>`); the full suite runs once after the last round.
# A green subset must not clear a red full run, so each run is classified: a runner given a
# test path is a related run, anything else — the lefthook form included, whose
# `--command <name>` is not a path — is full.
#   - only the runner's own arguments count. The runner is found with quoted text blanked out,
#     as in runs_tests, so `| grep "rspec ./spec/"` is not a runner; its arguments are then read
#     with the quotes dropped, so `"src/a.ts"` is still a path. A redirect and its target
#     (`> $TMPDIR/r.log`) and anything before the runner (`DATABASE_URL=$X`) are not arguments.
#   - a test path is a test file (`_spec.rb:42`, `test_a.py::test_x`) or a path under a test
#     directory, NOT any token with a slash: a flag value (`--config cfg/jest.config.js`) has one.
#   - paths the hook cannot read literally — `$(...)`, `$VAR`, backticks, or `xargs` feeding the
#     runner — make a run related, and so do the runners' rerun-a-subset flags.
# Classified as full: name filters (`pytest -k`, `jest -t`, `rspec --tag`) and non-test
# directories (`jest src/components`); `rspec spec/` reads as related.
SEGMENTS = re.compile(r"\|\|?|&&|;|\n")
TEST_PATH = re.compile(
    r"(?:_spec\.rb|_test\.rb|_test\.py|\.(?:test|spec)\.[jt]sx?|(?:^|/)test_\w+\.py)(?::\S*)?$"
    r"|^(?:\./)?(?:spec|tests?)/|(?:^|/)__tests__/")
SUBSET_FLAG = re.compile(r"^--(?:findRelatedTests|onlyChanged|changedSince|only-failures|"
                         r"next-failure|lf|last-failed)(?:=|$)")


def related_args(tokens):
    skip = False
    for tok in tokens:
        if skip:
            skip = False
            continue
        if "<" in tok or ">" in tok:
            skip = tok.endswith((">", "<"))  # `>` or `2>`: the next token is its target
            continue
        if "$" in tok or "`" in tok or SUBSET_FLAG.search(tok) or TEST_PATH.search(tok):
            return True
    return False


def is_full(command):
    """True unless some runner in the command is given test paths."""
    blank = QUOTED.sub(lambda q: " " * len(q.group(0)), command)  # same offsets, no quoted text
    bounds = [0] + [i for m in SEGMENTS.finditer(blank) for i in m.span()] + [len(blank)]
    for start, end in zip(bounds[::2], bounds[1::2]):
        m = TEST_CMD.search(blank, start, end)
        if not m:
            continue
        args = command[m.end():end].replace('"', " ").replace("'", " ").split()
        if "xargs" in blank[start:m.start()].split() or related_args(args):
            return False
    return True

# NB on the RSpec pattern: a suite that fails to LOAD prints
#   "0 examples, 0 failures, 1 error occurred outside of examples"
# which a naive "0 failures" check reads as green. It is red — nothing ran. Real line, taken
# from this corpus; test 7 pins it.
RSPEC = re.compile(
    r"(\d+) examples?, (\d+) failures?"
    r"(?:, (\d+) errors? occurred outside of examples)?")
JEST = re.compile(r"^(?:Tests|Test Suites)[:\s].*$", re.MULTILINE)
# pytest banners the summary between runs of '=' on one line. Matched as "a banner line",
# then unwrapped — NOT as `=+ (.*?) =+`, which is quadratic: a 40k-character run of '=' took
# 13.7s to fail to match, past this hook's 10s timeout. A hook that times out fails open, so
# a slow regex here does not slow the gate down, it deletes it. Test 25 pins the bound.
PYTEST_BANNER = re.compile(r"^={3,}.*={3,}$", re.MULTILINE)
COUNTED = re.compile(r"\b\d+\s+(?:failed|passed|errors?)\b")

# Both halves of this matter, and both are checked against real transcripts:
#   - the COUNT is read, not just the word. ESLint prints "0 errors, 1 warning" on a clean
#     run, and a green `npm test` chained with a lint step was being called red.
#   - it is only ever applied to a summary line, never to the whole output, because the habit
#     here is to chain typecheck && test && lint into a single command.
FAILED_N = re.compile(r"\b(\d+)\s+(?:failed|failures?|errors?)\b")


def has_failures(summary):
    return any(int(n) > 0 for n in FAILED_N.findall(summary))


def allow():
    sys.exit(0)


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def summaries(text):
    """Every (kind, 'red'|'green', summary) in a test run's output, kind being the runner family.

    Every summary in the output is collected, not just the first: one command routinely runs
    the backend and the frontend suites, and a green backend must not mask a red frontend.
    """
    found = []
    for m in RSPEC.finditer(text):
        red = int(m.group(2)) > 0 or int(m.group(3) or 0) > 0
        found.append(("rspec", "red" if red else "green", m.group(0)))
    for line in JEST.findall(text):
        found.append(("jest", "red" if has_failures(line) else "green", line.strip()))
    for banner in PYTEST_BANNER.findall(text):
        inner = banner.strip("=").strip()
        if not COUNTED.search(inner):
            continue  # a bare separator line is decoration, not a verdict
        found.append(("pytest", "red" if has_failures(inner) else "green", inner))
    return found


def verdict(text):
    """('red'|'green', summary) for a test run, or None if this output is not one."""
    return pick(summaries(text))


def pick(found):
    if not found:
        return None
    for _, state, summary in found:
        if state == "red":
            return "red", summary
    return found[-1][1:]


def result_text(blk):
    c = blk.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(i.get("text", "") for i in c if isinstance(i, dict))
    return ""


def last_run(transcript_path):
    """The deciding (state, summary, command, held) in the transcript. Raises if unreadable.

    That is the most recent run, unless it is green and a red full run is still held — only a
    green full run of the same runner family releases one, so in a repo with a backend and a
    frontend suite a green jest run does not release a red rspec one — in which case it is the
    held run, with held=True.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        raise IOError("transcript not readable")
    commands = {}
    latest = None
    held = {}  # kind -> the red full run holding it
    with open(transcript_path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            content = (obj.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_use" and blk.get("name") == "Bash":
                    cmd = (blk.get("input") or {}).get("command", "")
                    if isinstance(cmd, str) and runs_tests(cmd):
                        commands[blk.get("id")] = cmd
                elif blk.get("type") == "tool_result":
                    cmd = commands.get(blk.get("tool_use_id"))
                    if cmd is None:
                        continue
                    found = summaries(result_text(blk))
                    v = pick(found)
                    if not v:  # no summary => not a run (e.g. `rspec --version`); keep the last
                        continue
                    latest = (v[0], v[1], cmd, False)
                    if not is_full(cmd):
                        continue
                    for kind in {k for k, _, _ in found}:
                        reds = [s for k, state, s in found if k == kind and state == "red"]
                        if reds:
                            held[kind] = ("red", reds[0], cmd, True)
                        else:
                            held.pop(kind, None)
    if latest and latest[0] != "red" and held:
        return next(iter(held.values()))
    return latest


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
        if os.environ.get("CLAUDE_RED_SUITE_SKIP") == "1":
            allow()
        if data.get("tool_name") != "Bash":
            allow()
        command = (data.get("tool_input") or {}).get("command") or ""
        if not GIT_COMMIT.search(command):
            allow()

        try:
            run = last_run(data.get("transcript_path") or "")
        except Exception:
            allow()  # cannot verify -> never wedge the commit

        if not run or run[0] != "red":
            allow()

        _, summary, cmd, held = run
        # Both come from the transcript. Bounded before being echoed: a chained one-liner here
        # runs to several hundred characters, and the block message is read by the model.
        cmd = cmd if len(cmd) <= 160 else cmd[:157] + "..."
        summary = summary if len(summary) <= 120 else summary[:117] + "..."
        if held:
            head = ("Blocked: the last FULL test run in this session was RED, and this is a "
                    "commit.\n")
            how = ("A later green run did not clear it: only a green full run of the same suite "
                   "does, and\na related-tests run is not one. Run the runner with no path "
                   "arguments, or the lefthook form\nwhere pre-push queues the suite:\n"
                   "  SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out "
                   "lefthook run pre-push --force --no-tty --command <name>\n")
        else:
            head = "Blocked: the last test run in this session was RED, and this is a commit.\n"
            how = "Fix the failures, then run the suite again — a green run clears this gate.\n"
        block(
            head +
            f"  command: {cmd}\n"
            f"  verdict: {summary}\n" +
            how +
            "If it is already green, re-run it so the gate can see the result; the gate only\n"
            "believes output it has observed, never a claim that it passes.\n"
            "To commit over a red suite on purpose: CLAUDE_RED_SUITE_SKIP=1 (an env var, so it\n"
            "dies with the shell and cannot be left on and forgotten)."
        )
    except SystemExit:
        raise
    except Exception:
        allow()


if __name__ == "__main__":
    main()
