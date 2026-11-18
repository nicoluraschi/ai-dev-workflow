# Gate 6b reviews the PR in flight, not the whole spec

- **status:** shipped
- **date:** 2026-09-25
- **risk tier:** B — adds an argument to the contract of an allowlisted wrapper that every
  future gate-6b run passes through. Not Tier A: no auth, money or personal data.
- **amends:** `2026-09-cross-review-loop.md` (gate 6b), and the wrapper's `--pr` argument

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. Outcome

Gate 6b compares the diff of **one** PR against the **whole** spec, so it reports as missing
whatever has not been built yet. Two measured instances, both 2026-09-24 in a product repo, slug
`2026-09-feature-x`:

- **13:51, `feat/x-part-1`** (PR 1, tasks 1–3) — `6b-F01 BLOCKER`, a flow
  reported absent. That flow is tasks 4–8, which is PR 2's row.
- **19:00, `feat/x-part-2`** (PR 2, tasks 4–8, 10, 11) — `6b-F02 MAJOR`, an
  endpoint reported absent, whose own evidence cites the plan marking
  that endpoint **not started**. It is task 9, which is PR 3's row.

The second is the sharper one: Codex read the plan, saw the task was not started, and still
reported it. The gate has no way to be told what this PR is responsible for, so it assumes
everything.

6b is also the most expensive gate — ~1M input tokens, 5× gate 1b — so every one of those
findings is paid for at the highest rate the workflow charges.

**After this change** the caller states the PR's scope and 6b evaluates only the acceptance
criteria those tasks carry.

## 2. Scope

### In
- A `--tasks <ranges>` argument on `codex-audit`, scoping gate 6b.
- Validation of that argument as a strict numeric-range grammar, before it reaches the prompt.
- The scope recorded in the ledger header, so a scoped review cannot be read as a full one.
- `codex/prompts/6b.md` gaining the instruction that resolves tasks to criteria via the plan.
- Updating the gate-6b invocation in `claude/skills/feature-workflow/SKILL.md` to pass it.
- Extending `codex/bin/test_codex_audit.sh` — the suite that exists, 141 tests, with its Codex
  stub and its captured-prompt assertions.

### Out
- Putting 6b on the round protocol (Phase 2; `codex/prompts/6b.md:6-8`).
- Deriving the task list from `--pr` by parsing the plan's delivery table (D2).
- Any change to gates 1b/2b, whose trigger was back-tested and deliberately left alone —
  `2026-09-codex-gate-triage-backtest.md`.
- The round-2 `parseable` false positive in the wrapper. Real, unrelated, its own PR.
- Any CI. This repo has none by decision (`docs/ai-profile.md`).

## 3. Constraints

- **bash 3.2**, macOS, **no new dependencies** — as for every change to this wrapper.
- **`codex-audit` is allowlisted** as `Bash(codex-audit:*)`, so a new argument is reachable by
  an agent with no human prompt and must be validated as such.
- **Generic wrapper:** no project name, path or command may appear in `codex/bin/codex-audit`.
- The task → criterion mapping already exists in practice: plans number their tasks and each
  task names its criteria (`4. <task> … AC-11, AC-31.`). This change depends on
  that convention and does not invent it.

