# Transcript schema, as verified

Everything here was confirmed against a real corpus (61 main sessions, 142 subagent
transcripts, 214 MB) produced by Claude Code **2.1.x**, on 2026-09-22. The format is
undocumented and moves between releases. Treat this as a dated observation, not a contract.

When `analyze.py` reports unknown record types, the fix is: work out what the type is, add
it to `KNOWN_TYPES` if it carries no usage, teach the parser if it does, and update this
file with the date.

## Layout

```
~/.claude/projects/
  <project-slug>/                     # cwd with / replaced by -
    <session-uuid>.jsonl              # main session
    <session-uuid>/subagents/
      <subagent-id>.jsonl             # one per subagent, same record schema
```

Each subagent transcript has a sibling `<subagent-id>.meta.json` (verified 2026-09-29):
`agentType`, `toolUseId` (the parent's `Agent` tool_use id), `description`, `spawnDepth`,
`requestShape` (`foreground` | `background`), ….
`analyze.py` reads only `agentType`, `toolUseId` and `requestShape`; `description` is never
surfaced.

**Where a subagent returns** (verified 2026-09-29). Foreground: in the `Agent` tool_result.
Background: the tool_result only acknowledges the launch ("Async agent launched"); the return
is a later `user` record with `origin: {kind: "peer", from: <agent id>, handback: true}`,
followed by `queue-operation` records carrying a `<task-notification>`.

**The subagent directory does not always sit next to its parent.** After `EnterWorktree`,
subagent transcripts are written under the *worktree's* project slug, while the parent
`<session-uuid>.jsonl` stays under the original repo's slug. `analyze.py` therefore joins by
session id across all project folders.

`SendMessage` (resuming an agent) is **assumed, unverified**: `input.to` holding the target
agent id. The corpus holds no such call as of 2026-09-29; `analyze.py` only counts it in
`drift.unmeasured_resumes`.

Subagent transcripts are **separate files**, not inline. Records in a main transcript also
carry `isSidechain`, but the authoritative subagent accounting comes from the files.

## The duplication rule — the one that breaks naive parsers

One API response is written as **N JSONL lines, one per content block**, and every line
repeats the **complete** `usage` object.

Measured on one real session transcript (`<project-slug>/<session-id>.jsonl`):

| | |
|---|---|
| assistant lines | 2431 |
| distinct `message.id` | 1283 |
| distinct `requestId` | 1283 |
| worst single message | 9 lines, each repeating `output_tokens: 6184` |

Summing per line overcounts by ~1.9× on that file and up to 9× on a parallel-tool turn.
**Accumulate usage once per unique `message.id`.** `requestId` is 1:1 with it and works
equally well.

Tool calls are the exception: they are per content block and must be counted per
`tool_use.id`, not collapsed with the message.

## Records that carry usage

### `assistant`

```jsonc
{
  "type": "assistant",
  "uuid": "...", "parentUuid": "...", "requestId": "...",
  "sessionId": "...", "timestamp": "2026-09-01T15:53:29.868Z",
  "cwd": "...", "gitBranch": "main", "version": "2.1.200", "slug": "...",
  "isSidechain": false,
  "attributionSkill": "test-driven-development",   // optional
  "attributionMcpServer": "...", "attributionMcpTool": "...",  // optional
  "message": {
    "id": "msg_011Ced…",                 // THE dedup key
    "model": "claude-opus-5",
    "content": [ { "type": "text" | "thinking" | "tool_use", … } ],
    "usage": {
      "input_tokens": 7850,
      "output_tokens": 293,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 27546,
      "cache_creation": { "ephemeral_5m_input_tokens": 0,
                          "ephemeral_1h_input_tokens": 27546 },
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
      "service_tier": "standard", "speed": "standard",
      "iterations": [ … ]                // per-iteration repeat; do not sum
    }
  }
}
```

`message.usage.iterations[]` repeats the same figures per iteration. Ignore it; the
top-level fields are the totals.

### `cost-state` — the authoritative measurements

Cumulative and rewritten as the session proceeds, so **the last one wins**. Present in
35 of 61 sessions observed (newer CLI versions only).

```jsonc
// illustrative values
{
  "type": "cost-state", "sessionId": "...",
  "totalCostUSD": 4.2,
  "totalAPIDuration": 600000,             // model time, ms
  "totalAPIDurationWithoutRetries": 580000,
  "totalToolDuration": 900000,            // tool time, ms
  "totalDuration": 7200000,               // ELAPSED SPAN, not attention
  "totalLinesAdded": 120, "totalLinesRemoved": 30,
  "startTime": 1700000000000,
  "modelUsage": {
    "claude-opus-5[1m]": { "inputTokens": 1000, "outputTokens": 40000,
                           "thinkingTokens": 15000, "cacheReadInputTokens": 5000000,
                           "cacheCreationInputTokens": 120000, "costUSD": 4.2 }
  },
  "hasUnknownModelCost": false
}
```

Two traps:

- `totalDuration` is the session's **elapsed span**. A session left open overnight inflates
  it. `totalDuration - API - tool` is idle-or-human, never "thinking time".
- `modelUsage` keys carry variant suffixes (`claude-opus-5[1m]`) that do **not** match
  `message.model` (`claude-opus-5`). Do not join the two on the raw model name; the one
  sanctioned join strips the trailing `[...]` first (`_norm_model` in `analyze.py`).
- `modelUsage` is recorded per session **with subagents included**; there is no
  per-subagent cost, so `analyze.py` splits it by price weight.

## Records that carry time, PRs and structure

| Type / subtype | Fields | Use |
|---|---|---|
| `system` / `turn_duration` | `durationMs`, `messageCount` | Per-turn agent time; newer CLI only |
| `system` / `compact_boundary` | — | Compaction happened |
| `user` with `isCompactSummary: true` | — | The summary that replaced the context |
| `pr-link` | `prNumber`, `prUrl`, `prRepository`, `sessionId` | Session → PR mapping |
| `user` with `toolUseResult` | shape varies | Tool output size |
| `summary` | `summary`, `leafUuid` | Session titles |

### `toolUseResult` shapes

Heterogeneous — size it by re-serialising, never by reaching for a named field:

| Tool | Shape |
|---|---|
| Bash | `{stdout, stderr, interrupted, isImage, noOutputExpected}` |
| Edit | `{filePath, oldString, newString, structuredPatch, originalFile, …}` |
| Read | `{type, file}` |
| Write | `{type, filePath, content, structuredPatch, originalFile, …}` |
| Agent | `{agentId, prompt, description, resolvedModel, status, outputFile, …}` |
| others | bare string, or a list of content blocks |

`toolUseResult` is the CLI's local record, not what the model is sent: that is the matching
`message.content[]` block of type `tool_result`, in its `content` field. For Edit and Write the gap
is large (2026-11-13 corpus: `toolUseResult` ~4 KB mean, `content` ~150–220 B, a plain string), so
`analyze.py` sizes their `content` instead (`SENT_SIZED`). Other tools keep `toolUseResult`.

## Record types carrying no usage

Counted and skipped. Observed on the real corpus:

`user` · `system` · `summary` · `attachment` · `pr-link` · `ai-title` · `permission-mode` ·
`mode` · `bridge-session` · `last-prompt` · `agent-name` · `file-history-snapshot` ·
`queue-operation` · `progress` · `atis-latch` · `cost-state` · `file-history-delta` ·
`worktree-state` · `relocated` · `fork-context-ref` · `frame-link` ·
`artifact-comment-monitor` · `artifact-autoreact-ledger` · `session-owner` (main transcripts
only: `sessionId`, `accountUuid`, `organizationUuid`; never read)

The request log, about 1.4 GB in total on the 2026-10-29 corpus, carries no usage either:
`api-request-shape` (system prompt plus tool schemas, one record per distinct shape),
`api-request-blob` (raw message content, content-addressed by `hash`), `api-request` (request
params plus the `tail` of blob hashes sent) and `tools-used` (a list of tool names). The
assistant usage records already cost every request, and the blobs hold raw prompt and tool text.
Only `api-request-shape` is read, and only for sizes (`.fixed_context_measured`).

### `api-request-shape` (verified 2026-10-30, CLI 2.1.x)

```jsonc
{
  "type": "api-request-shape", "sessionId": "...", "shapeHash": "<64 hex>",
  "timestamp": "...", "version": "2.1.200",
  "agentId": "...",                       // subagent shapes only
  "shape": {
    "system": [ { "type": "text", "text": "..." } ],
    "tools": [ { "name", "description", "input_schema",
                 "eager_input_streaming"?, "defer_loading"?: true } ]
  }
}
```

Written into the session transcript (subagent shapes into the subagent's file), at most ~10 per
file. A `defer_loading: true` tool is sent but not loaded until fetched. The system prompt does
**not** contain CLAUDE.md (0 of 1,310 main shapes): memory and the skill listing arrive as
message attachments. `analyze.py` keeps lengths and counts only, never `text`, names or schemas.

## Codex rollouts

```
~/.codex/sessions/YYYY/MM/DD/rollout-<iso-ish>-<uuid>.jsonl
```

Every line is `{timestamp, ordinal, type, payload}` with `type` in `session_meta`,
`turn_context`, `world_state`, `response_item`, `event_msg`.

- `session_meta.payload` → `session_id`, `cwd`, `cli_version`, `originator` (`codex_exec`).
- `event_msg` with `payload.type == "token_count"` → `payload.info.total_token_usage` is
  **cumulative**; the last one is the session total. It also carries `rate_limits`.

## 5-hour blocks

`ccusage blocks` is reimplemented in `analyze.py` rather than taken as a dependency
(ccusage is not installed, and it would add a Node runtime for one feature). The algorithm:

1. Sort all message timestamps.
2. The first message opens a block, its start **floored to the hour**.
3. A block stays open for 5 hours.
4. A message at or past the window end — or more than 5 hours after the previous message —
   opens a new block.

## The gate log

Not a transcript: `~/.claude/gate-log.jsonl` (or `$GATE_LOG`), one JSON object per line, appended
by `gate-log` (`scripts/gate_log.py`) and read by `analyze.py` into `.gates`. Spec:
`docs/design/2026-10-gate-scorecard.md` §5. It lives outside every repository and is never committed.

| field | values |
|---|---|
| `ts` | ISO-8601 UTC: when the gate ran (an import takes the ledger's `date:` header) |
| `repo` | basename of the main checkout, so worktrees collapse |
| `slug` | spec slug; for the trivial and light lanes, the branch name |
| `lane` | `workflow` \| `light` \| `trivial` |
| `tier` | `routine` \| `B` \| `A`; `null` only on `codex`/`import` records (a `codex` record has one when `codex-audit` got `--tier`) |
| `trigger` | the feature-workflow clause quoted to name a Tier A/B, one line, ≤300 chars. Required on new A/B records, absent on routine and tierless ones; records before it existed lack it |
| `gate` | `1s 1b 2s 2d-data 2d-perf 2b 5s 5-data 5-migration 5-perf 5-obs 5-ui 5q 6-review 6b trivial-check` |
| `pr` | delivery-table index; present only when given |
| `thread` | Codex thread id from the ledger; `codex`/`import` records only. Rounds 1 and 2 share it, a `--rerun` gets a new one |
| `found`, `accepted` | `{blocker, major, minor}` counts. On Codex records `accepted.minor` is always `null` (minors are batch-triaged), and `accepted.blocker`/`major` are `null` when the ledger has findings but no response table (`responded=0`: a 6b whose triage was not recorded, or a round 2 that never ran). A `claude` record never carries `null` |
| `rejected`, `deferred`, `human` | counts, totals across severities. `human` = escalated to the developer; its later outcome is not recorded |
| `skipped` | `true` when the gate was due and recorded a skip |
| `rounds`, `wall_s` | Codex records only |
| `source` | `claude` (a `gate-log add`), `codex` (written by `codex-audit` from its ledger), `import` (`gate-log import-codex`) |

Invariants: `accepted[s] ≤ found[s]`, and `accepted + rejected + deferred + human ≤ found` in
total. A record carries counts only, never finding text. Run key, for `codex` and `import`:
(`repo`, `slug`, `gate`, `pr`, `thread`) — only the last record per key counts, because each is
cumulative for its ledger (round 2 repeats round 1's findings plus regressions, each regression
counting as a `major`). A `--rerun` archive (`<ledger>.superseded-<stamp>.md`) is imported as its
own run. In a `.gates` row, `accepted[s]` sums the records whose acceptance is known (`null` when
none is), `untriaged[s]` sums `found[s]` of the records where it is `null`, and `accept_rate[s]`
is `accepted[s] / (found[s] − untriaged[s])`.
Ledgers are counted by `codex-audit scorecard <ledger>` and nothing else (`key=value` lines,
which `gate-log` maps onto the record): `### <gate>-F<nn>` headings under a `## BLOCKER*` or
`## MAJOR*` heading in round 1, top-level bullets other than "None" under `## MINOR*`, and
distinct round-2 regressions (added to `found.major`). `accepted`/`rejected` come from the
response table, each id bucketed by the round-1 section it was filed under (not the table's
severity label). `human` is the distinct ids still open — round-2 verdict `maintain` or
`not resolved`, or response `human` — plus the distinct regressions; open ids are excluded from
`accepted`/`rejected`. Regions switch only on the wrapper's own headings. A record with no
`thread` (a ledger from before threads were recorded) uses its `ts` in the key instead, so an
archive and its live ledger stay two runs. Skip records are kept apart from reviews and dropped
when a review of the same (`repo`, `slug`, `gate`, `pr`) is as late or later; a skip after a
review stays counted. Every `claude` record counts. A line that fails these rules is skipped
and counted in `.drift.gate_log_unparseable`.

`.gate_units[]` has one row per (`repo`, `slug`) with a record in the window: `lane` (the
latest in-window record's), `tier` and `trigger` (from the last record *written* that carries a
tier, in or before the window — file order, since a round-2 record keeps round 1's ledger date;
`null` when none did) and `records` (the unit's in-window records, skips included). `.tier_mix` is `{lane: {tier: units}}`,
with `unknown` for a `null` tier.
