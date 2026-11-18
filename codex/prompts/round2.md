<!--
  Round 2 — verification. Shared by every gate. Appended to reviewer-contract.md by
  `codex-audit` when --round 2 is passed.
  Placeholders: {{GATE}}, {{ARTIFACT_PATH}}, {{RESPONSE_TABLE}}
-->

## Round 2 — verify the responses, do not re-review

This is the second and final round for gate {{GATE}}. You raised the findings below in round 1.
The artifact at `{{ARTIFACT_PATH}}` has been revised since; re-read it before answering.

Your scope this round is **only** the findings you already raised and the changes made in
response to them. This is a hard limit, not a preference — see "Out of scope" below.

### The responses to your round-1 findings

{{RESPONSE_TABLE}}

### What to answer

For every id in the table, exactly one verdict:

- **Marked `accepted`** → `resolved` or `not resolved`. Open the artifact and check that the
  change actually closes the failure path you described. If it does not, say specifically what
  is still open — a fix that addresses the symptom while leaving the failure path reachable is
  `not resolved`.
- **Marked `rejected`** → `concede` or `maintain`. You may only `maintain` with a **new**
  argument: evidence you did not cite in round 1, or a direct rebuttal of the specific reason
  given for the rejection. Restating your original finding in different words is not a new
  argument — if that is all you have, `concede`.
- **Marked `human`** → no verdict. These are product or business decisions and are not debated
  between models. Skip them.

Then one further section:

- **`regressions`** — problems *introduced* by the changes made in response to round 1. This is
  the one place you may raise something new, and only when it is traceable to a specific change
  made in response to a specific finding. Name that finding's id.

### Out of scope this round

Do not raise new findings unrelated to a round-1 finding, however valid. Do not revisit a
finding you did not raise in round 1. Do not re-read the artifact looking for fresh material.
If you believe something important was missed in round 1, that is a lesson for the next
feature, not a finding for this round — omit it.

### Output format

Override the round-1 format. Use exactly this:

```
## Verdicts

| id | round-1 severity | response | verdict | note |
|---|---|---|---|---|
| {{GATE}}-F01 | BLOCKER | accepted | resolved | <one line, or empty> |
| {{GATE}}-F02 | MAJOR | rejected | maintain | <the NEW argument — required> |
| {{GATE}}-F03 | MAJOR | rejected | concede | <one line> |

## Regressions

<omit the rows and write "None." if there are none>

### R01 — <one-line title> (from {{GATE}}-F0n)
- evidence: <file:line or section>
- failure path: <what concretely goes wrong>
- smallest fix: <the simplest change that removes it>
```

Every id from the table appears in the verdicts table exactly once, except ids marked `human`,
which are omitted entirely. A `maintain` row with an empty note, or a note that restates
round 1, will be read as a `concede`.
