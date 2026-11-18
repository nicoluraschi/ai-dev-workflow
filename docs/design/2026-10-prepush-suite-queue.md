# Pre-push suite queue: one heavy suite per kind, machine-wide

- **status:** shipped
- **date:** 2026-10-17
- **risk tier:** Routine — local tooling and hook config; no auth, money, personal data, data model or
  dependency (`lockf` ships with macOS).

Gate ids are the feature-workflow phase number plus a letter: s security audit, b Codex critique,
d data/performance design review, q independent QA (1 Specify, 2 Plan, 4 Implement, 5 Verify,
6 Review).

## 1. Outcome

With several sessions open, two or three reach the push at once. Each pre-push runs its full suites in
parallel at full width (Jest defaults to cores − 1 workers), so pushes compete for 10 cores: load
reached 70–98 on 2026-10-17, pushes took 20+ minutes, and Jest timed out twice. Every session stalls
together, which defeats the parallelism.

After this change, at most one Ruby suite and one JS suite run on the machine at a time, across all
repos. A push that finds its slot busy waits, says what it is waiting for, and runs when the slot frees.
Each Jest/Vitest run is capped at 2 workers, as CI already does in one product repo.

## 2. Scope

### In
- **`suite-queue <kind> <command> [args…]`**, a bash script at `git/bin/suite-queue`, linked onto PATH
  (`~/.local/bin`) by `install.sh`. Kinds: `ruby`, `js`.
- **Pre-push adoption**, with a fallback that runs the command directly when `suite-queue` is not on PATH:
  - two Rails + Jest product repos: `rspec` → `ruby`; `jest` → `js`, plus `--maxWorkers=2`
  - one Vitest product repo: `test` → `js`, plus a 2-worker cap for Vitest
- Docs: the dotfiles README inventory, and each repo's pre-push description, wherever it lives.

### Out
- Suites that agents run outside a push (Verify, ad-hoc). Revisit with data after v1.
- brakeman, bundler-audit, npm/pnpm audit, typecheck: light, so not queued.
- N-slot semaphores and priorities. One slot per kind is enough for v1.
- Linux support (`flock`): every repo here is solo and runs on this Mac.
- Skipping a pre-push run when Verify already passed on that tree.
- Enforcing the 4-session cap.

## 3. Constraints

- Lock files live at `~/.cache/suite-queue/<kind>.lock`, never in `$TMPDIR` or `/tmp`: Claude sessions can
  get a per-session `TMPDIR`, which would split the queue, and a fixed `/tmp` path is open to other users.
- The lock is a `flock` held by a live process (`lockf -k`), so a killed holder frees the slot
  immediately. There is no stale-lock cleanup to write.
- The command runs through `"$@"`, with no `eval` and no re-quoting.
- The fallback must not re-run a failed suite: `if command -v …; then …; else …; fi`, never `a && b || c`.
- Lefthook buffers each parallel command's output until it finishes, so stderr alone cannot announce a
  wait while it happens.

## 4. Decisions

- One slot per kind, machine-wide — a single push still runs its rspec and jest side by side (interview).
- The fallback keeps every repo pushable without these dotfiles (interview).
- Pre-push only for v1 (interview).
- All three repos are solo, so the fallback is a safety net, not a contributor concern (interview).
- The wait timeout defaults to 1200 s, overridable with `SUITE_QUEUE_TIMEOUT` (a positive integer of
  seconds) — a hung holder fails the waiting push loudly instead of hanging it forever.
- The wait message goes to `/dev/tty` when one can be opened, otherwise to stderr — the tty is the only
  path that reaches a human while lefthook buffers, and writing both shows it twice (1b R01); a session
  without a tty sees it in the hook output after.
- The holder is identified as `<repo dir name> <branch>`, with `(detached)` for a detached HEAD, read
  from a `<kind>.holder` file the holder writes after acquiring. It is best effort: a stale or missing
  file only degrades the message, never the lock.
- The command runs as a child with fd 9 closed, not via `exec` — a daemon the suite leaves behind must
  not inherit the lock (review). TERM/HUP/QUIT to the wrapper are passed on as TERM and the child is
  waited for; INT is not passed on, since Ctrl-C already reached the suite's process group.
- The holder's repo name comes from the parent of `--git-common-dir`, so a worktree at
  `~/worktrees/<repo>/<branch>` is named `<repo>`; outside git the branch shows as `-` (review).
- Follow-up: a suite that already passed on the exact same content is skipped — see
  `docs/design/2026-10-suite-queue-verified-skip.md`.
- 1b: resolved — 4 accepted, 0 rejected, 1 human (R01: tty-else-stderr, recommended).
- 2b: resolved — 3 accepted, 0 rejected, 1 human (F03: 1 s sampling is enough at the hook level; exact
  non-overlap is criterion 1's job).

## 6. Acceptance criteria

1. **Serializes one kind across repos.** For each kind (`ruby`, `js`), with a run holding the slot from
   one repo directory, a second run from a different repo directory starts its command only after the
   first exits (start/end timestamps prove no overlap).
2. **Kinds are independent.** Concurrent `ruby` and `js` runs overlap.
3. **Exit status propagates.** `suite-queue js true` exits 0; `suite-queue js sh -c 'exit 3'` exits 3.
4. **Arguments survive.** An argument containing spaces or `$` reaches the command byte-for-byte.
5. **Wait message.** A run that finds its slot busy prints exactly one `suite-queue: waiting for <kind>
   slot (held by <repo> <branch> since <HH:MM>)` line before it waits — to `/dev/tty` when one can be
   opened, otherwise to stderr; never both. An uncontended run prints nothing. A detached holder shows
   `(detached)`.
6. **Timeout.** With `SUITE_QUEUE_TIMEOUT=1` and the slot held, the waiter exits 75 with a message naming
   the kind, and its command never runs.
7. **Bad timeout.** `SUITE_QUEUE_TIMEOUT` set to `0`, `-5` or `abc` exits 64 and runs nothing.
8. **Killed holder frees the slot.** After `kill -9` of the holder, a waiter starts within 2 s.
9. **Usage errors.** An unknown kind, or no command, exits 64 with usage on stderr and runs nothing.
10. **Missing holder file.** If `<kind>.holder` is missing or unreadable, the wait message still prints
    with `held by unknown`, and the lock behaves normally.
11. **First run.** With `~/.cache/suite-queue` absent, an uncontended run creates it and runs the command.
12. **Installed.** After `install.sh`, `command -v suite-queue` resolves to `~/.local/bin/suite-queue`, a
    link into this repo.
13. **Hooks queue for real.** In each repo, two concurrent `lefthook run pre-push --force` runs (from two
    worktrees, or one repo against another) show each queued suite running one at a time; with no tty,
    the waiting hook's output contains the wait line.
14. **Fallback.** With `suite-queue` removed from PATH, each repo's `lefthook run pre-push --force`
    still passes.
15. **Capped.** During a Jest repo's pre-push, at most 2 Jest worker processes exist per run; the
    Vitest repo's suite runs with at most 2 workers.
16. **No re-run on failure.** With a deliberately failing suite, the pre-push fails and runs the suite
    exactly once, whether or not `suite-queue` is on PATH.
17. **Docs travel.** Each PR updates the docs that describe its pre-push hooks, and the dotfiles README
    lists `suite-queue`.

## 8. Acceptance criteria (security)

18. **Holder text is sanitized.** A holder file containing an ESC sequence prints with every
    non-printable character removed.
19. **Private lock dir.** `~/.cache/suite-queue` is created with mode 700.
