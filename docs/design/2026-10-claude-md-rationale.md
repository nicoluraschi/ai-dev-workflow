# CLAUDE.md rationale (2026-10)

`claude/CLAUDE.md` loads into every session in every repo, so it carries rules only. The why,
the evidence and the hook internals behind those rules live here. Trimmed on 2026-10-19:
4,594 → 2,336 tokens (chars/4), no rule changed; any further cut would drop a rule or a condition.

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

**Keep-in-CLAUDE.md test.** A rule that must always fire stays in CLAUDE.md even when a skill also
holds it: the two-round review cap lived only in `verification-before-completion` and loaded in 1 of
22 sessions. Skill loads, Oct 12-19, 250 sessions: security-audit 168, frontend-iteration 133,
code-review 133, ui-review 124, trivial-lane-check 119, feature-workflow 94, systematic-debugging
18, verification-before-completion 10.

## Moved here (rationale and evidence)

| Section | Rationale |
|---|---|
| Defaults | English everywhere: one language across code, docs, commits and chat. |
| Default loop | Redesign units get `/code-review high`: classifying them from the diff misfired three times, each costing a second review round. A review problem, not a spec problem, so they stay light-lane. A big light-lane diff is a reason to split the PR, not to escalate. |
| Security | IMPL runs inside Verify so its findings can still change the code before review. The trivial lane skips `feature-workflow`, so CLAUDE.md is the only thing carrying its IMPL check. Re-audit re-fires are correct: one caught a flaw introduced *by* a review fix. |
| Automatic gates | `audit-guard.py` **blocks** on an unambiguous path signal (security, data-integrity, migration-safety) and only **reminds** on content heuristics (observability, performance-review). An undismissable false positive is how a gate dies. |
| Skills that need you to ask | They need intent only I have, or a condition no hook reads. The `qa` agent is the costliest step: ~280-430k tokens, 11-44 min per run. |
| Worktrees | The main checkout stays on `main` for my own use. The isolation guard refused ~1,076 commands in 28 days; `cd x && y` also silently skips `y` when already in `x`. Long sessions cost more per message, and compaction drops the reasoning chain mid-feature. Cap of 4: at 5+ on 2026-10-17 the load average reached 55-75, the pre-push Jest suite timed out twice, and parallel sessions draw on the same usage budget. |
| Plans must state | Approval happens on a short brief that names the assumed decisions; spec and plan are the agents' working record. The old decision card said how a plan was checked, not what I was agreeing to; the approval brief puts the assumed decisions in front of me. Only the blocking or hard-to-undo ones: listing every mechanic made plans too long to read (2026-10-29 audit: ~800-word plans, four mechanics "assumed" in a prefix rename), so a light plan is the brief plus its acceptance criteria. |
| Surgical changes | Whole-file rewrites: one unit took 17 Edits on one file. |
| Goal-driven | `ui-review` is not optional, even when only functionality was requested. |
| Review discipline | Docs outside the repo drift within a day. Frontend PRs get a **What to check** section so their review is strict. |
| Model choice | Opus uses the most tokens per task: on 2026-10-17 every main session ran on Opus, one-line fixes included, and 88 general-purpose subagents ran on Opus in two days. |
| Communication | Mechanics questions don't block: I took the recommendation on 13 of 14. |
| Output budget | Generated text is read by me and re-read as context. Rationale in `2026-09-output-budget.md`. |

## Dropped as duplicates (where the text lives)

| Dropped text | Lives in |
|---|---|
| What `trivial-lane-check` runs (suite, coverage, `ui-review`, scope), and that it flags work that was never trivial | its SKILL.md and description (119 loads) |
| `feature-workflow` owns phases, interviews, when Codex audits | its SKILL.md and description (94 loads) |
| The detail of each gate's checklist (FKs, CHECKs, locking, backfill…) | each gate's description, always loaded |
| `qa-agent-confirm.py` makes every launch a prompt; 5q's four criticality criteria | the hook; `feature-workflow` 5q, `references/qa-gate.md` |
| `ruby-session-reminder.py` surfaces `ruby-version-manager` | the hook; README |
| `session-hygiene.py` thresholds (500 msgs / 8h; 4+ others in 30 min) and approximate count | the hook's constants and docstring |
| Main-branch edit guard scope and its `docs/` exemption | `block-edits-on-main.py`; the auto-mode environment note in `settings.json` |
| `no-commit-on-red.py` believes command output, never a claim | the hook. The rules it backs (re-run, don't claim green; a green related run doesn't clear a red full run) stay |
| Output-budget table rows restated in *PR descriptions* | *Output budget* |
