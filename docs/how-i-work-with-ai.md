# How I work with AI

The short version. This page tells the
story; every section links to where the [README](../README.md) lists the details. The reasoning
is in [`standard.md`](standard.md). When this page and the config disagree, the config wins and
this page gets fixed in the same PR.

## The idea in one line

**Claude writes, Codex reviews, I decide.** Agents draft; I own the plan, the trade-offs, the
review and what gets merged.

## The tools

- **Claude Code** (Anthropic, Opus model) is the main agent: it plans, writes code and tests, and
  runs the checks. Smaller, cheaper models (Sonnet, Haiku) handle searching and routine sub-tasks.
- **Codex CLI** (OpenAI) is a second opinion from a different provider. On high-risk work it
  critiques the spec, the plan and the final diff, read-only.
- **Zed** is where I read, navigate and review the code.
- **GitHub** holds every change as a small pull request.

All of it lives in one versioned repo. The files *are* the live setup: change one and the next
session behaves differently.

→ Models, agents, commands and CLIs: [At a glance](../README.md#-at-a-glance) · Codex's role:
[Codex as auditor](../README.md#-codex-as-auditor) · Editor setup:
[Zed](../README.md#-zed--where-i-read-code)

## How a piece of work flows

1. **Classify it out loud.** A one-line fix, a routine feature and a change touching login,
   money or personal data each get a different amount of process.
2. **Plan, then wait for my "go".** The plan states what's in, what's out, how we'll know it
   works, and every assumption as a question. No code before I approve it.
3. **Tests first.** A failing test, then the code that makes it pass.
4. **Review in proportion to risk.** Routine work gets an automated code review. Risky work also
   gets a security threat model, a written spec and Codex's critique.
5. **Prove it.** "Done" means I've seen the real test output, not a claim that it passed.
6. **One small PR per concern**, in its own isolated copy of the repo, so parallel sessions never
   collide.

→ The lanes and risk tiers: [A piece of work, end to end](../README.md#-a-piece-of-work-end-to-end)
· The full agreement: [`claude/CLAUDE.md`](../claude/CLAUDE.md)

## What's automatic and what's mine

Much of the know-how is packaged as **skills**: instructions the agent loads for a specific job,
like a security audit, a UI review or test-driven development.

The AI follows written instructions most of the time, not always. So the rules that matter are
**enforced by hooks**, small scripts that can block an action. For example, no edits on the main
branch, no commit while tests are red, and no ending a session while a security audit is owed.

What stays mine: approving plans, product and taste calls, anything touching security or privacy,
and the final merge. When in doubt, the agent stops and asks.

→ Every skill and when it runs: [Skills](../README.md#-skills) · Every hook:
[Hooks — the guarantees](../README.md#️-hooks--the-guarantees)

## Principles

- **Plan before code.** Most of my alignment with the AI happens at the plan, not the diff.
- **Small diffs.** A change I can't review properly is a change I shouldn't merge.
- **Security is never skipped** for looking small.
- **Two providers, not one.** The model that wrote the code doesn't get the last word on it.
- **Measure the setup itself.** I audit token cost and time from real sessions and drop the
  process that doesn't pay for itself.
- **Each project keeps its own facts** (`AGENTS.md`, `docs/`). This repo only says *how* I work.

→ The reasoning behind each: [`standard.md`](standard.md) · Measurements:
[`docs/design/`](design/) · Per-project settings:
[Per-project settings](../README.md#️-per-project-settings) · What's where:
[What's in the repo](../README.md#️-whats-in-the-repo)

## How the setup stays honest

- **A monthly audit** compares this page and the docs against the live config.
- **Gate cost is measured** from real session transcripts, not estimated.
- **Nothing moves on a claim:** code waits for an explicit "go", and "done" waits for real test
  output.
