# Gate 2b — 2026-09-codex-6b-pr-scope

- **artifact:** `docs/design/plans/2026-09-codex-6b-pr-scope.md`
- **date:** 2026-09-25 12:41
- **reviewer:** codex `codex-cli 0.152.0`, profile `audit`
- **profile:** `docs/ai-profile.md`
- **rounds:** 2

## Round 1 — Codex

## BLOCKER

None.

## MAJOR

### 2b-F01 — The prompt design does not explain how unscoped output remains byte-identical
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:37-43` adds a `{{TASKS}}` substitution and static instructions to `codex/prompts/6b.md`, while AC3 requires the unscoped prompt to remain byte-identical.
- failure path: Adding the instructions from Tasks 7–9 to the template changes every unscoped 6b prompt. Replacing only `{{TASKS}}` with an empty value still leaves the surrounding instruction or an extra line, failing AC3 and changing existing single-PR reviews.
- smallest fix: Specify a conditional scoped-instruction fragment that is spliced only when `--tasks` is present and emits zero bytes otherwise; compare against an immutable pre-change prompt fixture.

### 2b-F02 — The measured-case prompt tests pass when scoping is entirely absent
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:66-67`; the existing assembly at `codex/bin/codex-audit:399-400` inserts paths, not plan contents.
- failure path: `AC-25` and the fixture’s reset criteria are already absent from the assembled prompt because the reviewer reads them from the plan file. Both `check_absent` assertions pass even if `--tasks` is ignored and none of the resolve-only, silence, or fail-loudly instructions exists.
- smallest fix: Assert positively that the prompt contains the supplied task range, the plan path, and the exact obligations for selected criteria, silence, and unresolvable scopes. Retain AC12b/AC12c for consumer-level behavior.

### 2b-F03 — Invalid-input tests do not prove rejection precedes the outbound Codex call
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:59-60` checks exit status and ledger absence, whereas spec AC8 at `docs/design/2026-09-codex-6b-pr-scope.md:168-170` requires rejection before any file or Codex invocation.
- failure path: An invalid value such as `4-8;rm -rf /` could reach the prompt sent to Codex, followed by a non-zero exit without a ledger, and the planned test would pass. This is the security-relevant boundary of the allowlisted wrapper.
- smallest fix: For every AC8 input, clear and assert the Codex stub’s exec-call log remains absent, as already planned for AC4 and AC5c.

### 2b-F04 — The two manual validations collide on the same protected ledger
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:46`; D5 keeps paths independent of `--tasks` at `docs/design/2026-09-codex-6b-pr-scope.md:155-156`; `codex/bin/codex-audit:344-354` refuses a second round-1 run on that ledger.
- failure path: After the scoped motivating-case run writes the PR’s ledger, the `--tasks 99` run resolves to the same path and is refused before reaching Codex. Task 15 therefore cannot complete both AC12b and AC12c as sequenced.
- smallest fix: Specify the existing human-approved `--rerun` path for the second validation and record the first result before replacing it; the wrapper will archive the first ledger.

