---
artifacts: docs/design
codex_reviewer: yes
gates: 1b,2b,6b
---

# ai-dev-workflow — workflow profile

## Calibration

Single-developer tooling, no end users or production data; reversible through git. Reviews
should be calibrated to that: this is not a system with uptime.

Genuinely high-stakes here, and the only areas worth a BLOCKER:
- anything that widens what an agent may execute without a human prompt (the Bash allowlist,
  Codex sandbox and approval settings, hook trust);
- anything that could send code or specs out of a repository whose owner has not agreed to
  it — client and employer repositories in particular;
- anything that could put private material (personal data, client or product detail, local
  paths) into this public repository, its commits or its GitHub text.

Out of scope for BLOCKERs: bash and Python, macOS-only, single machine. Tests: `scripts/test-all`,
run in CI on every PR (the test suites, an install into a temporary `$HOME`, a link check and the
generic privacy patterns); it is a net under the local checks, not a deployment pipeline.
