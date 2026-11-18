---
name: trivial-lane-check
description: The verification gate for the two lanes that deliberately bypass feature-workflow — trivial work and light-lane (routine) work. Run it after implementing any change classified as trivial (a fix, a config tweak, a one-liner, a small tweak, a mechanical sweep) or light (a routine feature with no Tier A/B trigger), and before opening its PR or committing. Fires on "quick fix", "small change", "one-liner", "arreglo rápido", "cambio chico", on any trivial-tier classification, and before any commit or PR that did not go through feature-workflow. Runs the suite and shows real output, checks coverage on the changed lines, invokes ui-review for UI diffs, and scope-checks the diff against what was actually asked. It is a gate, not a process — no spec, no task breakdown.
---

# Trivial lane check

## Why this exists

The default loop has three lanes. Tier A/B work routes through `feature-workflow`, whose
phase 5 (Verify) runs the suite with real output, checks coverage on changed lines, invokes
`ui-review` on UI diffs, and audits the security surface before anything is reviewed.

The trivial lane has none of that. It was designed that way on purpose — ceremony on a
one-line fix is waste. But the trivial lane is where most merged work actually goes, and it
merges into production. The failure modes that surface latest — weak coverage, scope creep in
the diff, UI inconsistency — are exactly what phase 5 catches.

So: keep the lane fast, but never unguarded. Beyond the suite's own run time, this
check should cost about a minute. If it starts costing more, the change was probably not
trivial — see *Escalation*.

The light lane (CLAUDE.md *Default loop*) ends here too: routine features with new behaviour
but no Tier A/B trigger. It runs these four checks plus what *Light lane* below adds.

## What this is not

No spec. No task breakdown. No interview. No plan document. If you find yourself writing any
of those, you have the wrong skill — stop and use `feature-workflow`.

## The four checks

Run them in order. Report each with its evidence, not with a claim.

### 1. Evidence — the suite actually ran
Invoke `verification-before-completion`. Run the repo's real test command and show the real
output. "Tests pass" without the output is not a result; it is a hope. If the suite is red,
the check ends here — fix, then restart. When the repo's pre-push runs the suite through
`suite-queue`, use the lefthook form `verification-before-completion` names, so the push skips the
rerun.

### 2. Coverage on the changed lines

Not total project coverage — coverage of **what this diff changed**, against the ≥85% target.
A change that adds a branch and no test for that branch fails this check even if the project
average is 95%. CI enforces a project-wide floor, so a green CI run is not evidence about
*this* diff.

**Run the whole suite, not a subset.** Where the coverage tool enforces a minimum on every run
(SimpleCov's `minimum_coverage`, Jest's `coverageThreshold`), running a single spec file reports
the *project* percentage computed from only the files that spec touched — a few percent — and
exits non-zero. That failure is an artifact of the subset, not a fact about your
change, and acting on it wastes time. Use the same command CI uses.

**Read coverage from check 1's run; never start another full run for it.** A run in the lefthook
form already writes the artifacts: SimpleCov's `coverage/.resultset.json`, and with Jest's
`--coverage` the default `coverage/coverage-final.json`. A separate coverage run is a full suite
the push can't skip (`suite-form-guard.py` denies it where the suite is queued).

A full suite takes minutes, not seconds. Run it here, and once more after the last review round
if the review changed code — not after every fix (see *Light lane*). That is the price of the
only gate this lane has.

Then read per-file coverage out of the artifact the run already wrote; for SimpleCov:

```bash
# after a full `bundle exec rspec`
python3 - <<'COV'
import json, subprocess
changed = subprocess.run(["git","diff","--name-only","origin/main...HEAD"],
                         capture_output=True, text=True).stdout.split()
rs = json.load(open("coverage/.resultset.json"))
cov = next(iter(rs.values()))["coverage"]
for path, data in cov.items():
    rel = path.split("backend/")[-1]  # strip the app's own directory, if it has one
    if not any(c.endswith(rel) for c in changed):
        continue
    lines = data["lines"] if isinstance(data, dict) else data
    tracked = [x for x in lines if isinstance(x, int)]
    hit = [x for x in tracked if x > 0]
    miss = [n+1 for n, x in enumerate(lines) if x == 0]
    print(f"{rel}: {len(hit)}/{len(tracked)}" + (f"  uncovered: {miss}" if miss else ""))
COV
```

State plainly which changed lines are uncovered. If a line is genuinely untestable, say why.

### 3. UI diff → `ui-review`
If the diff touches `.tsx`, `.jsx`, `.css`, Tailwind classes, a page, a component or a layout,
invoke `ui-review` in review mode **now**, before the PR. Do this even when the request was
purely functional — UI regressions are caught here, by measurement, not by eye in review.

Run `frontend-iteration` first if the project has it, so the review has the design contract.
The screenshots and checks run inside the `ui-reviewer` agent, as `ui-review` step 1 says;
relay its findings verbatim. In the light lane, ask it for blockers and majors only (`ui-review`
step 5); the trivial lane gets the full report.

### 4. Scope pass
Read the diff as a reviewer would and answer one question: **does every changed line trace
directly to what was asked?**

Flag, and remove before the PR:
- drive-by refactors and reformatting of code that was not broken
- imports or variables your change orphaned (remove these)
- "while I was in here" improvements

Leave alone, and mention rather than delete: pre-existing dead code you did not create.

### Security
Per the global rules, a trivial change still gets the `security-audit` IMPL phase when it
touches auth, permissions, money, personal data, secrets, migrations, routes or external
integrations. That rule is not this skill's to relax; it is noted here because this lane is
the only thing carrying it.

