#!/usr/bin/env bash
#
# test_profile.sh — tests for profile.sh resolution.
#
# Run:  bash codex/lib/test_profile.sh
#
# The repository-geometry functions (profile_worktree_root / profile_main_root) are the
# seam: they are stubbed per case so the resolution order, frontmatter parsing and derived
# settings can be tested against fixtures without needing real repositories.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=profile.sh
source "$HERE/profile.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    pass=$((pass + 1))
    printf '  ok   %s\n' "$label"
  else
    fail=$((fail + 1))
    printf '  FAIL %s\n       expected: %s\n       actual:   %s\n' "$label" "$expected" "$actual"
  fi
}

check_status() {
  local label="$1" expected="$2"; shift 2
  "$@" >/dev/null 2>&1 && local actual=0 || local actual=$?
  check "$label" "$expected" "$actual"
}

# Point the geometry at a fixture tree.
use_repo() {
  local worktree="$1" main="${2:-$1}"
  eval "profile_worktree_root() { echo '$worktree'; }"
  eval "profile_main_root()     { echo '$main'; }"
}

write_profile() {
  local path="$1"; shift
  mkdir -p "$(dirname "$path")"
  cat > "$path"
}

echo "== resolution order =="

mkdir -p "$TMP/mainrepo" "$TMP/wt"
use_repo "$TMP/wt" "$TMP/mainrepo"
PROFILE_CONFIG_HOME="$TMP/config"

check "key is the main checkout's basename, not the worktree's" "mainrepo" "$(profile_key)"
check "no profile anywhere -> profile_path fails" "" "$(profile_path || true)"
check "no profile -> defaults" "docs/specs" "$(profile_get artifacts "$PROFILE_DEFAULT_ARTIFACTS")"

write_profile "$TMP/config/mainrepo.md" <<'EOF'
---
artifacts: ~/ai-work/mainrepo
codex_reviewer: no
---
EOF
check "out-of-repo profile found by key" "$TMP/config/mainrepo.md" "$(profile_path)"

write_profile "$TMP/mainrepo/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/from-main
---
EOF
check "main checkout beats out-of-repo" "$TMP/mainrepo/docs/ai-profile.md" "$(profile_path)"

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/from-worktree
---
EOF
check "worktree copy beats main checkout" "$TMP/wt/docs/ai-profile.md" "$(profile_path)"

echo "== frontmatter parsing =="

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
# a comment line, and a blank line follow

artifacts: docs/specs   # trailing comment is stripped
codex_reviewer:no-space-after-colon
gates: 1b,2b,6b
empty_value:
docs_product_language: es
---

# body

not_frontmatter: ignored
EOF

check "value trimmed, trailing comment stripped" "docs/specs" "$(profile_get artifacts X)"
check "no space after colon still parses" "no-space-after-colon" "$(profile_get codex_reviewer X)"
check "list value read whole" "1b,2b,6b" "$(profile_get gates X)"
check "empty value falls back to default" "DEFAULT" "$(profile_get empty_value DEFAULT)"
check "absent key falls back to default" "DEFAULT" "$(profile_get nope DEFAULT)"
check "key after the closing --- is not read" "DEFAULT" "$(profile_get not_frontmatter DEFAULT)"
check "later key still found" "es" "$(profile_get docs_product_language X)"

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
artifacts: docs/specs
EOF
check "file with no frontmatter fence yields defaults" "DEFAULT" "$(profile_get artifacts DEFAULT)"

echo "== gates and reviewer =="

# Sending an artifact to Codex sends it to another provider. A profile that says nothing
# about that has not authorized it, so the default must be `unset` — never `yes`.
write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
gates: 1b,2b
---
EOF
check "a profile that omits codex_reviewer is unset, not yes" "unset" "$(profile_codex_consent)"
check_status "and unset is not allowed"                       1 profile_codex_allowed

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
gates: 1b,2b
codex_reviewer: yes
---
EOF
check_status "1b enabled"       0 profile_gate_enabled 1b
check_status "2b enabled"       0 profile_gate_enabled 2b
check_status "6b not enabled"   1 profile_gate_enabled 6b
check_status "codex allowed"    0 profile_codex_allowed

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
gates: none
codex_reviewer: no
---
EOF
check_status "gates: none disables 1b" 1 profile_gate_enabled 1b
check_status "codex_reviewer: no"      1 profile_codex_allowed
check "an explicit no reads as no, not unset" "no" "$(profile_codex_consent)"

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
codex_reviewer: yes
---
EOF
check "an explicit yes reads as yes" "yes" "$(profile_codex_consent)"
check_status "and is allowed"        0 profile_codex_allowed

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
codex_reviewer: maybe
---
EOF
check "an unrecognised value is unset, never yes" "unset" "$(profile_codex_consent)"

