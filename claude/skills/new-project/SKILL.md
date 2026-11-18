---
name: new-project
description: Scaffold the standard project layer into the current repo, adapted to its stack — AGENTS.md, a thin CLAUDE.md, the docs/ tree (constitution, architecture, glossary, roadmap, ai-profile, QA guide, ADR + spec templates, and an operations runbook when the project has production runs), path-scoped .claude/rules, local hooks + CI pointers, and for frontends a design scaffold plus a frontend-iteration skill. Use when starting a new project or adding the standard structure to an existing one. Resolves the stack first, scaffolds the skeleton with stack-appropriate command pointers, and leaves every project-specific fact as an explicit placeholder for the human to confirm.
---

# New project bootstrap

Scaffold the standard project-layer structure into the current working directory. **Never overwrite an
existing file** — if one exists, show it and ask before touching it. Everything you create is a
skeleton: project-specific facts are left as `TODO`. Keep it stack-agnostic — only the command
pointers and per-area rules are pre-filled from the detected stack, and even those are marked
`TODO-confirm`, never treated as final.

If the repo already has code, history and its own conventions, this is the wrong skill — use
`adopt-project-layer`, which reconciles instead of scaffolding. It delegates back here for the
pieces that are genuinely missing.

**Work in a worktree** (`EnterWorktree`, landing at `~/worktrees/<repo>/<branch>`), like any other
change. In `~/Projects` the edit guard refuses `AGENTS.md`, `CLAUDE.md` and `docs/ai-profile.md` on
`main` anyway. The one exception is a repo with no commits yet: there is no `main` to branch from,
so make an initial commit first (a README is enough), then branch.

## Step 0 — resolve the stack (do this first)

- Detect from files present: `Gemfile` → Ruby/Rails, `package.json` → Node (inspect deps for
  Next/React/Vue/etc.), `pyproject.toml`/`requirements.txt` → Python, `go.mod` → Go, `Cargo.toml` →
  Rust, etc. A repo can be **multi-stack / multi-area** (e.g. `backend/` Rails + `web/` Next) — detect
  each area and its directory.
- If nothing is present or it's ambiguous, **ASK**: "What's the stack, and how is the repo laid out?"
  Don't guess.
- Use the resolved stack only to pre-fill the command pointers and per-area rule stubs below with that
  ecosystem's conventional shape. **Never invent exact commands** — mark them `TODO-confirm`.

Conventional command shapes by stack (starting points, not truth — the human confirms):
- Ruby/Rails: install `bundle install`; test `bundle exec rspec` or `bin/rails test`; lint `bin/rubocop`; run `bin/dev`
- Node: install `npm install`; test `npm test`; lint `npm run lint`; types `npm run typecheck`; run `npm run dev`
- Python: install `uv sync` or `pip install -r requirements.txt`; test `pytest`; lint `ruff check`; run per project
- Go: install `go mod download`; test `go test ./...`; lint `golangci-lint run`; run `go run ./...`
For any stack not listed, leave the pointers as plain `TODO` and ask.

**Coverage** is part of the stack, not an afterthought: `trivial-lane-check` measures coverage on the
changed lines against an 85% target and reads the tool's own report (SimpleCov's
`coverage/.resultset.json`, Jest's `--coverage`, `pytest --cov`). Wire the tool in with a minimum of
85 unless the human names another number.

**Pin versions to the current stable release**, not to versions copied from older projects.
Record the resolved versions in `AGENTS.md` under Stack.

**Generators write their own agent files.** Some scaffolders now emit an `AGENTS.md` / `CLAUDE.md`
inside their area (Next.js 16 writes `web/AGENTS.md` with a managed `nextjs-agent-rules` block, and
`web/CLAUDE.md` importing it). Keep them: leave the managed block untouched, and put area-specific
rules that must load with it (design non-negotiables, say) below it. Never delete one to make room
for the root file.

## What to create

### 1. `AGENTS.md` (repo root) — shared cross-agent context
Sections (fill Stack from Step 0; leave the rest as TODO skeletons):

