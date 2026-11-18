# feature-workflow — rationale and measurements

`claude/skills/feature-workflow/SKILL.md` stays in context for a whole feature session, so it
keeps the rules and at most one short "why" per rule. The evidence behind them lives here. Nothing
in this file is needed to run the workflow; read it before changing a rule, so the rule is not
optimized away for lack of its reason.

Unless stated otherwise, figures are from the 30 days to 2026-09-25. Moved out of SKILL.md in
2026-09.

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## Asking the human — one round per gate

118 `AskUserQuestion` calls, **719 minutes** of blocked wall-clock, 6.1 min average. That is the single largest
non-model contributor to elapsed time in the corpus, and unlike model time it buys nothing when it
is spread out.

5q is the exception because asking twice is what makes a gate get dismissed; a genuine fork in
approach is the other, because bundling it with bookkeeping hides it.

## Spec size cap (≤1,500 words)

Markdown was **32% of every byte authored** (more than `.rb` and `.tsx` combined), `docs/specs/`
alone 510 KB across 247 write/edit operations, with individual specs reaching 53 KB, 44 KB and 42 KB. The cost is not writing it once — it is
that a spec is re-read 10–12 times in a session, so a 53 KB spec is ~130k tokens of context before
anything is built.

## Extracting acceptance criteria by heading, not number

Anchoring on `## 6.` and stopping at `## 7.` silently drops every security criterion the threat
model produced, which is the one set you least want unverified. Measured on
one product spec: its four threat-model criteria (22–25) were all dropped.

The section numbers stay load-bearing because they are referenced across the skill and across
every existing spec.

## Edge-case sweep at spec time

It is the same checklist the `qa` agent uses later. That is the point: what the spec defines now is
what QA has an oracle for then, and the cheapest moment to define behaviour is before anything is
built.

## Delivery table

The PR index is the identity gate 6b passes as `--pr`, and the only such identity that exists
*before* the PR is opened — 6b runs before `gh pr create`, so there is no GitHub PR number to read
yet. Without the table, two PRs of one spec resolve to the same 6b ledger and the second silently
replaces the first.

## Codex gate cost and 6b `--tasks`

1b and 2b audit text: cheap input, high leverage. 6b audits a diff: expensive input, lower
leverage, partly covered by tests and CI — hence Tier A only.

Without `--tasks`, 6b judged a PR's diff against the whole spec and reported everything later PRs
had not built yet as missing — measured twice on 2026-09-24, once as a BLOCKER.

6b launches while `/code-review ultra` runs because both read the same finished diff, neither gates
the other, and waiting is dead wall-clock. 1b and 2b still hold their checkpoint until their outcome
is in §4, but since 2026-10-17 their round 1 runs in the background alongside the same phase's
Claude gates (1s; 2s and 2d). The usage audit of Sept 19 – Oct 17 measured 220 Codex runs at a
median 4.9 min, about two per branch, waited on in the foreground. The constraint is that Codex
reads the artifact live, so those gates' edits are held and folded in one pass after it exits. The
cost: round 1 no longer sees the security criteria or the 2s/2d fixes — it critiques the problem
and the approach, which is its job. 1b stays on every unit: its findings are often valuable. Since
2026-10-17, 2b is off for routine light-spec units (`2026-10-proportional-review` D1).

Since 2026-10-19, Tier B has one approval, at the 2b checkpoint; Tier A keeps the spec checkpoint.
Merging spec and plan under one Codex gate was measured first (a product repo, Oct 12–19, 52 Tier B
units) and rejected. Spec plus plan run to a median 2,885 words, and the acceptance criteria alone
to 609. The reviewer contract caps a run at 8 BLOCKER+MAJOR findings, so one gate would have
dropped 72 of 395 (18%). Only ~10 of 140 accepted 2b findings were visible from the spec alone:
the gates find different classes of problem. And phases 1–2 are ~12% of a Tier B session's
tokens. What a spec approval carried was 1b's **For the human** items (28 of 52 units); those
are now asked before planning, without an approval.

## Delegating mechanical loops to Sonnet

The earlier wording was "use a cheaper model here". It never happened, because it named no
specific work; the rule now lists the work.

Delegation already works where it is explicit: 175 subagent runs were **2% of output and 4.6% of
input**, on a healthy Sonnet/Opus/Haiku mix. It does not happen where it is merely permitted:
10,766 Bash calls on the main thread, 122 per session, each one re-sent behind 300–500k of context.
Opus carried 88% of the cost proxy. Moving reasoning to Sonnet is a real quality loss; moving
`gh pr view` and a rubocop loop off the main thread costs nothing and keeps their output out of the
session's context, which is the larger win.

## Phase 4 delegation to `implementer`

Measured on 2026-09-28/29 over five implementer runs (two scratch, three real features in
a product repo, CLI 2.1.284).

