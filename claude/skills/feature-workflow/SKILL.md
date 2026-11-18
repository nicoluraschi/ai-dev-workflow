---
name: feature-workflow
description: Spec-driven lifecycle for Tier A / Tier B work — auth, permissions, money, personal data, a data model or migration (except a new nullable, unconstrained column), a public contract, a new dependency or a new subsystem — from idea to deploy. Use when starting such work, or when light-lane work hits one of those triggers. Routine work, whatever its size, takes the light lane in CLAUDE.md instead. Walks through specify, plan (with its tasks), implement, verify, review, close with human checkpoints.
effort: high
---

# Feature workflow (spec-driven)

Follow these phases in order. Stop at each CHECKPOINT and wait for the human.
If a phase reveals a blocking unknown, surface it rather than assuming.

Verification and review are deliberately separate phases: **5 asks "does it work?"** (cheap,
deterministic, no token spend) and **6 asks "is it good?"** (the token spend, scaled by risk).
Never review a diff that hasn't passed 5 — you'd be reviewing something that's about to change.

**Models by phase.** The session runs on Opus (default `opus[1m]`, auto mode) for Specify, Plan,
every audit, Review and triage. Phase 4 and the deterministic checks of phase 5 go to the
`implementer` agent (Sonnet) when the plan is large enough (phase 4); phase 6 fixes follow the
*Who fixes* rule in phase 6. Codex runs on its own model.

The measurements behind these rules: `docs/design/2026-09-feature-workflow-rationale.md` (in this repo).

## Risk tier — state it out loud once, restate it when it changes

Classify once at phase 1 and say the tier out loud, so the
human never has to remember to ask for an audit — only to answer. Restate it at the gate where it
changes (a new dependency, a data model appears), not at every gate.

- **Tier A — sensitive:** touches authentication, authorization/permissions, money/billing, or
  personal data (PII).
- **Tier B — architectural:** changes a data model or adds a migration, except a new nullable,
  unconstrained column; changes a public contract — an interface (endpoint, payload, file or log
  format, CLI) consumed outside this repo's own deploy, or a breaking change to an existing one,
  since its two sides can deploy apart; adds a dependency; introduces a new subsystem, a new
  external integration included.
- **Routine:** neither of the above. It does not belong in this skill: it takes the light lane
  (CLAUDE.md *Default loop*). That includes a new nullable, unconstrained column (`data-integrity`
  and `migration-safety` still fire on its path) and a new interface only this repo consumes.
  Size is not a trigger — a large routine diff is split into PRs, not escalated.

Name the tier by quoting the clause above that triggers it. No clause to quote → routine. That
quote is the `--trigger` every gate record of the unit carries, so a misclassification can be
audited later; when the tier changes, the next records carry the new tier and its quote.

Tier A wins over Tier B when both apply. Codex 1b and 2b run on every unit; 6b only on Tier A.

**Security is not tier-gated.** The `security-audit` gates (1s / 2s / 5s) run at every tier; the
tier scales their depth, never whether they run.

## Gate scorecard — log every Claude gate

When a Claude gate returns, log it with one Bash call and no question to the human. Codex gates
(1b / 2b / 6b) record themselves inside `codex-audit`, from the same `--tier` and `--trigger`
passed to it.

```
gate-log add --gate <id> --lane workflow --tier <B|A> --trigger "<quoted clause>" --slug <slug> \
  [--pr <n>] --found B,M,m --accepted B,M,m --rejected <n> --deferred <n> --human <n> [--skipped]
```

Triples are `blocker,major,minor`; omitted counts are 0. Map each gate's own scale: `blocker` =
Critical / BLOCKER / 🔴; `major` = High / MAJOR / 🟠 or a `/code-review` correctness finding;
`minor` = the rest. `--accepted` counts findings fixed or absorbed. Add `--skipped` for a gate that
was due and not run. A delta re-audit is its own call. Gate ids: `1s` `2s` `5s` (security-audit),
`2d-data` `2d-perf`, `5-data` `5-migration` `5-perf` `5-obs` `5-ui` (phase 5 audits), `5q`,
`6-review` (`/code-review`).