```
# AGENTS.md

Shared, cross-agent context for <project>. Any AI agent working here reads this file (Claude Code
imports it from CLAUDE.md; other agents read it directly). Project facts live here; personal working
preferences live in the developer's global config.

## What this is
<TODO — one paragraph: what the project is and the core thesis>

## Stack
<pre-filled from Step 0; TODO-confirm versions/details>
<multi-area repos: name the local ports each area runs on>

## Repo layout
<TODO — top-level directories and what each is>

## Commands
| Task | Command |
|---|---|
| Install | <stack shape — TODO-confirm> |
| Test (full) | <the pre-push form from section 6 for a queued suite, else stack shape — TODO-confirm> |
| Test a subset | <stack shape with files, e.g. `rspec <spec files>`, `jest --findRelatedTests <files>`, `pnpm --filter <pkg> exec vitest run <files>` — TODO-confirm> |
| Coverage | <the full run's report — TODO-confirm> |
| Lint | <stack shape — TODO-confirm> |
| Types | <stack shape — TODO-confirm> |
| Security | <stack shape — TODO-confirm> |
| Run dev | <stack shape — TODO-confirm> |

Every CI check is runnable locally with one command, and the local hooks (see section 6) run them
before a commit or push, so CI failures are rare.

## Conventions
- Tests — <framework from Step 0 — TODO-confirm>. Every feature has at least one test. Coverage
  minimum is <85 — TODO-confirm>% and enforced — don't lower it to pass a build.
- Code review scope — lint, formatting, type checks, secret scanning, SAST and the test suite run
  in <hooks/CI from Step 0 — TODO-confirm> (see Commands above). Don't re-report what they already
  catch: in review those are false positives. Review — human or AI — is for what those tools cannot
  see: correctness and logic bugs, drift from the spec's acceptance criteria, behaviour left without
  a test, authorization and tenancy holes, and API or data-model design.
- Commits & branching — Conventional Commits; feature branch `<type>/<short-task-name>`, never `main`.
- PRs are small and frequent — green on its own, leaves `main` working, one reviewable concern.
- <TODO — language, naming, per-area structure>

## Architecture notes
Key decisions are recorded in `docs/architecture.md`; the weightiest get an ADR in `docs/adr/`.

## Domain glossary
Domain terms and invariants are in `docs/glossary.md` — read it before touching data.

## Guardrails
- No new dependencies without flagging them first.
- Schema/contract changes update `docs/architecture.md` in the same PR.
- Product/scope decisions belong to the owner — flag, don't guess.
- Don't weaken a linter, security or CI check to make a build pass.
- Collaboration model — `docs/constitution.md`. QA guide — `docs/qa.md`.
  AI gate calibration — `docs/ai-profile.md`.
```

If section 5 creates `docs/operations.md`, add `Runbooks — docs/operations.md.` to the last Guardrails
bullet.

### 2. `CLAUDE.md` (repo root) — thin

The global working agreement already carries the loop, the tiers, TDD and the gates. This file's job
is to import `AGENTS.md` and name what is **specific to this repo** — nothing else. Restating the
global loop here is how the two drift.

```
@AGENTS.md

## Claude Code

- The default loop (classify → trivial or light: plan+TDD / Tier A/B: `feature-workflow`; plan-gate,
  then apply without stop-and-show) lives in `~/.claude/CLAUDE.md` and applies here — don't restate it.
- Project specifics: use plan mode for any change outside `docs/`.
- Who writes what, TDD, and review-at-PR: see the collaboration model in `docs/constitution.md`.
- Personal cross-project preferences load from `~/.claude/CLAUDE.md` — don't duplicate them here.
```

If Step 0 detected a **frontend**, extend the "Project specifics" bullet with:
`frontend work starts with the `frontend-iteration` skill (loads design refs + their authority rules).`


### 3. `docs/ai-profile.md` — the workflow profile (do not skip this)

This is the file the AI gates read. Without it, `codex-audit` records
`skipped: outbound review not authorized for this repository (codex_reviewer is unset)` at every gate
and the independent review silently never happens — `codex_reviewer` has no default, because the safe
answer for code you don't own is "no".

- **Start from the template at `codex/profile.template.md` in this workflow repo** — read it in place, copy it to
  `docs/ai-profile.md`, and delete the fields whose default is right.
