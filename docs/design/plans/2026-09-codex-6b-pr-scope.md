# Plan — gate 6b reviews the PR in flight

Spec: `docs/design/2026-09-codex-6b-pr-scope.md`. Risk tier **B**.

**Delivery: one PR.** No delivery table, and therefore this feature's own gate 6b runs without
`--tasks` — which is exactly the D4 path the change must leave byte-identical.

**QA: skip** — no browser-observable surface (a bash CLI wrapper), and the changed behaviour is
covered by the suite plus the two by-hand reviewer validations AC12b/AC12c.

## Approach

The work splits along where each obligation can actually be enforced:

- **The wrapper** enforces everything decidable from argv alone: the grammar, the refusals, the
  gate restriction, the plan's existence, the ledger header.
- **The prompt** carries everything that needs the plan resolved: which criteria the tasks name,
  the silence, and the explicit failure when the scope resolves to nothing.

That split is D2 + D6 (the caller passes the task list explicitly; the reviewer reports a scope
that resolves to nothing), and it is what keeps Markdown parsing out of bash 3.2.

### The scoped instructions are a separate fragment (2b-F01)

AC3 requires the unscoped prompt to stay byte-identical, so the scoping instructions **must not
live in `codex/prompts/6b.md`'s body**. They go in `codex/prompts/6b.scope.md`, spliced at a
`{{TASKS_SCOPE}}` placeholder that sits alone on its line. `splice` drops the placeholder line
and prints the fragment's lines in its place, so an absent `--tasks` splices an empty file and
the line vanishes — zero bytes, not a blank line.

AC3 is proven against a **golden fixture captured from the pre-change wrapper**, committed before
task 1. A byte-identical claim measured against the post-change code proves nothing.

### The prompt tests assert positively (2b-F02)

The assembled prompt carries *paths*, not the plan's contents, so `check_absent "AC-25"` passes
whether or not scoping exists. Those assertions would have been vacuous. Every prompt test
therefore asserts **positively**: the task range is present, the plan path is present, and each
of the three obligations — resolve-only, silence, fail-loudly — appears verbatim. Consumer-level
behaviour stays with AC12b/AC12c, which is the only place it can live.

### Rejection is proven to precede the outbound call (2b-F03)

Exit code plus ledger-absence does not prove the value never reached Codex, and that is the
security boundary of an allowlisted wrapper. Every AC8/AC9 input clears the stub's exec-call log
and asserts it stays empty — the same assertion already planned for AC4 and AC5c.

### The two by-hand validations are sequenced, not collided (2b-F04)

AC12b and AC12c both run gate 6b on one slug, and D5 deliberately keeps `--tasks` out of the
ledger path, so the second run meets the round-1 overwrite guard. Sequence:

1. Run AC12b scoped. **Record its result in spec §4 before continuing.**
2. Run AC12c with `--rerun`, which archives the first ledger rather than destroying it.
   `--rerun` carries an `ask` permission rule, so it prompts — correct
   for a by-hand validation.

### `--tasks` is never reachable before its contract is whole (2b-F05, round 2)

Accepting the flag before the prompt honours it would hand an agent a full-spec review that
looks scoped — the exact failure this change exists to remove. Round 2 was right that moving the
prompt earlier was not enough: the flag would still be reachable before semantic validation, the
unsupported-gate refusal and the plan check.

So **the whole argv contract lands in one commit** — grammar, semantic rejections, the 1b/2b
refusal, the plan requirement and the splice, together with their tests. It is a larger commit
than the rest, deliberately: a partially accepted flag on an allowlisted command is a footgun,
and this contract is not divisible. Nothing before that commit makes `--tasks` reachable at all.

### The golden is normalised before comparison (R01)

The assembled prompt carries the fixture repo's absolute path, which lives under a fresh
`mktemp` root on every run, so a literal committed golden can never match. Both the captured
golden and the actual prompt have that root replaced by a stable token before they are diffed.

## Order of work

