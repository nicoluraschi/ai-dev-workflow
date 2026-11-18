---
name: usage-audit
description: Data-driven audit of what my AI development workflow actually costs in tokens and wall-clock time, measured from real session transcripts rather than from the config. Fires on "usage audit", "token audit", "efficiency audit", "what is costing me tokens", "where are my tokens going", "how long is a feature taking", "audit my sessions". Reads ~/.claude/projects transcripts and ~/.codex/sessions, reconstructs 5-hour limit windows, attributes consumption to skills, models, tools and PRs, and ranks findings by impact with the quality trade-off stated for each. Read-only. For a static review of the config itself, use config-audit instead.
---

# Usage audit


## Why this exists

`config-audit` reads the configuration and asks whether it is well built. This skill
ignores what the config claims and measures what actually happened: which sessions burned
what, where the wall-clock went, and what the 5-hour windows really looked like.

On a subscription, raw token totals are not the point. Three things are:

1. **Limit-window pressure** — Opus drains a 5-hour window faster than Sonnet. Hitting a
   cap mid-feature is the real cost.
2. **Wall-clock per feature** — the time from starting a PR to merging it.
3. **Context quality** — a bloated context degrades reasoning and buys extra iterations.
   Cheap tokens still cost correctness.

**Every finding must state its quality trade-off.** Reviews, TDD and Codex cross-checks are
expensive *on purpose*. "This step costs 90k tokens" is not a finding. "This step costs 90k
tokens and catches nothing the suite already catches" is. If a step's cost buys real
quality, say so and leave it alone.

## Ground rules

- **Read-only.** Analyse and report. Never edit config, never delete a transcript.
- **Evidence or silence.** Every finding names the session, the tool or the command, and
  the tokens or minutes. No impressions.
- **Don't re-derive what the script computed.** It already produces the numbers; spend the
  effort on interpretation.
- **Report to stdout.** No file is written unless the human asks for one.

## Step 1 — Measure

```bash
python3 ~/.claude/skills/usage-audit/scripts/analyze.py --days 30 > /tmp/usage.json
```

`--days 0` covers everything; `--project <substring>` narrows to one repo — it filters the
Codex runs by their `cwd` too. `--project-dir <path>` adds that checkout's CLAUDE.md to the
fixed-cost figure (otherwise only the global layer is counted). The script is
stdlib-only and takes about a second over a 200 MB corpus.

## Step 2 — Check `drift` before trusting a single number

The transcript format is undocumented and changes between CLI releases. The parser
validates rather than assumes, and reports what it could not account for:

```
.drift.unparseable_lines        malformed JSON lines
.drift.assistant_without_usage  assistant records carrying no usage
.drift.messages_without_id      assistant records with neither id nor requestId
.drift.subagents_without_meta   subagents with no usable .meta.json (agent_type "unknown")
.drift.unmeasured_resumes       SendMessage resumes of an implementer (counted, not measured)
.drift.unknown_types            record types the parser does not know
.drift.gate_log_unparseable     gate-log lines that are not a valid record (skipped)
```

**Non-zero `unknown_types` means the format moved.** Say so in the report, name the types,
and treat the affected numbers as a floor rather than a total. Do not quietly round it off
— a silently wrong efficiency report is worse than no report. Update `KNOWN_TYPES` and
`references/schema.md` once the new type is understood.

## Step 3 — Pick the lens from the 5-hour blocks

`.blocks[]` reconstructs the rolling windows that drive the subscription limits (a window
opens at the first message floored to the hour and runs five hours). Each block carries
`messages` (deduped API responses, comparable to `.totals.messages`) plus `output` and
`billed_input` — judge saturation on the **tokens**, not the message count. Look at the
heaviest blocks before deciding what the report is about:

- **Blocks are saturated** → the report leads with
  limit consumption, and model mix is the headline lever.
- **Blocks are comfortable** → limits are not the binding constraint. Lead with wall-clock
  and context quality instead, and say plainly that token reduction is not urgent.

Getting this backwards produces a report optimising something that was never a problem.

## Step 4 — Establish denominators

Totals are close to meaningless. The units that matter:

