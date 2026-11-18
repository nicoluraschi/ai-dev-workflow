# Review depth scales with risk

- **status:** done (2026-10-17). AC12 is checked at the next usage audit
- **date:** 2026-10-17
- **risk tier:** Routine — workflow prose only; no auth, money, personal data, model, API or
  dependency. Light spec.
- **closes:** usage audit 2026-10-17 (review cost on small changes)

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. Outcome

Small, low-risk work pays for review designed for large, risky work. Over the last 30 days the Codex
spec and plan audits (1b, 2b) ran on all 117 units whatever their tier: about 19 h of waiting, a
median of 9 min and 4 rounds per unit. A colour-token change got a
1,100-word spec, a 1,000-word plan and four Codex rounds. The routine code review (6-review)
rejected 59 of its 126 findings (47%), and each rejection costs triage time. Mechanical changes like
capitalizing status labels went through the full workflow when the trivial lane would have
been enough.

After this change, a routine unit with a light spec gets one Codex audit (1b) instead of two. The
routine review reports at most five findings. And a mechanical change whose decision is already made
takes the trivial lane even when it spans several files.

## 2. Scope

### In
- **PR 1 — review depth** (`feature-workflow`)
  - `SKILL.md` *Risk tier*, *Codex as independent auditor*, 2b: 2b does not run on a routine unit with
    a light spec (§4 D1).
  - `SKILL.md` phase 6: routine → `/code-review medium --max-findings 5`. Tier B and Tier A name
    `--max-findings default` (§4 D3).
  - Every doc that states these rules: `README.md` (the phase diagram's 2b node, the Codex gates
    table and its "run for anything non-trivial" line, the tier table) and
    `docs/design/2026-09-feature-workflow-rationale.md` (the "Codex stays on every unit" line).
- **PR 2 — lane bar**
  - `claude/CLAUDE.md` *Default loop*, Trivial bullet: the mechanical-sweep rule (§4 D4).
  - `trivial-lane-check` *Escalation*: "more than a handful of files" now gives way to that rule.

### Out
- The security gates 1s / 2s / 5s, and `security-audit` triage — unchanged (§4 D2).
- Tier A / Tier B units, and redesign units (Tier B by rule): they keep 1b + 2b and their review levels.
- The `codex-audit` wrapper, ledger grammar and `gate-log` schema: no new gate, no wrapper change.
- The `qa` agent, `performance-review`, `data-integrity`, `observability`: not cost drivers in the audit.
- Gate-log dedupe: `analyze.py` `gate_scorecard` already keeps one record per thread.

## 3. Constraints
- CLAUDE.md non-negotiable: no `security-audit` phase is skipped or downgraded.
- One concern per PR. The two PRs come from this one spec, and the plan opens with a delivery table.
- Imported Codex rows carry `tier: null`, so the value of 2b on routine units is not yet measured
  (§4 D5).

## 4. Decisions
- D1 **2b off for routine + light spec** — 1b attacks the problem, which is where a wrong decision is
  cheapest to catch. A light-spec routine plan restates an approved spec, so 2b mostly re-audits that
  spec. It is decided when the plan file is written, before 2s, and re-decided if the tier or the
  spec kind changes before approval: a move to B or A, or a spec that stops being light, brings 2b
  back. A 2b that is not due is not logged: `--skipped` means "due and not run".
- D2 **5s unchanged** — IMPL audits already end NARROW in 35 of 58 runs. Forcing NARROW by path would
  override "a maybe is a yes" on surfaces the guard's path list misses, such as a new outbound call.
  The developer dropped it on 2026-10-17.
- D3 **6-review capped at 5 on routine** — the cap keeps the highest-confidence findings at the same
  depth. `--max-findings` is sticky across invocations, so every tier names its value: `default` on B
  and A undoes a routine cap left over from earlier.
- D4 **Mechanical-sweep rule** — approved by the developer as written, 2026-10-17:
  *A change is trivial when it applies one decision the developer has already stated — in the request
  or a recorded design doc, never one the agent inferred — such as a token, a copy string, a rename or
  a style, and it touches no data model, migration, dependency, API contract, route or security path,
  whatever its file count.* A change that needs a decision guessed at, or a new behaviour to specify,
  is still non-trivial.
- D5 **Re-measure from the latest tier** — no new tooling. Codex rows log `tier: null`, live ones
  included. The authoritative tier is the one on the unit's **last-logged Claude gate row** (5s or
  6-review), which reflects any restatement after 2s. The next usage audit joins on `slug`; a unit with
  no Claude row after 2s counts as tier unknown, never routine. Teaching `codex-audit` to log the tier
  is a separate unit.
- 1b: needs-revision — 3 accepted, 0 rejected, 1 human
- 1b-F01 (human): D4 approved as written.
- 1b-F02 (human): no merge-time behavioural test; accepted with AC12 extended to the sweep route.
- 1b-F04 (human): the latest Claude row is the tier source (D5).
- 2b: resolved — 4 accepted, 0 rejected, 0 human
- D6 **Redesign units are never sweeps** (PR 2 6-review F2) — the redesign rule is the stricter one,
  backed by three measured misfires, so it wins over D4. A sweep that turns out to touch
  a route or security path escalates (F3).

## 6. Acceptance criteria
1. `feature-workflow` `SKILL.md` says 2b runs on every unit **except** a routine unit with a light
   spec, in *Risk tier*, *Codex as independent auditor* and the 2b section. No line still says 2b
   runs on every unit.
2. The 2b section says the decision is made when the plan file is written, and that a tier restated
   to B or A, or a spec that stops being light, before approval makes 2b due.
3. The 2b section says a 2b that is not due is not logged with `--skipped`.
4. 1b's wording is unchanged: it still runs on every unit, every tier.
5. Phase 6 routine reads `/code-review medium --max-findings 5`. Tier B reads `/code-review high
   --max-findings default`. Tier A's `ultra` instruction names `--max-findings default`.
6. Phase 6 says why the value is always named: `--max-findings` is sticky.
7. `security-audit` and the 1s / 5s sections are byte-identical to `main`. In 2s, only the clause that
   launches 2b and holds edits for it changes, to apply when 2b is due; every security instruction in
   2s is byte-identical.
8. Every `README.md` statement about when 2b runs or how deep phase 6 looks (the phase diagram's 2b
   node, the Codex gates table and the line after it, the tier table) and the rationale doc's "Codex
   stays on every unit" line agree with criteria 1 and 5. `grep` for "every unit" and "anything
   non-trivial" across `README.md`, `claude/` and the rationale doc returns no line that contradicts
   criterion 1.
9. (PR 2) `claude/CLAUDE.md`'s Trivial bullet carries D4's rule as the developer approved it, and keeps
   the security sentence.
10. (PR 2) `trivial-lane-check` *Escalation* no longer escalates on file count alone for a change that
    meets D4. Every other escalation trigger is unchanged.
11. The repo's existing test suite passes on each PR.
12. (After merge, not a merge gate) The next usage audit, using D5's join, shows no 2b row for a
    routine light-spec unit started after the merge, every routine 6-review logs ≤5 found, and it
    lists the multi-file `trivial-check` PRs merged after PR 2 so each can be checked against D4.

## 7. Edge cases swept
- Tier moves routine → B at the plan checkpoint: criterion 2.
- A multi-PR routine light spec: D1 applies per unit, not per PR. 6b is Tier A only, so it is unaffected.
- A routine cap left sticky into a Tier B review: criterion 5's `default`.
- A sweep that turns out to need a decision mid-way: D4's last clause, then the existing escalation.
- A unit with no Claude row after 2s: D5 counts it as tier unknown.
