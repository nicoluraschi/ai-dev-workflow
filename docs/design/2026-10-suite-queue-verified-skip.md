# suite-queue: skip a suite that already passed on the exact same content

- **status:** shipped
- **date:** 2026-10-17
- **risk tier:** Routine — local tooling and workflow skills; no auth, money, personal data, data model
  or dependency. Builds on `docs/design/2026-10-prepush-suite-queue.md`.

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. Outcome

Every PR runs its full suite twice on the same code: once in Verify, once in the pre-push hook. With
`suite-queue` serializing suites machine-wide, the second run also waits in the queue, so each push
costs a full suite plus queue time for no new information.

After this change, `suite-queue` records each passing run against the exact content it tested. A later
run of the same kind and command on the same content, with a clean working tree, is skipped at once,
without waiting for the slot, with one line saying when it passed. Any change to a tracked or untracked
(non-ignored) file means no match, and the suite runs.

## 2. Scope

### In
- **`git/bin/suite-queue`**: compute a content key before running; skip when a valid record matches
  and the tree is clean; once the slot is taken, delete any record for that key; on exit 0, record
  the key if the content is unchanged at the end of the run.
- **Verify runs the suite through the hook**: `verification-before-completion`, and the suite steps
  of `feature-workflow` phase 5 and `trivial-lane-check` check 1, say: when the repo's lefthook
  pre-push runs a suite through `suite-queue`, run it as
  `lefthook run pre-push --force --no-tty --command <name>`.
- **`claude/hooks/no-commit-on-red.py`**: that exact invocation counts as a test command, so a Verify
  run through lefthook still feeds the red-suite gate.
- Docs: the dotfiles README row for `suite-queue`, and one line in the base spec's §4 pointing here.

### Out
- Repos that don't run their suites through `suite-queue` (they keep running twice).
- Sharing records across machines, or trusting CI results.
- Keying on environment variables, gitignored files or installed dependencies beyond their lockfiles.
- Skipping brakeman, audits or typecheck.

## 3. Constraints

- **The key is the content, not the commit.** `kind`, the exact argv, the repo-relative working
  directory, and the tree hash of the working copy: tracked plus untracked, gitignored files excluded.
  The tree hash comes from `git add -A` into a temporary index seeded from the real one (so stat data
  keeps it fast), then `git write-tree`. The real index is never touched.
- **Recorded content is tested content.** The key is computed before the command starts and again
  after it exits 0. A record is written only if both match: a file added, removed or edited mid-run
  never gets recorded.
- **A skip needs a clean tree.** The pre-push hook tests the working copy, while the push sends commits.
  A skip is allowed only when the working copy equals `HEAD`'s tree (no changes, no untracked files),
  so the skipped content is exactly the pushed content.
- **The skip is decided before the slot.** The record check runs before the lock, so a skipped run never
  waits in the queue.
- **The latest real result wins.** A run deletes the record for its key once it holds the slot, and
  writes it again only on a pass. A rerun in flight (for example under `SUITE_QUEUE_FORCE=1`)
  therefore never lets a concurrent run skip on the older pass, and a red rerun leaves no pass
  behind (1b R01). Deleting only after the slot is taken keeps a valid pass when a run times out or
  is stopped while waiting; holding the slot means no other run of that kind can record meanwhile
  (review).
- **No key where git can't see the content:** an index with assume-unchanged or skip-worktree entries,
  or a repo with a submodule, gets no key, so the suite always runs (review).
- **The key is retaken once the slot is ours**, so a checkout during the wait invalidates the record
  of the content the run actually tests (review).
- **The temporary index keeps the real index's mtime** (`cp -p`): git's racy check compares entries
  against it, and a fresh mtime makes a same-size edit in that second hash as the old blob (review).
- **Fails safe.** If the key cannot be computed or a record cannot be read or written, the suite runs
  and nothing is recorded. A problem never turns into a skip.
- Records live under `<git-common-dir>/suite-queue/passed/` (mode 700), so every worktree of a repo
  shares them and they vanish with the repo. A record is valid for 7 days: older ones are ignored, and
  deleted whenever a new record is written.
- Outside a git repo nothing is recorded or skipped; the suite always runs.

## 4. Decisions

- The recorder is `suite-queue`, not `no-commit-on-red.py` — the hook can't tell a full suite from a
  single spec file, or which content a run tested (interview).