- **Per PR** — `.per_pr` is the rollup, keyed `repo#number`. **Read `allocation` first.**
  A session routinely opens several PRs, so a multi-PR session is split evenly across them
  and every PR it feeds is marked `"split"`. A split figure is an allocation, not a
  measurement — compare `"exact"` PRs against each other, and treat split ones as
  order-of-magnitude. `.unattributed` holds work that never reached a PR at all; if it is
  large, per-PR analysis covers less than it appears to.
- **Per branch** — `.sessions[].branches` when no PR was opened.
- **Per line changed** — `.totals.lines_added` / `lines_removed` from the measured
  `cost-state` records. A crude but revealing denominator.
- **Per session** — `.sessions[].context_per_message` is the average context carried per
  message. This is the context-bloat signal: it rises as a session accumulates.

## Step 5 — Work the ten areas

**1. Fixed per-session cost** (`.fixed_context`). What every session pays before any work
happens: global CLAUDE.md, skill descriptions, command and agent descriptions, project
CLAUDE.md. Commands and agents contribute only their frontmatter description; their bodies
load on invocation and are reported apart as `body_est_tokens`. Token
figures are estimated at 4 chars/token — present them as approximate, and use them for
relative weight, not as a budget. `total_est_tokens` is what **one** session pays. Each subagent re-pays the global share, so
the corpus-wide standing cost is `total_est_tokens × (.totals.sessions +
.totals.subagent_sessions)` — do not multiply the per-session figure by the corpus-wide
subagent count, which is neither quantity. A skill description that
never triggers is pure overhead on every session and every subagent.

`.fixed_context_measured` is the other half, measured from the request shapes actually sent
in the window: `main` and `subagent` each give `shapes`, plus `latest` and `median` of
`system_chars`, `eager_tool_chars`, `deferred_tool_chars`, `eager_tools`, `deferred_tools` and
`est_tokens` (system + eager tools, 4 chars/token). The median is over distinct shapes, not
weighted by how many requests each served, so lead with `latest`. Deferred tools stay out of context until
fetched, so they are sized apart. Present the two side by side, never as a gap: CLAUDE.md and
the skill listing arrive as message attachments, not in the system prompt, so the sets are
disjoint except the agent descriptions, which sit inside the Agent tool's schema. Sizes only:
never quote or name what the shapes contain.

**2. Session shape** (`.sessions[]`). `.totals.orphan_subagents` counts subagent transcripts
whose parent session file is gone anywhere under the root (a subagent directory attaches to its
parent even when it sits in another project folder, as after `EnterWorktree`); their tokens are in `.totals.subagent_tokens` but belong to
no session, so per-session subagent figures understate by that much. Tokens, `cache_hit_ratio`, messages, compactions,
subagent consumption. A low cache hit ratio means the context kept being invalidated —
usually a CLAUDE.md or MCP change mid-session, or a tool rewriting a file that is re-read.
`.compactions > 0` means a session outgrew its window: find what filled it.

**3. Tools** (`.sessions[].tools`). `result_bytes` per tool is where context actually goes.
For Edit and Write it is the `tool_result` content the model is sent, not the much larger local
`toolUseResult` record; every other tool is sized from `toolUseResult`.
`image_bytes` / `image_results` are kept separate on purpose: an image is tokenised by its
dimensions, not by the length of its base64 payload, so **never convert `image_bytes` to
tokens** or rank it against text. Report image-heavy tools by *call count*.
Look for: test runs dumping full output when a summary would do, the same file read many
times, greps returning hundreds of lines, and repeated failing commands. Rank by total
bytes, not call count — one 200 KB test dump beats fifty small reads.