## 4. Decisions

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | Criteria outside the PR's tasks | **Silence** — not reported at any severity, not mentioned | Chosen by the developer over a non-finding "out of scope" list. The residual is recorded below and has another owner. |
| D2 | Source of the task list | **Explicit `--tasks`**, never derived from `--pr` | Follows the rule `--pr` was designed under: explicit over derived. Deriving means parsing a Markdown table in bash 3.2, fragile against any change to the table's format. |
| D3 | `--tasks` with no plan file | **Hard error**, like 2b | Without the plan, tasks cannot be resolved to criteria, so the scope is unknowable. Silencing criteria blindly is worse than the bug this spec fixes. |
| D4 | `--tasks` absent | Behaviour byte-identical to today | Single-PR features are the common case and must not pay for this. Same posture as `--pr`. |
| D5 | Does `--tasks` discriminate the ledger path? | **No** — only `--pr` does | Two 6b runs on one spec are already separated by `--pr`. Adding a second discriminant would produce ledgers nothing links to. |
| D6 | Where an unresolvable scope is caught (1b-F02) | **In the prompt, by the reviewer** — not in the wrapper | The wrapper cannot tell that `--tasks 99` selects nothing without parsing the plan, which D2 refuses. The resolution happens in the reviewer, so the obligation belongs there: a scope that resolves to no criteria, or a plan with no task list, must produce an explicit failure finding, never a clean review. |
| D7 | Range character (1b-F03) | **ASCII `-` only**; the skill documents the transcription | Delivery tables are written with en dashes (`1–3`). Widening the grammar to accept them would sanitise rather than reject, against SR1's posture on an allowlisted command. The procedure states the transcription instead, and the error message names the en-dash case. |

### The residual of D1, recorded

Silence means a criterion that **no task claims** is reviewed by no 6b at all: each PR looks
only at its own tasks, and the union of the PRs' tasks does not cover an orphan criterion.

This hole has a different owner and is already closed there. **Gate 2b reviews the plan**, and
the plan carries a *"Tests, each traced to a criterion"* section — that product repo's reads
"Retraced at gate 2b: every criterion is now mapped to a spec that can actually fail if the
behaviour regresses." Criterion-to-task coverage is 2b's job, not 6b's. D1 is therefore safe
*because* 2b was left alone.

### Gate outcomes

- **1s (security, SPEC phase)** — FULL. `--tasks` is untrusted input reaching a prompt sent to
  another provider through an allowlisted command. Requirements folded into §5 as SR1–SR5.
- **1b (Codex, 2 rounds)** — 0 BLOCKER, 4 MAJOR in round 1; all four accepted. Round 2: 3
  resolved, **0 regressions**, 1 left open. Ledger:
  `docs/design/reviews/2026-09-codex-6b-pr-scope-1b.md`.
  - `1b-F02` was the one that did not close: AC5b proved only that the prompt carries the
    obligation, not that the reviewer acts on it. Closed by AC12c, which extends AC12b's
    by-hand validation to the `--tasks 99` case — the treatment round 2 itself pointed at
    ("unlike AC12b").
  - `1b-F03` is the finding that justified the gate: it caught that delivery tables are written
    with en dashes while SR1 admits ASCII only, so the documented procedure would have produced
    a rejected invocation. That is not visible from the spec alone — only from the real artifact.
- **Wrapper defect observed while running this gate.** Round 2 triggered the wrapper's
  `parseable` warning ("output does not follow the contract's format"), but round 2 uses the
  Verdicts table by contract, not BLOCKER/MAJOR headings. A false positive in the check, not in
  the review. Out of scope here (§2); it ships in its own PR.

- **2s (security, DESIGN phase)** — FULL, against the plan. SR1–SR5 are each assigned to a task
  and closed. One design-level observation, recorded rather than blocking: **D6 delegates half of
  SR3 to the reviewer**, and a reviewer is another provider's model, not a control the way code
  is. It is accepted because the failure mode is *under-reporting* — 6b misses a conformance
  finding — never widened execution, which is the class this repo's profile calls a BLOCKER.
  AC12c verifies it by observation once, which is the strongest check available for a
  non-deterministic component.