echo "== out-of-repo detection =="

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/specs
---
EOF
check_status "an in-repo profile is not out-of-repo" 1 profile_is_out_of_repo
rm -f "$TMP/wt/docs/ai-profile.md" "$TMP/mainrepo/docs/ai-profile.md"
write_profile "$TMP/config/mainrepo.md" <<'EOF'
---
artifacts: docs/specs
---
EOF
check_status "a profile under the config home is out-of-repo" 0 profile_is_out_of_repo
rm -f "$TMP/config/mainrepo.md"
check_status "no profile at all is not out-of-repo" 1 profile_is_out_of_repo

echo "== path canonicalisation =="

mkdir -p "$TMP/real"
ln -sfn "$TMP/real" "$TMP/link"
check "a symlinked path canonicalises to its target" \
  "$(cd "$TMP/real" && pwd -P)" "$(profile_canon_path "$TMP/link")"
check "a path that does not exist is returned unchanged" \
  "/no/such/place" "$(profile_canon_path /no/such/place)"

# A substring must not match a gate id: `b` is not `1b`, `1b2` is not `1b`.
write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
gates: 11b,2b
---
EOF
check_status "11b does not enable 1b" 1 profile_gate_enabled 1b
check_status "11b enables 11b"        0 profile_gate_enabled 11b

echo "== artifacts directory =="

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/specs
---
EOF
check "relative artifacts resolve against the WORKTREE" "$TMP/wt/docs/specs" "$(profile_artifacts_dir)"
check_status "relative artifacts are not external" 1 profile_is_external

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: ~/ai-work/acme
---
EOF
check "tilde artifacts expand to \$HOME" "$HOME/ai-work/acme" "$(profile_artifacts_dir)"
check_status "tilde artifacts are external" 0 profile_is_external

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: /var/ai-work/acme
---
EOF
check "absolute artifacts used as given" "/var/ai-work/acme" "$(profile_artifacts_dir)"
check_status "absolute artifacts are external" 0 profile_is_external

echo "== calibration =="

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/specs
---

# acme — workflow profile

## Calibration

Two engineers, ~400 daily users.

Billing is the high-stakes area.

## Post-steps

Upload to Drive.
EOF
expected="Two engineers, ~400 daily users.

Billing is the high-stakes area."
check "calibration stops at the next heading, blank lines trimmed" "$expected" "$(profile_calibration)"

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/specs
---

## Calibration
EOF
check "empty calibration falls back to the default" "$PROFILE_DEFAULT_CALIBRATION" "$(profile_calibration)"

# Regression: profile.template.md ships a Calibration section that is entirely an HTML
# comment explaining how to write one. A profile copied from it but never filled in would
# otherwise send those authoring instructions to the reviewer as the project context.
write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/specs
---

## Calibration

<!--
  Cover: team size, scale, deployment risk.
  Write it as if briefing a contractor on their first day.
-->
EOF
check "a calibration that is only a comment falls back to the default" \
  "$PROFILE_DEFAULT_CALIBRATION" "$(profile_calibration)"

write_profile "$TMP/wt/docs/ai-profile.md" <<'EOF'
---
artifacts: docs/specs
---

## Calibration

<!-- a hint to the author -->
Two engineers, one product owner.
EOF
check "comments are stripped but real prose is kept" \
  "Two engineers, one product owner." "$(profile_calibration)"

# The shipped template must not produce a usable calibration — if it does, the guard above
# is not actually covering the file it was written for.
TEMPLATE="$HERE/../profile.template.md"
if [[ -f "$TEMPLATE" ]]; then
  profile_path() { echo "$TEMPLATE"; }
  check "the shipped template yields the default, not its own instructions" \
    "$PROFILE_DEFAULT_CALIBRATION" "$(profile_calibration)"
  use_repo "$TMP/wt" "$TMP/mainrepo"
fi

rm -f "$TMP/wt/docs/ai-profile.md" "$TMP/mainrepo/docs/ai-profile.md" "$TMP/config/mainrepo.md"
check "no profile at all falls back to the default calibration" \
  "$PROFILE_DEFAULT_CALIBRATION" "$(profile_calibration)"

echo
echo "passed: $pass   failed: $fail"
[[ "$fail" -eq 0 ]]