- **Blank `codex_reviewer` the moment you copy it.** The template ships with `yes` as an example
  value; a copy that keeps it has answered the consent question by omission.
- **Interview for the Calibration block.** It is injected verbatim into every gate prompt and is the
  only thing that makes a review's severities mean anything. Written vaguely, every gate returns
  generic best-practice findings. Ask for: team size and who approves what; the scale a reviewer
  would otherwise guess wrong (users, rows, requests, growth); how a bad change is noticed and how
  fast it rolls back; the areas that are genuinely high-stakes here, named concretely; and what is
  explicitly **good enough** already, so reviewers stop re-litigating settled trade-offs.
- **Ask for `codex_reviewer` explicitly** — "may this repo's specs, plans and diffs be sent to Codex,
  a different provider?" Write down the answer given; never fill in `yes` yourself.
- Set `artifacts` (where specs and plans live — usually `docs/specs`; plans land in its `plans/`
  subfolder), `gates`, `commands_ref: AGENTS.md`, and the two doc-language fields.
- **`gates`: `1b,2b` is the standard set.** Add `6b` only if the project will carry Tier A work with
  detailed acceptance criteria — it audits a diff for criteria left unimplemented, which is expensive
  input, and `feature-workflow` runs it on Tier A only. Record why in the profile's body.
- Review ledgers live in `.git/codex-audit/`, never in the tracked tree — don't create a
  `docs/specs/reviews/` folder.
- **`commands_ref` points at `AGENTS.md`; never copy commands into the profile.** Two copies drift.
- If workflow files cannot be committed to this repo (client or employer code), the profile goes
  out-of-repo at `~/.config/ai-workflow/projects/<repo-dir-name>.md` instead, and must declare
  `repo_identity` — a directory basename isn't unique.

### 4. `docs/qa.md` — the QA guide

The `qa` agent reads this and nothing else about how the app runs; `/qa` stops if it is missing.
Create it from `~/.claude/skills/qa-methodology/references/docs-qa-template.md`, fill what Step 0
gives you (start command, ports) and leave the rest `TODO`. **No secrets** — test-user credentials
are named by env var or password-manager entry, never written out. For a project with no running
app (a library, a CLI with no state), say so and skip it.

### 5. `docs/` tree

- `docs/constitution.md` — validated skeleton:
```
# Constitution
Enduring principles that govern how <project> is built. Specs must respect these.

## Purpose
<TODO — what the project is for; the prime directive that resolves trade-offs>

## Product ownership
<TODO — who owns scope/product decisions; flag-don't-guess boundary>

## Scope discipline
<TODO — what's in the current phase; what's deferred/out of scope>

## Collaboration model
<TODO — who writes the code; e.g. Claude Code writes tests and implementation, migrations included>.
The developer keeps visibility and control through approval gates.

- **Approval is at the plan, not the diff.** Once the plan is approved (or, for a small, low-risk
  change, the request itself), Claude Code implements it fully — no pausing to show each edit. The
  developer reviews the result as a diff / PR. This mirrors the global `CLAUDE.md` default loop.
- **TDD, never skipped.** Failing test first, then implementation, then refactor. The test cases are
  agreed in the spec/plan; test and implementation code are then written together, without a
  separate per-step approval.
- **Planning is human-first.** The developer decides what to work on and in what order.
- **No silent scope creep.** A task that needs changes beyond what was asked stops and asks.

## Delivery
- Small, frequent PRs: green on its own, leaves `main` working, one reviewable concern.
- Feature branches only, never `main`. Open PRs with `gh pr create`. Never push to `main`, never
  merge a PR — the developer reviews and merges.
- Never weaken a linter, security or CI check to make a build pass.

## Language
<TODO — language for code/comments/commits/docs and for UI copy>
```
- `docs/architecture.md`:
```
# Architecture
When a decision changes, update this file (and the relevant ADR) in the same PR.

## Overview
<TODO — how the pieces fit together>

## Decisions
Record architectural decisions here; the weightiest get their own ADR in `docs/adr/`.
<TODO>

## Quality tooling & CI
<TODO from Step 0 and section 6 — lint/test/coverage/security commands, local hooks, CI workflows>

## Reference
- Domain — `docs/glossary.md` · Principles — `docs/constitution.md` · Plan — `docs/roadmap.md`
- QA guide — `docs/qa.md` · AI gate calibration — `docs/ai-profile.md`
```
- `docs/glossary.md`:
```
# Domain glossary & rules
Domain terms and the invariants not inferable from the code. Read before touching data.

## Terms
<TODO>

## Rules
<TODO — invariants that "look reasonable and are wrong" when violated>
```
- `docs/specs/_template.md` (verbatim):
```
# <Feature name> — spec
**Status:** draft | approved | in progress | done
**Date:** YYYY-MM-DD

## 1. Outcome
## 2. Scope   (In: … / Out: … ← the "out" prevents scope creep)
## 3. Constraints
## 4. Decisions   (Made: [decided] X because Y / Open: [OPEN — owner] question)
## 5. Task breakdown   (filled in the plan phase, ordered)
## 6. Acceptance criteria   (Given/when/then — each becomes a regression test)
```
- `docs/adr/_template.md` (verbatim):
```
# NNNN. <Title>

## Context
<Forces at play: problem, constraints, what this builds on. Facts, not the decision yet.>

## Decision
<The decision, stated plainly.>

## Alternatives considered
<Each realistic alternative and why it was not chosen.>

## Consequences
<What follows — the good, the costs, the couplings it creates.>

## Revisit triggers
<Concrete conditions under which to reopen this ADR.>
```
- `docs/roadmap.md` — minimal stub:
```
# Roadmap
<TODO — current phase and the ordered plan of work. Referenced by AGENTS.md and the constitution.>
```
- `docs/operations.md` — **optional.** Create it only if the project has production runs, scheduled
  jobs, data loads or anything else run by hand against a live environment.
  Ask if unclear. When created, it starts as a stub — a runbook nobody started is never written:
