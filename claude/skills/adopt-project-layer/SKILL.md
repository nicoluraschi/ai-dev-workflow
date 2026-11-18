---
name: adopt-project-layer
description: Bring an existing repo that already has its own conventions onto the standard project layer, by reconciling rather than scaffolding. Fires on "set this repo up like my others", "adopt the standard layer", "make this match my other repos", "add AGENTS.md to this project", "onboard this repo to my setup", and whenever starting work in a repo that lacks AGENTS.md, docs/ or .claude/rules but already has code and history. Establishes first whether workflow files may be committed here and whether this code may be sent to a second AI provider, then inventories what exists, diffs it against the reference layer, classifies every item as adopt / keep-local / override, and surfaces conflicts for a human decision before overwriting anything.
---

# Adopt the project layer (existing repos)

## Why this exists

`new-project` scaffolds the standard layer into a repo. That is the easy case. The hard case
is a repo that already has a `CLAUDE.md` someone else wrote, a README that documents different
commands, a test setup that does not match, and three years of history that encodes
conventions nobody wrote down.

Scaffolding into that repo overwrites decisions. Refusing to touch it leaves the repo outside
the setup. The job is neither: it is **reconciliation** — find out what is already there,
decide item by item what wins, and make the overrides deliberate and visible.

Use `new-project` for a clean repo. Use this one when there is something to lose.

## Step 0 — ownership and reach, before reading anything else

A repo you joined is not a repo you own. Three questions decide what this skill is even allowed
to do, and none of them have a safe default that can be assumed. Ask them together, up front.

1. **May workflow files be committed here?** In a repo with collaborators or an employer, an
   `AGENTS.md` and a `docs/` tree are changes to a shared project, not personal config. If the
   answer is no, the layer still works — it just lives outside the repo:
   - the workflow profile goes to `~/.config/ai-workflow/projects/<repo-dir-name>.md` and **must**
     declare `repo_identity`, because a directory basename isn't unique;
   - `artifacts:` in that profile points somewhere outside the repo (`~/...`), so specs and plans
     never land in a diff;
   - nothing else is created. Say plainly which pieces are being skipped and why.
2. **May this code be sent to Codex — a different provider?** `codex_reviewer` has no default
   precisely so this is never answered by omission. Absent a profile saying `yes`, every Codex gate
   records `skipped` and continues. That is the correct behaviour for client and employer code.
   Never set it to `yes` on the developer's behalf. The same question applies before proposing any
   third-party PR reviewer (CodeRabbit and friends) on a repo the developer does not own.
3. **Is the repo inside `~/Projects`?** Two global mechanisms are path-scoped and will quietly not
   apply otherwise: `block-edits-on-main.py` guards `main` inside `~/Projects` and this workflow
   repo only, and Codex only trusts `~/Projects` and `~/worktrees`, so `codex-audit` refuses to run
   elsewhere without a `[projects."<abs-path>"] trust_level = "trusted"` entry in
   `~/.config/ai-workflow/codex-projects.toml` (then re-run `install.sh` to render it). Say which
   case this repo is in rather than assuming the global layer covers it.

Do not proceed to the inventory until these are answered. They change what gets proposed, not just
how it gets committed.

## The reference layer

The standard layer (the reference repos implement it):

- `AGENTS.md` — shared cross-agent context: stack, layout, commands, conventions, guardrails
- `CLAUDE.md` — thin, imports AGENTS.md, carries only what is specific to this repo
- `docs/` — `constitution.md`, `architecture.md`, `glossary.md`, `roadmap.md`, `ai-profile.md`,
  `qa.md` (the QA guide the `qa` agent reads), plus `adr/`, `specs/` (with `plans/`) and, for
  frontends, `design/`
- optional, when they apply: `docs/operations.md` (repos with production runs or manual operations
  against a live environment) and `docs/design.md` (frontends whose look has settled — `ui-review`
  needs it)
- `.claude/rules/` — path-scoped rules (`backend.md`, `frontend.md`)
- `.claude/skills/frontend-iteration/` — for repos with a frontend
- local hooks + CI that actually run lint, format, secret scanning, SAST and the suite

Treat the reference as the target shape, not as content to copy. Another repo's architecture
notes are not this repo's architecture notes.

**`docs/ai-profile.md` is the one element that is not optional and not cosmetic.** Everything else
is documentation the developer can live without for a while; this file is what the AI gates read,
and its absence means the independent review silently never happens. Section 3 of `new-project`
covers how to build it — including the calibration interview, which is the part that makes a
review's severities mean anything.

## Step 1 — inventory before proposing anything

Read what is there. Do not write a single file during this step.

- existing `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.github/copilot-instructions.md`, and any
  other agent's config or skill directory — including nested ones (`web/AGENTS.md`), some written
  by a generator (Next.js 16 manages a block in its own); those are keep-local, never folded into
  the root file
