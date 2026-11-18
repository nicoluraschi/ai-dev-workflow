# How I Work With AI — Development Standard

**What this is:** the *why* behind this setup, a monthly audit instrument, and a way to explain the
workflow to others.

**Where the facts live:** the [README](../README.md) is the inventory — what's installed, what
it does, when it fires. This file states principles and reasons, and deliberately carries no
counts, thresholds or file lists, so a config change never makes it wrong. Measurements below are
dated: they are what was observed then, not a claim about now. When this file and the config
disagree, the config wins and this file gets corrected in the same PR.

---

## 1. My system at a glance

The core move is separating **how I want the agent to work** (stable, mine, cross-project) from
**the facts of a given project** (specific, in the repo), with a third layer for what varies per
repo:

- **Global layer** (`~/.claude/`) — my working agreement with the agent: plan-first, TDD, small
  diffs, stricter frontend review, no invented APIs, an output budget. Loads into every session.
- **Project layer** (in the repo) — `AGENTS.md` holds shared cross-agent context; a thin
  `CLAUDE.md` imports it with `@AGENTS.md`; `docs/` holds the constitution, architecture,
  glossary, specs and the QA guide.
- **Profile layer** — the small file that holds what *varies* per repo: calibration, where
  artifacts live, which gates run, and whether the repo may be shown to a second provider at all.
  It **points at** `AGENTS.md` for commands rather than copying them, so the two can't drift.

**Why `AGENTS.md` and not just `CLAUDE.md`:** Claude Code reads `CLAUDE.md`, but `AGENTS.md` is
the cross-tool standard other agents read too. So `AGENTS.md` is the single source of truth and
`CLAUDE.md` imports it.

**One loop, stated once.** The default loop lives in exactly one place — the global layer.
Project files *point* to it and never restate it.

**Everything is one versioned repo**, symlinked into `~/.claude` and `~/.codex`, so the files in
the repo *are* the live config and can't quietly diverge from what actually runs.

### Classify first: three lanes

- **Trivial** — a short plan, then TDD, ending at `trivial-lane-check`. That skill has the
  authority to say *this was never trivial* and move the work to a heavier lane.
- **Light** — routine work with new behaviour and no Tier A/B trigger, whatever its size: a plan
  in chat, TDD, then `trivial-lane-check`, the IMPL security audit and one `/code-review`.
- **Tier A / B** — the spec-driven lifecycle, through `feature-workflow`. Size is not a trigger:
  risk is what a change touches, not how many lines it has.

