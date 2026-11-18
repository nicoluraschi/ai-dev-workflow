# QA — the plan-time recommendation and gate 5q

Read *At plan time* in phase 2 and *Gate 5q* when phase 5 reaches it.

## At plan time (phase 2)

One line in the plan, always present:

`QA: skip | focused | full` — plus a one-line reason, and for focused/full the risk
areas written as *observable behaviours* ("a user must not see another user's saved items"),
never as implementation ("check the scope on the query"). The agent that runs QA never sees
the plan, so a risk area phrased as implementation is unusable to it.

**It is a recommendation, not a decision.** The human confirms or rejects it at 5q, and
`hooks/qa-agent-confirm.py` makes that binding. Write it as the case for spending the run,
not as a verdict that settles it.

Recommend `focused` **only** if the change touches one of these:
- authorization, ownership, tenancy, or another user's data;
- money, billing, or anything a user is charged for;
- data loss, corruption, or an irreversible action (delete, migrate, publish, send);
- a release you will hand to the PO as a deliverable.

A new or significantly changed user-facing flow is **not** on its own a reason — the tests
plus `ui-review` already cover it. Neither is variable user input (search, filters, forms,
imports) by itself: it earns QA only when it reaches one of the four above.

Recommend `full` only when several of the four hold at once, the feature is large, or the
human asked for it. **Otherwise recommend `skip`** — the default, justified by naming which of
the four the change does not touch.

**A criterion only counts if there is something to drive.** A change with no surface a person
can exercise yet — an API-only unit whose screens land later, a migration, a job with no
trigger — is `skip` however critical it is. Say when it *becomes* verifiable, so the unit that
adds the surface inherits the recommendation.

## Gate 5q

The `qa` agent is the costliest gate (measured: 11–44 min, ~280–430k tokens per run). Only the human
decides whether this change earns it.

- **Present the recommendation, then let the prompt be the question.** State, in three lines:
  the plan's recommendation, which of the four criticality criteria triggered it (or that none
  did), and the cost above. Then attempt the launch — `hooks/qa-agent-confirm.py` turns every
  launch into a permission prompt, and *that* is where the human answers. Do **not** also ask
  with `AskUserQuestion`: the same question twice in a row is how a gate stops being read and
  starts being dismissed.
- **The three lines are not optional.** The prompt carries the cost but cannot name which
  criterion fired, or why this change is the kind that earns a run. Without them the human is
  approving a number instead of making a decision.
- **A `skip` recommendation is also theirs to overturn.** One line naming what is being skipped
  and why, so rejecting the skip is as available as rejecting the run. Don't re-argue it beyond
  that line, and don't open a prompt for it — the line is enough.
- The hook covers every other route too — `/qa` typed directly, a passing request, a later
  session. There is no path that spends the run unasked, which is what makes the recommendation
  safe to state plainly rather than defensively.
- Once they say yes, run it from here, **inside phase 5, not before the PR.** Its findings produce
  a failing regression test and a fix — code churn that would invalidate a phase-6 review done
  first.
  ```
  /qa verify <spec-path> <focused|full>
  ```
- **The `/qa` command owns the independence, and it is the whole point.** The `qa` subagent gets
  the spec, the acceptance criteria, the risk areas, `docs/qa.md` and the environment — never the
  plan, the diff, the files touched, or a summary of what was built. Do not "help" it by adding
  context; a QA pass that has read the diff only re-derives the author's own reasoning.
- Triage its report yourself before bringing it to the human: each bug goes through
  `test-driven-development` (failing regression test first, then the fix); each Question is a
  spec question — it either changes the spec's §6 or is answered by it.
- Re-running after fixes is a delta: re-verify the criteria that failed, not the whole sweep.
  A re-run is a new launch and gets its own yes — it is not covered by the first one.
- Only phase 5's own criteria check is *not* replaced by this. That one is the author's
  self-check and stays; 5q is the independent pass on top of it, when the risk earns one.