- **2b (Codex, 2 rounds)** — 0 BLOCKER, 5 MAJOR in round 1; all five accepted. Round 2: 4
  resolved, **2 regressions introduced by the round-1 fixes**, 1 maintained. Ledger:
  `docs/design/reviews/2026-09-codex-6b-pr-scope-2b.md`.
  - `2b-F02` was the finding that paid for the gate: the planned `check_absent "AC-25"`
    assertions would have passed whether or not scoping existed, because the prompt carries
    *paths*, not plan contents. Every prompt test now asserts positively.
  - `2b-F04` caught that AC12b and AC12c collide on one ledger, since D5 deliberately keeps
    `--tasks` out of the path. Sequenced via `--rerun`, which archives.
  - `2b-F05` was maintained: moving the prompt earlier still left the flag reachable before
    semantic validation, the gate refusal and the plan check. Closed by making the whole argv
    contract a single atomic commit.
  - Round 2 caught two regressions introduced by round-1 fixes: `R01`, a golden
    fixture that can never match because it embeds a fresh `mktemp` path; `R02`, an AC8 test
    that lost its no-ledger assertion when it gained the exec-log one. **This is the fourth
    recorded instance of round 2 catching a regression in a round where everything was
    accepted** — the pattern `2026-09-codex-gate-triage-backtest.md` measured.
- **AC12b — by-hand reviewer validation, 2026-09-25. PASSES.** The branch that produced the
  original false finding had merged, so its merge commit was reconstructed into a throwaway
  worktree at that commit's parent with `git checkout <commit> -- .`; no file was deleted in it,
  so the reconstruction is faithful at 27 files / 2241 insertions / 48 deletions. Running the
  new wrapper as `6b --slug 2026-09-feature-x --pr 2 --tasks 4-8,10,11` (295s)
  returned 1 BLOCKER and 2 MAJOR, **all three in scope and each citing its criterion**:
  `6b-F01` on AC-15 (task 8), `6b-F02` on AC-41 (task 11), `6b-F03` on AC-37 (task 7). The
  MINORs cite AC-18, AC-15 and AC-38 — also in scope.
  **The task-9 finding did not reappear**: nothing referenced AC-25…28 or the absent
  task-9 endpoint. And the in-scope half held — `6b-F01` is a real finding about code
  that exists, not a "not built yet" complaint. Ledger:
  `docs/specs/reviews/2026-09-feature-x-6b-pr2.md` in that worktree.
- **AC12c — by-hand reviewer validation, 2026-09-25. PASSES.** Run against a minimal fixture
  repository rather than the reconstruction: the fail-loudly path needs only a plan whose task
  numbers exclude the requested one, so a one-file diff proves it for a fraction of the tokens
  (36s against 295s). `6b --slug 2026-09-mini --tasks 99` on a plan numbering tasks 1–3 returned
  a single BLOCKER — *"Task 99 does not exist in the plan … resolves to no acceptance criteria,
  so the requested conformance review has no valid scope"* — and **nothing else**. It did not
  return a clean review, which is the outcome SR3 exists to prevent. The ledger header recorded
  `- **scope:** tasks 99`.
- **6 (`/code-review high`, Tier B)** — 5 findings, **all five verified and fixed**; none
  rejected. Two made empirical claims that were reproduced before acting: F1 (a `/private`
  prefix frozen into the golden, which fails wherever `$TMPDIR` is not symlinked) and F4 (a
  64-bit arithmetic wrap accepting a backwards range). F2 and F3 were false greens in the new tests: the AC10 block compared two captures without
  asserting either run reached Codex, and `check_refused` pointed at the 6b ledger even when
  testing gates 1b and 2b.
  **F5's remedy departs from the suggestion.** The review proposed requiring `--pr` whenever
  `--tasks` is given; the guard shipped is narrower — `--tasks` with `--rerun` requires `--pr`.
  Only the archiving path can replace another PR's canonical ledger; a plain second run already
  dies at the overwrite guard. The broader rule would also forbid scoping a single-PR re-review
  to the tasks that changed, which is legitimate.
- **2d (performance, DESIGN phase)** — the change adds one regex match and one `awk`
  substitution per invocation, against a gate that sends ~1M input tokens. Immaterial; the full
  skill pass was not loaded because there is no runtime surface for it to examine. Stated here
  rather than skipped silently.

## 5. Security requirements

From gate 1s (STRIDE, FULL — `--tasks` is new untrusted input that reaches a prompt sent to
another provider, through a command an agent may run with no human prompt).