- how the app is started, its URLs and test users — the raw material for `docs/qa.md`
- `README.md` — especially the commands section, which is usually the real source of truth
- test framework, runner, and how CI actually invokes it
- CI workflows and local hooks (lefthook, husky, pre-commit) — what already runs deterministically,
  since that is exactly what review must then stop re-reporting
- any third-party AI reviewer already configured (`.coderabbit.yaml` and similar)
- any `docs/`, ADRs, runbooks or design notes under another name
- lint/format config, `.editorconfig`, secret scanning
- `CODEOWNERS`, branch protection, and the PR template — they tell you whether "adopt" is a
  decision you are entitled to make alone

Also read the git history briefly. Commit message style and branch names tell you the
conventions even when nothing documents them.

## Step 2 — diff against the reference, item by item

For each element of the reference layer, classify:

| Class | Meaning |
|---|---|
| **Missing** | Not present. Create it — this is the `new-project` part. |
| **Present, compatible** | Exists in a different place or name. Move or rename, keep content. |
| **Present, conflicting** | Exists and says something different. **Needs a decision.** |
| **Present, better** | The repo solves this better than the reference does. Keep it, and propose carrying it *back* into the reference layer. |
| **Local, keep** | Repo-specific and worth preserving even though the reference has no equivalent. |

The fourth class is not politeness. The reference layer got its current shape by absorbing what
worked in the two active projects; a repo that has already solved something better is where the
next improvement comes from. Name it explicitly instead of flattening it to match.

Do not resolve conflicts silently. The standing preference is toward consistency across
repos — a project's own documented convention can be overridden to match the reference — but
"can be" is not "will be without asking". Overriding another person's documented decision is
a human call, especially in a repo with collaborators.

## Step 3 — propose, then wait

Present the reconciliation as a table before touching anything:

```
Element              Status                  Proposal
AGENTS.md            Missing                 Create from repo's README commands + inferred stack
CLAUDE.md            Present, conflicting    Existing file has 200 lines of stack docs.
                                             Propose: move content to AGENTS.md, leave thin pointer.
                                             ⚠️ needs your decision
docs/                Present, compatible     `documentation/` exists → rename to docs/, keep content
docs/ai-profile.md   Missing                 Create; needs your answer on codex_reviewer and the
                                             calibration interview. ⚠️ needs your decision
docs/operations.md   Present, compatible     `RUNBOOK.md` at root → move to docs/operations.md
docs/adr/            Missing                 Create with template; 3 past decisions in README
                                             worth backfilling as ADRs
.claude/rules/       Missing                 Create backend.md + frontend.md from observed layout
local hooks / CI     Present, better         Repo runs semgrep + gitleaks in CI on every PR, which
                                             the reference only schedules weekly. Keep; propose
                                             adopting upward.
test conventions     Present, conflicting    Repo uses minitest; reference assumes RSpec.
                                             Propose: keep minitest. ⚠️ needs your decision
```

Every ⚠️ is a checkpoint. Wait for the human on each one.

## Step 4 — execute what was approved

Do it in a worktree (`EnterWorktree`, at `~/worktrees/<repo>/<branch>`), never on the main
checkout — the global worktree rule applies, and inside `~/Projects` the edit guard refuses
`AGENTS.md`, `CLAUDE.md` and `docs/ai-profile.md` on `main` anyway. Steps 0–3 are read-only and
can run from wherever the session opened.

Delegate to `new-project` for the genuinely missing pieces so the templates stay in one place
and do not drift between the two skills. Handle the moves, renames and merges here.

Leave project-specific facts you could not verify as explicit `TODO` markers rather than
guessing. An `AGENTS.md` that confidently states the wrong deploy target is worse than one
that admits it does not know.

Whatever the repo already runs deterministically — the hooks and CI found in Step 1 — goes into
the `AGENTS.md` Commands table and the code-review-scope paragraph **as it actually is**, not as
the reference describes it. That paragraph is a claim about this repo; copying the reference's
version of it into a repo with no SAST is how a review starts trusting checks that never ran.

## Hard rules

- **Never overwrite an existing `CLAUDE.md` or `AGENTS.md` without an explicit decision.**
- **Never commit workflow files into a repo the developer does not own** without asking — Step 0
  decides this, and "it's just documentation" is not the exception it sounds like.
- **Never enable a third-party AI reviewer, or set `codex_reviewer: yes`, on someone else's repo.**
  Silence means no. Sending code to another provider is not reversible by deleting a config file.
- **Never invent commands.** If you cannot verify how the suite runs, mark it TODO.
- **Do not reformat or restructure code.** This skill touches documentation and config only.
- **Record the overrides.** When the reference wins over a local convention, note why — in an
  ADR if the repo has them. Otherwise the next person re-litigates it.