**4. Model mix** (`.sessions[].models`, `.sessions[].model_usage`, `.subagents_by_type`,
`.implementer_handoff`). Compare output tokens and cost per model — but **never join the two
on the raw model name**. `models` is keyed from `message.model` (`claude-opus-5`) while
`model_usage` carries variant suffixes (`claude-opus-5[1m]`), so a naive join reports zero
cost for Opus and an orphan Haiku line. The one sanctioned join is `_norm_model` in
`analyze.py` (it drops a trailing `[...]`), already applied inside `subagents_by_type` and
`implementer_handoff`; anywhere else, report the two separately. The question is never "is
Opus expensive" but **"which work went to
Opus that Sonnet or Haiku would have done as well"** — exploration, running and summarising
tests, mechanical search, file inventory. Reasoning-heavy work belongs on Opus; say so and
leave it. `model_usage` also carries `thinkingTokens` per model.

- `.subagents_by_type[]` — one row per (`agent_type`, `model`): `spawns`, tokens,
  `weighted_tokens` and `cost_usd`. Compare agent types on `cost_usd` / `weighted_tokens`,
  **never raw cache tokens** (they are not comparable across models). `cost_usd` is the
  session's recorded cost split by price weight, an allocation not a measurement; `null`
  means no cost-state, and `unpriced_messages` counts what it could not price.
  `.totals.unallocated_cost_usd` is recorded cost with no message to split it by.
- `.implementer_handoff` — per implementer spawn return, the main-session (Opus) turns
  between it returning and the first phase-5 audit skill: the re-check overhead of delegating
  phase 4. `totals.median_opus_messages` is the headline; `totals.cost_usd` omits the
  `totals.unpriced_returns`, so say when it is non-zero. Resumes via `SendMessage` are only
  counted in `.drift.unmeasured_resumes`, not measured.

**5. Time** (`.sessions[].time`). Prefer the measured split, present when `source` is
`cost-state`:

- `api_ms` — model time
- `tool_ms` — tool time (tests, CI, browser)
- `idle_ms` — everything else. **Not the same as the human thinking.** It is derived from
  the session's elapsed span, so a session left open overnight lands almost entirely here.
  Never report it as "time you spent deciding".
- `active_ms` — bounded alternative, summing only gaps under five minutes. Use this when
  talking about attention.
- `span_ms` — elapsed span. **Never sum spans across sessions**; overlapping and abandoned
  sessions make the total meaningless.

`measured_sessions` in `.totals.time` says how many sessions carried a measured split.
Quote it whenever you quote the split — partial coverage is not a whole-corpus figure.

**6. Limit pressure** (`.blocks`). The heaviest windows, and what was running in them.

**7. Phase attribution** (`.sessions[].skills`). `attributionSkill` is recorded natively in
the transcripts, so workflow phases need no extra markers. It maps consumption onto the
real phases: `feature-workflow`, `test-driven-development`, `security-audit`, `code-review`,
`ui-review`, `verification-before-completion`. This is where the trade-off question gets
sharp — a gate that consumes heavily and has never changed an outcome is a candidate; a
gate that consumes heavily and catches real defects is working as designed. If the data
cannot tell which, say that rather than guessing.

**8. Codex** (`.codex`). Sessions, wall-clock added, and cumulative tokens for the audit
runs. The script measures what the cross-checks **cost**; it cannot measure what they were
**worth**. Judge value from the transcripts themselves — did the audit change the diff? —
and never present the cost alone as an argument for dropping them.

**9. Adherence** (`.sessions[].adherence_all`, and `.adherence` for the main context alone).
Whether the execution habits hold — batching independent calls, not re-reading what is already in
context, rewriting an own file whole instead of patching it many times. No hook enforces these in
flight, so this block is the only thing that finds out: **report it on every run**, as a table
against the baseline, even when the audit was asked for something else.

**Judge on `adherence_all`** — main session plus its subagents. The main-only figure flatters any
session that delegated. Redundancy is counted per context and summed, since each agent has its own.

| field | measures |
|---|---|
| `parallel_rate` | share of tool-carrying messages issuing several calls |
| `redundant_reads_approx` / `read_file_refs` | file reads of something already in context |
| `max_edits_one_file` | most Edits landed on one file, in any one context |

- `parallel_rate` counts **distinct `tool_use` ids grouped by `message.id`**, never lines
  carrying several blocks — parallel calls arrive as separate lines sharing one id, and the
  per-line reading reports 0%.
