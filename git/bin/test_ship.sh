#!/usr/bin/env bash
#
# test_ship.sh — tests for ship.
#
# Run:  bash git/bin/test_ship.sh
#
# Each case builds a bare origin, a main checkout and a linked worktree on
# branch feat, all under a temp dir. A fake gh on PATH stands in for GitHub:
# `pr view` prints $TMP/pr.json (plus mergeCommit once merged), and
# `pr merge` squashes origin/feat onto origin/main through a scratch clone,
# the way GitHub would. FAKE_GH_DRIFT=1 makes that squash add an extra file,
# so the merged tree no longer matches the branch.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$HERE/ship"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TMP="$(cd "$TMP" && pwd -P)"

export HOME="$TMP/home"
export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME" "$TMP/bin"

pass=0; fail=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$label"
  else
    fail=$((fail + 1))
    printf '  FAIL %s\n       expected: %s\n       actual:   %s\n' "$label" "$expected" "$actual"
  fi
}

yesno() { "$@" >/dev/null 2>&1 && echo yes || echo no; }

# --- fake gh ---------------------------------------------------------------
cat > "$TMP/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$FAKE_GH_DIR/calls"
case "$1 $2" in
  "pr view")
    merged=""; [[ -s "$FAKE_GH_DIR/merged" && "${FAKE_GH_NO_MERGE_COMMIT:-0}" != 1 ]] && merged="$(cat "$FAKE_GH_DIR/merged")"
    jq --arg m "$merged" 'if $m == "" then . else . + {mergeCommit: {oid: $m}} end' "$FAKE_GH_DIR/pr.json"
    ;;
  "pr merge")
    [[ "${FAKE_GH_MERGE_FAIL:-0}" == 1 ]] && { echo "fake gh: merge refused" >&2; exit 1; }
    branch="$(git branch --show-current)"
    origin="$(git remote get-url origin)"
    rm -rf "$FAKE_GH_DIR/squash"
    git clone -q -b main "$origin" "$FAKE_GH_DIR/squash"
    git -C "$FAKE_GH_DIR/squash" merge -q --squash "origin/$branch" >/dev/null
    [[ "${FAKE_GH_DRIFT:-0}" == 1 ]] && { echo drift > "$FAKE_GH_DIR/squash/drift.txt"; git -C "$FAKE_GH_DIR/squash" add drift.txt; }
    git -C "$FAKE_GH_DIR/squash" commit -q -m "feat (#1)"
    git -C "$FAKE_GH_DIR/squash" push -q origin main
    git -C "$FAKE_GH_DIR/squash" rev-parse HEAD > "$FAKE_GH_DIR/merged"
    [[ "${FAKE_GH_AUTODELETE:-0}" == 1 ]] && git -C "$FAKE_GH_DIR/squash" push -q origin --delete "$branch"
    true
    ;;
  *) echo "fake gh: unexpected $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$TMP/bin/gh"
export PATH="$TMP/bin:$PATH"
export FAKE_GH_DIR="$TMP/gh"

# --- fixture ---------------------------------------------------------------
# A fresh origin, main checkout and worktree for each case. pr.json describes an
# open, mergeable PR with no checks whose head is the worktree's HEAD.
setup() {
  rm -rf "$TMP/origin.git" "$TMP/main" "$TMP/worktrees" "$FAKE_GH_DIR"
  mkdir -p "$FAKE_GH_DIR"
  git init -q --bare -b main "$TMP/origin.git"
  git clone -q "$TMP/origin.git" "$TMP/main" 2>/dev/null
  git -C "$TMP/main" checkout -q -b main
  echo base > "$TMP/main/a.txt"
  git -C "$TMP/main" add a.txt; git -C "$TMP/main" commit -q -m base
  git -C "$TMP/main" push -q -u origin main
  WT="$TMP/worktrees/repo/feat"
  git -C "$TMP/main" worktree add -q -b feat "$WT"
  echo change > "$WT/b.txt"
  git -C "$WT" add b.txt; git -C "$WT" commit -q -m change
  git -C "$WT" push -q -u origin feat
  pr_json '.'
}

