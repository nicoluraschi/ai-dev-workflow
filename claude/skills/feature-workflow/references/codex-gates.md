# Codex gates — wrapper contract and round protocol

Read this when gate 1b, 2b or 6b fires. `SKILL.md` says when each gate runs; this file says how.

## The wrapper

**Always call the `codex-audit` wrapper — never raw `codex exec`.** The wrapper owns the reviewer
contract, the gate prompts, the project profile, the round protocol and the ledger. Calling Codex
directly skips all of it and produces a critique nothing records.

```
codex-audit <1b|2b|6b> [--slug <slug>] [--pr <id>] [--round 1|2] [--response <file>]
```

- Codex runs read-only under the `audit` profile, so it reads the working tree directly — **no git
  worktree needed**. Run it from inside the project repo (Codex requires a trusted git directory).
  **Claude runs the command, not the human:** it is non-interactive, so no second terminal.
- **Run round 1 of 1b and 2b in the background** (`run_in_background`) and work the same phase's
  Claude gates meanwhile. Codex reads the spec or plan live, so leave that file untouched until the
  wrapper exits — an edit mid-run is audited half-written. Round 2 runs after the fold, in the
  foreground: it is short and the checkpoint waits on it.
- **The wrapper writes the ledger; don't paste critique into the conversation.** Raw critique pasted
  verbatim is re-sent with every later turn of the session. The ledger lives at
  `$(git rev-parse --git-common-dir)/codex-audit/<slug>-<gate>.md`, or `<slug>-<gate>-pr<index>.md`
  when you passed `--pr` — never in the tracked tree, never committed. Tell the human the path the
  wrapper printed, and quote in the chat **only** the findings you act on or dispute. If the
  wrapper refuses because a ledger is still at an older location, run the command it prints.
- **Preserve Codex's independence.** The ledger holds its unedited words. Never paraphrase a finding
  into agreement with your own artifact, and never drop one because you disagree — answer it in the
  response table and say why. Your synthesis is an add-on, never a substitute.
- **Read the wrapper's exit code; they are not interchangeable:**
  - `0` — the gate ran and the ledger was written.
  - `3` — the gate was **skipped** and recorded (reviewer not authorized, disabled, or Codex not
    logged in). Say so out loud and continue; never report a skipped gate as a clean one.
  - `4` — round 1 found no BLOCKER/MAJOR, so round 2 was not needed. This is success.
  - `1` — a real failure. Stop and read the message. Two of these are deliberate refusals
    rather than faults, and neither is worked around: **"a gate is already running for this
    ledger"** means another gate holds it — wait for it, never start a second; **"this ledger
    already holds a round-1 review"** means the gate is done and its critique is on disk — read
    the ledger instead of re-running it. Re-running would discard a completed review,
    which is why the wrapper refuses rather than asking. **The one exception** is a ledger whose
    header says `outcome: UNPARSEABLE`: that gate produced nothing usable, so re-running *is* the
    right response — say so and ask the human to delete that ledger first.
- **Flow condition:** once a gate fires, do NOT advance past its checkpoint until the outcome is
  recorded in the spec's §4 Decisions. Tier B has no 1b checkpoint: there, 1b's outcome is
  recorded before Plan starts. The workflow stops you if you try to skip it.
- **Auth:** uses the stored ChatGPT login non-interactively. If a gate reports `skipped: Codex is
  not authenticated`, run `codex login` once in a terminal.
- **Permissions:** `codex-audit` is allowlisted in `settings.json`, so it runs without a prompt —
  it can only ever invoke the read-only `audit` profile. Raw `codex exec` is deliberately *not*
  allowlisted, because it can run anything. That asymmetry is the reason to use the wrapper.
- **First run in a repository:** if no profile authorizes sending this repo's artifacts to another
  provider, the gate records a skip rather than reviewing. Offer **once** to create
  `docs/ai-profile.md` — the wrapper's own message names the template path — interviewing for the
  calibration block, which is the part that makes severities mean anything. If the human declines,
  carry on without the gate and don't ask again this feature.

