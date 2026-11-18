#!/usr/bin/env python3
"""Tests for no-commit-on-red.py.

Run: python3 claude/hooks/test_no_commit_on_red.py

The hook reads the session transcript backwards for the most recent test run that
produced a parseable verdict, and refuses `git commit` if that verdict was red.
Exit 0 = allow, exit 2 = block.

The verdicts below are copied from real transcripts, not invented — including the
RSpec load-error line, which says "0 failures" and is red anyway.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-commit-on-red.py")

RSPEC_GREEN = "Finished in 2.71 seconds\n326 examples, 0 failures\nCoverage: 98.02%"
RSPEC_RED = "Failures:\n  1) User is valid\n\nFinished in 1.2 seconds\n3 examples, 1 failure"
# Real, and the trap: "0 failures" but the suite never loaded.
RSPEC_LOAD_ERROR = "An error occurred while loading ./spec/models/user_spec.rb.\n0 examples, 0 failures, 1 error occurred outside of examples"
RSPEC_VERSION = "RSpec 3.13 - rspec-core 3.13.6 - rspec-expectations 3.13.5"

JEST_GREEN = "Test Suites: 62 passed, 62 total\nTests:       457 passed, 457 total"
JEST_RED = "Test Suites: 1 failed, 61 passed, 62 total\nTests:       1 failed, 13 passed, 14 total"
PYTEST_RED = "=========== 1 failed, 5 passed in 0.52s ============"
PYTEST_GREEN = "=========== 6 passed in 0.48s ============"

# Verbatim from a real session transcript. The habit here is to chain the whole
# tool-chain into one command, so the test summary arrives surrounded by lint and typecheck
# output. ESLint's "0 errors, 1 warning" must not read as red: the failure search is scoped
# to the summary and ignores a ZERO count.
CHAINED_GREEN = """> tsc --noEmit

Test Suites: 46 passed, 46 total
Tests:       349 passed, 349 total
Snapshots:   0 total
Time:        8.2 s

=== lint ===
/Users/x/web/src/app/page.tsx
  12:7  warning  'x' is assigned a value but never used

\u2716 1 problem (0 errors, 1 warning)
0 errors and 1 warning potentially fixable with the `--fix` option."""

CHAINED_RED = """> tsc --noEmit

Test Suites: 1 failed, 45 passed, 46 total
Tests:       2 failed, 347 passed, 349 total

=== lint ===
\u2716 0 problems (0 errors, 0 warnings)"""

# backend and frontend suites in a single chained command
BOTH_BACKEND_RED = """326 examples, 0 failures