# Rewrite pr.json from the default through a jq filter.
pr_json() {
  jq -n --arg h "$(git -C "$WT" rev-parse HEAD)" \
    "{number: 1, state: \"OPEN\", isDraft: false, mergeable: \"MERGEABLE\", headRefOid: \$h, statusCheckRollup: []} | $1" \
    > "$FAKE_GH_DIR/pr.json"
}

run_ship() { (cd "$WT" && "$SUT" >"$TMP/out" 2>"$TMP/err"); echo $? > "$TMP/status"; }

merged_called() { grep -q "^pr merge" "$FAKE_GH_DIR/calls" 2>/dev/null && echo yes || echo no; }

# A refusal before the merge: non-zero, reason on stderr, nothing merged or deleted.
refused_before_merge() {
  local label="$1" reason="$2"
  run_ship
  check "$label: non-zero exit" "yes" "$([[ "$(cat "$TMP/status")" != 0 ]] && echo yes || echo no)"
  check "$label: says why" "yes" "$(yesno grep -q -i "$reason" "$TMP/err")"
  check "$label: gh pr merge not called" "no" "$(merged_called)"
  check "$label: worktree kept" "yes" "$([[ -d "$WT" ]] && echo yes || echo no)"
  check "$label: remote branch kept" "yes" "$(yesno git -C "$TMP/main" ls-remote --exit-code origin refs/heads/feat)"
}

# --- cases -----------------------------------------------------------------
echo "== happy path =="
setup
head="$(git -C "$WT" rev-parse HEAD)"
run_ship
merge="$(cat "$FAKE_GH_DIR/merged" 2>/dev/null)"
check "exit 0" "0" "$(cat "$TMP/status")"
check "squash-merged with the verified head" "pr merge 1 --squash --match-head-commit $head" "$(grep '^pr merge' "$FAKE_GH_DIR/calls" 2>/dev/null)"
check "reports the merge commit" "yes" "$(yesno grep -q "${merge:-nomerge}" "$TMP/out")"
check "remote branch deleted" "no" "$(yesno git -C "$TMP/main" ls-remote --exit-code origin refs/heads/feat)"
check "worktree removed" "no" "$([[ -d "$WT" ]] && echo yes || echo no)"
check "empty worktree parent dirs tidied" "no" "$([[ -d "$TMP/worktrees" ]] && echo yes || echo no)"
check "local branch deleted" "no" "$(yesno git -C "$TMP/main" rev-parse --verify -q refs/heads/feat)"
check "main checkout fast-forwarded to the merge commit" "${merge:-nomerge}" "$(git -C "$TMP/main" rev-parse HEAD)"

echo "== refusals before the merge =="
setup; echo dirty >> "$WT/b.txt"
refused_before_merge "modified file" "uncommitted"
setup; echo new > "$WT/c.txt"
refused_before_merge "untracked file" "uncommitted"
setup; echo more > "$WT/c.txt"; git -C "$WT" add c.txt; git -C "$WT" commit -q -m more
refused_before_merge "unpushed commit" "push first"
setup
echo moved > "$TMP/main/d.txt"; git -C "$TMP/main" add d.txt; git -C "$TMP/main" commit -q -m moved; git -C "$TMP/main" push -q origin main
refused_before_merge "branch behind origin/main" "rebase"
setup; pr_json '.headRefOid = "0000000000000000000000000000000000000000"'
refused_before_merge "PR head differs from HEAD" "PR head"
setup; pr_json '.isDraft = true'
refused_before_merge "draft PR" "draft"
setup; pr_json '.state = "CLOSED"'
refused_before_merge "PR not open" "CLOSED"
setup; pr_json '.mergeable = "CONFLICTING"'
refused_before_merge "conflicting PR" "CONFLICTING"
setup; pr_json '.statusCheckRollup = [{name: "test", conclusion: "FAILURE"}]'
refused_before_merge "failing check" "test: FAILURE"
setup; pr_json '.statusCheckRollup = [{name: "test", status: "IN_PROGRESS", conclusion: ""}]'
refused_before_merge "pending check run" "test: PENDING"
setup; pr_json '.statusCheckRollup = [{context: "ci/legacy", state: "PENDING"}]'
refused_before_merge "pending status context" "ci/legacy: PENDING"
setup; git -C "$TMP/main" checkout -q -b feat2; WT="$TMP/main"
refused_before_merge "main checkout instead of a worktree" "not the main checkout"
setup; git -C "$WT" checkout -q --detach; git -C "$TMP/main" checkout -q --detach; git -C "$WT" checkout -q main
refused_before_merge "on main" "on main"
setup; git -C "$WT" checkout -q --detach
refused_before_merge "detached HEAD" "detached"
setup; rm "$FAKE_GH_DIR/pr.json"
refused_before_merge "no PR for the branch" "no PR"

