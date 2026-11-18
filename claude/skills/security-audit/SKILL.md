---
name: security-audit
description: Security audit and threat modeling across all phases of development. Trigger automatically at specification (identify threats before design), design (evaluate trust boundaries and data flows), and implementation (audit generated code). Use whenever writing or reviewing specs, designing systems or APIs, generating or reviewing code, making authentication/authorization decisions, handling user data or secrets, designing database schemas, or integrating external services. Also invoke explicitly with "security review", "is this secure?", "check for vulnerabilities", "threat model this", or "OWASP check". Do not skip this even for small features — security issues introduced early are the most expensive to fix.
context: fork
agent: general-purpose
effort: high
---

# /security-audit

## Inputs — you run in a fork

This skill runs in a fresh subagent (`context: fork`), on the caller's model, so its reads and
tool calls do not ride on the main session's context. You see **only the args**, never the
conversation. The caller passes, in `args`:

| Arg | Needed for |
|---|---|
| Phase: `SPEC`, `DESIGN` or `IMPL` | every run |
| Spec or plan path (the acceptance criteria live there or are pasted) | SPEC, DESIGN; IMPL when one exists |
| The diff command and the repo path: `git diff main` while work is uncommitted (`main...HEAD` sees commits only), or a file list | IMPL |
| SPEC's threats (1s) | DESIGN |
| Decisions agreed in chat that are not in any file | whenever they exist |
| Previous audit's findings and the range since it | a re-audit (delta) |

An input you need is missing → return `Security audit — <phase>: ⚪ not run — missing <input>`
and stop. Never guess the phase, the range or a previous finding. You cannot ask anyone: the
caller relays your return verbatim, then acts on it (a STOP stops the main session).

**Caller:** the fork runs in the background; relay its return when its notice arrives.
`audit-guard.py` counts the run only once that notice says it completed and the return carries
its 🟢 or 🔴 verdict, so every audit return ends with one and a `⚪ not run` never does. A
`⚪ not run` is not an audit: re-invoke with the missing input before doing anything else.

**IMPL also audits untracked files:** `git diff` never shows them, so list them with
`git status --short` and read every new file on the change, whatever command the caller passed.

## Phase Selection

| You have | Phase to run | Then read |
|---|---|---|
| A feature description, user story, or requirements doc | **SPEC** | `references/spec.md` |
| A system design, API contract, data model, or architecture | **DESIGN** | `references/design.md` |
| Code, a diff, or an implementation | **IMPL** | `references/impl.md` |

Run STEP 0 first; on FULL, read **only** your phase's reference (steps, checklist, output
template). No phase in the args? See *Inputs*. End-to-end work runs all three, one pass per phase.

## STEP 0: TRIAGE — scale the depth

**Mandatory first step of every phase.** It decides how much audit, never *whether*: the
check does not scale; the write-up does.

1. **Reachability** — does it alter who can reach what? (authentication, authorization,
   ownership scoping, roles, tenancy, allowed origins, routes, middleware, permissions)
2. **Data** — does it move, store, log or expose data that matters? (PII, credentials,
   tokens, money, secrets)
3. **Trust boundary** — does it add or change a boundary crossing? (a new endpoint,
   outbound call, input parsed from an untrusted source, or SQL / shell / file / template sink)
4. **Primitives** — does it change a cryptographic or session primitive? (hashing, random,
   token lifetime, cookie flags)

**Any yes → FULL:** the phase reference, in full.
**All four no → NARROW:** no checklist, no stack detection, no findings table — only:

```
**Security audit — [phase], narrow:** 🟢 no findings — [one clause: why none of reachability / data / trust boundary / primitives is touched].
```

A narrow verdict **is** a real audit result: it satisfies the gate, belongs in the ledger, and
is a claim you are accountable for. **A "maybe" is a yes.** Calibration: an allowed-origins list
moved to the environment *looks* like config and is FULL (question 1); a JSON config key, or
one scalar in an owner-scoped `strong_parameters` allowlist, is NARROW.

**Output budget** (CLAUDE.md): no findings → `Security audit — <phase>: 🟢 <verdict>`;
otherwise failures only, ≤40 words each. SPEC's security requirements and a re-audit's
status table are deliverables, not padding.

## Re-audit after a fix — the delta

The gate re-fires after each sensitive edit: a fix can introduce what it was for. On a re-invocation **in the same session** (the caller passes the previous findings and the
range since that audit), audit only the hunks changed since the previous audit, plus every previous finding (closed, and stayed closed). No checklist over
unchanged code, no stack re-detection, no restating accepted findings.

```
**Security audit — re-audit over the delta.** [N] file(s) changed since the last audit.

| Previous finding | Status |
|---|---|
| [#/severity/what] | ✅ closed / ⚠️ still open / 🔴 regressed |

**New in the delta:** [findings table, or "none"]
**Verdict:** 🟢 No blockers / 🔴 [N] critical
```

## Severity scale

| Level | Meaning | Action |
|---|---|---|
| 🔴 Critical | Exploitable by an external attacker with low effort | Block — do not proceed |
| 🟠 High | Significant risk; exploitable under reasonable conditions | Fix before merge |
| 🟡 Medium | Real issue but requires specific conditions or internal access | Fix in this sprint |
| 🔵 Low | Minor hardening or defense-in-depth improvement | Address when convenient |
| ℹ️ Info | Observation or suggestion | No action required |

## Blocking behavior

Any 🔴 Critical in IMPL: output the full findings table and an explicit **STOP** notice.
The caller generates no further code, migrations or configuration for this feature until it is
resolved, then re-audits the fix as a delta. This holds however the task was framed ("just finish it", "we'll fix security later").