## The round protocol (1b, 2b)

1b and 2b run up to **two rounds**. Round 1 is the critique. Then, for every BLOCKER/MAJOR id,
write a response table to a file — one row each, in **exactly** these four columns, each row
starting at column 0:

```
| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | BLOCKER | accepted | criterion 3 now asserts at the reader (spec §6) |
| 1b-F02 | MAJOR | rejected | the empty case cannot occur: the list is filtered upstream |
| 1b-F03 | MAJOR | human | whether to charge for this is the PO's call |
```

The column order is not cosmetic — the wrapper parses it to build the metrics and to pull the
`human` rows into the ledger's "For the human" section. A different layout still runs, but it
silently produces zero counts and drops every `human` item from your checkpoint list.

`status` is exactly one of:

| status | meaning |
|---|---|
| `accepted` | the artifact changed; say where |
| `rejected` | verified against the code or the spec — not merely asserted |
| `human` | a product/PO/business call; not debated between models |

Every round-1 BLOCKER/MAJOR needs exactly one row: the wrapper rejects a table that omits an
id, invents one, or answers the same id twice. MINORs are batch-triaged (fix now / defer /
reject) with no per-item debate and no rows. Then:

```
codex-audit 1b --slug <slug> --round 2 --response <response-table-file> \
  --tier <B|A> --trigger "<quoted clause>"
```

Every `codex-audit` call takes the unit's `--tier` and the feature-workflow clause quoted to name
it (`--trigger`). They reach the gate scorecard only, never Codex. Without them the gate still
runs, warns, and its record has no tier.

Round 2 verifies its own findings and reports regressions; it may not open new topics. Whatever is
still `maintained`, `not resolved`, or `human` lands in the ledger's **For the human** section —
that, and not the raw critique, is what you bring to the checkpoint. The models do not argue
further.

## Gate 6b — one PR of a multi-PR spec

```
codex-audit 6b --slug <slug> --tier A --trigger "<quoted clause>"     # the spec ships in one PR
codex-audit 6b --slug <slug> --pr <index> --tasks <ranges> --tier A --trigger "<quoted clause>"
```

Both arguments come from **the same row of the plan's delivery table**. `<index>` is that
row's PR number — not a GitHub PR number, which does not exist yet at this point in the
workflow. `<ranges>` is that row's Tasks cell.

They do different jobs and you need both. `--pr` gives this PR its own ledger; without it
each 6b overwrites the last one's. `--tasks` tells the gate which acceptance criteria this
PR is answerable for; without it 6b judges the diff against the *whole* spec and reports
everything the other PRs have not built yet as missing.

**Transcribe the range to ASCII.** Delivery tables are written with en dashes and `--tasks`
takes hyphens, so the row `4–8, 10 and 11` is passed as `--tasks 4-8,10,11`. The wrapper
refuses an en dash rather than guessing, and says so.

6b runs a single round.
**Record the triage instead.** After step 6's triage, write the response table for every 6b
BLOCKER/MAJOR, in the round-protocol format above (Fix now → `accepted`, Reject → `rejected`,
Defer or left to the human → `human`), and run the same command with `--response`:

```
codex-audit 6b --slug <slug> [--pr <index>] --response <response-table-file> --tier A --trigger "<quoted clause>"
```

It calls no Codex: it appends the table to the 6b ledger and re-records it, so the scorecard
shows what 6b's findings were worth. Exit 4 means 6b found no BLOCKER/MAJOR: nothing to record.

## Codex as a second opinion (ad-hoc, not a gated step)
Outside this flow, Codex is also the "second senior engineer" for a stuck architecture decision:
pose the same question to both agents and compare the reasoning (`codex exec --profile audit "…"`).
This is ad-hoc — not a checkpoint, not gated by the risk tier, and the one place raw `codex exec`
is the right call, because there is no artifact and no ledger. It will prompt for permission; that
is intended.
