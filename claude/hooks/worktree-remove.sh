#!/usr/bin/env bash
# WorktreeRemove hook for Claude Code
# Cleans up a worktree created by worktree-create.sh. Because we replaced the
# default creation, we also own removal here.
#
# Input (JSON on stdin), e.g.:
#   { "hook_event_name": "WorktreeRemove", "cwd": "<project-root>",
#     "worktree_path": "<absolute-path>" }
# All output goes to stderr. This hook never hard-fails the session.
set -uo pipefail

INPUT=$(cat)

command -v jq >/dev/null || { echo "worktree-remove: jq is required" >&2; exit 0; }

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
WT=$(echo "$INPUT"  | jq -r '.worktree_path // empty')
[ -n "$WT" ]  || { echo "worktree-remove: no worktree_path in payload" >&2; exit 0; }
[ -n "$CWD" ] || CWD="$PWD"

# Extension point: tear down per-worktree resources here (e.g. drop a DB whose
# name you derived from the branch in worktree-create.sh), output to stderr.

# Remove the worktree, tolerating it already being gone (idempotent).
if git -C "$CWD" worktree remove "$WT" 2>/dev/null \
   || git -C "$CWD" worktree remove --force "$WT" 2>/dev/null; then
  echo "worktree-remove: removed $WT" >&2
else
  echo "worktree-remove: $WT already gone or not a worktree" >&2
fi

# Tidy now-empty parent dirs (e.g. a leftover ~/worktrees/<repo>/feat/), never fatal.
rmdir -p "$(dirname "$WT")" 2>/dev/null || true

exit 0
