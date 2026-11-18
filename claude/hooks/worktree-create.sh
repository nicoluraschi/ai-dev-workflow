#!/usr/bin/env bash
# WorktreeCreate hook for Claude Code
# Places every new worktree at:  ~/worktrees/<repo>/<branch>
#
# This hook REPLACES Claude Code's default worktree creation, so it must:
#   - create the worktree itself, and
#   - print the absolute worktree path (and NOTHING else) to stdout.
# Everything else goes to stderr. A non-zero exit aborts creation.
#
# Input (JSON on stdin), e.g.:
#   { "hook_event_name": "WorktreeCreate", "cwd": "<project-root>",
#     "name": "<worktree-name>", "branch_name": "<branch>", "upstream": "<ref>" }
set -euo pipefail

INPUT=$(cat)   # stdin can only be read once

command -v jq >/dev/null || { echo "worktree-create: jq is required" >&2; exit 1; }

CWD=$(echo "$INPUT"    | jq -r '.cwd // empty')
NAME=$(echo "$INPUT"   | jq -r '.name // empty')
BRANCH=$(echo "$INPUT" | jq -r '.branch_name // empty')
[ -n "$CWD" ] || CWD="$PWD"

# The branch drives the folder nesting: "feat/card-accents" -> .../feat/card-accents.
# Fall back to the worktree name if no branch was provided.
[ -n "$BRANCH" ] || BRANCH="$NAME"
[ -n "$BRANCH" ] || { echo "worktree-create: no branch or name in payload" >&2; exit 1; }

# Resolve the MAIN repo root even if we're invoked from inside another worktree,
# so <repo> is always the real repository name.
COMMON=$(git -C "$CWD" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ -n "$COMMON" ]; then
  MAIN_ROOT=$(dirname "$COMMON")   # strips the trailing /.git
else
  MAIN_ROOT="$CWD"
fi
REPO=$(basename "$MAIN_ROOT")

DEST="$HOME/worktrees/$REPO/$BRANCH"
mkdir -p "$(dirname "$DEST")"

# Create the worktree. New branches are based on the current HEAD of $CWD, which
# mirrors Claude's in-session "branch from current" behaviour. To base new
# branches on the remote default instead, fetch first and use origin/HEAD as the
# start point on the `-b` line below.
if git -C "$CWD" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git -C "$CWD" worktree add "$DEST" "$BRANCH" >&2
else
  git -C "$CWD" worktree add -b "$BRANCH" "$DEST" >&2
fi

# Because this hook replaces the default creation, .worktreeinclude is NOT
# processed. Copy any gitignored local config you need by hand here. Failures
# are warnings, never fatal (the worktree already exists at this point).
for f in .env.local .env.development.local .env.test.local; do
  if [ -f "$MAIN_ROOT/$f" ]; then
    cp "$MAIN_ROOT/$f" "$DEST/$f" \
      && echo "worktree-create: copied $f" >&2 \
      || echo "worktree-create: warning, failed to copy $f" >&2
  fi
done

# Copy existing node_modules into the new worktree (top-level, and one level deep, e.g.
# web/node_modules) so npm/jest/etc. work immediately instead of failing on the first
# `git push` (lefthook pre-push running a test suite that needs a package that was never
# installed here). A REAL copy, not a symlink: Next.js's Turbopack refuses to resolve a
# node_modules that's a symlink pointing outside the project root ("Symlink [project]/
# node_modules is invalid, it points out of the filesystem root"), which breaks `next dev`
# and `next build` outright. `cp -c` asks for a macOS APFS copy-on-write clone (instant, no extra disk usage);
# falls back to a plain recursive copy everywhere else (Linux, non-APFS). Skipped, not
# failed, if node_modules doesn't exist yet, is already there, or the copy fails.
for NM in "$MAIN_ROOT/node_modules" "$MAIN_ROOT"/*/node_modules; do
  [ -d "$NM" ] || continue
  REL="${NM#"$MAIN_ROOT"/}"
  TARGET="$DEST/$REL"
  if [ -e "$TARGET" ]; then
    continue
  fi
  mkdir -p "$(dirname "$TARGET")" 2>/dev/null || true
  if cp -Rc "$NM" "$TARGET" 2>/dev/null || cp -R "$NM" "$TARGET" 2>/dev/null; then
    echo "worktree-create: copied $REL from the main checkout" >&2
  else
    echo "worktree-create: warning, failed to copy $REL" >&2
    continue
  fi
  # The main checkout is pulled but rarely reinstalled, so the copy can predate the lockfile
  # (a package added last week is simply missing). `npm ls --depth=0` catches a missing or
  # mismatched top-level package; then reinstall from the lockfile. Never fatal.
  PKG_DIR=$(dirname "$TARGET")
  if [ -f "$PKG_DIR/package-lock.json" ] && ! (cd "$PKG_DIR" && npm ls --depth=0 >/dev/null 2>&1); then
    echo "worktree-create: $REL is behind the lockfile, running npm ci" >&2
    (cd "$PKG_DIR" && npm ci --no-audit --no-fund >&2) \
      || echo "worktree-create: warning, npm ci failed in $REL" >&2
  fi
done

# Extension point: project setup, output to stderr so it doesn't touch the path:
#   ( cd "$DEST" && bundle install && bin/rails db:prepare ) >&2

# The contract: print ONLY the worktree path to stdout.
echo "$DEST"