The phases themselves are in the [README](../README.md#-a-piece-of-work-end-to-end). The one
structural choice worth explaining here: **Verify ("does it work?") and Review ("is it good?")
are separate phases, in that order.** Any check whose *output* is a code change — the
implementation security audit, `ui-review`, independent QA — has to run before the check whose
*input* is the code. A review of a diff that is about to change is wasted work. That is not
"verification first" as a matter of taste; QA was the first test of whether the rule generalises,
and it did.

### Three reviewers, and what each one is ignorant of

This is the part I'd lead with when explaining it, because it is a design, not a tool list:

- **The author** — Claude, which wrote the spec and the plan on Opus, and the code either inline
  or through the implementer agent. Knows everything about the conversation, and is therefore the
  worst judge of whether the result is right.
- **Codex (1b / 2b / 6b)** — reads the *artifacts* and attacks them. Ignorant of the conversation
  that produced them; it sees the spec, not the reasoning that talked me into it.
- **qa (5q)** — reads the *spec* and drives the *running app*. Ignorant of the plan, the diff, the
  files touched, and any summary of what was built.

Each is useful in proportion to what it doesn't know. An auditor handed the implementation stops
auditing and starts agreeing — it re-derives the author's reasoning, which is the same reasoning
that produced the bug. So independence isn't a disposition I ask a model to adopt; it's a property
of what the prompt is *allowed to contain*, and that made it something I could enforce
mechanically rather than hope for.

### Gates that fire on what the change is

Review skills fire on **what the change is**, not on either of us remembering them — blocking on
an unambiguous path signal, only reminding on a content heuristic.

**Security is the one with no conditions.** Three phases, mandatory in both lanes. A Critical
finding stops the work. **Depth scales, and a mechanism makes that true:** a four-question triage
(reachability, data, trust boundary, primitives). Any yes → FULL. **Any maybe → FULL.** All four
no → a one-line narrow verdict. Re-audits cover only the hunks that moved plus the previous
findings.

**Every gate reports failures, not passes.** A clean result is one line. The check is unchanged —
what went is the prose around it.

**QA is deliberately *not* a gate.** It fires on nothing: no hook, no path signal, no content
heuristic. The decision is made once, by me, at the plan — where the risk is already being
reasoned about — and the default answer is skip. A gate that fired on "user-facing change" would
have been easy to build and would have produced a QA report on every copy tweak, which is exactly
how a quality system decays. **The check that earns its place is the one you can decline cheaply.**

---

## 2. The framing facts

**Role: implementer → orchestrator.** The value moves toward architecture, agent coordination,
quality evaluation, and problem decomposition.

**Full delegation is a myth.** Engineers use AI for ~60% of their work but fully delegate only
0–20% of tasks.

**Delegation criteria are empirical.** Easily verifiable or low-risk → delegate. Conceptually hard
or design-dependent → keep or collaborate.

**The point that keeps holding up:** AI pays off most when you already know what the
answer should look like.

**Where I sit.** Agents write against a spec I approved, and nothing merges until it passes the
tests, the gates and my review. My work is the spec, the design decisions and the verdict.

---

## 3. The six dimensions

### 3.1 Spec and intent

The lifecycle produces a versioned spec with acceptance criteria before implementation, interviews
me before drafting, and updates the spec on close. Codex attacks the spec for every Tier A / B
unit.

The edge-case checklist that QA uses to find bugs is also swept during Specify, to find *undefined
behaviour* — the same categories, two phases apart. What the spec defines at phase 1 is what QA has
an oracle for at phase 5; what it leaves silent comes back as a Question rather than a Bug.

**Specs are capped, and scaled by surface.** Specs had reached 11k words (2026-09) — past specifying and
into designing — and a spec is re-read many times in a session, so its length is paid again on
every read. A spec that doesn't fit is a signal the feature should ship across several PRs. A unit
with no data model, API, auth or dependency gets a lighter spec — but its acceptance criteria are
never cut: they are what QA verifies against.

**Independence is only as clean as the spec is implementation-free.** The QA agent receives the
spec's acceptance criteria *verbatim* — that is the design. When a criterion names a method, a
class or a serializer, it reaches the "ignorant" reviewer, not because the orchestrator leaked it
but because it was written into the spec.

What remains permanently mine: **conformance is not intent.** QA does not fix that — it is another
conformance check, just an independent one. The spec can be met perfectly, verified twice by two
ignorant reviewers, and still be the wrong spec.

### 3.2 Harness

Hooks for what must not depend on memory, review skills on automatic triggers, two enforcement
levels, per-gate escape hatches that expire, a release valve after two refusals, and tests for the
hooks themselves.

**No commit on a red suite** reads the summary line of the latest run, not the exit code (a pipe
makes it `tail`'s). It believes observed output, never a claim.

**The QA read-only guard parses, it doesn't pattern-match.** It exists because `disallowedTools`
removes Edit and Write but does not sandbox Bash. It resolves shell quoting and decides what is a
command by position, because a guard tested only against attacks its author imagined is green and
blind in the same shape — the mirror test (§4) in the one file whose entire job is not to be
fooled.

### 3.3 Context

Global vs project split, `AGENTS.md` plus a thin `CLAUDE.md`, path-scoped rules, short files.
Auto-memory writes its own notes and drifts like anything else — audit it monthly, and treat a
memory naming a file or flag as a claim to verify.

**Generated text is context, because it is.** Every spec, plan, review ledger and long final
message is re-read in later turns. Capping it is a context decision as much as a readability one,
and moving the Codex ledgers out of the tracked tree removed files that were committed, re-read and
never used.

`docs/qa.md` is a per-project file and a thing that can rot. **A stale QA guide is worse than
none**: it sends a reviewer that trusts it down a path that no longer exists, and that reviewer has
no code-level context to notice.

### 3.4 Orchestration

**The review layer:** the Codex loop is a protocol with mechanisms that hold under pressure — one
allowlisted entry point, two rounds then me, a verbatim ledger, a checkpoint that surfaces only the
disputes, narrowed trust, and exit codes that distinguish *ran and found nothing* from *did not
run*. The ledger is Codex's unedited words — the thing that stops the author from paraphrasing its
critic — kept outside the tracked tree; the spec records one verdict line.

QA has a second protocol of the same shape: a single entry point (`/qa`), a fixed brief it is
allowed to contain, a report format, and a hard rule that the orchestrator shows the report
unedited. The same three questions — *what is this reviewer ignorant of, what would quietly restore
its knowledge, and what stops the author from editing its verdict* — turned out to be the whole
design both times.

**Where the clock goes (measured, 2026-09):** median 27.5 minutes of model-plus-tool time per PR,
**91% model, 9% tools.** Gates were ≈25% of model minutes overall. With 91% of the clock being the
model writing, how much it writes is the lever — which is what the output budget pulls.

**Which model does the writing is the second lever.** Planning is where a wrong assumption costs the
most, because everything after inherits it, so it gets the strongest model. Implementing an approved
plan is narrower work, so it can go to a cheaper one — but only through a mechanism that works. Two
did not: `opusplan` chooses the model by mode, so a session in auto mode would run Specify on
Sonnet; and a skill pinned to a model inline was ignored in auto mode. What works is a subagent with
a pinned model.

The cost of a subagent is that it starts with an empty context — measured once at ~45k tokens of
fixed overhead per spawn, against re-reading 165k of context on every inline message in a normal
session and 473k in a long one. It only knows what is written down, which is why **the plan is its
brief**. The audits stay on Opus even though Verify is mostly deterministic: the rules forbid
downgrading `security-audit`, and the same reasoning covers the others.

**Rollback rule.** Compare delegated features against recent inline ones. Roll back if total
cache-read plus cache-create tokens are not lower, if more than one feature in three needed a task
re-delegated, or if review finds more logic or TDD defects than before.

### 3.5 Delegation criteria

High-verifiability and low-stakes goes to the agent; design decisions, org context and problem
definition stay mine.

I delegate *verification* to an agent that is structurally prevented from knowing how the thing was
built. That is a better answer to "how do you know the generated code is right?" than any amount of
coverage, because it changes *who is checking* rather than *how much*.

### 3.6 Review

Verify and Review are separate phases. `trivial-lane-check` closes the "small change" bypass. A hook
refuses to let a PR open before the review its tier requires has produced a citable result.
`ui-review` is mandatory before any user-facing change is called done, and it measures in a real
browser rather than agreeing with me.

QA is the first check whose oracle is the spec text alone, exercised against the running system. It
is the countermeasure to the mirror test that isn't "read the tests more carefully". **And the
limit:** it verifies conformance, not intent.

**A long PR body is less reviewable, not more.** A 3,500-word body buries the part that needs my
judgement in the part that doesn't. The body carries what and why, test evidence in one line, risks,
and only the *deferred* findings. Frontend PRs keep extra room, because that is where I review
strictest.

**The delegate's report is a claim, not evidence:** the main session re-runs the suite and compares
the agent's file list with `git diff`.

**What no hook can check:** whether the human reads the evidence; so the evidence column, not the
verdict line, is what gets read.

---

## 4. Failure modes worth naming

- **Mirror test** — the agent writes both the test and the code, so the test encodes its own
  misunderstanding and passes green. *Countermeasure:* I confirm the cases before implementing — and
  an independent pass whose oracle is the spec rather than the code.
- **Missing case** — cases iterated with the agent are reviewed against the agent's framing.
  *Countermeasure:* my own list before opening the chat; the edge-case sweep at Specify.
- **Hallucinated dependencies** — *Countermeasure:* lock files, CI that installs clean.
- **Unbounded loops** — *Countermeasure:* iteration limits and explicit termination.
- **Spec-to-code drift** — *Countermeasure:* update the spec on close; Verify flags drift.
- **Conformance is not intent** — green everywhere, solves the wrong problem. *Countermeasure:* only
  a human who understands the domain catches this one. Two ignorant reviewers do not add up to one
  informed one.
- **Captured auditor** — the agent that wrote the artifact summarizes its own critic.
  *Countermeasure:* the verbatim ledger; the unedited QA report; synthesis is an add-on, never a
  substitute.
- **The informed auditor** — nobody edits the critique; the reviewer is simply *told too much* up
  front. *Countermeasure:* the brief is a fixed list, the orchestrator is forbidden from adding to
  it, and the agent reports contamination as a defect. **And the subtler leak: the spec's own
  acceptance criteria, when they name a class or a method** (§3.1).
- **The reviewer who trusts the suite** — an independent reviewer sees green and calls the
  criterion passed. *Countermeasure:* the suite is a map, never evidence. No PASS without something
  observed against the running system in that session; otherwise NOT VERIFIED.
- **The confident subagent report** — a subagent that starts with an empty context fills its gaps
  by asserting, and the report reads as finished work, which is why it gets skimmed.
  *Countermeasure:* treat it as a claim — re-run the suite, compare with `git diff`, and write the
  plan to stand on its own so there is less to guess.
- **Gate fatigue** — a noisy gate gets silenced, and the blunt way to silence it takes every other
  gate with it. *Countermeasure:* per-skill silencing; block only on unambiguous path signals;
  auto-release after two refusals; silencers that expire.
- **The forgotten silencer** — the escape hatch works as designed and then never closes.
  *Countermeasure:* a TTL that deletes itself.
- **Consent by default** — code reaches a second provider because nobody decided it shouldn't.
  *Countermeasure:* `codex_reviewer` has no default; absent consent is a recorded skip.
- **The trivial bypass** — "it's a small change" routes work around every gate.
  *Countermeasure:* `trivial-lane-check` gates that lane too.
- **Tier by surface** — classifying a change's risk from how its diff looks, when the kind of work
  already says. *Countermeasure:* redesign units always get the deeper review (`/code-review
  high`); the tier is restated at the PR gate.
- **Ceremony by size** — a big but low-risk diff unlocks the full lifecycle. *Countermeasure:* tiers
  come from what a change touches; size only splits PRs.
- **Context creep** — a session outlives the work it was opened for. *Countermeasure:* one session
  per worktree.
- **Shared mutable config** — a setting several parallel sessions can write. `/model` persisted a
  choice into the tracked `settings.json`, so a switch in one session dirtied the checkout for all
  the others, and a Stop hook then blocked their turns. *Countermeasure:* remove the reason to
  switch; when a switch is unavoidable, use the session-only option.
- **Optimising the wrong constraint** — an efficiency measurement that ranks steps by cost alone
  argues for dismantling the gates. *Countermeasure:* `usage-audit` requires every finding to state
  what quality its cost buys.
- **Ceremony mistaken for rigour** — a gate that writes a full report to say "nothing here" feels
  more thorough than one that says it in one line, and is not. *Countermeasure:* triage before
  spending; measure minutes per PR, not gates per PR.
- **Length mistaken for diligence** — nobody decides to write an 11k-word spec; each paragraph looks
  like care, and the total is a document too long to review and a context bill paid on every
  re-read. *Countermeasure:* numeric caps, failures not passes, and a baseline to re-measure
  against — because a cap nobody measures is a wish.
- **The untested installer** — a setup script only ever run on the machine that already works
  reports success while omitting something, indefinitely. *Countermeasure:* when adding a new *kind*
  of thing to the repo, check the installer owns it before checking anything else.
- **Docs that restate the config** — a description kept somewhere the config change never touches
  drifts within a day. *Countermeasure:* docs live in the repo, change in the same PR, and this file
  states reasons rather than counts.
- **Prompt jockey** — prompt, PR, glance at green, merge. *Countermeasure:* this document.

---

## 5. What I never delegate

- Architecture decisions.
- Anything needing organizational context or taste.
- Defining which problem is worth solving.
- The final review of anything going to production with user data.
- Learning a new domain.
- Consent for whose code leaves the machine.
- **Deciding whether a QA finding is a bug or a spec change.** The agent is required to raise the
  ambiguity, and forbidden from resolving it.
- **The audits.** The implementer writes and runs the suite; it does not audit its own work, and
  the audits do not move to the cheaper model.

---

## 6. Monthly audit (10 minutes)

- Are my `CLAUDE.md` and `AGENTS.md` still accurate? Any instruction no longer true?
- **Does the README still match the config?** Every count, name and path in it.
- Did I audit Claude Code's auto-memory this month?
- Does what `feature-workflow` says it runs still match the Codex config that exists?
- Did a gate expire back on and immediately get re-silenced? That's a gate telling me it's
  miscalibrated.
- Any repo I started work in without a profile — and did anything leave to Codex without consent?
- Which skills fired this month, by transcript evidence rather than belief?
- What did a feature cost — minutes per PR, and what share were gates?
- Did any session outlive the worktree it was opened for?
- **Are this month's specs, PR bodies and gate reports inside the output budget?** A cap nobody
  checks is a wish.
- **Is every `QA:` line in this month's plans a real decision, or is skip the answer I always give?**
  A default that is never overridden isn't a default, it's a removal.
- **Is `docs/qa.md` still true in each repo that has one?** It is read by a reviewer with no code
  context, so it cannot self-correct.
- **Do my acceptance criteria name classes, methods or files?**
- **Did delegation pay back?** Compare tokens per feature and re-delegations against the rollback
  rule in §3.4.
- **Did any implementer report differ from `git diff` or the suite output?**
- **Did the review phase run on Opus?** Read the model on the transcript, not the setting.
- **Did a `/model` switch dirty this repo's checkout this month?**
- Is anything running live that isn't captured in this repo — **and does `install.sh` actually
  own it?**
- Are the open known-gap issues still open for a reason?
- Any CI check that never fails?
- Has my delegation criterion changed? Why?
- Can I still explain every architecture decision in my live projects?

Two or more in the red means rereading §3.6.

---

## 7. Sources

- **2026 Agentic Coding Trends Report** (Anthropic) — the 60% / 0–20% figure.
- **"Skills for the future software profession"** (2026 roundtables).
- **Addy Osmani, "The Next Two Years."**
- **Spec-driven development** (GitHub Spec Kit; "From Code to Contract", Feb 2026).
- **Claude Code docs** — memory, plan mode, hooks, skills, subagents, MCP.
- **Session transcripts** — measured evidence of what the workflow does.

---

## 8. The final note

My edge isn't that I use agents well. It's that I know what the answer should look like before I
ask for it. The system in this document exists to protect that edge, not replace it.

**Every mechanism I add makes it easier to stop paying attention.** The gates are there so my
attention lands where it matters — not so I can stop supplying any.

An over-built quality system fails by making each check so expensive that removing checks becomes
the obvious next move.

The better a reviewer's output looks, the less of it gets read. **The failure mode of a good
reviewer is not being wrong. It is being trusted.**

Attention is the budget everything else spends, so output is capped.

The whole thing still reduces to one rule:

**Don't delegate the thing that makes you good at delegating.**