| # | Task | Criteria |
|---|---|---|
| 1 | Commit the golden fixture of today's unscoped 6b prompt | 3 |
| 2 | `codex/prompts/6b.scope.md`: resolve tasks via the plan, evaluate only those criteria | 1 |
| 3 | Same fragment: silence for out-of-scope criteria | 2 |
| 4 | Same fragment: explicit failure on an unresolvable scope or a plan with no task list | 5b |
| 5 | `{{TASKS_SCOPE}}` placeholder in `6b.md`; splice the fragment, or nothing | 3, 10 |
| 6 | Fixture plan in the test repo (delivery table, numbered tasks naming `AC-n`) | 11, 12 |
| 7 | **One atomic commit — the whole argv contract.** `--tasks` parsed with `TASKS_RE`; descending ranges, zero, leading zeros and empty elements rejected; en-dashed ranges rejected with a message naming the case; refused on gates 1b and 2b; the plan required for 6b — every refusal before any file and before `codex`. With its tests. | 8, 9, 9b, 5c, 4 |
| 8 | Ledger header records the scope verbatim; absent without `--tasks` | 6, 7 |
| 9 | `--tasks` leaves ledger and events paths untouched | 5 |
| 10 | Positive scoping assertions for the two measured cases | 11, 12 |
| 11 | `feature-workflow/SKILL.md`: document `--tasks` and the ASCII transcription rule | 13, 13b |
| 12 | By-hand validation AC12b; record in §4; then AC12c with `--rerun` | 12b, 12c |

Tasks 1–6 make `--tasks` no more reachable than it is today: the fragment exists but nothing
accepts the flag. Task 7 is the only commit in which it becomes usable, and it is whole.

**Fixture, not the real repo.** AC11/AC12 come from a real multi-PR plan, but the suite must not
read another repository: a test reaching into one is neither hermetic nor portable. The fixture repo gets a plan
reproducing the same shape (delivery table with en-dashed ranges, numbered tasks naming their
`AC-n`). The *real* case is AC12b, by hand, once.

## Tests, each traced to a criterion

Extending `codex/bin/test_codex_audit.sh` (141 tests, green before this change). The harness already
captures the assembled prompt in `$TMP_PROMPT_FILE` and provides `check`, `check_contains`,
`check_absent`. One addition is needed: the stub must log its `exec` invocations so a test can
assert the outbound call never happened.

| Test | Criterion | Shape |
|---|---|---|
| `4-8;rm -rf /`, `a`, `-4`, `4 8`, `{{`, `""` each exit non-zero | 8 | exit code + **stub exec log empty** + **no ledger created** (R02) |
| `8-4`, `0`, `4,,5`, `04` each exit non-zero | 9 | exit code + stub exec log empty + no ledger created (R02) |
| `4–8` exits non-zero, stderr names the en-dash case | 9b | exit code + stderr match |
| `--tasks` on 1b and on 2b exits non-zero | 5c | exit code + stub exec log empty |
| 6b + `--tasks`, no plan file ⇒ exit non-zero | 4 | exit code + stub exec log empty |
| 6b without `--tasks` ⇒ prompt byte-identical to the golden fixture | 3 | `diff` against the committed fixture, **both sides normalised on the `mktemp` root** (R01) |
| Scoped run ⇒ prompt contains the range `4-8,10,11` verbatim | 1 | `check_contains` |
| Scoped run ⇒ prompt contains the plan path | 1 | `check_contains` |
| Scoped run ⇒ prompt contains the resolve-only obligation | 1 | `check_contains` |
| Scoped run ⇒ prompt contains the silence obligation | 2 | `check_contains` |
| Scoped run ⇒ prompt contains the fail-loudly obligation | 5b | `check_contains` |
| Unscoped run ⇒ none of those three obligations appears | 3 | `check_absent` ×3 |
| Accepted `--tasks` ⇒ contract section byte-identical to the unscoped run | 10 | diff of the contract slice |
| Fixture plan + `--tasks 1-3` ⇒ that range, not another, reaches the prompt | 11 | `check_contains` + `check_absent` on the wrong range |
| Fixture plan + `--tasks 4-8,10,11` ⇒ same | 12 | `check_contains` + `check_absent` |
| `--tasks 9` accepted (single element is a valid list) | edge | exit 0 |
| Scoped run ⇒ ledger header carries the scope | 6 | `check_contains` on the ledger |
| Unscoped run ⇒ ledger header has no scope line | 7 | `check_absent` on the ledger |
| Scoped run ⇒ ledger and events paths unchanged | 5 | path assertions |

AC1, AC2 and AC5b are assertions that the prompt carries the instruction; AC12b and AC12c are
the by-hand checks that the reviewer acts on it. Round 2 of gate 1b is explicit that the first
kind cannot substitute for the second, and 2b-F02 is why the first kind must assert positively.

## Open

None. `2b-F05` was maintained in round 2 and is closed above by making the argv contract a
single atomic commit; `R01` and `R02` were regressions introduced by the round-1 fixes and are
closed in the approach and the test table. All three go to the checkpoint for arbitration —
the models do not argue further.
