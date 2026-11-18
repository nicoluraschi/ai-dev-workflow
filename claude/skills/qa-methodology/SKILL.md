---
name: qa-methodology
description: QA methodology for black-box verification of a running web app against its spec (focused or full depth) and for designing test cases from a spec. Covers deriving cases from acceptance criteria, edge-case heuristics, exploratory charters, evidence rules and the report format. Use whenever doing QA, acceptance testing, exploratory testing or verifying a feature against acceptance criteria.
---

# QA methodology

Identify mode and depth before doing anything.

| Mode   | Depth   | When                                        |
|--------|---------|---------------------------------------------|
| verify | focused | Default. Most features that warrant QA.     |
| verify | full    | Large or sensitive features, or on request. |
| design | —       | Only on explicit request.                   |

## 1. Derive test conditions from the spec

For every acceptance criterion (AC), derive:
- one positive case (the happy path the AC describes),
- one negative case (invalid input, missing permission, wrong state),
- boundary cases where the AC involves a limit, range, count or date.

Behaviours the spec implies but does not define are Questions: the spec is the only
oracle. A behaviour that is merely surprising, but that no criterion forbids, is a
Question too.

## 2. Depth

**Focused** — a bounded pass, not a small sweep. **Budget: ~20 tool calls.**
- Every AC: one positive and one negative case. Boundaries only where the AC itself
  states a limit, range, count or date.
- Only the risk areas you were given. Do **not** open `references/edge-cases.md` — it
  belongs to full depth.
- No free exploration, no charters.
- Stop when every AC and risk area has a result, or when the budget is spent —
  whichever comes first. Whatever is left goes under Coverage as "not tested and why";
  an unfinished focused pass reported honestly is worth more than a full sweep nobody
  asked for.

**Full** — the budget, the `edge-cases.md` exclusion and the no-charters rule above
belong to focused alone. None of them carries over; this is the sweep.
- Every AC: positive and negative case, as in focused.
- Boundaries for every AC, not only where the AC states one.
- Go through every category in `references/edge-cases.md`; skip only what does not
  apply, and say why under Coverage.
- One or two exploratory charters (section 3).

## 3. Exploratory charters (full depth only)

A charter is: "Explore <area> with <approach> to discover <risk>." Keep each short.
Record what you tried, not only what failed — a charter that found nothing is a
coverage statement.

## 4. Evidence

Every result needs evidence observed in this session: an HTTP status and the relevant
body, a screenshot or a precise description of the rendered page, a log line, a DB row
read with a query. No evidence means `NOT VERIFIED`, never `PASS`.

The project's own test suite is not evidence. It was written by whoever wrote the
feature, from the same understanding of the spec that produced the feature — if that
understanding was wrong, the suite is green and wrong together. Use it to find the
surface; verify against the running system.

## 5. Report formats

### Verify

```
# QA report: <feature> (<focused|full>)

Verdict: PASS | FAIL | BLOCKED

## Acceptance criteria
| AC  | Status                     | Evidence |
|-----|----------------------------|----------|
| AC1 | PASS / FAIL / NOT VERIFIED | ...      |

## Bugs
### BUG-1 [S1|S2|S3|S4] <short title>
- Steps to reproduce: 1. ... 2. ...
- Expected (per spec): ...
- Actual: ...
- Evidence: ...
- Suggested regression test: <request/system/model spec> asserting ...

## Questions / spec gaps
- Q1: ...

## Coverage
- Tested: ...
- Not tested and why: ...
- Charters run (full only): ...
```

Severity: **S1** blocks the main flow, loses or corrupts data, or exposes another
user's data. **S2** breaks an AC but has a workaround. **S3** minor wrong behaviour.
**S4** cosmetic.

Verdict is FAIL if any AC fails or any S1/S2 bug exists; BLOCKED if the app could not
be run or the inputs were missing. A PASS that still has NOT VERIFIED criteria must
say so on the verdict line.

### Design

```
# QA test design: <feature>

## Test cases by acceptance criterion
### AC1: <text>
- TC1.1 [positive] <steps> -> <expected, citing the spec>
- TC1.2 [negative] ...
- TC1.3 [boundary] ...

## Additional edge cases
- ...

## Questions / spec gaps
- Q1: <what the spec does not define> — why it matters
```

## 6. Per-project context

Each project keeps its QA guide at `docs/qa.md`: how to start the app, test users,
seed data, where specs live, critical flows, and what is out of scope. Create one from
`references/docs-qa-template.md`. It holds no secrets — only the name of the env var
or the password-manager entry that does.
