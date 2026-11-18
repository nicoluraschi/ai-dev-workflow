# Should the Codex gates 1b/2b be triaged? — back-test

- **status:** decided — **no change shipped**
- **date:** 2026-09-25
- **risk tier:** B (it would have changed the trigger of every future gate)
- **relates to:** `2026-09-cross-review-loop.md` (the gates)

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. The question

Gates 1b and 2b run "for anything non-trivial", with no floor. A one-file change therefore
pays two ~6-minute Codex runs plus two response tables. The proposal was to add a triage step
modelled on `security-audit`'s STEP 0: four questions, any "maybe" is a yes, all-no gives a
short verdict and skips the gate.

Two candidate criteria were formulated and both were back-tested against the recorded runs
before any spec was written. **Both were falsified.** No change shipped.

## 2. Method

Every gate run leaves a ledger. 19 exist; 17 carry findings (the two `*-codex-spec` /
`*-codex-plan` files in a product repo predate the current contract and hold none).

Findings are `### <gate>-F<n> — title` headings under a `## BLOCKER` / `## MAJOR` / `## MINOR`
section. Counting them by section:

```sh
sev_of() { # $1=ledger $2=finding-id
  awk -v id="$2" '
    /^## BLOCKER/{s="BLOCKER";next} /^## MAJOR/{s="MAJOR";next} /^## MINOR/{s="MINOR";next}
    /^## Round 2/{s="";next}
    $0 ~ "^### " id " " {print s; exit}' "$1"
}
```

**The extractor is validated:** run over the 17 ledgers it yields exactly **21 BLOCKERs and
59 MAJORs**, reproducing the figures from the 2026-09-24/25 usage audit digit for digit. The
results below are measurements, not readings of the slugs.

## 3. Back-test 1 — trigger the gates on contract change

**Criterion under test.** Run 1b/2b when the change introduces or alters a contract something
depends on (data model, API, visible flow, tool interface). Skip when it only rearranges what
exists (behaviour-preserving refactor, config, docs, renames, style).

**Result: it skips 0 of the 17 runs — except one, and that one found 2 BLOCKERs.**

A content-revision spec in a product repo is by that definition pure rearrangement: a content
revision, 36 passages replaced and 50 added, no schema, no API, no new flow, no tool
interface. It goes to SKIP. Its two BLOCKERs:

- `1b-F01` — the 36 rejected ids are enumerated in no artifact, so criterion 3 is untestable.
- `1b-F02` — the persisted payload is rejected on size before its id is examined, so
  criterion 9 cannot pass without contradicting the stated scope.

Neither is a contract change. Both are consistency gaps in a content revision — precisely the
category the criterion sends to SKIP.

**Why the population is empty.** The exclusion list — behaviour-preserving refactor, config,
docs, renames, style — is almost verbatim the trivial lane's definition in the global
CLAUDE.md ("one-liners, fixes, config, small tweaks"). That lane already does not run 1b/2b:
it writes no spec and never enters `feature-workflow`. The criterion does not cut a new
population; it restates the trivial/non-trivial boundary in other words. What remains is work
judged non-trivial *and* purely rearranging — one case in 30 days, and an expensive one.

**Wrong axis, too.** The stated pain is about *small* changes; the criterion discriminates on
*contract*. A one-file change adding a CLI flag is small and is a contract change — it still
pays both gates. The criterion does not relieve the case that motivated it.

## 4. Back-test 2 — a response row only for BLOCKERs

**Criterion under test.** Keep the trigger; cut the ceremony instead. Require a response-table
row per BLOCKER only; batch-triage MAJORs the way MINORs already are.

**Result: 5 of the 6 regressions round 2 caught came from MAJOR fixes.**

| Ledger | Regression from | Severity |
|---|---|---|
| the content-revision spec, 1b | 1b-F04 | MAJOR |
| a product feature spec, 2b | 2b-F03 | MAJOR |
| another product spec, 1b | 1b-F01 | MAJOR |
| another product spec, 2b | 2b-F03 | MAJOR |
| a `codex-audit` wrapper spec, 1b | 1b-F01 | **BLOCKER** |
| the same wrapper spec, 2b | 2b-F03 | MAJOR |

Round 2 verifies its own findings against the response table. Removing the MAJOR rows removes
the input behind 83% of what it catches. This is not trimming ceremony; it is switching off
five of six regression detections.

## 5. Decision

**Leave gates 1b and 2b exactly as they are.** No triage step, no change to the response-table
protocol.

The framing that opened this work was "the cost is the ceremony, not the coverage". The
measurement says that here they are the same thing: **the response table is not ceremony around
the check, it is the check's second half.**

The magnitude does not support the effort either: 102 minutes of Codex across 30 days is
~3.4 min/day, against 21 BLOCKERs — 20 of which were caught before any code existed.

## 6. What would change this answer

Recorded so the question can be reopened on evidence rather than on feel:

- A run of 1b/2b that returns **empty** — none has yet, in 17.
- A sustained population of non-trivial work that is genuinely pure rearrangement. One case
  in 30 days is not that population.
- Round 2 ceasing to catch regressions from accepted MAJORs — at which point the MAJOR row
  is bookkeeping and back-test 2 should be re-run.

Re-run both with the extractor in §2 against the then-current ledgers before deciding.
