---
# Workflow profile (L2). Keep it small — this file holds calibration, not project facts.
# Project facts (stack, commands, conventions) belong in AGENTS.md; this file points at it
# rather than copying it, so the two can't drift.
#
# Every field below is optional. Delete the ones where the default is right.

# Where specs and plans live. (Review ledgers live in .git/codex-audit/, never here.)
#   relative path  -> inside the repo, resolved against the worktree root
#   ~/... or /...  -> outside the repo, for code where workflow files can't be committed
artifacts: docs/specs

# May this project's artifacts be sent to Codex (a different provider)?
# `no` makes every Codex gate record `skipped: reviewer disabled by profile` and continue.
codex_reviewer: yes

# Which Codex gates run here. `none` disables them all without answering `no` above.
gates: 1b,2b

# The file holding this project's verification commands — read, never duplicated here.
commands_ref: AGENTS.md

# Document languages. Technical docs are code-adjacent; product docs are the PO-facing ones.
docs_technical_language: en
docs_product_language: en
---

# <project> — workflow profile

## Calibration

<!--
  This block is injected verbatim into every Codex gate prompt as {{CALIBRATION}}, and it is
  the single thing that makes a review's severities mean anything. Written badly, every gate
  returns generic best-practice findings. Write it as if briefing a contractor on their first
  day, and be specific about scale and about what is deliberately good enough.

  Cover:
  - Team size, and who approves what.
  - Scale that a reviewer would otherwise guess wrong: users, rows, requests, growth.
  - Deployment risk: how a bad change is noticed, and how fast it can be rolled back.
  - The areas that are genuinely high-stakes here, named concretely.
  - What is explicitly "good enough" — the trade-offs already made deliberately, so a
    reviewer stops re-litigating them at every gate.
-->

## Post-steps

<!--
  Optional. Anything that must happen to a product doc after it is approved — an upload, a
  hand-off, a notification. Project-specific by definition; it lives here and never in a
  global skill. Delete this section if there are none.
-->
