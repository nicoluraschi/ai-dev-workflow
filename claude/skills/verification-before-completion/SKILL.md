---
name: verification-before-completion
description: "Run the real verification commands and show their output before any claim that work is done, fixed, passing, or ready. Fires at the Verify phase of feature-workflow, before opening or merging a PR, before reporting a task complete, and the moment you are about to write 'done', 'fixed', 'it works', 'tests pass', 'ready to merge', 'listo' or 'ya está'. Also fires before handing a change back for review. Evidence before assertions: never assert a state you have not observed in command output in this session."
---

# Verification Before Completion

Source: https://github.com/obra/superpowers/tree/main/skills/verification-before-completion (MIT, modified, see `LICENSE` in this directory).

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

**Suites queued by `suite-queue`.** When the repo's lefthook pre-push runs a suite through
`suite-queue`, run it as
`SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out lefthook run pre-push --force --no-tty --command <name>`
— the same command the push runs, so the passing result lets the push skip it. The force makes this
a fresh run; a `suite-queue: skipped` line is a previous run, not evidence. `LEFTHOOK_OUTPUT` shows
the runner's output even where lefthook.yml sets `output: [failure]`, which prints nothing for a
green run: no summary means no evidence.

**Review-fix rounds: related tests per round, the full suite once after the last.** Each fix
changes the content, so a full run per round is one the push can never skip — a full Jest run can
take 6+ minutes, so a full run per fix round is wasted.
- While fixing, run only the tests for the files a fix touched (`rspec <spec files>`,
  `jest --findRelatedTests <files>`). Read the examples/failures line: a coverage-threshold exit
  on a subset (SimpleCov `minimum_coverage`, Jest `coverageThreshold`) is an artifact of the
  subset, not a red.
- A related run is evidence for that fix, never for "done", "ready" or "tests pass". Don't commit
  between rounds: `no-commit-on-red` holds a red full run until a green full run clears it, but
  it can't tell that a green full run predates your fixes, so a green subset after it passes.
- Never start the full suite while a review is running or its fixes are pending: a run that
  predates the last fix is spent. Reviews are capped at two rounds (`feature-workflow` phase 6,
  `trivial-lane-check` *Light lane*), so the last one is known.
- After the last round, if any fix changed code, run the full suite once in the lefthook form
  above and re-check coverage on the changed code. That run is what the commit, the push skip and
  the PR rest on.

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don't believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you'll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.
