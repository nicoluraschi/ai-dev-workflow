# Gate 1b — 2026-09-codex-6b-pr-scope

- **artifact:** `docs/design/2026-09-codex-6b-pr-scope.md`
- **date:** 2026-09-25 12:34
- **reviewer:** codex `codex-cli 0.152.0`, profile `audit`
- **profile:** `docs/ai-profile.md`
- **rounds:** 2

## Round 1 — Codex

## BLOCKER

None.

## MAJOR

### 1b-F01 — Prompt assertions do not verify that Gate 6b honors the scope
- evidence: `docs/design/2026-09-codex-6b-pr-scope.md:109-113,132-136` — AC1, AC2, AC11, and AC12 inspect only the assembled prompt.
- failure path: All criteria pass if the prompt contains the new instructions but the reviewer ignores them and continues emitting the two known out-of-scope findings. The feature then provides no operational benefit.
- smallest fix: Add a consumer-level criterion requiring the resulting review to omit the named out-of-scope findings while still detecting a known in-scope violation.

### 1b-F02 — Unresolvable scopes contradict the requirement to fail loudly
- evidence: `docs/design/2026-09-codex-6b-pr-scope.md:97-102,148-151` — SR3 forbids scopes resolving to nothing, but undefined task numbers and plans without task lists are allowed to reach the reviewer without an acceptance criterion governing the result.
- failure path: A typo such as `--tasks 99`, or a plan lacking the expected task structure, selects zero criteria. D1 then permits an empty review that appears clean—the exact false-success state SR3 says must never occur.
- smallest fix: Define acceptance criteria for undefined requested tasks and missing task lists, requiring an unmistakable failure rather than a clean scoped review.

### 1b-F03 — The documented task source uses a range character rejected by the required grammar
- evidence: `docs/design/2026-09-codex-6b-pr-scope.md:89-93,138-140`; `claude/skills/feature-workflow/SKILL.md:190-194` — SR1 permits ASCII `-`, while the delivery-table example that AC13 names as the source uses en dashes (`1–3`, `4–8`).
- failure path: Following the documented procedure by copying a task range from the standard delivery table causes validation to reject the Gate 6b invocation.
- smallest fix: Require the delivery table and CLI invocation to use the same canonical range syntax, or explicitly define the required transcription.

### 1b-F04 — Rejection of `--tasks` on gates 1b and 2b has no acceptance criterion
- evidence: `docs/design/2026-09-codex-6b-pr-scope.md:94-96,129-130,150` — the edge-case table promises a usage error, but AC10 checks only that the reviewer contract is unchanged.
- failure path: An implementation may accept the flag on 1b or 2b and place its narrowing instruction in those gates’ prompt bodies while satisfying every stated criterion, suppressing findings in gates that are explicitly not scoped.
- smallest fix: Add criteria requiring `--tasks` on gates 1b and 2b to fail before creating files or invoking Codex.

## MINOR

- Repeated `--tasks` arguments have no defined outcome, so a parser could silently choose one scope and discard another.
<!-- round 1 wall clock: 121s -->

## Response to round 1 — Claude

| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | MAJOR | accepted | AC12b added: the prompt assertions cannot prove the reviewer honours the scope, so it is verified once by hand against the motivating case — re-run 6b on the multi-PR feature that motivated this change with --tasks 4-8,10,11, confirm 6b-F02 is gone while an in-scope violation is still reported, record the result in §4 before shipping. Deliberately not a unit test: the suite stubs Codex so no tokens are spent, and a non-deterministic reviewer cannot be one. |
| 1b-F02 | MAJOR | accepted | Real contradiction between SR3 and the edge-case table. Resolved by D6: the wrapper cannot see that --tasks 99 selects nothing without parsing the plan (D2 refuses that), so the obligation moves to where the resolution happens — the prompt now requires an explicit failure finding when the scope resolves to no criteria or the plan has no task list. SR3 amended to say the grammar carries only half; AC5b added; two edge-table rows corrected. |
| 1b-F03 | MAJOR | accepted | Confirmed against the real artifact: a real delivery table uses en dashes (1–3, 4–8) and SR1 admits ASCII - only. Kept ASCII-only rather than widening the grammar, since sanitising is against SR1's posture on an allowlisted command. D7 added, AC9b requires the error message to name the en-dash case, AC13b requires the skill to state the transcription. |
| 1b-F04 | MAJOR | accepted | SR5 and AC5c added: --tasks on gate 1b or 2b exits non-zero before any file is created and before codex runs. The failure path is right — accepting it there would let a caller inject a narrowing instruction into a gate the spec never scoped, suppressing its findings. Edge-table row now points at the criterion instead of promising a bare usage error. |

## Round 2 — Codex

## Verdicts

| id | round-1 severity | response | verdict | note |
|---|---|---|---|---|
| 1b-F01 | MAJOR | accepted | resolved | AC12b verifies the consumed review output against the motivating case and prevents an empty review from passing. |
| 1b-F02 | MAJOR | accepted | not resolved | AC5b verifies only that the prompt contains an obligation; unlike AC12b, it never verifies that an undefined task or missing task list actually produces the required failure finding, so the silent-clean-review path remains. |
| 1b-F03 | MAJOR | accepted | resolved | D7, AC9b, and AC13b define the ASCII transcription, make the common mistake diagnosable, and ensure the documented procedure supplies accepted input. |
| 1b-F04 | MAJOR | accepted | resolved | SR5 and AC5c require both unsupported gates to fail before creating files or invoking Codex. |

## Regressions

None.
<!-- round 2 wall clock: 46s -->

## For the human

These did not close. Nothing below was settled between the models — each one needs you.

| id | severity | why it is open | note |
|---|---|---|---|
| 1b-F02 | MAJOR | fix did not close it | AC5b verifies only that the prompt contains an obligation; unlike AC12b, it never verifies that an undefined task or missing task list actually produces the required failure finding, so the silent-clean-review path remains.

## Metrics

| | |
|---|---|
| round-1 findings (BLOCKER+MAJOR) | 4 |
| accepted / rejected / human | 4 / 0 / 0 |
| resolved / not resolved | 3 / 1 |
| conceded / maintained | 0 / 0 |
| regressions found in round 2 | 0 |
| still open for the human | 1 |
| wall clock | round 1 121s · round 2 46s |