### 2b-F05 — The first implementation step temporarily accepts a scope it does not honor
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:32-40` accepts and validates `--tasks` in Task 1, but does not give it scoping semantics until Tasks 7–9.
- failure path: If work stops after Tasks 1–6, an agent can run the allowlisted command with `--tasks`, receive a full-spec review, and treat it as scoped—recreating the false BLOCKER/MAJOR behavior this change exists to remove.
- smallest fix: Land argument acceptance and the conditional prompt semantics atomically, or keep `--tasks` rejected as unsupported until Tasks 7–9 are complete.

## MINOR

- `docs/design/plans/2026-09-codex-6b-pr-scope.md:70` checks only that an unscoped ledger lacks a scope line; AC7 requires the entire header to remain byte-identical.
- Task 10 does not mention the separate skip-ledger header writer at `codex/bin/codex-audit:292-302`; clarify whether AC6 applies there and test it if it does.
<!-- round 1 wall clock: 198s -->

## Response to round 1 — Claude

| id | severity | status | change / reason |
|---|---|---|---|
| 2b-F01 | MAJOR | accepted | Correct: static instructions in 6b.md change every unscoped prompt. The scoped instructions move to a separate fragment codex/prompts/6b.scope.md, spliced at a {{TASKS_SCOPE}} placeholder alone on its line; splice drops that line and prints the fragment's, so an absent --tasks splices an empty file and the line vanishes — zero bytes, not a blank line. AC3 is now proven against a golden fixture captured from the PRE-change wrapper and committed as task 1, since a byte-identical claim measured against post-change code proves nothing. |
| 2b-F02 | MAJOR | accepted | The strongest finding of this gate. The prompt carries paths, not plan contents, so check_absent "AC-25" passes whether or not scoping exists. Every prompt test now asserts positively: the range verbatim, the plan path, and each of the three obligations (resolve-only, silence, fail-loudly). Added the mirror test that an unscoped run contains none of the three. Consumer behaviour stays with AC12b/AC12c. |
| 2b-F03 | MAJOR | accepted | Exit code plus ledger absence does not prove the value never left, and that is the security boundary of an allowlisted wrapper. The stub gains an exec-call log; every AC8 and AC9 input now asserts it stays empty, matching what was already planned for AC4 and AC5c. |
| 2b-F04 | MAJOR | accepted | Real sequencing defect: D5 keeps --tasks out of the ledger path, so AC12c meets the round-1 overwrite guard left by AC12b and cannot run as sequenced. Task 15 is now explicit — run AC12b, record its result in spec section 4, then run AC12c with --rerun, which archives rather than destroys. The ask rule on --rerun prompts, which is correct for a by-hand validation. |
| 2b-F05 | MAJOR | accepted | Accepting the flag before the prompt honours it would hand an agent a full-spec review that looks scoped — the exact failure this change removes. The order of work was restructured: the fragment and the substitution land first, and --tasks becomes reachable only in the same commit that gives it meaning (tasks 5 and 6 are one commit). |

## Round 2 — Codex

## Verdicts

| id | round-1 severity | response | verdict | note |
|---|---|---|---|---|
| 2b-F01 | MAJOR | accepted | resolved | Conditional fragment splicing removes the scoped block without leaving bytes in unscoped prompts. |
| 2b-F02 | MAJOR | accepted | resolved | Positive assertions now verify the range, plan path, and all three scoping obligations. |
| 2b-F03 | MAJOR | accepted | resolved | The exec-call log directly verifies that rejected values never reach Codex. |
| 2b-F04 | MAJOR | accepted | resolved | Recording AC12b before an archival `--rerun` makes both validations executable without losing evidence. |
| 2b-F05 | MAJOR | accepted | not resolved | Tasks 5–6 expose `--tasks` before Tasks 7–10 add semantic validation, unsupported-gate refusal, and the required plan check; stopping after Task 6 still leaves an incomplete accepted contract. |

## Regressions

### R01 — The committed golden contains a randomized fixture path (from 2b-F01)
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:30-31,103`; `codex/bin/test_codex_audit.sh:16,80`; `codex/bin/codex-audit:383-385`
- failure path: The assembled prompt contains the fixture repository’s absolute path under a new `mktemp` directory on every run. A literal committed golden captured once therefore differs on every later run even when the unscoped prompt is otherwise byte-identical.
- smallest fix: Normalize the temporary root to a stable token in both captured and actual prompts, or substitute the current fixture path into a committed golden template before comparison.

### R02 — The AC8 test dropped its no-file assertion (from 2b-F03)
- evidence: `docs/design/plans/2026-09-codex-6b-pr-scope.md:98`; `docs/design/2026-09-codex-6b-pr-scope.md:168-170`
- failure path: The revised test proves Codex was not invoked but now passes if invalid input creates a ledger before rejection, leaving a misleading canonical artifact or blocking a later valid run.
- smallest fix: Assert both that the stub exec log is empty and that no ledger was created.
<!-- round 2 wall clock: 97s -->

## For the human

These did not close. Nothing below was settled between the models — each one needs you.

| id | severity | why it is open | note |
|---|---|---|---|
| 2b-F05 | MAJOR | fix did not close it | Tasks 5–6 expose `--tasks` before Tasks 7–10 add semantic validation, unsupported-gate refusal, and the required plan check; stopping after Task 6 still leaves an incomplete accepted contract.
| regression | — | introduced by the fixes | R01 — The committed golden contains a randomized fixture path (from 2b-F01)
| regression | — | introduced by the fixes | R02 — The AC8 test dropped its no-file assertion (from 2b-F03)

## Metrics

| | |
|---|---|
| round-1 findings (BLOCKER+MAJOR) | 5 |
| accepted / rejected / human | 5 / 0 / 0 |
| resolved / not resolved | 4 / 1 |
| conceded / maintained | 0 / 0 |
| regressions found in round 2 | 2 |
| still open for the human | 3 |
| wall clock | round 1 198s · round 2 97s |