- Read `redundant_reads_approx` against `read_file_refs`, never `read_calls`: one command naming
  five files adds five. It counts the Read tool and shell reads: commands are tokenized with
  `shlex` (quotes, continuations, heredoc bodies dropped), and only a simple command that is
  `cat`/`head`/`tail`/`nl`/`sed -n` counts — not after a pipe, not writing (`> f`), not reading
  a heredoc — and only the files it names. Keyed by basename and seeded from Edit/Write targets, so a
  re-read after a legitimate change (merge, another session) also counts. `approx` means a habit
  signal, not a total to quote.
- `max_edits_one_file` keys on the **last two path segments**: worktree and main checkout
  collapse, `specs/x.md` and `plans/x.md` stay separate.

Compare against your recorded baseline, not the previous run.

**10. Gate scorecard** (`.gates[]`, read from `~/.claude/gate-log.jsonl` or `--gate-log`). One
row per gate and lane: `runs` (skips excluded), `skipped`, `runs_with_findings`, `found` and
`accepted` per severity, `untriaged` per severity (findings whose outcome was never recorded — a
6b whose triage was not recorded with `--response`, and Codex minors are never triaged one by one), `rejected`,
`deferred`, `human`, `accept_rate` per severity over the triaged findings only (`null` when none
were triaged) and, for Codex gates, `wall_s`. `human` means escalated to the developer; what was
decided afterwards is not recorded, so never fold it into accepted. Never read `untriaged` as
rejected: a gate whose findings are mostly untriaged has no measured value yet, high or low.

- **Set value beside cost, at the granularity cost exists.** Claude gates have cost only per skill
  (`.sessions[].skills`): `security-audit` spans 1s, 2s and 5s, so put the three rows together
  against that one figure and never split it. Codex gates have `wall_s` per gate; set it beside
  `.codex` tokens.
- **State the run count behind every claim.** "5s: 3 accepted of 4 found" on 4 runs is an
  anecdote, not a rate; say `runs` and call anything under about ten runs a floor.
- **Zero findings is not proof of zero value.** A clean gate may have deterred a bad change, may
  guard a surface that rarely breaks, and a Claude re-audit logs its own clean run. A gate with
  many runs, no findings and real cost is a question for the developer, not a deletion.
- Check `.drift.gate_log_unparseable` first, and note the log starts when `gate-log` was
  installed (Codex ledgers can be backfilled with `gate-log import-codex <repo>`; Claude gates
  cannot).
- **Audit the tier, not just the gates.** `.tier_mix` counts units per lane and tier (`unknown`:
  no record carried one, i.e. Codex gates logged before `codex-audit` took `--tier`).
  `.gate_units[]` gives each unit (`repo`, `slug`) its latest `tier` and the `trigger` — the
  feature-workflow clause quoted to name it. Read the Tier A/B triggers against that clause's
  text: a quote that does not describe the unit's change is a misclassification. Report the
  share of `unknown` beside any claim about the mix.

## Step 6 — Report

Findings ranked by estimated impact, highest first. Each one:

```
### <finding> — <estimated impact: tokens/window share or minutes per feature>
Evidence:    <session id, tool or command, measured numbers; when the rollback question
             is in play, `subagents_by_type` rows and `implementer_handoff.totals`>
Cause:       <what produces it>
Trade-off:   <what quality this cost currently buys, honestly>
Recommendation: <what to change, or explicitly "leave this alone">
```

Close with:

- **The lens** chosen in step 3 and why.
- **What is already efficient** — name it, so it does not get "optimised" later.
- **Confidence**, including any `drift` that limits it.

Then stop. Recommendations only — this skill changes nothing itself.

## Traps

- **Don't call `cache_read` waste.** It is cheap and mostly unavoidable. High cache_read
  *per message* signals a bloated context; high cache_read in total just means long sessions.
- **Don't sum `span_ms`.** See area 5.
- **Don't treat `totalCostUSD` as money.** On a subscription plan it is not billed. It is
  useful as a *relative* weight and a proxy for limit consumption — label it that way.
- **Don't recommend cutting a gate on cost alone.** State what it buys first.
- **Don't compare a spike session to a feature session.** Group by PR before comparing.
