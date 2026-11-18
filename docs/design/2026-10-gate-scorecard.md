# Gate scorecard: every gate logs what it found, usage-audit reports it

- **status:** done (2026-10-17)
- **date:** 2026-10-17
- **risk tier:** Routine — local tooling, no auth, money, personal data or dependency. Borderline
  Tier B (a new log format read by another tool); restated at the plan if the diff passes ~400
  lines.
- **closes:** config audit 2026-10-17

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. Outcome

Gate cost was measured; gate yield was not. `usage-audit` already measures what gates *cost*; nothing records what each gate *found* and what was accepted
at triage.

Today:
- Codex gates (1b/2b/6b) write a structured `## Metrics` table and a response table into each
  ledger under `<git-common-dir>/codex-audit/`.
- 1s/2s/2d leave one §4 verdict line in the spec, in prose too varied to parse.
- Phase 5/6 gates and the whole trivial lane leave no durable record.

After this change, every gate run in either lane appends one record to a single local log, and
`usage-audit` turns it into a per-gate scorecard: runs, findings by severity, how many of each
severity were accepted at triage, and — as totals across severities — how many were rejected,
deferred or escalated to the developer. What the developer later decides on an escalated finding
is not recorded (D3).

## 2. Scope

### In
- **`gate-log`**, a stdlib Python CLI linked onto PATH by `install.sh` (like `codex-audit`):
  - `gate-log add …` appends one record (§5).
  - `gate-log import-codex <repo-path>` backfills from that repo's existing Codex ledgers.
- **`codex-audit` records each round itself** through `gate-log add`.
- **`feature-workflow`** and **`trivial-lane-check`**: one instruction per gate to call
  `gate-log add` where its verdict is recorded (§4 line, approval brief, triage).
- **`usage-audit`**: `analyze.py` reads the log into a new `.gates` report key; `SKILL.md` gains
  area 10 *Gate scorecard*; `references/schema.md` documents the record.
- `gate-log` allowlisted in `settings.json`; README inventory updated.

### Out
- A "would another gate or test have caught it" tag per finding.
- Backfilling Claude gates from spec §4 prose.
- Per-gate cost for Claude gates: cost exists only per skill (`security-audit` spans 1s/2s/5s), so
  the report sets scorecard and cost side by side at that granularity, never claiming more.
- Re-recording a `human` finding after the developer decides it (D3).
- Any scheduler. "Monthly" is the cadence the developer runs `usage-audit` at.
- Recording gates that did not fire. A gate that ran clean is recorded.
- Changing any gate's behaviour, severity scale or verdict wording.

## 3. Constraints
- Stdlib only. Tests use synthetic fixtures and a temp log path, never the real log.
- The log lives outside every repository (`~/.claude/gate-log.jsonl`, overridable only by the
  `GATE_LOG` environment variable) and is never committed.
- Up to four sessions append concurrently (CLAUDE.md cap).
- Recording a gate costs one Bash call and no question to the human.

## 4. Decisions
- **D1 — One JSONL log, not parsed prose** — the trivial lane has no spec, and §4 wording varies.
- **D2 — Both lanes** — the trivial lane is where ceremony is least visible.
- **D3 — Counts only, `human` is final** — value = accepted findings per severity. `human` means
  "escalated to the developer" and is reported as its own bucket, never folded into accepted.