## Asking the human — one round per gate, not one question at a time

When a gate needs the human, collect everything you need from them and ask it in **one**
`AskUserQuestion` call — it takes up to four questions. Anything low-stakes is not a question at
all: state the assumption, proceed, and surface it as an OPEN decision they can overturn. Every
question stalls the pipeline until they come back to the terminal.

Two exceptions: 5q, where the permission prompt **is** the question, and a genuine fork in
approach, which gets its own round rather than being bundled with bookkeeping.

## Approval brief — opens the spec, plan and triage checkpoints
The human approves from this brief, not from the spec or plan files, so it says *what they are
agreeing to*, not how it was checked. Open each checkpoint with it, before anything else, in this
order and about 25 lines; it counts as a plan under CLAUDE.md *Output budget*. Plain language, no
internal jargon outside item 7; when a spec or plan file holds the item, it ends with that
`path:line`, so one part can be read in full.

```
Approval brief — <slug>, <spec | plan | triage> · Tier <B | A | light> — <why, ≤8 words>
1. What & why:   <2 lines: the outcome and who it is for>
2. Before → after: <3–5 bullets a user or the data would notice>
3. Decided for you: <per blocking or hard-to-undo decision: chosen · main alternative · why · (you said | assumed)>
4. Hard to undo:  <migrations, public contracts, dependencies, data changes; or "nothing">
5. Out:           <explicitly out of scope>
6. Your answer:   <numbered decisions only the human can make, or "none">
7. Checks:        <gate> <n> acc / <n> rej / <n> human · … ("—" if skipped; "no signal" if not due)
Reply: go · change <item> · reject
```


- **3 is the point of the brief.** Every decision the spec or plan made that the human did not
  state and that blocks (CLAUDE.md *Communication*: product, taste, security, privacy) or is hard
  to undo goes here marked `assumed`, numbered so `change 3.2` overturns one: each is an open
  question that `go` answers with the default shown (CLAUDE.md *Plans must state*). Mechanics
  (test layout, how a doc is edited, file structure) are decided, not listed; one a reviewer
  needs goes in the PR's **What**. In doubt, list it and ask it in 6, as every assumed
  decision that blocks is.
- **6 is asked**, in the same round (*Asking the human*); 1b's and 2b's **For the human** items
  join it. Past four questions, the most blocking go in `AskUserQuestion` and the rest as numbered
  questions in the same message.
- **Re-approval is a delta.** When the human changed the spec or plan and it comes back, the brief
  lists only what changed since the last one they saw, plus 6 and 7.
- **At triage**, 1–3 become one line on what the change now does; 4 stays when the code added
  something hard to undo the plan did not have; 5 lists the findings being
  deferred; 7 reports the review and phase 5 audits as `fix <n> / defer <n> / reject <n>`.

## What the reviewers must NOT report

Whatever the repo's hooks and CI already run (lint, formatting, type checks, secret scanning, SAST,
the test suite) is covered for free; findings of that kind are false positives, from Claude or
Codex. AI review covers only: logic bugs in the changed lines; drift from the acceptance criteria
and cases left without a test; security *logic* (authorization, tenancy, IDOR); API and data-model
design. `security-audit` works the security seam at 1s / 2s / 5s and is never dropped as "noise" —
but it stays on that seam and does not re-report scanner findings. `data-integrity` and
`performance-review` work the design seam at 2d / 5.

## Codex as independent auditor

Gates 1b, 2b and 6b bring in **Codex CLI** as an *independent auditor*: it reads artifacts Claude
produced and attacks them. It never writes production code. Pattern:
**Claude generates → Codex confronts → the human arbitrates.** Execution stays 100% in Claude Code;
there is deliberately no Codex gate on Tasks or Implement.

1b and 2b audit *text* — cheap, catching a wrong decision before code exists. Run both on every
feature-workflow unit. 6b audits a *diff* — expensive, partly covered by tests and CI; run it only
for Tier A.

