# Portable AI workflow + Claude ↔ Codex cross-review loop — design brief

**Status:** shipped
**Date:** 2026-09-22
**Scope:** `~/dotfiles` (Claude Code + Codex config). Not tied to any single project.

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 0. How to use this brief (for Claude Code)

- This is a **non-trivial change to the global workflow**. Treat it with plan-first discipline:
  read this brief, read the real files it touches, then propose a plan. No edits before an explicit "go".
- This brief states the *what* and the *constraints*. The *how* (exact file edits, script code)
  is yours to plan against the files as they really are. Where this brief and the real files
  disagree, say so — don't silently pick one.
- Deliver in the phases of §10, each one a separate, reviewable commit in dotfiles.
- Items marked **[OPEN — the owner]** are decisions for the human. Ask; don't decide.

## 1. Goals and non-goals

**Goals**
1. The workflow (phases, gates, conventions, artifact layout, review protocol) is **defined once,
   globally**, and behaves the same in any repository: personal, client, or employer.
2. Everything project-specific lives in a **small, declarative project profile**, with sane
   defaults when it's missing.
3. Codex cross-checks become a **bounded two-round loop** (critique → response → verification),
   instead of today's stateless one-shot `codex exec`.
4. The human's checkpoint shrinks to **the disputes**, not the full raw critique.
5. Net time per feature stays roughly flat: the extra round is paid for by better-calibrated
   critiques and smaller arbitration.

**Non-goals**
- No external orchestrator (Hermes or similar) in this iteration. The protocol must stay
  portable to one later.
- No Codex participation in the trivial lane.
- No change to the security gates (1s / 2s / 5s) beyond referencing them consistently.

## 2. Portability principle: three layers

| Layer | What it holds | Where it lives | Changes when |
|---|---|---|---|
| **L1 — Global, fixed** | Workflow skills, gate definitions and numbering, reviewer contract, round protocol, `codex-audit` wrapper, naming and artifact conventions | `~/dotfiles` → symlinked into `~/.claude`, `~/.codex` | You change how you work |
| **L2 — Project profile** | Calibration context, artifact location, doc language, verification commands, enabled gates/reviewers | See §2.1 resolution order | You join or reshape a project |
| **L3 — Feature artifacts** | Spec, plan, review ledgers | Location given by L2 | Every feature |

**Hard rule:** L1 never hardcodes a project name, path, command, language, or domain assumption.
Anything that varies by project is read from L2, with a documented default. Grep L1 for
project-specific strings as part of acceptance (§11).

### 2.1 Project profile

A single file, deliberately small. Resolution order:

1. In-repo: `.ai/profile.md` (committed — for repos you own).
2. Out-of-repo: `~/.config/ai-workflow/projects/<repo-name>.md` (for repos where you can't or
   shouldn't add workflow files — client/employer code).
3. Neither exists → global defaults, and at the first gate, offer once to create one (asking
   the questions needed to fill it). Never block on it.

Proposed fields (Claude Code: refine the list; keep it short):

- **Context for review calibration:** team size, scale (users, data volume), who approves what,
  deployment risk, the risk areas that are genuinely high-stakes here, what is explicitly
  "good enough" for this project.
- **Artifacts:** `in_repo: <dir>` (default `docs/specs`) or `external: ~/ai-work/<repo>/`.
  Specs, plans and ledgers all resolve from this one setting.
- **Languages:** technical docs (default English); product docs such as specs/PRDs
  (default English). *Example:* a product repo sets product docs to Spanish.
- **Post-steps for product docs**, if any. *Example:* a project uploads specs to a shared
  folder for a stakeholder. This belongs in the profile, never in a global skill.
- **Verification commands:** test, lint, security, coverage (defaults: detect from the repo).
- **Reviewers allowed:** `codex: yes|no` (some employers won't allow code to leave for another
  provider), and what to do if not (see §7).
- **Gate overrides:** e.g. disable 6b, or force 1b/2b on every non-trivial change.

Example profiles for two product repos are part of the deliverable — two different projects
are the real test of portability.

### 2.2 AGENTS.md vs profile

AGENTS.md stays what it is: project facts for any agent. The profile holds only workflow
calibration. In repos where AGENTS.md isn't yours, nothing in L1 may depend on it existing.

## 3. Reviewer contract (global, injected into every Codex gate)

One file in dotfiles (suggested: `~/dotfiles/codex/reviewer-contract.md`), prepended by the
wrapper to every gate prompt, followed by the project's calibration context from L2. Draft —
Claude Code may tighten it:

```
You are an independent reviewer. Your job is to find what would cause real harm if shipped
as written, not to list every possible improvement.

Project context (calibrate everything to it):
{{profile.calibration}}

Severity:
- BLOCKER: will cause incorrect behaviour, data loss, a security hole, or makes the
  artifact unimplementable as written. Must cite concrete evidence.
- MAJOR: a real gap likely to cause rework or a production issue in THIS project's context.
- MINOR: worth noting; will not be looped on.
Anything that is "best practice" without a concrete failure path in this context is MINOR at
most.

For every BLOCKER/MAJOR, include:
- id: <gate>-F<nn> (e.g. 2b-F03), stable across rounds
- evidence: file:line, spec section, or plan step
- failure path: what concretely goes wrong
- smallest fix: the simplest change that removes the failure path

Limits: at most 8 BLOCKER+MAJOR findings; if you have more, keep the most severe and say how
many you dropped. Group MINORs in one short list at the end.

Do not propose new process, governance, or documentation unless its absence causes a
concrete failure in this project.
```

## 4. Round protocol

### 4.1 Shape

1. **Round 1 — critique.** Codex reviews the artifact under the contract.
2. **Response — Claude.** For every BLOCKER/MAJOR id, exactly one of:
   - `accepted` + what changed (reference to the section/line of the revised artifact);
   - `rejected` + reason, **verified against code or spec**, not asserted;
   - `human` — a product/PO/business decision; not debated between models.
   MINORs: batch-triaged (fix now / defer / reject), no per-item debate.
3. **Round 2 — verification.** Codex receives the revised artifact + the response table and
   answers only:
   - per `accepted`: `resolved` | `not resolved` (why);
   - per `rejected`: `concede` | `maintain` (with a **new** argument, not a restatement);
   - `regressions`: problems introduced by the fixes themselves.
   It may **not** open new topics unrelated to a change.
4. **Close.** Anything `maintained` or `not resolved` after round 2 goes to the human. Models do
   not argue further.

### 4.2 Limits per gate

| Gate | Artifact | Max rounds | Objective arbiter between rounds |
|---|---|---|---|
| 1b | Spec | 2 | — |
| 2b | Plan | 2 | — |
| 6b | Diff vs spec (spec-conformance axis only) | 3 | Test suite must be green before each round |

Early stop: round 2 is skipped when round 1 has zero BLOCKER/MAJOR.

### 4.3 Session continuity

Round 2 should resume Codex's round-1 session so it judges its own findings with its original
reasoning. Capture the session/thread id from round 1 (e.g. from `codex exec --json` output) and
resume it (`codex exec resume <id>`). **Verify these flags against the installed Codex CLI
version** before relying on them; if resume isn't viable, fall back to a fresh session whose
only context is the ledger + revised artifact.

### 4.4 The ledger (one file per gate per delivery)

> **Amended 2026-09-25**, when the wrapper gained `--pr`. This section originally
> read "one file per gate per feature", with the path `<artifacts>/reviews/<slug>-<gate>.md`. That
> holds only while a spec ships in a single PR. Gate 6b ran twice against
> `2026-09-feature-x` — once per half of a three-PR delivery — and both runs
> resolved to one path, so the first ledger exists in no checkout. A spec delivered across several
> PRs legitimately earns one ledger per gate **per PR**.

Path: `<artifacts>/reviews/<slug>-<gate>.md`, or `<slug>-<gate>-pr<index>.md` when `--pr` is
given (resolved from L2). `<index>` is the PR's row in the plan's delivery table — an identity
that exists before the PR is opened, unlike a GitHub PR number. Without `--pr` the path is
exactly as it was, so every ledger written before this amendment stays valid.

A ledger is also now protected in three ways it was not: a lock keyed on the resolved path stops
two gates writing it at once, the round-1 path refuses to replace a ledger that already holds a
review, and the escape that does allow replacement archives the old one rather than destroying it.

Contains, in order:

1. Header: gate, artifact path + revision, date, reviewer model, round count.
2. Round 1 — Codex output, **verbatim**.
3. Response table (id · severity · status · change/reason).
4. Round 2 — Codex output, **verbatim**.
5. **For the human:** only the open items (maintained / not resolved / `human`).
6. Metrics footer: findings by severity; accepted / rejected / conceded / maintained;
   regressions found in round 2; wall-clock per round.

The spec's §4 records a short summary + a link to the ledger — no longer the full synthesis.
This replaces both the "session scratchpad" instruction and the ad-hoc `docs/specs/reviews/`
practice with one rule.

### 4.5 Plans get a home

Before 2b, the plan is written to `<artifacts>/plans/<slug>.md`. The wrapper reads it from the
file — no more serializing the plan into a shell argument. Plan-mode files in `~/.claude/plans/`
are scratch, not the record.

## 5. `codex-audit` v2 — single entry point

The wrapper becomes the only way gates call Codex; `feature-workflow` calls the wrapper, never
raw `codex exec`. Prompts live in one place in dotfiles (one file per gate), not duplicated in
the skill.

Interface (Claude Code: refine):

```
codex-audit <1b|2b|6b> [--slug <slug>] [--round 1|2] [--response <file>]
```

Responsibilities:
- Resolve the profile (§2.1) and the artifact paths from it; default slug = most recent spec.
- Build the prompt: reviewer contract + calibration context + gate prompt (+ response table on
  round 2).
- Run with the read-only `audit` profile; write/append to the ledger; capture the session id for
  round 2.
- Exit non-zero with a clear message on: missing artifact, Codex not authenticated, reviewer
  disabled by profile.
- Must work from any repo and any worktree path.

## 6. Normalize naming and policy (single source of truth)

- Gate ids are **1b / 2b / 6b**, defined only in `feature-workflow`. README, wrapper comments and
  the PR hook reference them; they don't restate them.
- The 6b prompt keeps its spec-conformance-only axis (what's missing, not style) so it doesn't
  overlap `/code-review`.
- One trigger policy (today README and skill disagree). Proposed: 1b and 2b for every
  non-trivial change; 6b for Tier A; overridable per project in L2.

## 7. Degradation

- Profile says `codex: no`, or Codex unavailable → the gate records `skipped: <reason>` in §4 and
  continues. **[OPEN — the owner]** whether to substitute a fresh-context Claude reviewer under the same
  contract in that case (same-provider review is weaker but not worthless).
- Artifacts external (not in repo) → everything still works; PR description links nothing
  private.
- No profile → defaults + one-time offer to create it.

## 8. Permissions and trust

- **[OPEN — the owner]** Allowlist exactly the `codex-audit` wrapper in Claude Code's Bash permissions.
  Rationale: the `audit` profile is `sandbox_mode = "read-only"`, `approval_policy = "never"`; with
  two rounds per gate, a prompt per call becomes pure interruption. Raw `codex exec` stays
  un-allowlisted.
- Narrow Codex `trust_level = "trusted"` from the whole `$HOME` to `~/Projects` and `~/worktrees`
  (gates run from worktrees, which today only work because `$HOME` is trusted).

## 10. Rollout

1. **Phase 1 — foundations:** profile resolution + defaults, reviewer contract, `codex-audit` v2
   (1b and 2b, rounds 1–2, ledger), `feature-workflow` 1b/2b rewired, plans written to file,
   trust narrowing. Profiles for two product repos.
2. **Pilot:** the next non-trivial feature in each of those two repos. Collect ledger
   metrics.
3. **Phase 2:** 6b on the loop (up to 3 rounds, tests green between rounds).

**Kill criteria after the pilot:** if round 2 rarely finds real issues (fixes that didn't close
a gap, or regressions), drop round 2 and keep the contract + ledger only.

## 11. Acceptance criteria

1. Given a repo with no profile, when a non-trivial feature reaches 1b, then the gate runs on
   defaults and offers once to create a profile.
2. Given a repo where workflow files can't be committed, when the profile is external, then
   specs, plans and ledgers are written outside the repo and nothing is added to it.
3. Given round 1 with zero BLOCKER/MAJOR, then round 2 is not run.
4. Given a finding Claude rejects, when Codex maintains it in round 2, then it appears in the
   ledger's "For the human" section and the models do not exchange further on it.
5. Given round 2, then Codex's output contains no new findings unrelated to a change made in
   response to round 1.
6. Given the same feature workflow run in two different product repos, then gate ids, ledger
   format and artifact layout are identical; only profile-driven values differ.
7. `grep` over L1 files finds no project names, project paths, or project-specific commands.
8. The wrapper works from `~/Projects/...` and `~/worktrees/...` alike.
9. Every Codex output is preserved verbatim in the ledger.

## 12. Open decisions

- **[OPEN — the owner]** Allowlist the wrapper (§8).
- **[OPEN — the owner]** Fallback reviewer when Codex isn't allowed (§7).
- **[OPEN — the owner]** Profile location name (`.ai/profile.md` is a proposal).
- **[OPEN]** Whether Tier B should also get 6b once Phase 2 proves out.

---

## 13. Decisions resolved (2026-09-22)

Recorded at the start of Phase 1. The sections above are preserved as written —
where a decision below supersedes a proposal above, this section wins. The owner decided each one;
the rationale is the consequence that made it a decision, not a restatement of the question.

| § | Question | Decision | Supersedes |
|---|---|---|---|
| 12 | In-repo profile location | `docs/ai-profile.md` | `.ai/profile.md` in §2.1 |
| 8 | Allowlist the wrapper | Yes — `Bash(codex-audit:*)` only; raw `codex exec` keeps prompting | — |
| 7 | Fallback when `codex: no` or Codex unavailable | None. Record `skipped: <reason>` and continue | The open question in §7 |
| 2.1 | Out-of-repo profile key | Repo **directory basename**, resolved via `git-common-dir` | "`<repo-name>`", which was ambiguous |

**Why the profile key needed deciding.** A project's repository directory can differ from the
name its worktrees live under: say the repository is `~/Projects/app` while its worktrees are
under `~/worktrees/product/`, and both `~/worktrees/product/` and `~/worktrees/app/` exist on
disk. Resolving the key from `git rev-parse --path-format=absolute --git-common-dir` and taking
the basename of its parent yields `app` from every checkout — verified from the main checkout
and from a worktree under the other name. Resolution never reads the worktree path, so the
naming drift cannot affect it, and §11 acceptance criterion 8 holds by construction. The
out-of-repo key is therefore `app`, and the in-repo profile is `app/docs/ai-profile.md`.

**Consequences carried into Phase 1.**

1. Allowlisting makes `codex/bin/codex-audit` a **trust boundary**: anything able to write that
   file gains unprompted Bash execution. A trust-boundary change, recorded at gate 2s rather
   than passed off as a config tweak.
2. `feature-workflow` currently states the Bash prompt for `codex exec` is a confirmation point
   that must not be allowlisted. That line becomes false with decision §8 and is rewritten: the
   wrapper is allowlisted because it can only ever run the read-only `audit` profile; raw
   `codex exec` is not, because it can run anything.
3. `skipped` must be a **distinct outcome** in the §4.4 metrics footer. A skipped gate and a gate
   that ran and found zero BLOCKER/MAJOR both render as "0 findings" otherwise, which would make
   the Phase 2 pilot metrics misleading about how often Codex actually ran.

## 14. Corrections to this brief (found by reading the real files)

Phase 1 planning read every file §0 points at. Where the brief describes the setup as it is not,
the truth is recorded here; the prose above is left untouched.

- **§6 — gate numbering is split three ways, not one.** `feature-workflow/SKILL.md` and
  `hooks/gh-pr-create-review-reminder.py` say **6b**; `codex/bin/codex-audit`,
  `codex/audit.config.toml` and `README.md` say **5b**. Phase 1 changes three files, not two.
  Separately, `ui-review/SKILL.md` ("2b. Web Interface Guidelines") and `commands/config-audit.md`
  ("Phase 4b") are a *different* numbering namespace that collides with the gate ids; §6's rule is
  scoped to **Codex gate ids** to avoid claiming those.
- **§5 — the wrapper's verbs are `spec|plan|diff`, not `1b|2b|6b`**, and `--slug` / `--round` /
  `--response` do not exist (slug is positional today). v2 is a breaking rename, not a refinement.
- **§4.3 — verified against codex-cli 0.152.0.** `codex exec --json` emits
  `{"type":"thread.started","thread_id":"<uuid>"}` as its first event, and
  `codex exec resume <uuid>` works. **But `resume` accepts no `-p/--profile`, no `--sandbox` and
  no `-C/--cd`**, so round 2 cannot re-apply the `audit` profile by name and would otherwise
  inherit the base config's `approval_policy = "on-request"`. Round 2 passes
  `-c sandbox_mode="read-only" -c approval_policy="never"` explicitly. `resume` also filters
  sessions by cwd, so round 2 must run from the same directory as round 1.
- **`codex exec` reads stdin whenever stdin is not a TTY**, which it never is under Claude's Bash
  tool. The v1 wrapper's `[[ ! -t 0 ]]` branch therefore fires on *every* Claude-driven call. v2
  redirects `< /dev/null` explicitly.
- **§2.2 — the split is cleaner in this brief than on disk.** The verification commands §2.1 wants
  in the profile already exist and are maintained in each repo's `AGENTS.md` Commands table, as
  do the doc-language rules and the review-scope rule. The profile therefore *points at* `AGENTS.md`
  for commands and language where one exists, and carries only what `AGENTS.md` lacks. L1 still
  never depends on `AGENTS.md` existing — the dependency lives in L2.
- **§11 acceptance criterion 7 cannot pass as written.** A grep over L1 today legitimately hits
  `claude/CLAUDE.md` (product repos as worktree-path *examples*), `codex/config.toml` (a
  product repo's trust block), `skills/adopt-project-layer/SKILL.md` (a product repo named in
  a trigger phrase) and `hooks/block-edits-on-main.py` (`~/Projects` as a machine path). AC7 is
  scoped to the files Phase 1 adds plus `feature-workflow` and the wrapper, and excludes machine
  paths.
- **§4.5 — the plan reaches the wrapper on stdin today**, not "serialized into a shell argument".
  The fix stands either way.
- **§8 — narrowing trust removes `~/dotfiles`.** It is trusted today only because all of `$HOME`
  is. After narrowing to `~/Projects` and `~/worktrees`, `codex-audit` cannot run against the main
  dotfiles checkout. Accepted: the worktree rule means this work happens under `~/worktrees/`
  anyway, and a third trust root would widen what §8 set out to narrow.
- **§4.4 — the ledger path collides with existing practice.** One project's
  `docs/specs/reviews/` already held two Codex review files under another naming scheme. They
  are left as they are; the new scheme applies from the next feature onward.