- **Main context at delegation: 115k, 150k and 175k** in the three real sessions, growing to
  180–320k by the end. Every inline turn re-reads that on Opus. A spawn costs one first-turn write
  of 44.5–46.6k on Sonnet. The direction holds without prices, so the earlier "3+ tasks or 4+
  files" cut-off was far too conservative; only a one-task plan stays inline, where the brief and
  the re-check cost about as much as the work.
- **Spawn composition** (run E, by characters): tool schemas 48% (the Artifact tool alone 37%),
  the skill listing 20%, CLAUDE.md + AGENTS.md + memory 17%, the two preloaded skills 5%, deferred
  tool names 4%. Dropping `Artifact` and `mcp__*` removes the first and most of the last; a
  headless probe measured the MCP part at −2.7k (headless sessions never load Artifact).
- **False environment claims** ("no AGENTS.md", "not a git repo") came only from the two scratch
  runs, which ran a definition without the check-with-a-command rule: a shell alias changed what
  `ls` printed, and one run started outside any repo. The three real runs made none.
- **Reports matched the transcripts** in all three real runs, red evidence included. Only a
  scratch run on the old definition over-claimed TDD.
- **audit-guard** records the implementer's edits under the parent's session and releases only on
  an audit run after them; `SubagentStop` never blocks (tests S1–S4b).
- **Resumes: none yet.** All three parents fixed inline. Phase 4 and 6 now resume the same agent.

## Open items

- **Rollback metric.** Raw cache tokens are not comparable across models and the change moved two
  variables (context and model). The measurement now exists: `usage-audit` reports
  `subagents_by_type` (agent type × model, recorded cost apportioned by price weight) and
  `implementer_handoff` (main-session Opus turns from an implementer's return to the first
  audit; median 1.5 over 8 returns on 2026-09-29). Still open: a control feature with
  `model: opus` to separate the two variables.
- **Implementer effort level.** Wait for a baseline of three features.
- **1h cache for resumes.** `experimental: { cacheTtl: "1h" }` exists in agent frontmatter, but
  1h writes cost more on every write, and there have been no resumes. Revisit once resumes happen.
- **`omitClaudeMd`.** Would cut the 17% instruction share, but the project CLAUDE.md imports
  AGENTS.md, which names the test command; the brief would have to carry it. Experiment only.
- **Skill listing, 20% of a spawn.** No per-agent way to trim it was found.
- **TDD evidence by hook.** Deferred: reports matched transcripts. The agent edits only through
  Edit and Write, so every edit passes the hooks.
- **Fresh-context 5s.** Done 2026-11: `security-audit` carries `context: fork`, as `/code-review`
  already did, so every phase runs in a fresh subagent on the caller's model (measured ~40–55k
  context against 200–366k in the main session). A fork runs in the background: its `Skill`
  call returns "launched" and the result arrives later as a `<task-notification>` with the same
  tool-use-id, both in the main transcript `audit-guard.py` reads. The guard counts a forked run
  only once that notice says `completed` and the return carries a 🟢/🔴 verdict (fails closed:
  a `⚪ not run` or a crash has none). Only a user row that is wholly a notice counts, never
  notice-shaped text echoed in a reminder. In flight it does not block: the notice wakes the
  session and the next Stop re-checks. A
  skill run only inside a subagent's own transcript does not count. trivial-lane-check's suite and
  coverage checks stay inline: `no-commit-on-red.py` reads the suite verdict from the main
  transcript, and moving them would silently open the commit gate.

## Phase 5 before phase 6

`ui-review`, `security-audit` IMPL, `performance-review` IMPL and 5q all sit in phase 5 for one
reason: their findings change code, and a phase-6 review of a diff that is about to change is
wasted work.

`5-perf` and `5-obs` run only on a signal in the diff (2026-10-19). Gate ledger, a product repo,
Oct 17-19: `5-perf` 19 runs, 3 found, 1 accepted (a major, on a unit adding a table and its
queries); `5-obs` 10 runs, 3 found, 0 accepted; each ~2 turns and ~300k cache reads. Tier A had
one run of each, no findings. The signal check reads the diff rather than the tier, because a
hot query on an auth path still matters; audit-guard is unchanged, since it only reminds on
these two and never sees the tier.

## 5q — the qa agent's cost, and why it is asked at 5q

Four real runs in September 2026: 99-156 turns, 59-83 tool calls, 11-44 minutes and ~280-430k
billable tokens per run.

This deliberately reverses an older rule that the decision was settled at the plan and re-asking
at 5q was ceremony. That argument held while the cost was invisible. Against 44 minutes and 400k
tokens, ten seconds of confirmation is the cheapest thing in the phase.

## `/code-review` level

A bare `/code-review` reuses whatever level was typed last — in another session, possibly days ago —
so every gate that runs it names the level explicitly.
