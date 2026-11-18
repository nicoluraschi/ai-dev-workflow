---
description: Show what is in flight — your open PRs across repos and every worktree under ~/worktrees, with the stale ones marked. Use when the user asks what is open, in flight or pending, or which worktrees can be cleaned up.
allowed-tools: Bash(inflight)
---

`inflight` (in `git/bin/`, on PATH) builds the whole report and changes nothing; your job is to
run it and relay what it says.

1. Run `inflight` once, as a plain command. No arguments.
2. Relay its output as-is. Then, in one line, name the STALE worktrees with no
   "check before removing" note: those are safe to clear. A stale one with the note needs the
   user to look first, for the reason it gives.
3. Do not remove, merge, push or close anything, and do not run follow-up git or gh commands.
   Cleaning up is the user's call: `/ship` from a worktree whose PR is open, or
   `git worktree remove` by the user for one already merged.