=== web ===
Test Suites: 1 failed, 61 total
Tests:       1 failed, 13 passed, 14 total"""

BOTH_GREEN = RSPEC_GREEN + "\n\n" + JEST_GREEN

# Verbatim from `lefthook run pre-push --force --no-tty --command rspec` (lefthook v2.1.10), box
# glyphs and colour codes included: the runner's own lines come through undecorated.
LEFTHOOK_RSPEC_RED = (
    "\x1b[38;2;0;0;0m│\x1b[m 🥊 lefthook  v2.1.10   hook:  \x1b[1mpre-push\x1b[m \x1b[38;2;56;56;56m│\x1b[m\n"
    "sync hooks: ✔️(pre-push)\n┃  rspec ❯ \nFinished in 1s\n3 examples, 1 failure\n\nexit status 1\n"
    "\x1b[38;2;56;56;56m  ────────────────────────────────────\x1b[m\n"
    "summary: (done in 0.01 seconds)\n🥊 rspec (0.01 seconds)")
LEFTHOOK_JEST_GREEN = (
    "┃  jest ❯ \nTest Suites: 2 passed, 2 total\nTests:       4 passed, 4 total\n\n"
    "summary: (done in 0.01 seconds)\n✔️ jest (0.01 seconds)")

results = []


def run(payload, env=None):
    e = dict(os.environ)
    e.pop("CLAUDE_RED_SUITE_SKIP", None)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, HOOK],
                          input=payload if isinstance(payload, str) else json.dumps(payload),
                          capture_output=True, text=True, timeout=15, env=e)


def pre(command, transcript="", tool="Bash"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"command": command}, "session_id": "s1",
            "transcript_path": transcript}


def transcript(path, runs):
    """runs: list of (command, output, is_error). Written in order, oldest first."""
    lines = []
    for i, (cmd, out, err) in enumerate(runs):
        tid = f"tu_{i}"
        lines.append(json.dumps({"timestamp": f"2026-09-24T10:0{i}:00.000Z", "message": {
            "role": "assistant", "content": [
                {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}))
        lines.append(json.dumps({"timestamp": f"2026-09-24T10:0{i}:30.000Z", "message": {
            "role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": out, "is_error": err}]}}))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  -- " + detail) if detail and not cond else ""))


def main():
    with tempfile.TemporaryDirectory() as td:
        t = lambda n, runs: transcript(os.path.join(td, f"{n}.jsonl"), runs)

        # --- the core contract ---
        p = run(pre("git commit -m 'wip'", t("a1", [("bundle exec rspec", RSPEC_RED, False)])))
        check("1. red rspec blocks the commit", p.returncode == 2, f"rc={p.returncode}")

        p = run(pre("git commit -m 'ok'", t("a2", [("bundle exec rspec", RSPEC_GREEN, False)])))
        check("2. green rspec allows the commit", p.returncode == 0, f"rc={p.returncode} {p.stderr[:120]}")

        p = run(pre("git commit -m 'wip'", t("a3", [("npm test", JEST_RED, False)])))
        check("3. red jest blocks", p.returncode == 2, f"rc={p.returncode}")

        p = run(pre("git commit -m 'ok'", t("a4", [("npm test", JEST_GREEN, False)])))
        check("4. green jest allows", p.returncode == 0, f"rc={p.returncode}")

        p = run(pre("git commit -m 'x'", t("a5", [("pytest", PYTEST_RED, False)])))
        check("5. red pytest blocks", p.returncode == 2, f"rc={p.returncode}")

        p = run(pre("git commit -m 'x'", t("a6", [("pytest", PYTEST_GREEN, False)])))
        check("6. green pytest allows", p.returncode == 0, f"rc={p.returncode}")

        # --- the trap: "0 failures" that is actually red ---
        p = run(pre("git commit -m 'x'", t("a7", [("bundle exec rspec", RSPEC_LOAD_ERROR, False)])))
        check("7. rspec load error is red despite saying '0 failures'",
              p.returncode == 2, f"rc={p.returncode}")

        # --- the real reason is_error cannot be trusted: the pipe eats the exit code ---
        p = run(pre("git commit -m 'x'",
                    t("a8", [("bundle exec rspec 2>&1 | tail -12", RSPEC_RED, False)])))
        check("8. a piped red run still blocks (is_error was False)",
              p.returncode == 2, f"rc={p.returncode}")

        # --- most recent verdict wins ---
        p = run(pre("git commit -m 'x'", t("a9", [("bundle exec rspec", RSPEC_RED, False),
                                                  ("bundle exec rspec", RSPEC_GREEN, False)])))
        check("9. green after red allows", p.returncode == 0, f"rc={p.returncode}")

        p = run(pre("git commit -m 'x'", t("a10", [("bundle exec rspec", RSPEC_GREEN, False),
                                                   ("bundle exec rspec", RSPEC_RED, False)])))
        check("10. red after green blocks", p.returncode == 2, f"rc={p.returncode}")

        # --- a command that is not a test run must not be mistaken for one ---
        p = run(pre("git commit -m 'x'", t("a11", [("bundle exec rspec", RSPEC_RED, False),
                                                   ("bundle exec rspec --version", RSPEC_VERSION, False)])))
        check("11. `rspec --version` is not a run, so the red verdict still stands",
              p.returncode == 2, f"rc={p.returncode}")

        # --- silence is not red ---
        p = run(pre("git commit -m 'x'", t("a12", [("ls -la", "a\nb", False)])))
        check("12. no test run at all allows the commit", p.returncode == 0, f"rc={p.returncode}")

        # --- scope: only git commit, only Bash ---
        p = run(pre("git status", t("a13", [("bundle exec rspec", RSPEC_RED, False)])))
        check("13. a non-commit command is untouched", p.returncode == 0, f"rc={p.returncode}")

        p = run(pre("git commit -m 'x'", t("a14", [("bundle exec rspec", RSPEC_RED, False)]),
                    tool="Edit"))
        check("14. a non-Bash tool is untouched", p.returncode == 0, f"rc={p.returncode}")

        p = run(pre("echo 'remember to git commit later'",
                    t("a15", [("bundle exec rspec", RSPEC_RED, False)])))
        check("15. `git commit` inside a quoted string is not a commit",
              p.returncode == 0, f"rc={p.returncode}")

        p = run(pre("git add -A && git commit -m 'x'",
                    t("a16", [("bundle exec rspec", RSPEC_RED, False)])))
        check("16. a chained git commit is caught", p.returncode == 2, f"rc={p.returncode}")

        p = run(pre("git commit --amend --no-edit",
                    t("a17", [("bundle exec rspec", RSPEC_RED, False)])))
        check("17. --amend is caught too", p.returncode == 2, f"rc={p.returncode}")

        # --- regressions found by running the parser over real transcripts ---
        p = run(pre("git commit -m 'x'", t("a21", [("npm run typecheck && npm test && npm run lint",
                                                    CHAINED_GREEN, False)])))
        check("21. green suite chained with lint output is NOT red ('0 errors' is not a failure)",
              p.returncode == 0, f"rc={p.returncode} :: {p.stderr[:200]}")

        p = run(pre("git commit -m 'x'", t("a22", [("npm run typecheck && npm test && npm run lint",
                                                    CHAINED_RED, False)])))
        check("22. a genuinely red suite still blocks through the same noise",
              p.returncode == 2, f"rc={p.returncode}")

        p = run(pre("git commit -m 'x'", t("a23", [("bundle exec rspec && npm test",
                                                    BOTH_BACKEND_RED, False)])))
        check("23. green backend + red frontend in one command is red",
              p.returncode == 2, f"rc={p.returncode}")

        p = run(pre("git commit -m 'x'", t("a24", [("npm test", "Tests:       0 failed, 12 passed, 12 total", False)])))
        check("24. an explicit '0 failed' is green", p.returncode == 0, f"rc={p.returncode}")

        # --- a command that TALKS about tests is not a command that RUNS them ---
        # Real false positive, caught by sweeping the corpus: a research command carrying
        # `echo "=== what a red rspec summary looks like ==="` matched the pre-filter, and its
        # output (literal RSpec summary lines, because it was grepping for them) was then read
        # as a verdict. Quoted strings are stripped before the pre-filter runs.
        TALKS = ('cd /x && echo "=== what a red rspec summary looks like ===" && '
                 'grep -rhoE "[0-9]+ examples?, [0-9]+ failures?" /tmp/t.jsonl')
        p = run(pre("git commit -m 'x'",
                    t("a27", [(TALKS, "0 examples, 0 failures, 1 error occurred outside of examples",
                               False)])))
        check("27. a command that only mentions rspec in a quoted string is not a test run",
              p.returncode == 0, f"rc={p.returncode} :: {p.stderr[:160]}")

        # ...but a real run whose env var happens to be quoted is still a run
        REAL = 'DATABASE_URL="postgres://u:p@localhost:5433/db" RAILS_ENV=test bundle exec rspec 2>&1 | tail -12'
        p = run(pre("git commit -m 'x'", t("a28", [(REAL, RSPEC_RED, False)])))
        check("28. quoted env vars do not hide a real run", p.returncode == 2, f"rc={p.returncode}")

        # --- the parser must stay linear on hostile output ---
        # A hook that exceeds its 10s timeout fails open, so a quadratic regex does not just
        # slow the commit down: it silently deletes the gate. Measured at 13.7s before the fix.
        import time as _t
        import importlib.util as _il
        _sp = _il.spec_from_file_location("hook", HOOK)
        _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
        worst = 0.0
        for hostile in ("=" * 40000, "=" * 3 + ("x" * 4000 + " 1 fail") * 20 + "=" * 3,
                        "x" * 400000, "Tests:   1 passed\n" * 20000):
            _t0 = _t.time(); _m.verdict(hostile); worst = max(worst, _t.time() - _t0)
        check("25. the parser stays fast on pathological output (no catastrophic backtracking)",
              worst < 1.0, f"worst={worst:.2f}s")

        p = run(pre("git commit -m 'x'", t("a26", [("pytest", "=" * 40000, False)])))
        check("26. a wall of '=' is not a verdict", p.returncode == 0, f"rc={p.returncode}")

        # --- Verify runs suites through lefthook (suite-queue); the gate must still see them ---
        lh = "SUITE_QUEUE_FORCE=1 lefthook run pre-push --force --no-tty --command "
        p = run(pre("git commit -m 'x'", t("a27", [(lh + "rspec", RSPEC_RED, False)])))
        check("27. a red rspec run through lefthook blocks", p.returncode == 2, f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a28", [(lh + "rspec", RSPEC_GREEN, False)])))
        check("28. a green rspec run through lefthook allows", p.returncode == 0, f"rc={p.returncode}")
        # a command named `test`: no runner name in it, only the lefthook form matches
        p = run(pre("git commit -m 'x'", t("a29", [(lh + "test", JEST_RED, False)])))
        check("29. a red run through lefthook --command test blocks", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a30", [(lh + "rspec", LEFTHOOK_RSPEC_RED, False)])))
        check("30. real lefthook framing around a red rspec still blocks", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a31", [(lh + "jest", LEFTHOOK_JEST_GREEN, False)])))
        check("31. real lefthook framing around a green jest allows", p.returncode == 0,
              f"rc={p.returncode}")

        # --- review-fix rounds run related tests; only a green FULL run clears a red full one ---
        related_rb = "bundle exec rspec spec/models/user_spec.rb"
        p = run(pre("git commit -m 'x'", t("a32", [("bundle exec rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False)])))
        check("32. a green related run does not clear a red full run", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a33", [(lh + "jest", JEST_RED, False),
                                                   ("npx jest --findRelatedTests src/a.ts",
                                                    JEST_GREEN, False)])))
        check("33. --findRelatedTests green does not clear a red lefthook run", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a34", [("bundle exec rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False),
                                                   (lh + "rspec", RSPEC_GREEN, False)])))
        check("34. a green full run after the related one clears it", p.returncode == 0,
              f"rc={p.returncode} :: {p.stderr[:160]}")
        p = run(pre("git commit -m 'x'", t("a35", [("bundle exec rspec", RSPEC_GREEN, False),
                                                   (related_rb, RSPEC_RED, False)])))
        check("35. a red related run still blocks", p.returncode == 2, f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a36", [(related_rb, RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False)])))
        check("36. a green related run clears a red related run", p.returncode == 0,
              f"rc={p.returncode} :: {p.stderr[:160]}")
        p = run(pre("git commit -m 'x'", t("a37", [("bundle exec rspec", RSPEC_RED, False),
                                                   ("bundle exec rspec spec/x_spec.rb:42",
                                                    RSPEC_GREEN, False)])))
        check("37. `spec/x_spec.rb:42` is a related run", p.returncode == 2, f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a38", [
            ("bundle exec rspec", RSPEC_RED, False),
            ("bundle exec rspec --format progress 2>&1 | tail -12", RSPEC_GREEN, False)])))
        check("38. flags, redirects and pipes are not paths: still a full run", p.returncode == 0,
              f"rc={p.returncode} :: {p.stderr[:160]}")
        p = run(pre("git commit -m 'x'", t("a39", [
            ("bundle exec rspec", RSPEC_RED, False),
            ("bundle exec rspec && npm test -- src/a.test.ts", BOTH_GREEN, False)])))
        check("39. a chain with one related runner is a related run", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a40", [("bundle exec rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False)])),
                env={"CLAUDE_RED_SUITE_SKIP": "1"})
        check("40. the env override releases a held full-run red", p.returncode == 0,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a41", [("bundle exec rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False)])))
        msg = p.stderr
        check("41. the block names the full run and says a related run does not clear it",
              "command: bundle exec rspec\n" in msg and "related" in msg
              and "no path arguments" in msg, msg[:300])

        # --- paths that are not literal tokens are still a related run ---
        for n, cmd in (("42", "git diff --name-only | xargs bundle exec rspec"),
                       ("43", "bundle exec rspec $(git diff --name-only -- spec)"),
                       ("44", 'npx jest --findRelatedTests "src/a.ts"')):
            p = run(pre("git commit -m 'x'", t("a" + n, [(lh + "rspec", RSPEC_RED, False),
                                                         (cmd, RSPEC_GREEN, False)])))
            check(f"{n}. `{cmd}` is a related run", p.returncode == 2, f"rc={p.returncode}")

        # --- a slash in a flag value or a redirect target is not a test path ---
        p = run(pre("git commit -m 'x'", t("a45", [
            ("npx jest --config config/jest.config.js", JEST_RED, False),
            ("npx jest src/a.test.ts", JEST_GREEN, False)])))
        check("45. `--config dir/file` keeps the run full", p.returncode == 2, f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a46", [
            ("bundle exec rspec > /tmp/rspec.log; tail -20 /tmp/rspec.log", RSPEC_RED, False),
            (related_rb, RSPEC_GREEN, False)])))
        check("46. a redirect target keeps the run full", p.returncode == 2, f"rc={p.returncode}")

        # --- one suite's green full run does not release another suite's red one ---
        p = run(pre("git commit -m 'x'", t("a47", [("bundle exec rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False),
                                                   ("npm test", JEST_GREEN, False)])))
        check("47. a green full jest run does not clear a red full rspec run", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a48", [
            ("bundle exec rspec && npm test", BOTH_BACKEND_RED, False),
            (related_rb, RSPEC_GREEN, False),
            ("bundle exec rspec && npm test", BOTH_GREEN, False)])))
        check("48. a green full run of both suites clears both", p.returncode == 0,
              f"rc={p.returncode} :: {p.stderr[:160]}")

        # --- the runners' own rerun-a-subset flags, and paths not at the start of a token ---
        for n, full, cmd, out in (
                ("49", "bundle exec rspec", "bundle exec rspec --only-failures", RSPEC_GREEN),
                ("50", "pytest", "pytest --lf", PYTEST_GREEN),
                ("51", "npx jest", "npx jest --onlyChanged", JEST_GREEN),
                ("52", "pytest", "pytest claude/hooks/test_x.py", PYTEST_GREEN),
                ("53", "pytest", "pytest test_a.py::test_x", PYTEST_GREEN),
                ("54", "npx jest", "npx jest src/__tests__/foo.js", JEST_GREEN)):
            red = {"pytest": PYTEST_RED, "npx jest": JEST_RED}.get(full, RSPEC_RED)
            p = run(pre("git commit -m 'x'", t("a" + n, [(full, red, False), (cmd, out, False)])))
            check(f"{n}. `{cmd}` is a related run", p.returncode == 2, f"rc={p.returncode}")

        # --- a runner name quoted in a later pipe segment does not make the run related ---
        p = run(pre("git commit -m 'x'", t("a55", [
            ('bundle exec rspec 2>&1 | grep "rspec ./spec/"', RSPEC_RED, False),
            (related_rb, RSPEC_GREEN, False)])))
        check("55. a quoted `rspec ./spec/` in a grep keeps the run full", p.returncode == 2,
              f"rc={p.returncode}")

        # --- `$` outside the runner's arguments does not make the run related ---
        for n, cmd in (("56", "bundle exec rspec > $TMPDIR/r.log 2>&1"),
                       ("57", "DATABASE_URL=$TEST_DB bundle exec rspec")):
            p = run(pre("git commit -m 'x'", t("a" + n, [("bundle exec rspec", RSPEC_RED, False),
                                                         (cmd, RSPEC_GREEN, False)])))
            check(f"{n}. `{cmd}` is a full run and clears the hold", p.returncode == 0,
                  f"rc={p.returncode} :: {p.stderr[:160]}")

        # --- the Verify form forces lefthook's output back (repos with `output: [failure]`) ---
        lho = ("SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out "
               "lefthook run pre-push --force --no-tty --command ")
        p = run(pre("git commit -m 'x'", t("a58", [(lho + "rspec", LEFTHOOK_RSPEC_RED, False)])))
        check("58. a red run in the output-forcing form blocks", p.returncode == 2,
              f"rc={p.returncode}")
        p = run(pre("git commit -m 'x'", t("a59", [(lho + "jest", LEFTHOOK_JEST_GREEN, False)])))
        check("59. a green run in the output-forcing form allows", p.returncode == 0,
              f"rc={p.returncode} :: {p.stderr[:160]}")
        p = run(pre("git commit -m 'x'", t("a60", [(lho + "rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False),
                                                   (lho + "rspec", RSPEC_GREEN, False)])))
        check("60. the output-forcing form is a full run and clears a held red", p.returncode == 0,
              f"rc={p.returncode} :: {p.stderr[:160]}")
        p = run(pre("git commit -m 'x'", t("a61", [(lho + "rspec", RSPEC_RED, False),
                                                   (related_rb, RSPEC_GREEN, False)])))
        check("61. a held red from the output-forcing form names that form",
              p.returncode == 2 and lho + "<name>" in p.stderr, p.stderr[:400])

        # --- escape hatch, and failing open ---
        p = run(pre("git commit -m 'x'", t("a18", [("bundle exec rspec", RSPEC_RED, False)])),
                env={"CLAUDE_RED_SUITE_SKIP": "1"})
        check("18. the env override releases the gate", p.returncode == 0, f"rc={p.returncode}")

        a = run("not json").returncode == 0
        b = run(pre("git commit -m 'x'", os.path.join(td, "missing.jsonl"))).returncode == 0
        c = run(pre("git commit -m 'x'", "")).returncode == 0
        check("19. fails open on bad input / missing / absent transcript", a and b and c,
              f"{a} {b} {c}")

        # --- the message has to be actionable ---
        p = run(pre("git commit -m 'x'", t("a20", [("bundle exec rspec", RSPEC_RED, False)])))
        msg = p.stderr
        check("20. the block names the failing run and how to proceed",
              "rspec" in msg and ("1 failure" in msg or "failure" in msg)
              and "CLAUDE_RED_SUITE_SKIP" in msg, msg[:240])

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