### Data, migrations and observability
Same deal for `data-integrity` and `migration-safety` on any schema or migration change
(`data-integrity` also on a model's associations, validations, enums, callbacks or constraints), and
`observability` on a new endpoint or job. These are enforced by `hooks/audit-guard.py`, which is
session-level rather than workflow-level — skipping `feature-workflow` does not skip them.

## Escalation — when trivial was the wrong call

Classification happens before the work, with incomplete information. It is often wrong, and
the cost of being wrong is that everything above is the *only* review this change gets.

Stop and reclassify to `feature-workflow` if, during implementation, any of these turned out
to be true — in either lane (the Tier B clauses as `feature-workflow` defines them):

- it changes a data model or adds a migration, except a new nullable, unconstrained column
- it adds a dependency
- it changes a public contract: an interface consumed outside the repo, or a breaking change to
  an existing one
- it touches auth, permissions, money or personal data
- it introduces a new subsystem

Trivial work that hits none of those but needed a decision you had to guess at, new behaviour
to specify, or its own tests to explain what it does — or was taken as a mechanical sweep and
turned out to touch a route or a security path — was light, not trivial: say so, give it a
light plan (the approval brief plus its criteria, CLAUDE.md *Plans must state*), and finish it in
the light lane.

Reclassifying is cheap and expected. Discovering at review time that a "one-liner" reshaped a
model is not.

**Reclassifying carries the QA recommendation with it.** `feature-workflow`'s plan phase requires a
`QA: skip | focused | full` line; a change that escalates into that lane gets one like any
other. This lane itself has no QA step and deliberately does not ask for one — a trivial change
that is genuinely trivial answers `skip` every time, and asking the question anyway is the kind
of ceremony this lane exists to avoid. The one signal worth acting on without escalating: if the
change turned out to be user-facing and you cannot say which observable behaviour it should
produce, that is not a QA gap, it is a sign the change was never trivial.

## Code review

**Trivial:** `/code-review medium --max-findings 5` is **recommended, not required** — requiring it would
erode the speed that makes this lane worth having. Recommend it when the diff is larger than a
few lines, touches logic rather than data, or when check 4 found something.

## Light lane

After the four checks, the light lane always runs, in order:

1. `security-audit` **IMPL phase** on the diff (5s). It runs in a fresh fork that sees only its
   args: pass the phase, the repo path and diff command (`git diff main` for uncommitted work), the acceptance criteria, any decision
   agreed only in chat, and on a re-audit the previous findings (its *Inputs* table). Relay its
   return verbatim. Its triage decides NARROW or FULL; a 🔴 Critical blocks, as everywhere.
2. **Review, then triage it by hand** with `receiving-code-review` (fix now / defer / reject),
   fixing inline before any next round — at most two rounds:
   ```
   /code-review medium --max-findings 5          # routine
   /code-review high --max-findings default      # a redesign unit
   ```
   Always name both flags: they are sticky. **Two rounds, then stop:** round 2 re-reviews only
   the hunks a round-1 logic fix changed, and there is no round 3 — fix round 2's accepted
   findings without reviewing them again. A correctness bug you cannot fix with confidence goes
   to the human before the PR is opened; anything else left goes to its **Deferred** section. The cap is on
   `/code-review` only — a fixed hunk still gets its 5s re-audit, and a 🔴 Critical still blocks.
3. **Related tests between rounds, the full suite once at the end.** While fixing, run only the
   tests for the files a fix touched. Never start the full suite while a review is running or its
   fixes are pending: a run that predates the last fix is spent. After the last fix, if any fix
   changed code, run the full suite once in the lefthook form `verification-before-completion`
   names and re-check coverage (checks 1–2).

The conditional audits in *Data, migrations and observability* still fire on what the change is —
a new job or integration in this lane gets `observability`.

No spec, no Codex, no `implementer`, and no triage checkpoint unless the cap leaves a
correctness bug open: the human reviews the PR. Defers go in
its **Deferred** section.

## Record the run

Last, log this check and each gate it ran, one Bash call each and no question to the human, so the
scorecard sees this lane too. Use `--lane trivial` or `--lane light`, with
`--tier routine --slug <branch name>`:

```
gate-log add --gate trivial-check --lane <trivial|light> --tier routine --slug <branch> --found B,M,m --accepted B,M,m
```

- `trivial-check` is recorded once per run. `--found` counts what checks 1–4 raised (a red suite
  or uncovered logic is `major`; scope leftovers are `minor`), `--accepted` what was fixed before
  the PR. A clean run is recorded with zeros.
- Add one call per audit you actually ran: `5s` (security-audit), `5-data`, `5-migration`, `5-obs`,
  `5-ui` (`ui-review`), and in the light lane `6-review` once, both rounds summed (fix now → `--accepted`, reject →
  `--rejected`, defer → `--deferred`). Triples are `blocker,major,minor`: Critical / 🔴 = blocker, High / 🟠 =
  major, the rest minor — the mapping in `feature-workflow` *Gate scorecard*. For `5-ui` use its
  Severity column, and count `Minors omitted: <n>` in `--found` minor.

## Output

Report as a short checklist, each line carrying its evidence:

```
Trivial lane check — fix(backend): survive the other error URI.parse can raise
  1. Suite     ✅ 76 examples, 0 failures (output above)
  2. Coverage  ✅ 3/3 changed lines covered; new rescue branch has a spec
  3. UI        — no UI files in diff
  4. Scope     ✅ every changed line traces to the request
  Security     — no sensitive surface touched
  → ready for PR. /code-review not recommended (4-line diff, single rescue)
```

Then stop. Do not append a summary of what the change does; the PR description covers that,
following CLAUDE.md *PR descriptions* — this checklist condenses into its **Review** line.
Each line is evidence and stays; anything a check found is ≤40 words (CLAUDE.md *Output budget*).