- Verify runs suites through `lefthook run pre-push --command <name>`, so the command matches the
  push byte for byte, and Verify runs also go through the queue (interview).
- "Same code" means exact content, so a Verify run before committing still counts once that exact
  content is committed (interview).
- Verify always forces (`SUITE_QUEUE_FORCE=1 lefthook run pre-push --force --no-tty --command <name>`):
  `verification-before-completion` rejects a previous run as evidence, so Verify produces fresh
  output and writes the record, and only the push skips (plan).
- `SUITE_QUEUE_FORCE=1` runs the suite whatever the records say — an env var, so it dies with
  the shell.
- A skip is not a pass: no-commit-on-red still reads the last real run's summary.
- A record is named by the sha256 of its key and holds the full key; a skip needs both to match, so a
  stray or hand-made file never skips by accident. CI still runs every suite as the backstop (1s).
- 1b: resolved — 6 accepted, 0 rejected, 1 human (R01: an executing run invalidates its record first,
  recommended).
- 2b: not run; plan approved at the checkpoint.

## 6. Acceptance criteria

1. **Pass is recorded.** After `suite-queue js true` exits 0 in a clean repo, a record for that key exists.
2. **Failure is not recorded.** After `suite-queue js false`, no record exists, and a rerun runs the command.
3. **Skip on match.** A second identical run in the same clean repo skips the command (proven by a marker
   file it never writes), exits 0, and prints one line to stderr:
   `suite-queue: skipped <kind> — passed on this exact content at <HH:MM> (SUITE_QUEUE_FORCE=1 to run)`.
4. **New content runs.** Changing a tracked file, adding an untracked one, or committing content that
   has no record all make the next run execute.
5. **Ignored files don't count.** Changing a gitignored file doesn't prevent a skip.
6. **Different command or dir runs.** A different argv, or the same argv from another subdirectory, runs.
7. **Verify before commit counts.** With uncommitted changes, a passing run executes and records; a
   repeat while still dirty executes again. Once that exact content is committed and the tree is clean,
   the next run skips.
8. **New file verified, then committed.** A pass with a new untracked file, followed by committing that
   file unchanged, makes the next run skip.
9. **Edited mid-run is not recorded.** If the command edits a tracked file, adds a file or removes one,
   and exits 0, no record is written.
10. **Skip doesn't wait.** With the kind's slot held by another run, a matching run skips within 1 s.
11. **Red rerun clears the pass.** After a pass is recorded, a forced failing run on the same content
    deletes the record, and the next normal run executes. While that forced rerun is still running, a
    concurrent normal run on the same content does not skip.
12. **Worktrees share records.** A pass in one worktree lets a second worktree on the same content skip.
13. **Force.** `SUITE_QUEUE_FORCE=1` runs despite a matching record.
14. **Outside git.** Nothing is recorded, and the command always runs.
15. **Index untouched.** The repo's real index (staged state) is byte-identical before and after a run.
16. **Age.** A record older than 7 days doesn't skip, and is deleted when a new record is written.
17. **Fails safe.** If the records dir can't be written, or `git write-tree` fails, the command runs and
    exits with its own status.
18. **End to end.** In a temp repo whose `lefthook.yml` pre-push runs a suite through `suite-queue`,
    `lefthook run pre-push --force --no-tty --command <name>` followed by a commit and an ordinary
    `lefthook run pre-push` executes the suite exactly once.
19. **No-commit-on-red sees the Verify form.** A result for
    `lefthook run pre-push --force --no-tty --command rspec` with a red RSpec summary blocks a commit,
    and one with a green summary allows it.
20. **Skills and docs say it.** `verification-before-completion`, `feature-workflow` phase 5 and
    `trivial-lane-check` check 1 name the lefthook form; the README row and the base spec's §4 mention
    the skip.
21. **Existing behaviour holds.** Every test in `git/bin/test_suite_queue.sh` still passes.

## 8. Acceptance criteria (security)

22. **Forged records don't skip.** A file in `passed/` whose name or content doesn't match the key's
    sha256 and full key never causes a skip.
23. **Pruning stays in its lane.** Pruning only deletes files named with exactly 64 hex characters
    inside `passed/`; any other file there survives.
24. **Private records dir.** `<git-common-dir>/suite-queue/passed/` is mode 700.