```
# Operations
Runbooks for tasks that happen outside the normal PR flow — provisioning, data loads, anything run
by hand against a live environment.

<TODO — one section per recurring operation: preconditions, the exact command, how to tell it
worked, and what to do when it didn't.>
```
  When created, add it to `docs/architecture.md` § Reference and the `AGENTS.md` Guardrails.

### 6. Quality tooling — local hooks and CI

`AGENTS.md` tells every reviewer not to re-report what lint, formatting, type checks, secret scanning,
SAST and the suite already catch. **That instruction is only honest if those checks actually run.**
Scaffolding the docs without the tooling produces a repo where nothing is checked and nobody reviews
for it either.

Propose, and confirm with the human before adding any dependency:

- **Local git hooks** — Lefthook is the standing choice. Shape: `pre-commit` runs lint + formatter on
  staged files plus `gitleaks protect --staged --redact`; `pre-push` runs the test suite (with
  coverage, so the minimum is enforced locally) and the security scanners. One block per area for a
  multi-area repo (`root: backend/`, `root: web/`).
- **Queue an RSpec, Jest or Vitest suite** (`npm test` or `pnpm test` included) through `suite-queue`, which
  runs one suite per kind machine-wide and skips content that already passed. One line, the same
  `<cmd>` in both branches:
  `run: if command -v suite-queue >/dev/null; then suite-queue <ruby|js> <cmd>; else <cmd>; fi`.
  The Commands table's full-suite row is then
  `SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out lefthook run pre-push --force --no-tty --command <name>`
  (lefthook 2.x; the env var keeps a green run's summary visible under `output: [failure]`):
  a pass recorded through the hook is what the push skips on, and `suite-form-guard.py` denies
  other full-run forms. One queued suite per runner per repo: the guard maps each runner to one
  command. Other runners and stacks run their suite directly.
- **CI** — a workflow per area running the same commands, plus a scheduled dependency-audit workflow
  and `dependabot.yml`. The rule is **one command per check, runnable locally** — a CI step nobody can
  reproduce on their machine is a step that gets ignored.
- **A third-party PR reviewer** (e.g. `.coderabbit.yaml`) is optional, not part of the layer. Offer it
  once; if taken, give it per-path instructions that match `.claude/rules/`.

Then write the actual commands into the `AGENTS.md` Commands table and `docs/architecture.md`
§ Quality tooling — those are the copies everything else reads.

### 7. Frontend extras — ONLY if Step 0 detected a frontend

- **`docs/design/README.md` — the authority map over visual references.** Says, per reference, what it
  governs (aesthetics / structure / states) and what NOT to take from it. A reference with no stated
  authority is decoration, not a decision.
```
# Design references
Visual references for the UI. **Documentation, not source.** The authority map for frontend work —
the `frontend-iteration` skill reads it before writing UI.

## Files
| File | What it is | Authority | Do not take |
|---|---|---|---|
| _(none yet)_ | — | — | — |

## Where styling and components come from
<TODO — component library and conventions>. Surface visual gaps instead of inventing defaults.

## Where product assets go
Anything the app renders belongs in the app, not here. This folder holds only what documents a decision.
```
- **`docs/design.md` — the design contract, optional at scaffold time.** It is extracted from
  shipped code — colors, typography, spacing, shape, component inventory: what the code *actually
  does*, which is what `ui-review` diffs future screens against. A new project has no shipped UI to
  extract from, so don't create it now. Create it once the look has settled (the first screens are
  built), from `~/.claude/skills/ui-review/assets/design-template.md`, reading the real styling
  config, global stylesheet and components. Where the code is inconsistent, list both values under
  "Known inconsistencies" — never average them into a clean scale. The Personality section is the
  one part code cannot produce: ask the human and record the date it was confirmed.
  `docs/design/` is intent, `docs/design.md` is reality — say so where they disagree. Until it
  exists, `ui-review` will stop and ask for it; tell the human that.
