---
description: Deep, interview-driven audit of my whole agentic-AI setup — my current way of working is a primary input; produces honest per-area analysis, recommendations, and a prioritized roadmap
argument-hint: [optional area to go deep on, e.g. skills | hooks | mcp | workflow]
allowed-tools: Read, Glob, Grep, Bash(ls:*), Bash(cat:*), Bash(find:*), Bash(stat:*), Bash(wc:*)
---

Run a deep audit of my entire setup for working with AI coding agents. Unlike a
quick inventory, the goal is depth: how I actually work today is a primary
input, and I want honest analysis, real recommendations, and a plan — not just
a keep/drop list of what's in use.

## Ground rules
- READ-ONLY (no write tools are permitted). Produce analysis and a plan; I make
  the changes later, myself. Don't modify my live config.
- Depth over coverage. Better to interrogate the handful of things that matter
  than to skim everything. If something is mediocre, say so — and say exactly
  how you'd sharpen it.
- Be critical and specific. No rubber-stamping. Back every verdict with a
  reason tied to how I work.
- One topic at a time in the interview — this is a conversation, not a form.
  Ask before assuming my intent.

## Phase 1 — Map the setup
Silently inventory every AI-config surface across both agents:
- **Claude Code** (global ~/.claude and this project): CLAUDE.md, skills, agents,
  commands, hooks + their scripts, MCP servers (~/.claude.json / .mcp.json), settings.
- **Codex CLI**: ~/.codex/config.toml, the `audit` profile file
  ~/.codex/audit.config.toml (a separate file layered on the base config, not a
  [profiles.audit] section), and the three Codex cross-check gates
  embedded in the feature-workflow skill.
Use this as raw material — don't dump the full list back at me yet.

## Phase 2 — Interview me about how I actually work
Before judging anything, understand my real workflow. Ask me, in focused rounds:
- How I plan, test, and review; how much autonomy I hand to agents; what I
  delegate vs do myself.
- Which skills / agents / commands I actually reach for — and which I never
  touch. Walk through what you found and ask me, concretely, "do you use this?"
- Where I lose time, fight the tools, or have quietly worked around friction.
- What I wish worked, and where the tooling adds friction or leaves gaps.
Fold my answers into everything that follows.

## Phase 3 — Deep analysis, per area
For each meaningful piece, go past keep/drop. Sort it into: used and pulling
its weight / used but weak (could be sharper) / unused dead weight / actively
getting in my way. For each, assess:
- Is it earning its context cost and its place?
- Is it well-crafted for its job? (e.g. skill descriptions that actually
  trigger, a CLAUDE.md that's lean and imperative rather than bloated, hooks
  doing something still worth doing, MCP servers I genuinely use.)
- Does it duplicate or conflict with something else? Is there a better pattern
  for it now?

## Phase 4 — Alignment & gaps (the important part)
Cross-check my stated workflow against the config:
- Where does my config assume a way of working I don't actually use?
- Where does how I work need support the config doesn't give me?
- What friction have I normalized that a config change could remove?
- What am I NOT using that would clearly fit how I work?

## Phase 4b — Codex & cross-agent drift (Claude ↔ Codex)
The two agents share one workflow, so also audit the Codex side and — most
important — whether the two halves still agree.
- **Codex config coherence** (~/.codex/config.toml + ~/.codex/audit.config.toml):
  the `audit` profile exists and is coherent for its job — a real model id (not a
  stale/renamed one), reasoning effort set, and a read-only sandbox (it must not be
  able to write). Flag unknown/misspelled keys and any setting that contradicts an
  "independent read-only auditor".
- **Gate coherence** (feature-workflow's three cross-check gates): all three exist,
  share the same large/risky/architectural trigger, and every one runs through the
  `codex-audit` wrapper (a raw `codex exec` in a gate is itself a finding) with the
  right spec path (docs/specs/YYYY-MM-<slug>.md).
- **Cross-agent drift (highest value):** does what the skill *says* it runs match
  the Codex config that actually exists? `codex-audit` runs Codex with the `audit`
  profile → that profile must be defined. The gate's spec path → must match where specs really
  live. The gate assumes read-only → the profile must actually be read-only. Any
  mismatch between the two sides is a finding — it silently breaks the gates at the
  worst moment.

## Phase 5 — Recommendations
Opinionated and tailored: what to cut, what to sharpen (name the specific
weakness), what to add, what to restructure. For each: the why, the expected
payoff, rough effort, and whether it's a clear improvement or a matter of taste.

## Phase 6 — Roadmap, then stop
Give me a prioritized plan: quick wins first, bigger refactors after. Then STOP
and wait — we'll work through the changes together, one at a time.

If I passed a focus area ("$ARGUMENTS"), go deep there and treat the rest as
context.