**Never wait idle on 1b or 2b.** Launch round 1 of each gate that is due in the background the moment its artifact is written,
and run the Claude gates of the same phase while Codex works (1s; 2s and 2d). Codex reads the file
live, so nothing edits the spec or plan until the gate exits: those gates' findings are held, then
folded together with the accepted Codex findings in one edit. The checkpoint still waits for both.

When any of them fires, read `references/codex-gates.md` first: always through the `codex-audit`
wrapper, never raw `codex exec`; the ledger, exit codes and round protocol are there. Ad-hoc
second opinions on a stuck decision, outside any gate, are described there too.

## 1. Specify
- **Interview first — don't draft from assumptions.** Before writing the spec, ask a focused,
  batched round of questions to fill every template slot you can't answer with confidence:
  outcome, who it's for, scope boundaries (especially what's *out*), constraints, edge cases,
  and any fork in approach. Wait for the answers; don't draft until they're in.
- Then expand into a spec at `docs/specs/YYYY-MM-<slug>.md` using `docs/specs/_template.md`,
  filling: outcome, scope (in / out), constraints, prior decisions, open decisions, acceptance criteria.
- **Keep the spec at ≤1,500 words** (CLAUDE.md *Output budget*). Past that it is designing, not
  specifying — a signal to ship across several PRs (phase 2's delivery table). It is re-read many
  times per session, so its size is paid on every read.
- **Light spec** when the unit touches no data model, API contract, auth/PII or dependency (a new
  subsystem, typically): **≤800 words excluding the acceptance criteria**, which are never capped. Outcome;
  Scope with *Out* mandatory and *In* pointing at the design ref rather than restating it; Decisions
  one line each, `<decision> — <because>`; acceptance criteria in full.
- **Gate findings are never restated in Decisions**, light or full spec. An accepted finding lands as
  the criterion or scope line it changes; Decisions carries only the gate's one-line verdict (1b below).
- **Re-read the acceptance criteria by themselves, not the whole spec.** In every later phase, pull
  those sections out rather than reading the file end to end:

  ```
  awk '/^## [0-9]+\. Acceptance criteria/{f=1;print;next} f&&/^## /{f=0} f' docs/specs/<slug>.md
  ```

  **Match on the heading text, never on a section number.** A spec that went through gate 1s carries
  *two* criteria sections — `## 6. Acceptance criteria` and, after the security requirements,
  `## 8. Acceptance criteria (security)`. Anchoring on `## 6.` silently drops every security
  criterion.

  The section numbers stay load-bearing, so do not renumber the template to make extraction easier.
- **Sweep the edge-case heuristics before you call the criteria done.** For each category in
  `qa-methodology/references/edge-cases.md` that applies, ask what the spec says happens. Undefined
  behaviour found here is an **OPEN decision**, not a
  test case: what the spec defines now is what QA has an oracle for later.
- Anything still unresolved after the interview → mark as an OPEN decision. Don't design past
  open decisions that block the approach.
- No checkpoint yet: 1s and 1b still change the spec. Tier A approves it once, at the start of
  phase 2; Tier B approves it together with the plan, at the 2b checkpoint.

## 1s. Security threat model (mandatory — every feature, every tier)
- Launch 1b in the background first (below), then invoke the `security-audit` skill, **SPEC
  phase**, against the spec you just wrote. It runs forked and sees only its args: pass the
  phase, the spec path and any decision agreed only in chat (its *Inputs* table).
- Fold its **Security Requirements** into the spec's acceptance criteria — a security requirement
  that isn't an acceptance criterion never gets a test, and phase 5 won't catch its absence. Fold
  them once 1b's round 1 has exited, in the same edit as its accepted findings.
- Tier A: work the full STRIDE table.
- This gate has **no tier exemption**. It runs even when the feature looks routine.
- After its verdict: `gate-log add --gate 1s …` (*Gate scorecard*).

## 1b. Spec cross-check (every unit — launched before 1s)
- Read `references/codex-gates.md`. Codex attacks the *problem*, not a proposed solution. Run it in
  the background and work 1s meanwhile, without touching the spec:
  ```
  codex-audit 1b --slug <slug> --tier <B|A> --trigger "<quoted clause>"
  ```
- If it found BLOCKER/MAJOR findings, fold the accepted ones with 1s's requirements, write the
  response table and run round 2:
  ```
  codex-audit 1b --slug <slug> --round 2 --response <file> --tier <B|A> --trigger "<quoted clause>"
  ```
- Record in the spec's §4 Decisions **one line**:
  `1b: <verdict> — <n> accepted, <n> rejected, <n> human`, plus one line per `human` item. No
  summary, no ledger link. Do not proceed to Plan until that is recorded.

## 2. Plan
- Before any planning, the spec is final: 1s's security criteria folded in, 1b's verdict in §4.
  Then, by tier:
  - **Tier A — CHECKPOINT:** human approves the spec from its approval brief, with 1b's **For the
    human** items asked in the same round. It stops here even when 1b was skipped (exit `3`): a skip
    removes the cross-check, never the approval.
  - **Tier B — no spec checkpoint.** Approval happens on a brief, and a spec approved alone
    would carry little; the 2b checkpoint approves spec and plan together. If 1b's ledger has
    **For the human** items, ask them now in one round — the plan is built on their answers;
    none → go straight to the plan. A skip (exit `3`) still ends at the 2b checkpoint.
  If the answers change the spec, re-run 1s as a delta over the changed criteria and restate the
  tier if it moved, before planning starts (Tier A: before its approval counts). A move to Tier A
  brings its spec checkpoint back.
- Stay in plan mode — no edits yet.
- Produce an implementation plan: files to touch, approach, order of work.
- **If the spec ships across more than one PR, the plan must open with a delivery table.** One
  row per PR: index, branch, the tasks it carries, and its state.

  ```
  | PR | Branch | Tasks | State |
  |---|---|---|---|
  | 1 | `feat/thing-backend` | 1–3 | merged (#95) |
  | 2 | `feat/thing-web`     | 4–8 | in progress |
  | 3 | *(not opened)*       | 9   | not started |
  ```

  The **PR index is the identity gate 6b passes as `--pr`** — the only one that exists before
  the PR is opened; without it, two PRs of one spec share one 6b ledger.
- **Write the plan to `<artifacts>/plans/<slug>.md`.** Gate 2b reads it from that file. Plan-mode files under `~/.claude/plans/` are
  scratch, not the record.
- **Include the numbered task list** — granular and ordered, each task naming the acceptance
  criteria it carries. The delivery table's Tasks cells and 6b's `--tasks` resolve against it, so
  it must exist at plan time, and 2b audits it with the rest of the plan.
- List the tests you'll write, each traceable to an acceptance criterion.
- **Write the plan as the implementer's brief.** An agent with no memory of this conversation must
  be able to implement it: the files, each task's criteria, the test command (AGENTS.md names it),
  and a **Decisions from conversation** section for anything settled in chat that the spec does not
  hold. Approving the plan confirms the brief is complete.
- Where the approach has a genuine fork (data model, library, boundary), surface the options with
  their trade-offs and ask — don't pick silently.
- **Record the QA recommendation** — one line in the plan, always present:
  `QA: skip | focused | full` plus a one-line reason. It is a recommendation the human confirms
  at 5q, not a decision. Write it by the criteria in `references/qa-gate.md` (*At plan time*):
  `focused` only for the four criticality criteria, `skip` by default.

## 2s. Security design review (mandatory — every feature, every tier)
- Launch 2b in the background first (below); then invoke the `security-audit` skill,
  **DESIGN phase**, against the plan; pass the phase, the spec and plan paths, and 1s's threats.
  Hold the plan edits it asks for until 2b's round 1 has
  exited.
- Every threat raised at 1s must be closed by the design, or explicitly deferred with a reason
  recorded in the spec's §4 Decisions. Silence is not closure.
- Verdict 🔴 Blocked → fix the design before the CHECKPOINT below. Never carry a known design gap
  into implementation intending to patch it in code.
- After its verdict: `gate-log add --gate 2s …`.

## 2d. Conditional design reviews (data + performance)
Unlike 1s/2s, these fire on what the change *is*; `hooks/audit-guard.py` also enforces them.

- **Data model touched** (new table, relationship, constraint, or a migration): invoke
  `data-integrity`, **DESIGN phase** — FKs, uniqueness, CHECK constraints, soft-delete semantics,
  state machines. Migration safety is not its job: `migration-safety` owns migrations at
  phase 5.
- **Tier B** (new subsystem, data model, or public API contract): invoke `performance-review`,
  **DESIGN phase** — hot paths, N+1 shapes, fan-out, cache invalidation. A query problem is
  cheapest to catch here, in the plan, before the code exists.
- Record whatever either one blocks on in the spec's §4 Decisions before the CHECKPOINT below.
  `data-integrity` also writes its verdict there, recommendations counted:
  `2d-data: <verdict> — <n> accepted, <n> rejected, <n> deferred` (phase 5's CONFORMANCE reads it).
  Like 2s, they run while 2b works, and their plan edits wait for it.
- After each verdict: `gate-log add --gate 2d-data …` or `--gate 2d-perf …`.

## 2b. Plan cross-check (every unit — launched before 2s and 2d)
- Read `references/codex-gates.md`, then run round 1 in the background as soon as the plan file is
  written; fold its accepted findings with 2s's and 2d's in one plan edit:
  ```
  codex-audit 2b --slug <slug> --tier <B|A> --trigger "<quoted clause>"
  codex-audit 2b --slug <slug> --round 2 --response <file> --tier <B|A> --trigger "<quoted clause>"
  ```
  (Round 2 only if round 1 found something.)
- It audits the task list as part of the plan: coverage and order apply to tasks too.
- Record the one-line verdict in §4, as for 1b.
- CHECKPOINT: human approves the plan before any file is touched — at Tier B, the spec with it,
  the unit's only approval before code. If the human changes the spec here, re-run 1s as a
  delta over the changed criteria and update the plan tasks they affect before the approval
  counts. Open with the approval brief (at Tier B it covers spec and plan); the ledger's **For
  the human** section — the open disputes, not the whole critique — goes in its item 6.

## 3. Tasks
Tasks live in the plan (phase 2) — there is no separate phase; the number stays so references hold.

## 4. Implement (TDD)
- **Delegate to the `implementer` agent (Sonnet) unless the plan is a single task.** By phase 4
  this session carries 115–175k of context, re-read on Opus by every inline turn; a spawn is a
  one-time write of about 30–45k on Sonnet. It takes phase 4 and the deterministic checks of
  phase 5 (suite, coverage, criteria trace); this session stays on Opus for the audits, Review and
  triage.
- **The brief:** worktree path, spec path, plan path, risk tier, and any decision that could not be
  written into the plan (phase 2 requires the plan to stand on its own). The agent starts with an
  empty context and never commits.
- **Do not trust its report.** When it returns, re-run the full suite once and show the real output
  (the commit hook believes only output it observed), and compare its files-changed list with
  `git diff --stat`. Record the agent ID it returns. On `GAPS` or a red re-run, fix the plan here
  if it was wrong, then resume **the same** agent with `SendMessage` and that ID, naming only the
  affected tasks or failures — a fresh spawn only if the resume fails. On `BLOCKED`, implement
  inline.
- **Inline path:** invoke the `test-driven-development` skill and follow it for every task. One
  concern at a time; keep each diff small and reviewable.
- **Observability is part of the work, not a follow-up.** For any new endpoint, job or external
  integration, invoke `observability` in **GENERATE mode** and write the logging, error tracking
  and metrics *alongside* the implementation (the agent does the same).
- **Delegate the mechanical loops to a Sonnet subagent; keep the reasoning on Opus.** Hand a
  subagent: running the suite and reporting only what failed; the lint/format loop; waiting on
  `gh pr checks`; file and inventory sweeps. Keep on Opus: the spec, the plan, and every audit and
  review.

## 5. Verify — does it work?
Deterministic checks only. No AI review in this phase. Everything here can change code, which is
why it runs before phase 6. When phase 4 was delegated, `implementer` did the suite, coverage and
criteria trace below; the audit gates always run in this session, on Opus — CLAUDE.md forbids
downgrading `security-audit`, and the same holds for the other audits.
- Run the full test suite via `verification-before-completion`: run the check and show the
  real output. No "done", "passing" or "green" claim without the evidence to back it. Report
  coverage on the changed code against the ≥85% target. When the repo's pre-push runs the suite
  through `suite-queue`, use the lefthook form that skill names, so the push skips the rerun.
- Confirm every acceptance criterion is met; check the implementation against the spec and
  flag any drift.
- **For any change that touches UI files**, invoke `ui-review` in review mode *here*, before the
  review phase. This is not optional — UI regressions are caught here, by measurement, not by
  eye in review.
- For frontend changes, also drive the affected screen — in the same `ui-reviewer` launch as
  `ui-review`, never with screenshots in this session — and report what you observed,
  not just that tests pass.
- **Security audit — mandatory, every change, every tier.** Invoke the `security-audit` skill,
  **IMPL phase**, on the diff; pass the phase, the repo path and diff command (`git diff main` if uncommitted), the spec path, and
  on a re-audit the previous findings. Relay its return verbatim. Keep it on the security-logic seam — authorization, tenancy, IDOR,
  trust boundaries — not what SAST already flags. Any 🔴 Critical finding **blocks**: fix it and
  re-audit the affected code before phase 6.
- **Schema or migration touched, or a model's constraint surface** (an association, validation,
  enum, callback, or a null/default/unique/FK constraint added or removed; a scope or method is
  not) → `data-integrity` on that surface, plus `migration-safety` for anything under
  `db/migrate/` (locking, backfill, reversibility, and whether schema and code can deploy
  independently). Both are hook-enforced: the turn will not end until they have run. When §4's
  `2d-data:` line shows 0 rejected and 0 deferred and the plan's data model has not changed since,
  `data-integrity` runs in **CONFORMANCE** mode with the spec and plan paths: a full review only on
  what drifted from the plan, one line otherwise. Log it as `5-data` either way.
- **Perf and obs run only on a signal**, at either tier, and so does `data-integrity` on a model
  file. Read the added and removed lines of
  `git diff -U0 <base>` — the base branch against the working tree, so uncommitted phase-4 work
  counts; no signal → the audit is not due: write `<gate> no signal` on the
  triage brief's item 7 and log nothing (`--skipped` means due and not run).
- **Perf signal** (a query, a loop doing I/O, a job, a cache, or an external call added or
  changed) → `performance-review`, **IMPL phase** on the diff: N+1s, unbounded queries, missing
  indexes, work inside loops.
- **Obs signal** (a new endpoint, job class or external integration) → `observability` in
  **AUDIT mode** on the diff: is the failure path logged, does the error reach Sentry, is there a
  metric for the thing that matters.
- **Gate: everything must be green before phase 6.** A red suite means fix, then re-verify.
- At triage, log each audit above that ran (`5s`, `5-data`, `5-migration`, `5-perf`, `5-obs`,
  `5-ui`), with `--accepted` counting what was fixed.

## 5q. Independent QA (never without the human's yes)
The `qa` agent is the most expensive step in this workflow, and only the human decides whether a
change earns it. Read `references/qa-gate.md` and follow it: state the recommendation, the
criterion that fired and the cost in three lines, then attempt the launch and let the
`hooks/qa-agent-confirm.py` prompt be the question — never also ask with `AskUserQuestion`. A
`skip` gets one line and no launch. On a
yes, run `/qa verify <spec-path> <focused|full>` here, inside phase 5, and never hand the `qa`
agent the plan or the diff. Log `5q` when its report returns; a skip is not logged.

## 6. Review — is it good?
This is where the tokens go. Scale the spend to the risk tier; don't review twice with the same
question.

- **Tier B (architectural) → one deeper review:**
  ```
  /code-review high --max-findings default
  ```
- **Tier A (auth / money / personal data) → two reviews on *different* axes:**
  1. Ask the human to run `/code-review ultra --max-findings default`. **Claude cannot
     launch it; the human has to type it.** Ask for it explicitly at this gate.
  2. Codex on the spec-conformance axis — what's *missing*, not what's wrong, so the two
     reviews don't overlap (gate 6b). **Launch this while `ultra` is running, not after it** —
     neither gates the other; only the triage below needs both. Read `references/codex-gates.md`
     for the invocation — a multi-PR spec passes `--pr` and `--tasks` from its delivery-table row.
  Record the one-line 6b verdict in §4; anything deferred goes in the PR body's deferred list.

**Always name the level.** A bare `/code-review` silently reuses whatever level was typed last,
which makes both the depth and the cost unpredictable. Name `--max-findings` too: it is sticky in
the same way, so a light-lane cap of 5 would silently carry into the next Tier B review.

The session stays on Opus, so `/code-review` reviews on Opus with no extra step. `ultra` runs in
the cloud, not on the session model.

**Never pass `--fix`.** Auto-applied cleanups pollute a focused diff and defeat the human's review.
If cleanups are genuinely wanted, run `/simplify` afterwards as a deliberate, separate pass in its
own commit.

- **Triage every finding by hand** using `receiving-code-review` — verify the claim, don't perform
  agreement. Sort into exactly three buckets:
  1. **Fix now** — real bug, fix it before the PR.
  2. **Defer** — real but out of scope; note it in the PR description.
  3. **Reject** — false positive; record a one-line reason.
- Log `6-review` once, after the last round, with both rounds' findings summed: Fix now → `--accepted`, Reject → `--rejected`,
  Defer → `--deferred`, anything left to the human → `--human`. Tier A: record 6b's share of the
  triage with `codex-audit 6b … --response` (`references/codex-gates.md`, *Gate 6b*).
- **Who fixes.** Size the **Fix now** bucket.
  - **Small** (fewer than 3 logic fixes and fewer than 4 files): fix inline on Opus with
    `test-driven-development` — the context is already here, a spawn is not paid back.
  - **Large, and phase 4 was delegated:** resume that `implementer` with `SendMessage` and its
    recorded agent ID, in fix mode. The brief: the **Fix now** list (location, problem, agreed
    fix), the human's arbitration, and "re-read every file changed since you returned". If the
    resume fails, spawn a fresh `implementer` with the phase 4 brief plus that list.
  - **Large, and phase 4 was inline:** fix inline on Opus — a big fix batch on a small plan means
    the plan missed something, which needs the reasoning here.
  - Never hand it **Defer** or **Reject** findings, or the raw review output. Re-check its report
    as in phase 4.
- **Two review rounds, then stop.** Round 2 is a delta: re-run `/code-review` only if a round-1
  fix changed logic, and scope it to the fixed hunks (the touched files as its path target, at the
  tier's level) — not the whole diff again. A rename, a test added, or a comment needs no
  re-review. There is no round 3: fix round 2's accepted findings without reviewing them again. A
  correctness bug you cannot fix with confidence goes to the human at the checkpoint below;
  anything else left goes to the PR's **Deferred** section. The cap is on `/code-review` only — a fixed hunk
  still gets its security re-audit, and a 🔴 Critical still blocks.
- **Related tests between rounds, the full suite once at the end.** While fixing, run only the
  tests for the files a fix touched. Never start the full suite while a review is running or its
  fixes are pending: a run that predates the last fix is spent. After the last fix, if any fix
  changed code, run the full suite once in the lefthook form `verification-before-completion`
  names and re-check coverage on the changed code. This holds inline and for an `implementer` in
  fix mode.
- CHECKPOINT: human arbitrates the triage before the PR is opened. Open with the approval brief, triage form.

## 7. Close
- Prepare a small, focused PR. The body follows CLAUDE.md *PR descriptions* and stays within
  *Output budget*. **Why** carries the spec path; when 5q ran, **Review** adds the QA verdict and
  any bug left unfixed. No gate-by-gate narrative.
- On merge: set the spec status to done and record any decisions made during implementation.
- If the code diverged from the spec for a good reason, update the spec — never leave it stale.