- **`.claude/skills/frontend-iteration/SKILL.md`** — start from the template at
  `~/.claude/skills/frontend-iteration/skill.md`, then **rewrite it around this project's actual
  authority map** rather than leaving the generic Customization stub: name the reference files and
  what each governs, the component library, the styleguide route if there is one, and the rule that a
  visual question with no answer in the references gets surfaced, not guessed. A project skill that
  still reads like the template is one nobody wrote.

### 8. `.claude/rules/<area>.md` — one per distinct area detected in Step 0
For a multi-area repo (e.g. `web/` + `backend/`), create one rule per area with `paths:` frontmatter.
For a single-area repo, skip these (conventions already live in AGENTS.md) and say so.
```
---
paths:
  - "<area>/**"
---

# <Area> rules (<area>/)
Standard <stack> conventions.

## Structure
<TODO — where logic/components live for this stack>

## Testing
<TODO — framework from Step 0; no spec hits the network>

## Naming
<TODO — this stack's file/symbol naming>

## Gates that apply here
<TODO — name the automatic skills this area triggers, so they're visible at the path they fire on:
`migration-safety` for anything under the migrations directory, `frontend-iteration` before any UI
work, `data-integrity` for schema and model changes. Say why it matters *here*, not in general.>
```

### 9. `.gitignore`
Add, creating the file if absent:
- `logs/` — agent and hook runtime output, not a project artifact.
- `.env`, `.env.*` with a `!.env.example` negation, if the stack uses dotenv files.

`.claude/settings.local.json` needs no entry: the global gitignore (`~/.config/git/ignore`) already
covers it. Worktrees need none either: they live outside the repo at `~/worktrees/<repo>/<branch>`.

## After scaffolding
- Run `/context` to confirm `CLAUDE.md` + imported `AGENTS.md` load (and the `frontend-iteration`
  skill is discoverable, if created).
- **Check the repo is under a Codex trusted root.** `~/.codex/config.toml` trusts
  `~/Projects` and `~/worktrees`. A repo outside those needs its own
  `[projects."<abs-path>"] trust_level = "trusted"` entry, or every Codex gate skips with no obvious
  cause. Say which case this repo is in.
- Give the human a **confirm checklist**: the pre-filled commands, the test framework and coverage
  minimum, the repo layout, the mission/purpose, the `codex_reviewer` answer,
  the optional docs created or skipped, and each per-area rule. **Explicitly flag every
  value pre-filled from a stack default** so it can be corrected.
- Do NOT treat any pre-filled command as final — they are starting points the human confirms.
- Deliver it as one PR from the worktree, shaped like any other (global *PR descriptions*).