The repo profile names one BLOCKER class that applies: *anything that widens what an agent may
execute without a human prompt.*

- **SR1 — `--tasks` is validated against `^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$`, rejected
  rather than sanitised, before it reaches the prompt.** It is spliced into instructions sent
  to another provider; any wider character class makes prompt injection reachable through an
  allowlisted command. Same posture the wrapper already applies to `--slug`, `--pr` and the
  thread id read back from a ledger.
- **SR2 — `--tasks` reaches only the gate-6b prompt body**, never the reviewer contract, so it
  cannot restate the sandbox or approval settings. It narrows what Codex *reports*; it must not
  touch what Codex may *do*.
- **SR3 — an unusable scope must fail loudly, never silently.** D1 makes a scope that resolves
  to nothing indistinguishable from a clean conformance review: 6b would report nothing and
  read as "the diff delivers the spec". A descending range (`8-4`), a zero, an empty element
  (`4,,5`) are therefore rejected outright. This is the same property the wrapper already
  protects when it refuses to let a skip ledger be mistaken for a gate that ran and found
  nothing. **The grammar cannot catch every unusable scope** — `--tasks 99` is well-formed and
  selects nothing. That half is carried by D6, in the prompt, where the resolution happens.
- **SR5 — `--tasks` is refused on gates 1b and 2b** (1b-F04), before any file is created and
  before `codex` runs. Accepting it there would let a caller place a narrowing instruction into
  the prompt of a gate that is explicitly not scoped, suppressing its findings. That is
  narrowing what a reviewer reports on a surface the spec never authorised.
- **SR4 — the ledger header records the scope verbatim.** A scoped review that does not say it
  was scoped is a review that will later be read as full coverage. Same reasoning as SR3, at
  the artifact rather than the run.

## 6. Acceptance criteria

**Scoping**
1. Given `--tasks 4-8,10,11`, the assembled prompt instructs the reviewer to evaluate only the
   criteria the plan's task list assigns to tasks 4, 5, 6, 7, 8, 10 and 11.
2. **(D1)** Given `--tasks`, the prompt instructs that a criterion outside those tasks is not
   reported at any severity and not mentioned.
3. **(D4)** Given no `--tasks`, the assembled 6b prompt is byte-identical to today's.
3b. **(review F1)** That comparison normalises both the physical and the logical temporary root.
    macOS hands back a logical `mktemp` path while the wrapper writes the physical one, so
    normalising one form alone freezes a `/private` prefix into the golden and the guard then
    fails wherever the two coincide — and the natural reaction, regenerating the golden, would
    silently defeat the guard it exists to be.
4. **(D3)** Given `--tasks` and no plan at `$PLAN_DIR/$slug.md`, the wrapper exits non-zero
   **and `codex` is never invoked** — the refusal precedes the spend.
5. **(D5)** Given `--tasks`, the ledger and events paths are unchanged by it; only `--pr`
   discriminates them.
5b. **(1b-F02, D6)** Given `--tasks 99` — well-formed but naming a task the plan does not
    define — the prompt obliges the reviewer to report an explicit failure rather than a clean
    scoped review. Same for a plan carrying no recognisable task list. A silently empty review
    must fail this.
5c. **(1b-F04, SR5)** Given `--tasks` on gate 1b or on gate 2b, the wrapper exits non-zero
    before creating any file and before invoking `codex`.
5d. **(review F5)** Given `--tasks` together with `--rerun` and no `--pr`, the wrapper exits
    non-zero: the archive would otherwise replace the ledger at the unscoped path, which another
    PR's description links to. A plain scoped run needs no such guard — a second one meets the
    overwrite guard and dies safely.

**Honesty of the record**
6. **(SR4)** Given `--tasks 4-8,10,11`, the ledger header records that scope verbatim.
7. Given no `--tasks`, the ledger header is byte-identical to today's — no empty scope line.

**Validation**
8. **(SR1)** Given `--tasks` outside the grammar — `4-8;rm -rf /`, `a`, `-4`, `4 8`, `{{`,
   empty — the wrapper exits non-zero before creating any file and before invoking `codex`.
