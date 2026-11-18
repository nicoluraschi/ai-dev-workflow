#!/usr/bin/env bash
#
# test_codex_audit.sh — tests for the codex-audit wrapper.
#
# Run:  bash codex/bin/test_codex_audit.sh
#
# Codex is stubbed on PATH, so no review is ever sent and no quota is spent. The stub
# reproduces the parts of the real CLI the wrapper depends on: `login status`, `--version`,
# the `thread.started` JSONL event, and `-o <file>` for the final message.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$HERE/codex-audit"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Every gate the wrapper finishes appends to the scorecard log. Point it at a temp file before
# anything runs, or this suite would write fixture gates into the real ~/.claude/gate-log.jsonl.
export GATE_LOG="$TMP/gate-log.jsonl"

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
check_contains() {
  local label="$1" needle="$2" file="$3"
  if grep -qF -- "$needle" "$file" 2>/dev/null; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$label"
  else
    fail=$((fail + 1)); printf '  FAIL %s\n       %s not found in %s\n' "$label" "$needle" "$file"
  fi
}
check_absent() {
  local label="$1" needle="$2" file="$3"
  if grep -qF -- "$needle" "$file" 2>/dev/null; then
    fail=$((fail + 1)); printf '  FAIL %s\n       %s unexpectedly present\n' "$label" "$needle"
  else
    pass=$((pass + 1)); printf '  ok   %s\n' "$label"
  fi
}
# Golden-file comparison. The fixture repo lives under a fresh `mktemp` root on every run, so
# both sides are normalised first -- without it a committed golden can never match (2b R01).
# $TMPDIR is behind a symlink on macOS (/var -> /private/var), so `mktemp -d` hands back a
# LOGICAL path while the wrapper writes the PHYSICAL one into the prompt. Normalising only the
# logical form leaves a "/private" prefix frozen into the golden, which then fails on any host
# where the two coincide. Each physical form is substituted before its logical counterpart, and
# $REPO before $TMP because $REPO lives inside it.
normalise_prompt() {
  local rphys tphys
  rphys="$(cd "$REPO" && pwd -P)"
  tphys="$(cd "$TMP"  && pwd -P)"
  sed -e "s|$rphys|{{REPO}}|g" -e "s|$REPO|{{REPO}}|g" \
      -e "s|$tphys|{{TMP}}|g"  -e "s|$TMP|{{TMP}}|g" "$1"
}
check_golden() {
  local label="$1" golden="$2" actual="$3"
  if [[ -n "${UPDATE_GOLDEN:-}" ]]; then cp "$actual" "$golden"; fi
  if diff -q "$golden" "$actual" >/dev/null 2>&1; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$label"
  else
    fail=$((fail + 1)); printf '  FAIL %s\n' "$label"
    diff "$golden" "$actual" 2>&1 | head -15 | sed 's/^/       /'
  fi
}

# --- the Codex stub --------------------------------------------------------
mkdir -p "$TMP/bin"
cat > "$TMP/bin/codex" <<'STUB'
#!/usr/bin/env bash
case "${1:-}" in
  login)     exit "${FAKE_CODEX_LOGIN_EXIT:-0}" ;;
  --version) echo "codex-cli 0.152.0-stub"; exit 0 ;;
esac
[[ "${1:-}" == "exec" ]] || { echo "stub: unexpected: $*" >&2; exit 64; }
[[ -n "${FAKE_CODEX_EXIT:-}" ]] && exit "$FAKE_CODEX_EXIT"
out=""; prev=""
for a in "$@"; do
  [[ "$prev" == "-o" || "$prev" == "--output-last-message" ]] && out="$a"
  prev="$a"
