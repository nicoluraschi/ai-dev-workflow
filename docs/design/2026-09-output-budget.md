# Output budget — numeric caps on generated text

- **status:** shipped
- **date:** 2026-09-25
- **risk tier:** B — changes the contract of the allowlisted `codex-audit` wrapper (ledger
  location) and touches 10+ files. Not Tier A: no auth, money or personal data.

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. Outcome

Generated text is too long to read and is re-read as context. Baseline, 2026-09-25:

| Artifact | Now |
|---|---|
| Specs (two product repos) | 2.7k–11k words |
| PR bodies (last 25) | median ~750 words, peaks 3.5k |
| Codex ledgers committed under `docs/specs/reviews/` | 17 files, ~16.7k words in one product repo |

The template for a spec is 71 words, so length comes from the skills' instructions, and nothing
caps it. Outcome: every kind of output has a number, and Codex ledgers stop landing in the repo.

## 2. Scope

**In**
- `claude/CLAUDE.md`: a new *Output budget* section holding the caps (§6).
- `feature-workflow`: spec cap (replaces the ~15 KB rule), PR body shape in §7 Close, gates
  1b/2b/6b record a one-line verdict in §4 instead of a summary + ledger link.
- Output sections of the gate skills: `security-audit`, `data-integrity`, `migration-safety`,
  `performance-review`, `observability`, `trivial-lane-check`, `ui-review`.
- `codex/reviewer-contract.md`: cap on each finding.
- `codex/bin/codex-audit`: ledger directory moves from `<artifacts>/reviews/` to
  `$(git rev-parse --git-common-dir)/codex-audit/`, plus its tests.
- `new-project`, `adopt-project-layer`: drop any `reviews/` scaffolding they reference.

**Out**
- Deleting the 17 committed review files in the product repos (a later per-repo PR).
- Shrinking the skills' own text (a context-cost problem, not an output one).
- Any hook that measures or blocks on length.
- Rewriting existing specs or PRs.

## 3. Constraints

- The wrapper's lock, "already holds a round-1 review" refusal, `--rerun` archive and round-2
  resume all read the ledger file: they must keep working at the new path.
- `git-common-dir` is shared by every worktree of a repo. For in-repo artifacts this is a change:
  an uncommitted ledger used to be per worktree, now every worktree sees it (and its lock).
  Intended — it stops a second worktree from re-running the same gate/slug.
- Round 2 resumes the Codex thread by id; Codex never reads the ledger path, so moving it under
  `.git/` needs no sandbox change.

## 4. Decisions

- [decided] Numeric caps, not qualitative guidance: measurable against the baseline above.
- [decided] Ledger lives outside the tracked tree (`.git/codex-audit/`), not deleted and not
  merely gitignored: keeps the anti-re-run protection that saves Codex tokens.
- [decided] Only the verdict goes into the spec: one line per gate (§6).
- [decided] Enforcement is rules and output templates only; re-measure against §1 later.
- [decided] Caps as proposed (§6). The only permitted overrun is the evidence of a 🔴 Critical /
  BLOCKER finding. Word counts exclude file paths, code and table syntax.
- [decided] The one-line clean verdict applies to Claude's gate skills. Codex keeps the heading
  format `codex-audit` parses (BLOCKER/MAJOR/MINOR sections); only the per-finding cap applies.
- [decided] Legacy ledgers: if the new path is empty and `<artifacts>/reviews/<same name>` exists,
  the wrapper refuses and prints the `mv` that relocates it. No dual-path reads.
- [decided] `trivial-lane-check`'s per-check lines are verification evidence, not findings, and
  keep their format.
- 1b: 4 accepted, 0 rejected, 1 human (F03: session/gate output is only verifiable by
  re-measuring against §1; no hook, per the enforcement decision).
- 2b: 3 accepted, 0 rejected, 0 human; round-2 regression R01 (CLAUDE.md three-line verdict) and
  F03 verification gap fixed in the plan after round 2.
- code-review high: 9 fixed, 1 rejected (finding 2, shared ledgers across worktrees — intended; §3 corrected).

## 5. Task breakdown

Filled in the plan phase.

## 6. Acceptance criteria

The caps, which become the text of the new section:

| Output | Cap |
|---|---|
| Status line during work | 1–2 lines |
| Final message of a turn | ≤150 words; no restating the plan, no narrating the process |
| PR body | ≤250 words: what + why, test evidence in one line, risks, deferred findings |
| Spec | ≤1,500 words |
| Gate report with no findings | 1 line: gate, verdict |
| Each gate/Codex finding | ≤40 words: location, problem, fix |
| Gate verdict in spec §4 | 1 line: `<gate>: <verdict> — <n> accepted, <n> rejected, <n> human` |

1. Given `CLAUDE.md`, when read, then it holds an *Output budget* section with every cap in the
   table above.
2. Given `feature-workflow`, then the spec rule says ≤1,500 words, §7 Close prescribes the PR
   body shape above within 250 words, and 1b/2b/6b say to record the one-line verdict with no
   ledger link.
3. Given each gate skill listed in §2, then its output section states: no findings → one line;
   each finding ≤40 words; no checklist echo.
4. Given `reviewer-contract.md`, then each finding is capped at 40 words.
5. Given a `codex-audit` run in a repo, when round 1 completes, then the ledger is written under
   `$(git rev-parse --git-common-dir)/codex-audit/` and nothing is created under
   `<artifacts>/reviews/`.
6. Given a ledger already at the new path, when round 1 is re-run without `--rerun`, then the
   wrapper refuses as today; round 2 finds and resumes it; the lock file lives beside it.
7. Given two worktrees of one repo, when both run the same gate/slug, then they contend on the
   same lock (shared common dir).
8. Given `test_codex_audit.sh`, when run, then it passes with the paths updated.
9. Given a ledger at the new path, when round 1 runs with `--rerun`, then the old one is archived
   beside it as today.
10. Given only a legacy ledger at `<artifacts>/reviews/`, when any round runs, then the wrapper
    exits 1 with the `mv` command to the new path.
11. Given `claude/skills/`, `claude/CLAUDE.md` and `codex/` (excluding the wrapper's legacy
    check), when grepped, then none points to `reviews/` as the ledger location; the wrapper
    prints the ledger path on every run, including the round-2 early stop.
12. Given this feature's own PR and spec, then the body is ≤250 words and the spec ≤1,500.
13. Given `new-project` and `adopt-project-layer`, then neither creates or mentions a
   `reviews/` directory under the artifacts dir.
