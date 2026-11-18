#!/usr/bin/env zsh
#
# test_zed.zsh — tests for the zw worktree opener.
#
# Run:  zsh shell/test_zed.zsh
#
# Seams: ZW_ROOT relocates ~/worktrees onto a fixture tree, and ZW_DRY_RUN
# makes zw print "open <path>" instead of launching Zed — so the resolution
# rules are testable without a worktree or a GUI.

emulate -L zsh
setopt no_unset

HERE="${0:A:h}"
source "$HERE/zed.zsh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

typeset -g pass=0 fail=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    (( pass++ )); printf '  ok   %s\n' "$label"
  else
    (( fail++ ))
    printf '  FAIL %s\n       expected: %s\n       actual:   %s\n' "$label" "$expected" "$actual"
  fi
}

check_status() {
  local label="$1" expected="$2"; shift 2
  "$@" >/dev/null 2>&1 && local actual=0 || local actual=$?
  check "$label" "$expected" "$actual"
}

# A worktree is a directory holding a .git entry — git writes a .git FILE in a
# linked worktree, so that is what marks a leaf regardless of nesting depth.
worktree() { mkdir -p "$TMP/$1" && touch "$TMP/$1/.git"; }

export ZW_ROOT="$TMP" ZW_DRY_RUN=1

worktree webapp/feat/add-widget
worktree webapp/fix/slow-request-timeout
worktree webapp/docs/readme-images
worktree app/feat/book-navigation
worktree api/chore/migration-safety-rule   # the only one for this repo

echo "== opening =="
check "repo + branch"             "open $TMP/webapp/feat/add-widget"        "$(zw webapp feat/add-widget)"
check "a repo with one worktree needs no branch" \
                                  "open $TMP/api/chore/migration-safety-rule" "$(zw api)"
check "branch path with no slash still resolves" \
                                  "open $TMP/app/feat/book-navigation" "$(zw app feat/book-navigation)"

echo "== listing =="
check "no arguments lists the repos" \
  "api
app
webapp" "$(zw)"
check "an ambiguous repo lists its worktrees" \
  "docs/readme-images
feat/add-widget
fix/slow-request-timeout" "$(zw webapp)"

echo "== a repo with no worktrees left =="
# Real state after `git worktree remove` takes the last one: the repo directory
# survives, empty. zsh splits empty output into a ONE-element array holding "",
# so this was being misread as "exactly one worktree" and opening "<repo>/".
mkdir -p "$TMP/emptyrepo"
check "stdout stays empty"  ""  "$(zw emptyrepo 2>/dev/null)"
check_status "exits non-zero"  1  zw emptyrepo
# The real defect was the MESSAGE: an empty list became branch="" and the user
# was told "<root>/emptyrepo/ is not a worktree" — a path with a stray trailing
# slash that never existed. Assert what it says, not just that it failed.
check "says the repo has no worktrees, not that <repo>/ is not one" \
  "zw: no worktrees under emptyrepo"  "$(zw emptyrepo 2>&1 >/dev/null)"
mkdir -p "$TMP/onlyjunk/notaworktree"
check "a repo dir whose children are not worktrees is the same case" \
  "zw: no worktrees under onlyjunk"   "$(zw onlyjunk 2>&1 >/dev/null)"

echo "== failure modes =="
check_status "an ambiguous repo is not an error, it lists"  0 zw webapp
check_status "unknown repo -> non-zero"                     1 zw nosuchrepo
check_status "unknown branch -> non-zero"                   1 zw webapp feat/nope
check_status "a path that exists but is not a worktree"     1 zw webapp feat

echo "== completion =="
check "_zw_repos"     "api app emptyrepo onlyjunk webapp" "$(_zw_repos | tr '\n' ' ' | sed 's/ $//')"
check "_zw_branches"  "docs/readme-images feat/add-widget fix/slow-request-timeout" \
                      "$(_zw_branches webapp | tr '\n' ' ' | sed 's/ $//')"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
(( fail == 0 ))