done
echo "$*" > "$TMP_ARGV_FILE"
for a in "$@"; do
  case "$a" in
    -*|exec|resume) ;;
    *) [[ ${#a} -gt 200 ]] && printf '%s' "$a" > "$TMP_PROMPT_FILE" ;;
  esac
done
echo '{"type":"thread.started","thread_id":"stub-thread-0001"}'
echo '{"type":"turn.started"}'
[[ -n "$out" ]] && cp "$FAKE_CODEX_MESSAGE" "$out"
echo '{"type":"turn.completed"}'
exit 0
STUB
chmod +x "$TMP/bin/codex"
export PATH="$TMP/bin:$PATH"
export TMP_ARGV_FILE="$TMP/argv.txt"
export TMP_PROMPT_FILE="$TMP/prompt.txt"

# --- a fixture repository --------------------------------------------------
REPO="$TMP/acme"
mkdir -p "$REPO/docs/specs/plans"
git -C "$REPO" init -q 2>/dev/null || { echo "cannot init fixture repo"; exit 1; }
git -C "$REPO" config user.email t@example.com
git -C "$REPO" config user.name test
echo '# Thing — spec'     > "$REPO/docs/specs/2026-09-thing.md"
echo '# template'         > "$REPO/docs/specs/_template.md"
# The fixture plan reproduces the shape the scoped gate has to read: a delivery table whose
# ranges are written with EN DASHES (as real plans are), and a numbered task list in which each
# task names the criteria it carries.
cat > "$REPO/docs/specs/plans/2026-09-thing.md" <<'PLAN'
# Thing — plan

| PR | Branch | Tasks | State |
|---|---|---|---|
| 1 | `feat/thing-one` | 1–3 | merged |
| 2 | `feat/thing-two` | 4–8, 10 and 11 | in progress |
| 3 | *(not opened)* | 9 | not started |

## Order of work

1. Config. AC-1, AC-2.
2. The model. AC-3.
3. Registration. AC-4…6.
4. The mailer. AC-11, AC-31.
5. Reset request. AC-12.
6. The change service. AC-22.
7. The changed mailer. AC-37, AC-38.
8. Reset verification. AC-13.
9. The account surface. AC-25…28.
10. Observability. AC-39.
11. Sweeps. AC-24, AC-41.
PLAN
git -C "$REPO" add -A
git -C "$REPO" commit -qm init

PROFILE="$REPO/docs/ai-profile.md"
# The baseline profile authorizes the outbound review. Without one the wrapper refuses to
# send anything — see the "consent" block below, which is the point of the default.
base_profile() {
  cat > "$PROFILE" <<'EOF'
---
artifacts: docs/specs
codex_reviewer: yes
gates: 1b,2b,6b
---
EOF
}
base_profile

cat > "$TMP/with-findings.md" <<'EOF'
## BLOCKER

### 1b-F01 — criterion 3 passes without the feature
- evidence: docs/specs/2026-09-thing.md §6
- failure path: the assertion is on the writer, never the reader
- smallest fix: assert at the consuming layer

## MAJOR

### 1b-F02 — no criterion for the empty case
- evidence: §6
- failure path: empty renders a raw error
- smallest fix: add a criterion

## MINOR

- the title could be shorter
EOF

cat > "$TMP/no-findings.md" <<'EOF'
## BLOCKER

None.

## MAJOR

None.
EOF

cat > "$TMP/round2.md" <<'EOF'
## Verdicts

| id | round-1 severity | response | verdict | note |
|---|---|---|---|---|
| 1b-F01 | BLOCKER | accepted | resolved | the criterion now asserts at the reader |
| 1b-F02 | MAJOR | rejected | maintain | the empty case occurs on a filtered list |

## Regressions

### R01 — the new criterion has no fixture (from 1b-F01)
- evidence: §6
- failure path: the test cannot be written as specified
- smallest fix: add the fixture
EOF

cat > "$TMP/response.md" <<'EOF'
| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | BLOCKER | accepted | criterion 3 rewritten |
| 1b-F02 | MAJOR | rejected | the empty case cannot occur |
EOF

export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"
# Ledgers live in the git common dir, never in the tracked tree.
LD="$REPO/.git/codex-audit"
LEDGER="$LD/2026-09-thing-1b.md"
run() { ( cd "$REPO" && "$WRAPPER" "$@" >"$TMP/out.log" 2>"$TMP/err.log" ); echo $?; }
reset_reviews() { rm -rf "$LD"; }

echo "== usage and preconditions =="
check "no arguments is a usage error"      2 "$(run)"
check "unknown gate is a usage error"      2 "$(run 9z)"
check "6b round 2 is refused in Phase 1"   1 "$(run 6b --round 2)"
check "missing spec is an error"           1 "$(run 1b --slug nope)"
check "round 2 without --response errors"  1 "$(run 1b --slug 2026-09-thing --round 2 --response /nope)"

echo "== consent: nothing leaves without an explicit decision =="
reset_reviews
rm -f "$PROFILE"
check "no profile at all does not send the artifact" 3 "$(run 1b --slug 2026-09-thing)"
check_contains "refusal is recorded as a skip" "outbound review not authorized" "$LEDGER"
check_absent   "and no review was run"         "## Round 1" "$LEDGER"
check_contains "the message says how to authorize" "codex_reviewer: yes" "$TMP/err.log"

reset_reviews
cat > "$PROFILE" <<'EOF'
---
artifacts: docs/specs
gates: 1b,2b
---
EOF
check "a profile that omits codex_reviewer still refuses" 3 "$(run 1b --slug 2026-09-thing)"
check_contains "unset is not read as yes" "codex_reviewer is unset" "$LEDGER"

reset_reviews
cat > "$PROFILE" <<'EOF'
---
artifacts: docs/specs
codex_reviewer: no
gates: 1b,2b
---
EOF
check "an explicit no is distinguished from unset" 3 "$(run 1b --slug 2026-09-thing)"
check_contains "explicit refusal recorded" "reviewer disabled by profile" "$LEDGER"
base_profile

echo "== gate 1b, round 1 =="
reset_reviews
check "round 1 succeeds" 0 "$(run 1b --slug 2026-09-thing)"
check_contains "ledger written"            "# Gate 1b — 2026-09-thing" "$LEDGER"
check_contains "thread id recorded"        "<!-- thread_id: stub-thread-0001 -->" "$LEDGER"
check_contains "cwd recorded for resume"   "<!-- cwd: $REPO -->" "$LEDGER"
check_contains "rounds start at 1"         "- **rounds:** 1" "$LEDGER"
check_contains "codex output is verbatim"  "### 1b-F01 — criterion 3 passes without the feature" "$LEDGER"
check_contains "reviewer model recorded"   "codex-cli 0.152.0-stub" "$LEDGER"
check_absent   "home dir written as ~, not \\~" '\~' "$LEDGER"
check_absent   "no early-stop marker when findings exist" "- **outcome:** no BLOCKER/MAJOR" "$LEDGER"

echo "== prompt assembly =="
check_contains "contract is in the prompt"      "You are an independent reviewer." "$TMP_PROMPT_FILE"
check_contains "gate prompt is in the prompt"   "Gate 1b — critique the spec" "$TMP_PROMPT_FILE"
check_contains "spec path substituted"          "$REPO/docs/specs/2026-09-thing.md" "$TMP_PROMPT_FILE"
check_contains "gate id substituted"            "1b-F<nn>" "$TMP_PROMPT_FILE"
check_absent   "placeholders all resolved"      "{{" "$TMP_PROMPT_FILE"
check_absent   "template HTML comments stripped" "<!--" "$TMP_PROMPT_FILE"
check_contains "read-only audit profile used"   "-p audit" "$TMP_ARGV_FILE"

echo "== the unscoped 6b prompt is frozen (AC3) =="
# A characterization guard: it passes the moment it is written, by construction. Its job is to
# go red when `{{TASKS_SCOPE}}` is added to the template, proving the scoped instructions leave
# no bytes behind in an unscoped run.
# No reset_reviews here: 6b writes its own ledger, and wiping the directory would take the
# round-1 1b ledger that the round-2 tests below depend on.
run 6b --slug 2026-09-thing >/dev/null
normalise_prompt "$TMP_PROMPT_FILE" > "$TMP/6b.actual"
check_golden "unscoped 6b prompt matches the committed golden" "$HERE/test_6b_prompt.golden" "$TMP/6b.actual"

echo "== response table must answer every finding =="
cat > "$TMP/incomplete.md" <<'EOF'
| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | BLOCKER | accepted | rewritten |
EOF
check "a finding left unanswered blocks round 2" 1 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/incomplete.md")"
check_contains "and says which" "1b-F02" "$TMP/err.log"

cat > "$TMP/invented.md" <<'EOF'
| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | BLOCKER | accepted | rewritten |
| 1b-F02 | MAJOR | rejected | cannot occur |
| 1b-F09 | MAJOR | accepted | invented |
EOF
check "answering a finding round 1 never raised blocks round 2" 1 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/invented.md")"
check_contains "and says which" "1b-F09" "$TMP/err.log"

echo "== malformed response tables fail LOUDLY, not silently =="
# Regression: these greps match nothing, and under set -e + pipefail that used to abort the
# script with exit 1 and no stderr at all — while the skill tells the caller exit 1 means
# "read the message".
printf 'no table here at all\n' > "$TMP/nolayout.md"
check "a response with no ids is rejected" 1 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/nolayout.md")"
check_contains "and explains which are unanswered" "1b-F01" "$TMP/err.log"

: > "$TMP/empty.md"
check "an empty response file is rejected" 1 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/empty.md")"
check_contains "and still explains why" "does not answer every round-1 finding" "$TMP/err.log"

cat > "$TMP/aslist.md" <<'EOF'
- 1b-F01: accepted, criterion rewritten
- 1b-F02: rejected, cannot occur
EOF
check "a response written as a list still validates ids" 0 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/aslist.md")"

# That round 2 appended to the ledger. Start from a clean round 1 so the metrics assertions
# below count this feature's findings and not the ones this section just appended.
reset_reviews
run 1b --slug 2026-09-thing >/dev/null

echo "== gate 1b, round 2 =="
export FAKE_CODEX_MESSAGE="$TMP/round2.md"
check "round 2 succeeds" 0 "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check_contains "response table appended"    "criterion 3 rewritten" "$LEDGER"
check_contains "round 2 section appended"   "## Round 2 — Codex, verbatim" "$LEDGER"
check_contains "round count bumped"         "- **rounds:** 2" "$LEDGER"
check_contains "round 2 resumed the thread" "resume" "$TMP_ARGV_FILE"
# The id is passed after `--` so it can never be read as a flag, however it was spelled.
check_contains "the thread id is passed after --" "-- stub-thread-0001" "$TMP_ARGV_FILE"
check_contains "round 2 re-applies read-only"   'sandbox_mode=read-only' "$TMP_ARGV_FILE"
check_contains "round 2 re-applies no-approval" 'approval_policy=never'  "$TMP_ARGV_FILE"
check_contains "round 2 prompt carries the response" "1b-F02 | MAJOR | rejected" "$TMP_PROMPT_FILE"

echo "== the human only sees what did not close =="
check_contains "For the human section written" "## For the human" "$LEDGER"
check_contains "a maintained finding is open"  "Codex maintains it" "$LEDGER"
check_contains "a regression is open"          "introduced by the fixes" "$LEDGER"
check_absent   "a resolved finding is not"     "1b-F01 | BLOCKER | Codex maintains it" "$LEDGER"
check_contains "metrics footer written"        "## Metrics" "$LEDGER"
check_contains "metrics count the round-1 findings" "| round-1 findings (BLOCKER+MAJOR) | 2 |" "$LEDGER"
check_contains "metrics count concede/maintain"     "| conceded / maintained | 0 / 1 |" "$LEDGER"
check_contains "metrics count regressions"          "| regressions found in round 2 | 1 |" "$LEDGER"
check_contains "metrics carry both rounds' clocks"  "| wall clock |" "$LEDGER"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

echo "== unparseable output is never recorded as clean =="
reset_reviews
cat > "$TMP/offformat.md" <<'EOF'
I reviewed the spec and found some things worth mentioning.

**1b-F01** criterion 3 passes without the feature.
EOF
export FAKE_CODEX_MESSAGE="$TMP/offformat.md"
check "an off-format review still succeeds" 0 "$(run 1b --slug 2026-09-thing)"
check_contains "but is marked UNPARSEABLE"   "- **outcome:** UNPARSEABLE" "$LEDGER"
check_absent   "and never claims it was clean" "no BLOCKER/MAJOR — round 2 not required" "$LEDGER"
check_contains "the warning reaches the caller" "does not follow the contract's format" "$TMP/err.log"
# The invariant is that unparseable output must never be treated as the §4.2 early stop
# (exit 4, "round 1 found nothing"). Exiting 1 here is correct and better: the response
# answers ids the ledger never recorded, because nothing was parsed out of it.
r2_status="$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check "round 2 after unparseable output is NOT an early stop" "not-4" \
  "$( [[ "$r2_status" == "4" ]] && echo "4" || echo "not-4" )"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

echo "== a real ledger is never clobbered by a skip =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
check_contains "round 1 recorded" "## Round 1" "$LEDGER"
check "a later skip exits 3" 3 "$(FAKE_CODEX_LOGIN_EXIT=1 run 1b --slug 2026-09-thing)"
check_contains "but the review survives" "### 1b-F01" "$LEDGER"
check_absent   "and was not replaced by a stub" "**skipped:**" "$LEDGER"

echo "== a crafted thread id cannot become a codex flag =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
awk '{ sub(/^<!-- thread_id: .* -->$/, "<!-- thread_id: --dangerously-bypass-approvals-and-sandbox -->"); print }' \
  "$LEDGER" > "$TMP/led.new" && mv "$TMP/led.new" "$LEDGER"
grep -v '^<!-- cwd:' "$LEDGER" > "$TMP/led.new" && mv "$TMP/led.new" "$LEDGER"
check "resume refuses a thread id that is really a flag" 1 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check_contains "and says why" "not a valid session id" "$TMP/err.log"

echo "== early stop (design §4.2) =="
reset_reviews
export FAKE_CODEX_MESSAGE="$TMP/no-findings.md"
check "round 1 with no findings still succeeds" 0 "$(run 1b --slug 2026-09-thing)"
check_contains "early stop recorded" "- **outcome:** no BLOCKER/MAJOR" "$LEDGER"
check "round 2 after a clean round 1 exits 4" 4 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check_absent "round 2 did not append" "## Round 2 — Codex, verbatim" "$LEDGER"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

echo "== gate 2b =="
reset_reviews
check "2b succeeds when the plan file exists" 0 "$(run 2b --slug 2026-09-thing)"
check_contains "2b reviews the plan, not the spec" \
  "$REPO/docs/specs/plans/2026-09-thing.md" "$LD/2026-09-thing-2b.md"
mv "$REPO/docs/specs/plans/2026-09-thing.md" "$TMP/plan.bak"
check "2b errors when the plan was never written to a file" 1 "$(run 2b --slug 2026-09-thing)"
mv "$TMP/plan.bak" "$REPO/docs/specs/plans/2026-09-thing.md"

echo "== slug defaulting =="
reset_reviews
touch "$REPO/docs/specs/2026-09-thing.md"
check "slug defaults to the newest spec" 0 "$(run 1b)"
check "_template is never chosen as the slug" "false" \
  "$( [[ -f "$LD/_template-1b.md" ]] && echo true || echo false )"

echo "== degradation (design §7) =="
reset_reviews
cat > "$PROFILE" <<'EOF'
---
artifacts: docs/specs
codex_reviewer: yes
gates: 2b
---
EOF
check "gate not enabled by profile exits 3" 3 "$(run 1b --slug 2026-09-thing)"
check_contains "disabled gate recorded" "gate 1b not enabled by profile" "$LEDGER"
base_profile

reset_reviews
check "unauthenticated Codex exits 3, not 1" 3 \
  "$(FAKE_CODEX_LOGIN_EXIT=1 run 1b --slug 2026-09-thing)"
check_contains "auth failure recorded" "Codex is not authenticated" "$LEDGER"

reset_reviews
check "a non-zero codex exit fails the gate" 1 "$(FAKE_CODEX_EXIT=7 run 1b --slug 2026-09-thing)"

echo "== external artifacts (acceptance criterion 2) =="
reset_reviews
mkdir -p "$TMP/external/specs"
cp "$REPO/docs/specs/2026-09-thing.md" "$TMP/external/specs/"
cat > "$PROFILE" <<EOF
---
artifacts: $TMP/external/specs
codex_reviewer: yes
gates: 1b,2b
---
EOF
check "external artifacts: gate runs" 0 "$(run 1b --slug 2026-09-thing)"
check "external artifacts: ledger written to the git common dir" "true" \
  "$( [[ -f "$LD/2026-09-thing-1b.md" ]] && echo true || echo false )"
check "external artifacts: nothing written into the repo's artifacts" "true" \
  "$( [[ ! -d "$REPO/docs/specs/reviews" ]] && echo true || echo false )"
check "external artifacts: no reviews dir in the external artifacts" "true" \
  "$( [[ ! -d "$TMP/external/specs/reviews" ]] && echo true || echo false )"
check "external artifacts: an implicit slug is refused" 1 "$(run 1b)"
check_contains "and explains why" "may belong to another branch" "$TMP/err.log"
base_profile

echo "== out-of-repo profile identity =="
reset_reviews
rm -f "$PROFILE"
CFG="$TMP/config/projects"
mkdir -p "$CFG"
export PROFILE_CONFIG_HOME="$CFG"
cat > "$CFG/acme.md" <<'EOF'
---
artifacts: docs/specs
codex_reviewer: yes
gates: 1b,2b
---
EOF
check "out-of-repo profile without repo_identity is refused" 1 "$(run 1b --slug 2026-09-thing)"
check_contains "and says what to add" "repo_identity:" "$TMP/err.log"

cat > "$CFG/acme.md" <<'EOF'
---
artifacts: docs/specs
codex_reviewer: yes
gates: 1b,2b
repo_identity: github.com/someone-else/acme
---
EOF
check "a profile belonging to another repo is refused" 1 "$(run 1b --slug 2026-09-thing)"
check_contains "and names the mismatch" "profile/repository mismatch" "$TMP/err.log"

cat > "$CFG/acme.md" <<EOF
---
artifacts: docs/specs
codex_reviewer: yes
gates: 1b,2b
repo_identity: $REPO
---
EOF
check "a matching out-of-repo profile runs" 0 "$(run 1b --slug 2026-09-thing)"
unset PROFILE_CONFIG_HOME
base_profile

echo "== calibration reaches the prompt =="
reset_reviews
cat > "$PROFILE" <<'EOF'
---
artifacts: docs/specs
codex_reviewer: yes
gates: 1b,2b
---

## Calibration

Two engineers. Billing is the only high-stakes area.
EOF
run 1b --slug 2026-09-thing >/dev/null
check_contains "profile calibration injected" "Billing is the only high-stakes area." "$TMP_PROMPT_FILE"
check_absent   "default calibration replaced" "No project profile was found" "$TMP_PROMPT_FILE"

echo "== arguments that become paths are validated (AC20) =="
reset_reviews
# These all already exit non-zero today, for the wrong reason ("spec not found"), so the exit
# code alone cannot tell a validated build from an unvalidated one. Assert the message.
run 1b --slug ../../escape >/dev/null
check_contains "traversal in --slug is rejected"   "invalid --slug" "$TMP/err.log"
run 1b --slug 'a/b' >/dev/null
check_contains "separator in --slug is rejected"   "invalid --slug" "$TMP/err.log"
run 1b --slug '-x' >/dev/null
check_contains "leading dash in --slug is rejected" "invalid --slug" "$TMP/err.log"
run 1b --slug 2026-09-thing --pr '../../escape' >/dev/null
check_contains "traversal in --pr is rejected"     "invalid --pr" "$TMP/err.log"
run 1b --slug 2026-09-thing --pr 'a/b' >/dev/null
check_contains "separator in --pr is rejected"     "invalid --pr" "$TMP/err.log"
check "empty --pr is a usage error"        2 "$(run 1b --slug 2026-09-thing --pr '')"
# Rejection must happen before anything is written.
check "no reviews dir created by rejected runs" "absent" "$([[ -d "$LD" ]] && echo present || echo absent)"

echo "== ledger identity: --pr discriminates, absence changes nothing (AC15-18) =="
reset_reviews
R="$LD"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

run 1b --slug 2026-09-thing >/dev/null
check "no --pr keeps the path unchanged (AC17)" "present" \
  "$([[ -f "$R/2026-09-thing-1b.md" ]] && echo present || echo absent)"

reset_reviews
run 1b --slug 2026-09-thing --pr 2 >/dev/null
check "--pr 2 writes its own ledger (AC15)" "present" \
  "$([[ -f "$R/2026-09-thing-1b-pr2.md" ]] && echo present || echo absent)"
check "--pr 2 does not write the bare path (AC15)" "absent" \
  "$([[ -f "$R/2026-09-thing-1b.md" ]] && echo present || echo absent)"

# The criterion a constant-mapping implementation must fail.
reset_reviews
run 6b --slug 2026-09-thing --pr 1 >/dev/null
run 6b --slug 2026-09-thing --pr 2 >/dev/null
check "two distinct --pr leave two ledgers (AC16)" "2" \
  "$(ls "$R" 2>/dev/null | grep -c '2026-09-thing-6b-pr[12].md')"

# An empty review dumps raw events beside the ledger; that sibling must carry the same identity.
reset_reviews
: > "$TMP/empty.md"
FAKE_CODEX_MESSAGE="$TMP/empty.md" run 1b --slug 2026-09-thing --pr 2 >/dev/null
check "events file inherits --pr (AC18)" "present" \
  "$([[ -f "$R/2026-09-thing-1b-pr2.events.jsonl" ]] && echo present || echo absent)"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

echo "== the overwrite guard runs before the spend (AC9-11) =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
LED="$R/2026-09-thing-1b.md"
before="$(md5 -q "$LED")"
rm -f "$TMP_ARGV_FILE"
# The second run must produce DIFFERENT output, or "byte-identical" passes even when the
# ledger was rewritten -- same stub, same minute, same bytes.
cat > "$TMP/other-findings.md" <<'EOF'
## BLOCKER

### 1b-F09 — a completely different finding
- evidence: nowhere
- failure path: none

## MAJOR

None.
EOF
export FAKE_CODEX_MESSAGE="$TMP/other-findings.md"

check "a second round 1 is refused (AC9)" 1 "$(run 1b --slug 2026-09-thing)"
check "the existing ledger is byte-identical (AC9)" "$before" "$(md5 -q "$LED")"
check "codex was never invoked (AC9)" "absent" \
  "$([[ -f "$TMP_ARGV_FILE" ]] && echo present || echo absent)"
check_contains "the refusal reports the artifact revision (AC9)" "artifact revision" "$TMP/err.log"
check_absent  "the refusal does not teach --rerun (AC10)" "--rerun" "$TMP/err.log"
check_absent  "the refused review never reached the ledger (AC9)" "1b-F09" "$LED"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

# A skip is not a review: it must not require --rerun to be replaced.
reset_reviews
rm -f "$PROFILE"
run 1b --slug 2026-09-thing >/dev/null      # records a skip (no consent)
base_profile
check "a skip ledger is replaced without --rerun (AC11)" 0 "$(run 1b --slug 2026-09-thing)"
check_contains "and now holds a real review (AC11)" "## Round 1" "$LED"

echo "== --rerun archives, never destroys (AC12-14) =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
export FAKE_CODEX_MESSAGE="$TMP/other-findings.md"

check "--rerun succeeds" 0 "$(run 1b --slug 2026-09-thing --rerun)"
check_contains "the new review is written (AC12)" "1b-F09" "$LED"
check "the previous review survives as an archive (AC12)" "1" \
  "$(ls "$R" 2>/dev/null | grep -c '2026-09-thing-1b.md.superseded-.*\.md')"

# A failed rerun must not empty the canonical path -- specs and PRs link to it.
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
before="$(md5 -q "$LED")"
archives_before="$(ls "$R" 2>/dev/null | grep -c 'superseded' || true)"
FAKE_CODEX_EXIT=1 run 1b --slug 2026-09-thing --rerun >/dev/null
check "a failed rerun leaves the ledger byte-identical (AC12b)" "$before" "$(md5 -q "$LED" 2>/dev/null)"
check "a failed rerun archives nothing (AC12b)" "$archives_before" \
  "$(ls "$R" 2>/dev/null | grep -c 'superseded' || true)"

# Two reruns inside the same clock tick must not collide.
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
CODEX_AUDIT_TEST_CLOCK=FIXED run 1b --slug 2026-09-thing --rerun >/dev/null
CODEX_AUDIT_TEST_CLOCK=FIXED run 1b --slug 2026-09-thing --rerun >/dev/null
check "two reruns in one tick leave two archives (AC13)" "2" \
  "$(ls "$R" 2>/dev/null | grep -c 'superseded' || true)"

# Archiving must not consult git: an external artifacts dir is outside every repository.
mkdir -p "$TMP/external/specs"
cp "$REPO/docs/specs/2026-09-thing.md" "$TMP/external/specs/" 2>/dev/null || true
reset_reviews
cat > "$PROFILE" <<EOF
---
artifacts: $TMP/external/specs
codex_reviewer: yes
gates: 1b,2b
---
EOF
run 1b --slug 2026-09-thing >/dev/null
check "external rerun succeeds outside any repo (AC14)" 0 "$(run 1b --slug 2026-09-thing --rerun)"
check "external rerun archives the old ledger (AC14)" "1" \
  "$(ls "$LD" 2>/dev/null | grep -c 'superseded' || true)"
base_profile

echo "== ledger location: git common dir, never the tracked tree (output-budget AC5, AC10) =="
reset_reviews; rm -rf "$REPO/docs/specs/reviews"
check "round 1 writes the ledger under .git/codex-audit" 0 "$(run 1b --slug 2026-09-thing)"
check "ledger present at the new path" "present" \
  "$([[ -f "$LEDGER" ]] && echo present || echo absent)"
check "nothing created under <artifacts>/reviews" "absent" \
  "$([[ -d "$REPO/docs/specs/reviews" ]] && echo present || echo absent)"

# A ledger written by the old wrapper: refuse, and hand over the copy that relocates it.
mkdir -p "$REPO/docs/specs/reviews"
mv "$LEDGER" "$REPO/docs/specs/reviews/"
check "a legacy-only ledger refuses round 1" 1 "$(run 1b --slug 2026-09-thing)"
check_contains "and prints the copy" "cp " "$TMP/err.log"
check "a legacy-only ledger refuses round 2" 1 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
mv_cmd="$(grep -E '^ +mkdir -p .* && cp ' "$TMP/err.log" | head -1)"
( cd "$REPO" && eval "$mv_cmd" )
check "the printed command copies, leaving the tracked legacy file in place" "present" \
  "$([[ -f "$REPO/docs/specs/reviews/$(basename "$LEDGER")" ]] && echo present || echo absent)"
check "after the printed copy, round 2 resumes" 0 \
  "$(FAKE_CODEX_MESSAGE="$TMP/round2.md" run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
rm -rf "$REPO/docs/specs/reviews"

# A legacy file that only records a skip is not a review: it must not block (design §7).
reset_reviews
mkdir -p "$REPO/docs/specs/reviews"
printf '# Gate 1b — skipped\n' > "$REPO/docs/specs/reviews/$(basename "$LEDGER")"
rm -f "$PROFILE"
check "a legacy skip record does not block a disabled reviewer" 3 "$(run 1b --slug 2026-09-thing)"
base_profile
rm -rf "$REPO/docs/specs/reviews"

echo "== the early stop names the ledger (output-budget AC11) =="
reset_reviews
export FAKE_CODEX_MESSAGE="$TMP/no-findings.md"
run 1b --slug 2026-09-thing >/dev/null
check "clean round 1 then round 2 exits 4" 4 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check_contains "and prints the ledger path" "ledger: " "$TMP/err.log"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

echo "== the lock (AC1-8) =="
# run_bg <barrier-file> <args...> -- starts the wrapper, blocks it at the named barrier,
# and returns once it has actually arrived there. Without this the "second invocation" races
# the first and the test proves nothing.
# await_barrier <file> [how-many-processes]
await_barrier() {
  local f="$1" want="${2:-1}" i=0
  # `wc -l < missing` fails in the shell, before any redirection of wc's own stderr can
  # suppress it, and floods the suite output with errors that read like failures.
  while [[ "$(grep -c '' "$f.reached" 2>/dev/null || echo 0)" -lt "$want" ]]; do
    sleep 0.05; i=$((i + 1))
    [[ $i -gt 200 ]] && return 1
  done
  return 0    # without this the function returns the status of the `-gt` test, which is
}             # false on every successful path
# `exec` matters: without it $! is the subshell and a signal kills the wrapper's parent,
# orphaning the wrapper with the lock still held.
start_held() {
  local barrier="$1"; shift
  ( cd "$REPO" && exec env CODEX_AUDIT_TEST_BARRIER_POSTRUN="$barrier" \
      "$WRAPPER" "$@" >"$TMP/bg.out" 2>"$TMP/bg.err" ) &
}

reset_reviews
B="$TMP/barrier-postrun"; rm -f "$B" "$B.reached"; : > "$B"
start_held "$B" 1b --slug 2026-09-thing; bg_pid=$!
await_barrier "$B" || { echo "  FAIL barrier never reached"; fail=$((fail+1)); }
rm -f "$TMP_ARGV_FILE"

# The first process has RETURNED from codex and has not yet written. This is the window AC2
# names; a sleeping stub could not reach it, because a blocked stub means codex never returned.
second="$(run 1b --slug 2026-09-thing)"
check "a second run is refused inside the post-codex window (AC2)" 1 "$second"
check "and it never invoked codex (AC1)" "absent" \
  "$([[ -f "$TMP_ARGV_FILE" ]] && echo present || echo absent)"
check_contains "and says the gate is already running" "already running" "$TMP/err.log"

# A different ledger path must not contend with it.
check "a different --pr does not contend (AC3)" 0 "$(run 1b --slug 2026-09-thing --pr 7)"
rm -f "$B"; wait $bg_pid 2>/dev/null; true

echo "== stale locks (AC4-6b) =="
reset_reviews
LOCKDIR="$R/.2026-09-thing-1b.lock"
mkdir -p "$LOCKDIR"
printf '%s\n%s\n%s\n' 999999 "$(hostname)" "long ago" > "$LOCKDIR/owner"
check "a lock owned by a dead pid is broken (AC4)" 0 "$(run 1b --slug 2026-09-thing)"

reset_reviews
mkdir -p "$LOCKDIR"
printf '%s\n%s\n%s\n' "$$" "some-other-host" "$(ps -o lstart= -p $$ 2>/dev/null)" > "$LOCKDIR/owner"
check "a live lock from another host is never broken (AC5)" 1 "$(run 1b --slug 2026-09-thing)"
rm -rf "$LOCKDIR"

reset_reviews
mkdir -p "$LOCKDIR"
printf '%s\n%s\n%s\n' "$$" "$(hostname)" "a different start time" > "$LOCKDIR/owner"
check "a recycled pid is recognised as stale (AC6)" 0 "$(run 1b --slug 2026-09-thing)"

# Two processes that both find the same stale lock: exactly one may proceed. A read-then-delete
# implementation lets both through, which silently restores the concurrency the lock exists to
# prevent -- and does it precisely when something has already gone wrong.
reset_reviews
mkdir -p "$LOCKDIR"
printf '%s\n%s\n%s\n' 999999 "$(hostname)" "long ago" > "$LOCKDIR/owner"
SB="$TMP/barrier-stale"; rm -f "$SB" "$SB.reached"; : > "$SB"
stale_run() {
  # No `exec`: this case needs the exit status, not signal delivery.
  ( cd "$REPO" && CODEX_AUDIT_TEST_BARRIER_STALE="$SB" \
      "$WRAPPER" 1b --slug 2026-09-thing >"$TMP/stale.$1.out" 2>"$TMP/stale.$1.err"
    echo $? > "$TMP/stale.$1.rc" ) &
}
# Started one at a time, each confirmed at the barrier before the next begins. Starting both
# at once is a race: if the first broke the lock and finished before the second started, the
# second would find no lock, acquire it legitimately, and the test would report two winners
# while the implementation was correct.
stale_run 1
await_barrier "$SB" 1 || { echo "  FAIL process 1 never reached the stale barrier"; fail=$((fail+1)); }
stale_run 2
await_barrier "$SB" 2 || { echo "  FAIL process 2 never reached the stale barrier"; fail=$((fail+1)); }
rm -f "$SB"
wait
winners="$(cat "$TMP/stale.1.rc" "$TMP/stale.2.rc" 2>/dev/null | grep -c '^0$')"
if [[ "$winners" != "1" ]]; then
  echo "    DIAG rc1=$(cat "$TMP/stale.1.rc" 2>/dev/null) rc2=$(cat "$TMP/stale.2.rc" 2>/dev/null)"
  echo "    DIAG reached=[$(tr '\n' ' ' < "$SB.reached" 2>/dev/null)]"
  echo "    DIAG err1: $(tail -3 "$TMP/stale.1.err" 2>/dev/null | tr '\n' '|')"
  echo "    DIAG err2: $(tail -3 "$TMP/stale.2.err" 2>/dev/null | tr '\n' '|')"
fi
check "exactly one process wins a stale lock (AC6b)" "1" "$winners"

echo "== signals release the lock (AC7) =="
for sig in INT TERM; do
  reset_reviews
  rm -f "$B" "$B.reached"; : > "$B"
  start_held "$B" 1b --slug 2026-09-thing; bg_pid=$!
  await_barrier "$B" || true
  kill -"$sig" "$bg_pid" 2>/dev/null; wait $bg_pid 2>/dev/null; true
  rm -f "$B"
  check "$sig releases the lock (AC7)" "absent" \
    "$([[ -d "$LOCKDIR" ]] && echo present || echo absent)"
done

echo "== worktrees of one repo share the lock (output-budget AC7) =="
reset_reviews
git -C "$REPO" worktree add -q "$TMP/acme-wt" 2>/dev/null
rm -f "$B" "$B.reached"; : > "$B"
start_held "$B" 1b --slug 2026-09-thing; bg_pid=$!
await_barrier "$B" || { echo "  FAIL barrier never reached"; fail=$((fail+1)); }
wt_rc="$( ( cd "$TMP/acme-wt" && "$WRAPPER" 1b --slug 2026-09-thing >/dev/null 2>"$TMP/wt.err" ); echo $? )"
rm -f "$B"; wait "$bg_pid" 2>/dev/null
check "a run from a second worktree is refused" 1 "$wt_rc"
check_contains "because the lock is shared" "a gate is already running" "$TMP/wt.err"

echo "== round 2 and the skip path take the same lock (AC8, AC8b) =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
check "round 2 still succeeds under the lock (AC8)" 0 \
  "$(FAKE_CODEX_MESSAGE="$TMP/round2.md" run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"

reset_reviews
rm -f "$B" "$B.reached"; : > "$B"
start_held "$B" 1b --slug 2026-09-thing; bg_pid=$!
await_barrier "$B" || true
rm -f "$PROFILE"                      # this invocation would record_skip
check "a skip-producing run blocks on the lock (AC8b)" 1 "$(run 1b --slug 2026-09-thing)"
base_profile
rm -f "$B"; wait $bg_pid 2>/dev/null; true

# Regression pins, not TDD: the gate-5 security audit hypothesised that CODEX_AUDIT_TEST_CLOCK
# and a crafted owner pid were unvalidated sinks, and both turned out already safe -- the clock
# is always prefixed, so `..` is never its own path segment and the `mv` fails before anything
# is overwritten; a bogus pid is caught by the start-time half of the staleness test, which must
# ALSO match for a lock to count as live. These pin that, so a later refactor cannot quietly
# remove the property.
echo "== paths and owners stay unescapable (security regression pins) =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
CODEX_AUDIT_TEST_CLOCK='../../escape' run 1b --slug 2026-09-thing --rerun >/dev/null
check "a traversing clock cannot place an archive (SR1)" "absent" \
  "$([[ -e "$REPO/docs/escape.md" || -e "$REPO/escape.md" ]] && echo present || echo absent)"
check "and no archive escaped the ledger dir (SR1)" "0" \
  "$(find "$REPO" -name '*superseded*' -not -path "*/.git/codex-audit/*" 2>/dev/null | wc -l | tr -d ' ')"

# A crafted owner file must not turn `kill -0` into a query about every process.
reset_reviews
mkdir -p "$LOCKDIR"
printf '%s\n%s\n%s\n' '-1' "$(hostname)" "whatever" > "$LOCKDIR/owner"
check "a non-numeric owner pid is treated as stale (SR5)" 0 "$(run 1b --slug 2026-09-thing)"

echo "== a half-claimed lock is not stale (review F1) =="
# `mkdir` wins the race, the owner file lands a moment later. A second process that reads the
# gap must not conclude the lock is free: that is the original hole, reopened from the inside.
reset_reviews
mkdir -p "$LOCKDIR"                      # no owner file: mid-claim
check "an ownerless lock is treated as live" 1 "$(run 1b --slug 2026-09-thing)"
# ...but a process that died between mkdir and the owner write must not block the gate forever.
reset_reviews
mkdir -p "$LOCKDIR"
touch -t 200001010000 "$LOCKDIR"
check "an ownerless lock left to go cold is broken" 0 "$(run 1b --slug 2026-09-thing)"

echo "== a live lock we may not signal is still live (review F2) =="
# `kill -0` cannot tell ESRCH from EPERM, so another user's live process reads as "gone".
# The start-time comparison can tell, and is what decides.
reset_reviews
mkdir -p "$LOCKDIR"
printf '%s\n%s\n%s\n' 1 "$(hostname)" "$(ps -o lstart= -p 1 2>/dev/null)" > "$LOCKDIR/owner"
check "a lock held by an unsignalable live pid is not broken" 1 "$(run 1b --slug 2026-09-thing)"
rm -rf "$LOCKDIR"

echo "== a failed archive never costs the new review (review F3) =="
reset_reviews
run 1b --slug 2026-09-thing >/dev/null
before="$(md5 -q "$LED")"
export FAKE_CODEX_MESSAGE="$TMP/other-findings.md"
# An unresolvable archive target: the parent directory does not exist, so `mv` fails.
CODEX_AUDIT_TEST_CLOCK='nodir/x' run 1b --slug 2026-09-thing --rerun >/dev/null
check "the old ledger survives a failed archive" "$before" "$(md5 -q "$LED" 2>/dev/null)"
check "and the new review is kept, not discarded" "1" \
  "$(grep -rl '1b-F09' "$R" 2>/dev/null | wc -l | tr -d ' ')"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"

echo "== --tasks: refusals land before anything leaves (AC4, AC5c, AC8, AC9) =="
TASKS_LED="$LD/2026-09-thing-6b.md"
# Exit code alone does not prove the value never left: that is the security boundary of an
# allowlisted wrapper (gate 2b, 2b-F03). The stub writes $TMP_ARGV_FILE only on its `exec`
# branch, so its absence is proof Codex was never invoked. R02: assert the ledger too.
check_refused() {
  local label="$1"; shift
  # The ledger is derived from the gate under test, not hardcoded to 6b: a refused 1b run would
  # write 2026-09-thing-1b.md, and a check pointed at the 6b path would never see it.
  local gate_under_test="$1"
  local led="$LD/2026-09-thing-$gate_under_test.md"
  reset_reviews
  rm -f "$TMP_ARGV_FILE"
  local code called ledger
  code="$(run "$@")"
  called=no;   [[ -f "$TMP_ARGV_FILE" ]] && called=yes
  ledger=absent; [[ -f "$led" ]] && ledger=created
  if [[ "$code" != "0" && "$called" == "no" && "$ledger" == "absent" ]]; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$label"
  else
    fail=$((fail + 1))
    printf '  FAIL %s\n       exit=%s codex_called=%s ledger=%s\n' "$label" "$code" "$called" "$ledger"
  fi
}

check_refused "a shell metacharacter is refused"   6b --slug 2026-09-thing --tasks '4-8;rm -rf /'
check_refused "a letter is refused"                6b --slug 2026-09-thing --tasks 'a'
check_refused "a leading dash is refused"          6b --slug 2026-09-thing --tasks '-4'
check_refused "a space-separated list is refused"  6b --slug 2026-09-thing --tasks '4 8'
check_refused "a template placeholder is refused"  6b --slug 2026-09-thing --tasks '{{'
check_refused "an empty value is refused"          6b --slug 2026-09-thing --tasks ''
check_refused "a descending range is refused"      6b --slug 2026-09-thing --tasks '8-4'
check_refused "task zero is refused"               6b --slug 2026-09-thing --tasks '0'
check_refused "an empty element is refused"        6b --slug 2026-09-thing --tasks '4,,5'
check_refused "a leading zero is refused"          6b --slug 2026-09-thing --tasks '04'
check_refused "--tasks on gate 1b is refused"      1b --slug 2026-09-thing --tasks '1-3'
check_refused "--tasks on gate 2b is refused"      2b --slug 2026-09-thing --tasks '1-3'
# The range guard evaluates in bash arithmetic, which wraps at 64 bits: without the digit cap
# this overflows to a negative lower bound, reads as ascending, and buys a real Codex run for a
# scope that resolves to nothing.
check_refused "an overflowing range is refused"    6b --slug 2026-09-thing --tasks '9223372036854775808-1'
check_refused "five digits is refused"             6b --slug 2026-09-thing --tasks '10000'
# --rerun archives; without --pr it would archive over the path another PR's description links to.
check_refused "a scoped --rerun without --pr is refused" 6b --slug 2026-09-thing --tasks '4-8' --rerun

echo "== --tasks: the en-dash transcription trap (AC9b) =="
reset_reviews; rm -f "$TMP_ARGV_FILE"
check "an en-dashed range is refused" 1 "$(run 6b --slug 2026-09-thing --tasks '4–8')"
check_contains "and the message names the en-dash case" "en dash" "$TMP/err.log"

echo "== --tasks: the plan is required (AC4) =="
mv "$REPO/docs/specs/plans/2026-09-thing.md" "$TMP/plan.away"
check_refused "--tasks without a plan file is refused" 6b --slug 2026-09-thing --tasks '4-8'
mv "$TMP/plan.away" "$REPO/docs/specs/plans/2026-09-thing.md"

echo "== --tasks: the scoped prompt (AC1, AC2, AC5b, AC11, AC12) =="
# Positive assertions, not check_absent on a criterion id: the prompt carries paths, never the
# plan's contents, so an absence test passes whether or not scoping exists (gate 2b, 2b-F02).
reset_reviews
run 6b --slug 2026-09-thing --tasks '4-8,10,11' >/dev/null
check_contains "the range reaches the prompt verbatim"  "tasks 4-8,10,11 only" "$TMP_PROMPT_FILE"
check_contains "the plan path reaches the prompt"       "$REPO/docs/specs/plans/2026-09-thing.md" "$TMP_PROMPT_FILE"
check_contains "the resolve-only obligation is present" "Evaluate **only** the criteria those tasks name." "$TMP_PROMPT_FILE"
check_contains "the silence obligation is present"      "do not report it at any" "$TMP_PROMPT_FILE"
check_contains "the fail-loudly obligation is present"  "report that as an explicit failure" "$TMP_PROMPT_FILE"
check_absent   "no placeholder survives a scoped prompt" "{{" "$TMP_PROMPT_FILE"

reset_reviews
run 6b --slug 2026-09-thing --tasks '1-3' >/dev/null
check_contains "PR 1's range reaches the prompt" "tasks 1-3 only" "$TMP_PROMPT_FILE"
check_absent   "and PR 2's range does not"       "tasks 4-8,10,11 only" "$TMP_PROMPT_FILE"

reset_reviews
run 6b --slug 2026-09-thing >/dev/null
check_absent "unscoped: no resolve-only obligation" "Evaluate **only** the criteria" "$TMP_PROMPT_FILE"
check_absent "unscoped: no silence obligation"      "do not report it at any" "$TMP_PROMPT_FILE"
check_absent "unscoped: no fail-loudly obligation"  "report that as an explicit failure" "$TMP_PROMPT_FILE"

echo "== --tasks narrows reporting, never execution (AC10, SR2) =="
# Both exit codes are asserted: the stub only rewrites $TMP_PROMPT_FILE when `codex exec` is
# reached, so a scoped run that died earlier would leave the UNSCOPED prompt in place and the
# comparison would pass green while --tasks was entirely broken.
reset_reviews
check "the unscoped run reaches codex" 0 "$(run 6b --slug 2026-09-thing)"
sed -n '1,/^## Gate 6b/p' "$TMP_PROMPT_FILE" | sed '$d' > "$TMP/contract.unscoped"
reset_reviews
check "the scoped run reaches codex"   0 "$(run 6b --slug 2026-09-thing --pr 2 --tasks '4-8')"
sed -n '1,/^## Gate 6b/p' "$TMP_PROMPT_FILE" | sed '$d' > "$TMP/contract.scoped"
check "the reviewer contract is byte-identical under --tasks" "" "$(diff "$TMP/contract.unscoped" "$TMP/contract.scoped")"

echo "== --tasks: the ledger says it was scoped (AC5, AC6, AC7) =="
reset_reviews; run 6b --slug 2026-09-thing --tasks '4-8,10,11' >/dev/null
check_contains "a scoped ledger records its scope"   "- **scope:** tasks 4-8,10,11" "$TASKS_LED"
check "and --tasks leaves the ledger path alone" "1" "$([[ -f "$TASKS_LED" ]] && echo 1 || echo 0)"
reset_reviews; run 6b --slug 2026-09-thing >/dev/null
check_absent "an unscoped ledger carries no scope line" "- **scope:**" "$TASKS_LED"

echo "== --tasks: a single task is a valid list =="
reset_reviews
check "a bare task number is accepted" 0 "$(run 6b --slug 2026-09-thing --tasks '9')"

echo "== scorecard: each finished gate records itself (AC10, AC11, AC20) =="
glines() { if [[ -f "$GATE_LOG" ]]; then wc -l < "$GATE_LOG" | tr -d ' '; else echo 0; fi; }
last() { tail -1 "$GATE_LOG" | jq -r "$1"; }

reset_reviews; rm -f "$GATE_LOG"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"
check "round 1 exits 0" 0 "$(run 1b --slug 2026-09-thing)"
check "exit 0 appends one record" 1 "$(glines)"
check "it is a codex record for this gate and repo" "codex 1b 2026-09-thing acme" \
  "$(last '[.source, .gate, .slug, .repo] | join(" ")')"
check "its counts are the ledger's" "1/1/1" \
  "$(last '[.found.blocker, .found.major, .found.minor] | map(tostring) | join("/")')"

export FAKE_CODEX_MESSAGE="$TMP/round2.md"
check "round 2 exits 0" 0 "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check "round 2 appends a second record" 2 "$(glines)"
check "which is cumulative: round-1 findings plus the regression" "1/2/1" \
  "$(last '[.found.blocker, .found.major, .found.minor] | map(tostring) | join("/")')"
# F02 was rejected but Codex maintains it, and the regression is open: both are the human's now.
check "with the outcomes after round 2: F01 accepted, F02 and the regression escalated" "1 0 2 2" \
  "$(last '[.accepted.blocker, .rejected, .human, .rounds] | map(tostring) | join(" ")')"

echo "== scorecard: the unit's tier and its quoted trigger reach the record =="
reset_reviews; rm -f "$GATE_LOG"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"
check "--tier and --trigger are accepted" 0 \
  "$(run 1b --slug 2026-09-thing --tier B --trigger 'adds a dependency')"
check "the record carries both" "B|adds a dependency" "$(last '[.tier, .trigger] | join("|")')"
check_absent "and no missing-tier warning is printed" "--tier" "$TMP/err.log"
reset_reviews; rm -f "$GATE_LOG"
run 1b --slug 2026-09-thing --tier B --trigger '--migration' >/dev/null
check "a trigger that looks like a flag is still recorded as text" "--migration" "$(last .trigger)"

reset_reviews; rm -f "$GATE_LOG"
check "without --tier the gate still runs" 0 "$(run 1b --slug 2026-09-thing)"
check "and records a null tier, as before" "null" "$(last .tier)"
check_contains "with a warning naming the flag" "--tier" "$TMP/err.log"

reset_reviews; rm -f "$GATE_LOG" "$TMP_ARGV_FILE"
for bad in "--tier routine --trigger x" "--tier C --trigger x" "--tier B" "--trigger x"; do
  # shellcheck disable=SC2086  # word-splitting the flag list is the point
  check "codex-audit 1b $bad is a usage error" 2 "$(run 1b --slug 2026-09-thing $bad)"
done
check "a trigger with a newline is a usage error" 2 \
  "$(run 1b --slug 2026-09-thing --tier A --trigger "$(printf 'a\nb')")"
check_contains "refused as an invalid trigger, not an unknown flag" "invalid --trigger" "$TMP/err.log"
check "a 301-character trigger is a usage error" 2 \
  "$(run 1b --slug 2026-09-thing --tier B --trigger "$(printf 'x%.0s' {1..301})")"
check "none of them reached Codex" "absent" \
  "$([[ -f "$TMP_ARGV_FILE" ]] && echo present || echo absent)"
check "nor recorded anything" 0 "$(glines)"

reset_reviews; rm -f "$GATE_LOG"
export FAKE_CODEX_MESSAGE="$TMP/no-findings.md"
run 1b --slug 2026-09-thing >/dev/null
check "exit 4 (early stop) still exits 4" 4 \
  "$(run 1b --slug 2026-09-thing --round 2 --response "$TMP/response.md")"
check "and appends one more record" 2 "$(glines)"

reset_reviews; rm -f "$GATE_LOG"
export FAKE_CODEX_MESSAGE="$TMP/with-findings.md"
check "a skip exits 3" 3 "$(FAKE_CODEX_LOGIN_EXIT=1 run 1b --slug 2026-09-thing)"
check "and records a skip" "1 true" "$(echo "$(glines) $(last .skipped)")"

reset_reviews; rm -f "$GATE_LOG"
run 1b --slug 2026-09-thing >/dev/null
check "a skip over an existing review exits 3" 3 \
  "$(FAKE_CODEX_LOGIN_EXIT=1 run 1b --slug 2026-09-thing)"
check "and records nothing: a skip must not supersede a review" 1 "$(glines)"

reset_reviews; rm -f "$GATE_LOG"
check "a failed Codex run exits 1" 1 "$(FAKE_CODEX_EXIT=7 run 1b --slug 2026-09-thing)"
check "and records nothing" 0 "$(glines)"
check "a refused run (missing spec) exits 1" 1 "$(run 1b --slug nope)"
check "and records nothing either" 0 "$(glines)"

# A log that cannot be written must cost a warning, never the gate.
reset_reviews; rm -f "$GATE_LOG"
check "an unwritable log leaves the exit code at 0" 0 \
  "$(GATE_LOG=/dev/null/x/gate-log.jsonl run 1b --slug 2026-09-thing)"
check_contains "and the warning reaches the caller" "scorecard" "$TMP/err.log"
check_contains "and the ledger still holds the review" "### 1b-F01" "$LEDGER"
led_sum="$(md5 -q "$LEDGER")"
( cd "$REPO" && GATE_LOG=/dev/null/x/gate-log.jsonl python3 \
    "$HERE/../../claude/skills/usage-audit/scripts/gate_log.py" add --ledger "$LEDGER" ) >/dev/null 2>&1
check "a failed record never touches the ledger" "$led_sum" "$(md5 -q "$LEDGER")"

# The wrapper holds the counts but must not own the format (AC20).
check_contains "the only record path is gate_log.py add --ledger" 'gate_log.py" add --ledger' "$WRAPPER"
check_absent   "the wrapper never names the log file" "gate-log.jsonl" "$WRAPPER"
check_absent   "nor the variable that moves it" "GATE_LOG" "$WRAPPER"
check_absent   "nor builds JSON with jq" "jq -n" "$WRAPPER"
check_absent   "nor builds JSON with printf" "printf '{" "$WRAPPER"

echo "== scorecard mode: the wrapper is the only ledger counter (D9, AC7) =="
SC="$TMP/sc"; mkdir -p "$SC"
# val <ledger> <key>  -- one value out of `codex-audit scorecard`
val() { "$WRAPPER" scorecard "$1" 2>/dev/null | sed -n "s/^$2=//p"; }
# vals <ledger> <key>... -- several values, space separated
vals() { local f="$1" out="" k; shift; for k in "$@"; do out="$out$(val "$f" "$k") "; done; echo "${out% }"; }

# Two rounds: F01 accepted, F02 rejected but maintained, F03 sent to the human, F04 rejected;
# one regression written both as a heading and as a table row, and listed twice under
# "For the human" -- it must count once.
cat > "$SC/demo-1b.md" <<'EOF'
# Gate 1b — demo

<!-- thread_id: t-1 -->
<!-- cwd: /work/demo -->

- **artifact:** `~/work/demo.md`
- **date:** 2026-10-17 03:01
- **rounds:** 2

## Round 1 — Codex, verbatim

## BLOCKER

None.

## MAJOR

### 1b-F01 — SENTINEL-TITLE
- evidence: x
### 1b-F02 — second
- evidence: x
### 1b-F03 — third
- evidence: x
### 1b-F04 — fourth
- evidence: x

## MINOR

- a minor
- another minor
<!-- round 1 wall clock: 256s -->

## Response to round 1 — Claude

| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | MAJOR | accepted | done |
| 1b-F02 | MAJOR | rejected | cannot occur |
| 1b-F03 | MAJOR | human | product call |
| 1b-F04 | MAJOR | rejected | fine |

## Round 2 — Codex, verbatim

## Verdicts

| id | round-1 severity | response | verdict | note |
|---|---|---|---|---|
| 1b-F01 | MAJOR | accepted | resolved | fine |
| 1b-F02 | MAJOR | rejected | maintain | still real |
| 1b-F04 | MAJOR | rejected | concede | ok |

## Regressions

### R01 — a new problem (from 1b-F01)
- evidence: x
| R01 | MAJOR | duplicate row for the same regression |
<!-- round 2 wall clock: 83s -->

## For the human

| id | severity | why it is open | note |
|---|---|---|---|
| 1b-F02 | MAJOR | Codex maintains it | still real |
| 1b-F02 | MAJOR | Codex maintains it | still real |
| regression | — | introduced by the fixes | R01 |

## Metrics

| | |
|---|---|
EOF
# (pr is empty and the date holds a space, hence the double space and the split date.)
check "header keys: gate slug pr date thread rounds wall_s skipped status" \
  "1b demo  2026-10-17 03:01 t-1 2 339 0 ok" \
  "$(vals "$SC/demo-1b.md" gate slug pr date thread rounds wall_s skipped status)"
check "findings: 0 blocker, 4 major, 2 minor, 1 regression" "0 4 2 1" \
  "$(vals "$SC/demo-1b.md" blocker major minor regressions)"
check "outcomes: F01 accepted; F02 (maintained) and F03 (human) are open, not rejected" "0 1 1" \
  "$(vals "$SC/demo-1b.md" accepted_blocker accepted_major rejected)"
check "human is distinct open ids plus distinct regressions, duplicates counted once" "3" \
  "$(val "$SC/demo-1b.md" human)"
check "stdout is key=value lines and nothing else" "0" \
  "$("$WRAPPER" scorecard "$SC/demo-1b.md" 2>/dev/null | grep -vcE '^[a-z_]+=')"

# Modelled on a real ledger: 7 MAJOR all accepted, F05 not resolved, one regression.
{
  printf '%s\n' '# Gate 1b — real' '' '<!-- thread_id: t-real -->' '' '- **date:** 2026-10-17 03:01' \
    '- **rounds:** 2' '' '## Round 1 — Codex, verbatim' '' '## BLOCKER' '' 'None.' '' '## MAJOR' ''
  for n in 1 2 3 4 5 6 7; do printf '### 1b-F0%s — finding\n- evidence: x\n\n' "$n"; done
  printf '%s\n' '## MINOR' '' '- one' '- two' '- three' '<!-- round 1 wall clock: 256s -->' '' \
    '## Response to round 1 — Claude' '' '| id | severity | status | change / reason |' '|---|---|---|---|'
  for n in 1 2 3 4 5 6 7; do printf '| 1b-F0%s | MAJOR | accepted | done |\n' "$n"; done
  printf '%s\n' '' '## Round 2 — Codex, verbatim' '' '## Verdicts' '' \
    '| id | round-1 severity | response | verdict | note |' '|---|---|---|---|---|' \
    '| 1b-F05 | MAJOR | accepted | not resolved | still open |' '' '## Regressions' '' \
    '### R01 — a regression (from 1b-F02)' '<!-- round 2 wall clock: 83s -->' '' '## For the human'
} > "$SC/real-1b.md"
check "a real-shaped ledger: 7 major + 1 regression, 6 accepted, F05 and R01 human" "0 7 3 1 6 0 2" \
  "$(vals "$SC/real-1b.md" blocker major minor regressions accepted_major rejected human)"

# Regression shapes: a `### R01` under Verdicts, and a table-only row, are each one regression.
mkr() {  # mkr <file> <regression-lines...>
  local f="$1"; shift
  { printf '%s\n' '# Gate 1b — r' '' '- **date:** 2026-10-17 03:01' '- **rounds:** 2' '' \
      '## Round 1 — Codex, verbatim' '' '## MAJOR' '' '### 1b-F01 — x' '' \
      '## Response to round 1 — Claude' '' '| 1b-F01 | MAJOR | accepted | ok |' '' \
      '## Round 2 — Codex, verbatim' '' '## Verdicts' ''
    printf '%s\n' "$@"; } > "$f"
}
mkr "$SC/rv-1b.md" '### R01 — under Verdicts'
mkr "$SC/rt-1b.md" '| R01 | MAJOR | table row only |' '| R01 | MAJOR | same again |'
check "a '### R01' heading under '## Verdicts' is a regression, and a human item" "1 1" \
  "$(vals "$SC/rv-1b.md" regressions human)"
check "a table-only R01 row, repeated, is one regression" "1" "$(val "$SC/rt-1b.md" regressions)"

# Section headings are matched by prefix, as count_findings does.
cat > "$SC/plural-1b.md" <<'EOF'
# Gate 1b — plural

- **date:** 2026-10-11 08:30
- **rounds:** 1

## Round 1 — Codex, verbatim

## BLOCKERS

### 1b-F01 — a blocker under a plural heading

## MAJOR:

### 1b-F02 — a major under a colon heading

## MINOR

None.
EOF
check "'## BLOCKERS' and '## MAJOR:' are BLOCKER and MAJOR sections" "1 1" \
  "$(vals "$SC/plural-1b.md" blocker major)"

# A MAJOR written as prose with sub-bullets has no ### heading: the wrapper counts it as 0.
cat > "$SC/prose-1b.md" <<'EOF'
# Gate 1b — prose

- **date:** 2026-10-10 08:30
- **rounds:** 1

## Round 1 — Codex, verbatim

## BLOCKER

None.

## MAJOR

The spec is vague in three places:
- first
- second
- third

## MINOR

None.
EOF
check "a MAJOR without ### finding headings counts 0" "0 0" "$(vals "$SC/prose-1b.md" major minor)"

# Codex filed F01 under BLOCKER; Claude's table labelled it MAJOR. The section is the truth.
cat > "$SC/mislabel-1b.md" <<'EOF'
# Gate 1b — mislabel

- **date:** 2026-10-09 08:30
- **rounds:** 1

## Round 1 — Codex, verbatim

## BLOCKER

### 1b-F01 — really a blocker

## MAJOR

None.

## Response to round 1 — Claude

| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | MAJOR | accepted | fixed |
EOF
check "a response row is bucketed by the section it was filed under" "1 0" \
  "$(vals "$SC/mislabel-1b.md" accepted_blocker accepted_major)"

# The response file is pasted verbatim, headings included; none of them switches a region.
cat > "$SC/pasted-1b.md" <<'EOF'
# Gate 1b — pasted

- **date:** 2026-10-08 08:30
- **rounds:** 2

## Round 1 — Codex, verbatim

## MAJOR

### 1b-F01 — one
### 1b-F02 — two

## DROPPED

### 1b-F09 — dropped by Codex itself

## Response to round 1 — Claude

## Round 1 responses

| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | MAJOR | accepted | ok |
| 1b-F02 | MAJOR | rejected | no |
| 1b-F09 | MAJOR | accepted | only in DROPPED |

## Round 2 — Codex, verbatim

## Verdicts
EOF
check "a '## Round 1 responses' heading in the response leaves the counts intact" "2 1 1" \
  "$(vals "$SC/pasted-1b.md" major accepted_major rejected)"
check "an id that exists only under DROPPED is ignored" "0" "$(val "$SC/pasted-1b.md" accepted_blocker)"

# A bare '## ' heading used to crash a parser; here it just ends the section.
printf '%s\n' '# Gate 1b — bare' '' '- **date:** 2026-10-07 08:30' '- **rounds:** 1' '' \
  '## Round 1 — Codex, verbatim' '' '## MAJOR' '' '### 1b-F01 — one' '## ' '### 1b-F02 — after' \
  > "$SC/bare-1b.md"
check "a bare '## ' heading is harmless and ends the section" "ok 1" \
  "$(vals "$SC/bare-1b.md" status major)"

# A MINOR section that is one short "nothing here" bullet has no findings. Anything else is
# counted bullet by bullet: a real finding may start with "No ..." or "None of ...".
mkminor() {  # mkminor <file> <bullet-lines...>
  local f="$1"; shift
  { printf '%s\n' '# Gate 1b — m' '' '- **date:** 2026-10-05 08:30' '- **rounds:** 1' '' \
      '## Round 1 — Codex, verbatim' '' '## MINOR' ''
    printf '%s\n' "$@"; } > "$f"
}
i=0
for ph in '- **None.**' '- Nothing.' '- Not applicable' '- N/A — nothing to report'; do
  i=$((i + 1)); mkminor "$SC/ph$i-1b.md" "$ph"
  check "a lone placeholder bullet counts 0: $ph" "0" "$(val "$SC/ph$i-1b.md" minor)"
done
mkminor "$SC/real1-1b.md" '- No test covers the empty --pr case.'
check "'No test covers ...' is a finding, not a placeholder" "1" "$(val "$SC/real1-1b.md" minor)"
mkminor "$SC/real2-1b.md" '- None of the callers check the exit status.'
check "'None of the callers ...' is a finding, not a placeholder" "1" "$(val "$SC/real2-1b.md" minor)"
mkminor "$SC/mixed-1b.md" '- None.' '- The title could be shorter'
check "a placeholder-looking bullet beside a real one: both count" "2" "$(val "$SC/mixed-1b.md" minor)"

# A file name is data: a literal backslash-n in it must not become a newline (and so a forged
# key=value line) on its way into awk.
cp "$SC/mislabel-1b.md" "$SC"'/a\ngate=5s-1b.md'
check "a backslash sequence in the file name is not expanded: still one gate line, gate 1b" "1 1b" \
  "$("$WRAPPER" scorecard "$SC"'/a\ngate=5s-1b.md' 2>/dev/null | grep -c '^gate=') $(val "$SC"'/a\ngate=5s-1b.md' gate)"
check "and the slug keeps the backslash" 'a\ngate=5s' "$(val "$SC"'/a\ngate=5s-1b.md' slug)"

# Skips, unusable ledgers and archives.
printf '%s\n' '# Gate 1b — skipme' '' '- **skipped:** reviewer disabled by profile' \
  '- **date:** 2026-10-14 08:30' > "$SC/skipme-1b.md"
check "a skip ledger: status skip, skipped 1" "skip 1" "$(vals "$SC/skipme-1b.md" status skipped)"
printf '%s\n' '# Gate 1b — bad' '' '- **date:** 2026-10-13 08:30' '- **rounds:** 1' \
  '- **outcome:** UNPARSEABLE — the output does not follow the format' '' \
  '## Round 1 — Codex, verbatim' '' 'prose' > "$SC/bad-1b.md"
check "an UNPARSEABLE ledger is unrecordable" "unrecordable" "$(val "$SC/bad-1b.md" status)"
printf '%s\n' '# Gate 2b — noround' '' '- **date:** 2026-10-12 08:30' > "$SC/noround-2b.md"
check "a ledger with no round-1 heading is unrecordable" "unrecordable" "$(val "$SC/noround-2b.md" status)"
printf '%s\n' 'whatever' > "$SC/notes.md"
check "a file that is not named like a ledger is unrecordable" "unrecordable" "$(val "$SC/notes.md" status)"
check "and says so with an empty gate, which is how gate-log tells it from a broken ledger" "" \
  "$(val "$SC/notes.md" gate)"
check "a ledger-named file that is broken still names its gate" "1b" "$(val "$SC/bad-1b.md" gate)"
cp "$SC/mislabel-1b.md" "$SC/feature-x-6b-pr2.md.superseded-20261017T000000Z.md"
check "a --rerun archive reads gate, slug and pr from the base name" "6b feature-x 2" \
  "$(vals "$SC/feature-x-6b-pr2.md.superseded-20261017T000000Z.md" gate slug pr)"
check "no thread header: thread is empty" "" "$(val "$SC/mislabel-1b.md" thread)"
printf '%s\n' '# Gate 1b — blank' '<!-- thread_id:  -->' '- **date:** 2026-10-06 08:30' \
  '## Round 1 — Codex, verbatim' > "$SC/blank-1b.md"
check "a blank thread id is empty" "" "$(val "$SC/blank-1b.md" thread)"

# Whether triage happened at all: a one-shot 6b, or a 1b whose round 2 never ran, has findings
# and no response table, so what was accepted is unknown -- not zero.
check "a ledger with a response table says responded=1" 1 "$(val "$SC/demo-1b.md" responded)"
printf '%s\n' '# Gate 6b — untriaged' '- **date:** 2026-10-16 09:00' '- **rounds:** 1' \
  '## Round 1 — Codex, verbatim' '## BLOCKER' 'None.' '## MAJOR' '### 6b-F01 — one' \
  '### 6b-F02 — two' '## MINOR' 'None.' > "$SC/untriaged-6b.md"
check "a ledger with no response table says responded=0" "0 2" \
  "$(vals "$SC/untriaged-6b.md" responded major)"

# It is read-only and stands alone: no Codex, no profile, no log, no lock.
before="$(md5 -q "$SC/demo-1b.md")"
rm -f "$TMP_ARGV_FILE" "$GATE_LOG"
rm -f "$PROFILE"
check "scorecard needs no repo profile and exits 0" 0 \
  "$( cd "$TMP" && "$WRAPPER" scorecard "$SC/demo-1b.md" >/dev/null 2>&1; echo $? )"
base_profile
check "it never invoked codex" "absent" "$([[ -f "$TMP_ARGV_FILE" ]] && echo present || echo absent)"
check "it never touched the ledger" "$before" "$(md5 -q "$SC/demo-1b.md")"
check "it never wrote the scorecard log" "absent" "$([[ -f "$GATE_LOG" ]] && echo present || echo absent)"
check "a missing ledger path is an error" 1 "$( "$WRAPPER" scorecard "$SC/nope-1b.md" >/dev/null 2>&1; echo $? )"

# An existing ledger that cannot be read is exit 1 with a message, not awk's exit 2.
cp "$SC/mislabel-1b.md" "$SC/locked-1b.md"; chmod 000 "$SC/locked-1b.md"
check "an unreadable ledger exits 1, as the header says" 1 \
  "$( "$WRAPPER" scorecard "$SC/locked-1b.md" >/dev/null 2>"$TMP/sc.err"; echo $? )"
check_contains "and says it cannot read it" "cannot read" "$TMP/sc.err"
chmod 644 "$SC/locked-1b.md"

# A control character in the name never reaches the output: no forged key=value line.
NL_NAME="$SC/a"$'\n'"gate=5s-1b.md"
cp "$SC/mislabel-1b.md" "$NL_NAME"
check "a newline in the file name: only gate= and status=unrecordable come back" \
  "gate= status=unrecordable" "$("$WRAPPER" scorecard "$NL_NAME" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"

echo "== 6b triage: the response table is recorded without a Codex call =="
L6="$LD/2026-09-thing-6b.md"
cat > "$TMP/6b-findings.md" <<'EOF'
## BLOCKER

### 6b-F01 — criterion 2 has no test
- evidence: §6

## MAJOR

### 6b-F02 — the empty case is not built
- evidence: §6

## MINOR

None.
EOF
cat > "$TMP/6b-response.md" <<'EOF'
| id | severity | status | change / reason |
|---|---|---|---|
| 6b-F01 | BLOCKER | accepted | test added |
| 6b-F02 | MAJOR | rejected | another PR builds it |
EOF
reset_reviews; rm -f "$GATE_LOG"
export FAKE_CODEX_MESSAGE="$TMP/6b-findings.md"
check "6b round 1 exits 0" 0 "$(run 6b --slug 2026-09-thing --tier A --trigger 'touches auth')"
rm -f "$TMP_ARGV_FILE"
check "6b --response records the triage" 0 \
  "$(run 6b --slug 2026-09-thing --response "$TMP/6b-response.md" --tier A --trigger 'touches auth')"
check "without calling Codex" "absent" "$([[ -f "$TMP_ARGV_FILE" ]] && echo present || echo absent)"
check_contains "the table is appended under the response heading" "## Response to round 1 — Claude" "$L6"
check_contains "verbatim" "| 6b-F02 | MAJOR | rejected | another PR builds it |" "$L6"
check "scorecard reads it: 1 blocker accepted, 1 rejected, responded" "1 0 1 1" \
  "$(vals "$L6" accepted_blocker accepted_major rejected responded)"
check "a second record is appended" 2 "$(glines)"
check "which carries acceptance, not null, and the tier" "1 0 1 A" \
  "$(last '[.accepted.blocker, .accepted.major, .rejected, .tier] | map(tostring) | join(" ")')"
check "6b round 2 is still refused" 1 "$(run 6b --slug 2026-09-thing --round 2 --response "$TMP/6b-response.md")"

# triage <response-file> [run options...] -- a 6b triage with the unit's tier, as the skill runs it
triage() { local f="$1"; shift; run 6b --slug 2026-09-thing --response "$f" --tier A --trigger 'touches auth' "$@"; }

sum6="$(md5 -q "$L6")"
check "a second triage is refused" 1 "$(triage "$TMP/6b-response.md")"
check_contains "and says the ledger already holds one" "already holds a triage" "$TMP/err.log"
check "and leaves the ledger as it was" "$sum6" "$(md5 -q "$L6")"

reset_reviews
run 6b --slug 2026-09-thing >/dev/null
sum6="$(md5 -q "$L6")"
check "a triage without --tier is refused: it would replace the tiered record" 1 \
  "$(run 6b --slug 2026-09-thing --response "$TMP/6b-response.md")"
check_contains "and says to pass the tier" "--tier" "$TMP/err.log"
printf '%s\n' '| id | severity | status | change / reason |' '|---|---|---|---|' \
  '| 6b-F01 | BLOCKER | accepted | test added |' > "$TMP/6b-incomplete.md"
check "a triage missing a finding is refused" 1 "$(triage "$TMP/6b-incomplete.md")"
check_contains "and names it" "6b-F02" "$TMP/err.log"
printf '%s\n' '| id | severity | status | change / reason |' '|---|---|---|---|' \
  '| 6b-F01 | BLOCKER | accepted | same root cause as 6b-F02 |' > "$TMP/6b-inreason.md"
check "an id named only in another row's reason is refused" 1 "$(triage "$TMP/6b-inreason.md")"
check_contains "and names it" "6b-F02" "$TMP/err.log"
printf '%s\n' '| id | severity | status | change / reason |' '|---|---|---|---|' \
  '| 6b-F01 | BLOCKER | accepted | test added |' '| 6b-F02 | MAJOR | deferred | next PR |' \
  > "$TMP/6b-badstatus.md"
check "a status the scorecard cannot count is refused" 1 "$(triage "$TMP/6b-badstatus.md")"
check_contains "and names the row" "6b-F02 (deferred)" "$TMP/err.log"
cat "$TMP/6b-response.md" > "$TMP/6b-invented.md"
echo '| 6b-F09 | MAJOR | accepted | x |' >> "$TMP/6b-invented.md"
check "a triage inventing a finding is refused" 1 "$(triage "$TMP/6b-invented.md")"
cat "$TMP/6b-response.md" > "$TMP/6b-dupe.md"
echo '| 6b-F02 | MAJOR | accepted | x |' >> "$TMP/6b-dupe.md"
check "a triage answering a finding twice is refused" 1 "$(triage "$TMP/6b-dupe.md")"
check "none of them touched the ledger" "$sum6" "$(md5 -q "$L6")"
check "a missing response file is refused" 1 "$(triage "$TMP/nope.md")"

check "triage needs no Codex login: nothing leaves the machine" 0 \
  "$(FAKE_CODEX_LOGIN_EXIT=1 triage "$TMP/6b-response.md")"

reset_reviews
run 6b --slug 2026-09-thing >/dev/null
check "a failed record still exits 0" 0 "$(GATE_LOG=/dev/null/x/gate-log.jsonl triage "$TMP/6b-response.md")"
check_contains "and the warning names the manual re-record" "gate-log add --ledger" "$TMP/err.log"

reset_reviews
check "triage with no 6b ledger is refused" 1 "$(triage "$TMP/6b-response.md")"
FAKE_CODEX_LOGIN_EXIT=1 run 6b --slug 2026-09-thing >/dev/null
check "triage over a skip ledger is refused" 1 "$(triage "$TMP/6b-response.md")"
reset_reviews
printf '%s\n' 'free-form text, no severity headings' > "$TMP/6b-unparseable.md"
FAKE_CODEX_MESSAGE="$TMP/6b-unparseable.md" run 6b --slug 2026-09-thing >/dev/null
check "triage over an UNPARSEABLE ledger is refused" 1 "$(triage "$TMP/6b-response.md")"

reset_reviews
FAKE_CODEX_MESSAGE="$TMP/no-findings.md" run 6b --slug 2026-09-thing >/dev/null
sum6="$(md5 -q "$L6")"
check "a ledger with no BLOCKER/MAJOR has nothing to triage: exit 4" 4 "$(triage "$TMP/6b-response.md")"
check "and stays as it was" "$sum6" "$(md5 -q "$L6")"

echo
echo "passed: $pass   failed: $fail"
[[ "$fail" -eq 0 ]]