- **D4 — Codex backfill only** — ledgers carry structured metrics; Claude gates start from now.
- **D5 — The wrapper records Codex gates itself** — it holds the counts; Claude could forget.
- **D9 — `codex-audit` is the only ledger counter** — `codex-audit scorecard <ledger>` prints a
  ledger's counts as `key=value` lines; `gate-log` reads them for live and backfill records alike,
  because a second parser drifted from the wrapper in two review rounds (developer's call at triage).
- **D6 — Codex records supersede by run key; Claude records never do** — each Codex record is
  cumulative for its ledger, so the last one is complete; a Claude delta re-audit is its own run,
  so its clean result never erases what the first audit found.
- **D7 — Three severity buckets** — `blocker` (Critical, BLOCKER, 🔴), `major` (High, MAJOR, 🟠,
  a `/code-review` correctness finding), `minor` (everything else). The mapping lives in the
  feature-workflow instruction; each gate keeps its own scale.
- **D8 — `ts` is when the gate ran** — an import takes it from the ledger's `date:` header.
- 1s: 🟡 FULL — 1 Medium, 3 Low, folded into §8; 0 Critical.
- 1b: 7 MAJOR — 7 accepted, 0 rejected, 0 human; round-2 residue (F05, R01) closed by narrowing §1
  (round 2 read by hand: the wrapper could not parse its format).
- 2s: 🟢 clear — 1s threats closed by the plan. 2d performance: 🟢 no findings.
- 2b: 7 MAJOR — 7 accepted, 0 rejected, 0 human; round 2 all resolved, no regressions (read by
  hand). Amended §5 `tier` null and AC10's exit-3 split.
- 5s: 🟢 FULL, plus four delta re-audits 🟢. 5-perf: 🟢.
- 6-review (`/code-review high`): 27 fixed, 7 deferred (minor, tracked), 3 rejected. Round 2 led
  to D9.

## 5. Record

One JSON object per line:

| field | values |
|---|---|
| `ts` | ISO-8601 UTC: now, or the ledger date on import |
| `repo` | basename of the main checkout's top level (worktrees collapse) |
| `slug` | spec slug; for the trivial lane, the branch name |
| `lane` | `workflow` \| `trivial` |
| `tier` | `routine` \| `B` \| `A`; `null` only on `codex`/`import` records (a ledger has no tier; `codex-audit --tier` supplies one) |
| `trigger` | the feature-workflow clause quoted to name a Tier A/B (one line, ≤300 chars); added after this spec, so older records lack it |
| `gate` | `1s 1b 2s 2d-data 2d-perf 2b 5s 5-data 5-migration 5-perf 5-obs 5-ui 5q 6-review 6b trivial-check` |
| `pr` | delivery-table index, optional |
| `found` | `{blocker, major, minor}` counts |
| `accepted` | `{blocker, major, minor}` counts; on Codex records `minor` is `null`, and so are `blocker`/`major` when the ledger has findings but no response table (fixed after release: zero read as "none accepted") |
| `rejected`, `deferred`, `human` | counts |
| `skipped` | `true` when the gate was due but recorded a skip |
| `rounds`, `wall_s`, `thread` | Codex only; `thread` is the ledger's Codex thread id |
| `source` | `claude` \| `codex` \| `import` |

Run key, for `codex` and `import` only: (`repo`, `slug`, `gate`, `pr`, `thread`) — rounds 1 and 2
share a thread; a `--rerun` starts a new one, so it never erases the first review. `accepted[s] ≤ found[s]`;
`accepted + rejected + deferred + human ≤ found` in total. `runs` in the report excludes skips.

## 6. Acceptance criteria

`gate-log add`
- **AC1** A valid call appends exactly one line, valid JSON, with `ts`, `repo` and `source: claude`
  filled by the tool, and exits 0.
- **AC2** An unknown `gate`, `lane` or `tier`, a negative count, or a violation of either §5 sum
  rule exits non-zero, names the bad field, and writes nothing.
- **AC3** Run from a linked worktree, `repo` is the main checkout's basename.
- **AC4** The log's directory is created if missing; an existing log is only appended to.
- **AC5** Concurrent appends from several processes yield intact lines.
- **AC6** `install.sh` links an executable `gate-log` onto `~/.local/bin`.

`gate-log import-codex`
- **AC7** Each ledger with a round-1 review yields one `source: import` record: gate, slug, `pr`
  (from a `-pr<n>` suffix), `ts`, `rounds`, `wall_s`, `thread` and every count taken from
  `codex-audit scorecard` (D9): `found` = round-1 BLOCKER/MAJOR as the wrapper counts them, MINOR
  bullets other than "None", and distinct round-2 regressions; `accepted`/`rejected` from the
  response table, bucketed by each id's round-1 section and excluding ids still open
  (`accepted.minor: null`); `human` = distinct open ids. Superseded archives are imported too.
- **AC8** A skip ledger yields `skipped: true`; an `UNPARSEABLE` ledger, or one with no round 1, is
  reported on stderr and not recorded.
- **AC9** Importing twice yields the same `.gates` report as importing once.

`codex-audit`
- **AC10** After exit 0 or 4 the wrapper records the ledger cumulatively, as AC7 would read it;
  after an exit 3 that wrote a skip ledger, `skipped: true`; after an exit 3 that left an existing
  review untouched, or exit 1, nothing (a skip must never supersede a review, D6).
- **AC11** A failed record never changes the wrapper's exit code or ledger; it prints a warning.

`usage-audit`
- **AC12** `analyze.py` reports `.gates[]`, one row per gate and lane: `runs`, `skipped`,
  `runs_with_findings`, `found`, `accepted` per severity, `rejected`, `deferred`, `human`, and
  `accept_rate` per severity (`null` when nothing of that severity was found or its acceptance is
  unknown), plus Codex `wall_s`.
- **AC13** Among `codex`/`import` records only the last per run key counts; every `claude` record
  counts. `--days` filters on `ts`, `--project` on `repo`.
- **AC14** A missing log yields `.gates: []`; malformed lines are counted in
  `.drift.gate_log_unparseable`, never fatal.
- **AC15** `SKILL.md` area 10 sets the scorecard beside cost at the granularity cost exists (skill
  for Claude gates, `wall_s` for Codex), states the run count behind every claim, and warns that
  zero findings is not proof of zero value.

Workflow wiring
- **AC16** `feature-workflow` names the `gate-log add` call at each Claude gate it runs, states the
  D7 mapping once, and notes Codex gates self-record.
- **AC17** `trivial-lane-check` records itself as `trivial-check`, and each gate it runs, with
  `lane: trivial`.

## 7. Edge cases swept
- A Claude gate run twice on one unit (delta re-audit): two runs, both counted (D6).
- A spec shipped in several PRs: `pr` keeps per-PR 6b records apart.
- Round 2 of a Codex gate: its record repeats round 1's findings plus regressions (D6, AC10).
- Two repos sharing a basename merge in the report — accepted: one developer, distinct names.
- A repo renamed or a worktree removed: `repo` is captured at write time.
- Log growth: ~20 lines per feature; no rotation at this scale.

## 8. Acceptance criteria (security)
- **AC18** (SR1) `gate-log` accepts no option naming a file it writes; an unknown option exits
  non-zero and writes nothing.
- **AC19** (SR2) Records are serialized with a JSON encoder; a `slug` or `repo` containing a
  control character is rejected and nothing is written.
- **AC20** (SR3) `codex-audit` records only by invoking `gate-log add`, never by assembling JSON.
- **AC21** (SR4) A record carries only the §5 fields — never finding text; `import-codex` reads
  only the header, the severity sections' item counts, the response table's id/severity/status
  columns, and the Regressions table.
- **AC22** `settings.json` allowlists exactly `Bash(gate-log:*)` and nothing broader.