echo "== gh pr merge fails =="
setup
FAKE_GH_MERGE_FAIL=1 run_ship
check "non-zero exit" "yes" "$([[ "$(cat "$TMP/status")" != 0 ]] && echo yes || echo no)"
check "says the merge failed" "yes" "$(yesno grep -q -i "gh pr merge failed" "$TMP/err")"
check "worktree kept" "yes" "$([[ -d "$WT" ]] && echo yes || echo no)"
check "remote branch kept" "yes" "$(yesno git -C "$TMP/main" ls-remote --exit-code origin refs/heads/feat)"

echo "== passing checks are green =="
setup; pr_json '.statusCheckRollup = [{name: "a", conclusion: "SUCCESS"}, {name: "b", conclusion: "SKIPPED"}, {name: "c", conclusion: "NEUTRAL"}, {context: "d", state: "SUCCESS"}]'
run_ship
check "success, skipped, neutral checks: shipped" "0" "$(cat "$TMP/status")"

echo "== null check rollup is no checks =="
setup; pr_json '.statusCheckRollup = null'
run_ship
check "statusCheckRollup null: shipped" "0" "$(cat "$TMP/status")"

echo "== GitHub already deleted the head branch =="
setup
FAKE_GH_AUTODELETE=1 run_ship
check "exit 0" "0" "$(cat "$TMP/status")"
check "worktree removed" "no" "$([[ -d "$WT" ]] && echo yes || echo no)"
check "local branch deleted" "no" "$(yesno git -C "$TMP/main" rev-parse --verify -q refs/heads/feat)"

echo "== GitHub reports no merge commit =="
setup
FAKE_GH_NO_MERGE_COMMIT=1 run_ship
check "non-zero exit" "yes" "$([[ "$(cat "$TMP/status")" != 0 ]] && echo yes || echo no)"
check "says no merge commit was reported" "yes" "$(yesno grep -q -i "no merge commit" "$TMP/err")"
check "worktree kept" "yes" "$([[ -d "$WT" ]] && echo yes || echo no)"
check "remote branch kept" "yes" "$(yesno git -C "$TMP/main" ls-remote --exit-code origin refs/heads/feat)"

echo "== merged tree differs from the branch =="
setup
FAKE_GH_DRIFT=1 run_ship
check "non-zero exit" "yes" "$([[ "$(cat "$TMP/status")" != 0 ]] && echo yes || echo no)"
check "says the tree differs" "yes" "$(yesno grep -q -i "tree differs" "$TMP/err")"
check "worktree kept" "yes" "$([[ -d "$WT" ]] && echo yes || echo no)"
check "local branch kept" "yes" "$(yesno git -C "$TMP/main" rev-parse --verify -q refs/heads/feat)"
check "remote branch kept" "yes" "$(yesno git -C "$TMP/main" ls-remote --exit-code origin refs/heads/feat)"

echo "== main checkout not on main =="
setup; git -C "$TMP/main" checkout -q -b other
run_ship
check "exit 0" "0" "$(cat "$TMP/status")"
check "warns that main was not updated" "yes" "$(yesno grep -q -i "main not updated" "$TMP/err")"
check "main checkout left on its branch" "other" "$(git -C "$TMP/main" branch --show-current)"
check "worktree still removed" "no" "$([[ -d "$WT" ]] && echo yes || echo no)"
check "local branch still deleted" "no" "$(yesno git -C "$TMP/main" rev-parse --verify -q refs/heads/feat)"

echo "== fast-forward of main fails =="
setup; echo blocker > "$TMP/main/b.txt"
run_ship
check "exit 0" "0" "$(cat "$TMP/status")"
check "warns that main was not updated" "yes" "$(yesno grep -q -i "fast-forward failed, main not updated" "$TMP/err")"
check "worktree still removed" "no" "$([[ -d "$WT" ]] && echo yes || echo no)"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