9. **(SR3)** Given `8-4`, `0`, `4,,5` or `04`, the wrapper exits non-zero. An unusable scope
   must not resolve to an empty one.
9c. **(review F4)** Given a range whose numbers exceed four digits, the wrapper exits non-zero.
    The range check evaluates in bash arithmetic, which wraps at 64 bits, so an unbounded number
    would overflow to a negative lower bound, read as ascending, and buy a real Codex run for a
    scope resolving to nothing. The grammar's digit cap keeps arithmetic out of reach.
9b. **(1b-F03, D7)** Given a range copied verbatim from a delivery table with en dashes
    (`--tasks 4–8`), the wrapper exits non-zero **and its message names the en-dash case**, so
    the common transcription mistake is diagnosable rather than merely refused.
10. **(SR2)** Given any accepted `--tasks`, the reviewer contract section of the prompt is
    byte-identical to the unscoped run — the value reaches the gate prompt only.

**Regression — the two measured cases**
11. Given the `2026-09-feature-x` plan and `--tasks 1-3`, the assembled prompt's
    scope excludes PR 2's criteria. This is the 13:51 `6b-F01` false BLOCKER.
12. Given `--tasks 4-8,10,11`, the scope excludes AC-25…28 — task 9, not started. This is the
    19:00 `6b-F02` false MAJOR.
12b. **(1b-F01)** AC1–AC12 assert on the assembled prompt, which cannot prove the reviewer
     *honours* the scope. That is verified once, by hand, against the case that motivated this
     spec: re-run gate 6b on that repo's `feat/x-part-2` with
     `--tasks 4-8,10,11` and confirm `6b-F02` does not reappear **while an in-scope violation
     is still reported**. The result is recorded in §4 before this ships. It is deliberately
     not in the test suite: that suite stubs Codex precisely so no review is sent and no tokens
     are spent, and a non-deterministic reviewer cannot be a unit test.
12c. **(1b-F02, round 2)** The same by-hand validation covers the unresolvable scope, for the
     reason round 2 gave: AC5b proves the prompt carries the obligation, not that the reviewer
     acts on it. Re-run the same gate with `--tasks 99` and confirm it reports an explicit
     failure — **a clean scoped review fails this criterion.** Recorded in §4 alongside AC12b's
     result before this ships. Both halves of the silent-clean-review path are then closed by
     observation rather than by assertion.

**The documented procedure**
13. `claude/skills/feature-workflow/SKILL.md`'s gate-6b invocation documents `--tasks` sourced
    from the same delivery-table row that supplies `--pr`, and names that table as the source.
13b. **(1b-F03, D7)** That same documentation states the transcription rule: delivery tables are
     written with en dashes and `--tasks` takes ASCII hyphens, so `1–3` is passed as `1-3`.

## 7. Edge cases swept

| Category | Question | Answer |
|---|---|---|
| Text input | `--tasks` with a shell metacharacter or `{{` | AC8 — rejected before the prompt |
| Text input | Range copied with en dashes from a delivery table | AC9b — rejected, and the message names the case (D7) |
| Numbers | Descending range, zero, leading zero, empty element | AC9 — rejected, never an empty scope |
| Numbers | A task number the plan does not define | AC5b — the reviewer must report an explicit failure, never a clean review (D6). No wrapper check: it would need to parse the plan, which D2 refuses |
| Collections | One task, `--tasks 9` | Accepted: a single element is a valid range list |
| State/flow | `--tasks` on gate 1b or 2b | AC5c — exits non-zero before any file or `codex` (SR5) |
| Errors | Plan exists but has no task list | AC5b — an explicit failure finding, not an empty clean review (D6) |
| Presentation | Existing 6b ledgers | AC7 — untouched, header unchanged without `--tasks` |
| Auth | New flag reachable with no prompt | SR1/SR2 — data only, narrows reporting, never widens execution |
