---
description: Squash-merge the current branch's PR, delete its remote and local branch, remove its worktree and fast-forward main. Use when the user asks to merge the PR, ship it, or close out the work in this worktree.
allowed-tools: Bash(ship)
---

You are closing out this worktree's work. `ship` (in `git/bin/`, on PATH) does all of it and
proves each delete safe before making it; your job is to run it and relay what it says.

1. Run `ship` once, as a plain command from the worktree root. No arguments.
2. If it refuses or fails, report its reason verbatim and stop. Do not work around it: no
   `gh pr merge`, `git push --delete`, `branch -D` or `worktree remove --force` by hand, and do
   not fix the cause (rebase, push, commit) unless the user then asks for that.
3. If it succeeds, report the merge commit it printed and any warning (main not updated). If
   the `jira-backlog` reminder fired, follow it now (its `gh pr view` when it gives one, then
   the move to Done): that is the one thing allowed after the merge. Then say the worktree is gone, so this session has nowhere left to work and should end now — the
   next piece of work gets a new session.
