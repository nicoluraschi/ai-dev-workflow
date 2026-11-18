#!/usr/bin/env bash
#
# test_zed_ruby_test.sh — tests for zed-ruby-test.
#
# Run:  bash zed/bin/test_zed_ruby_test.sh
#
# The seam is ZED_RUBY_TEST_DRY_RUN: with it set, the script prints
# "<rails-root>\t<command>" instead of exec'ing bundler, so the two things
# worth testing — where it decided the Rails root is, and which runner it
# picked — are observable without a Ruby toolchain or a real project.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$HERE/zed-ruby-test"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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

check_status() {
  local label="$1" expected="$2"; shift 2
  "$@" >/dev/null 2>&1 && local actual=0 || local actual=$?
  check "$label" "$expected" "$actual"
}

run() { ZED_RUBY_TEST_DRY_RUN=1 "$SUT" "$@" 2>/dev/null; }

# --- fixtures --------------------------------------------------------------
# An RSpec app at the root, the shape a monorepo uses one level down.
rspec_app() {
  local root="$1"
  mkdir -p "$root/spec/models" "$root/app/models"
  touch "$root/Gemfile" "$root/.rspec"
  touch "$root/spec/models/book_spec.rb" "$root/app/models/book.rb"
}

# Rails + Minitest: bin/rails is what makes `rails test` a real command.
minitest_app() {
  local root="$1"
  mkdir -p "$root/test/models" "$root/bin"
  touch "$root/Gemfile" "$root/bin/rails"
  touch "$root/test/models/book_test.rb"
}

# Plain Ruby + Minitest: a Gemfile, a Rakefile, test/ — and no Rails anywhere.
# A small scratch project is exactly this shape.
plain_minitest_app() {
  local root="$1"
  mkdir -p "$root/test"
  touch "$root/Gemfile" "$root/Rakefile"
  touch "$root/test/catalog_test.rb"
}

echo "== RSpec =="
R="$TMP/rspec"; rspec_app "$R"
check "file"        "$R	bundle exec rspec spec/models/book_spec.rb"    "$(run "$R/spec/models/book_spec.rb")"
check "file:line"   "$R	bundle exec rspec spec/models/book_spec.rb:42" "$(run "$R/spec/models/book_spec.rb" 42)"
check "suite"       "$R	bundle exec rspec"                             "$(run --suite "$R/spec/models/book_spec.rb")"
check "suite from a non-test file" "$R	bundle exec rspec"              "$(run --suite "$R/app/models/book.rb")"

echo "== Minitest =="
M="$TMP/minitest"; minitest_app "$M"
check "file"      "$M	bundle exec rails test test/models/book_test.rb"    "$(run "$M/test/models/book_test.rb")"
check "file:line" "$M	bundle exec rails test test/models/book_test.rb:42" "$(run "$M/test/models/book_test.rb" 42)"
check "suite"     "$M	bundle exec rails test"                             "$(run --suite "$M/test/models/book_test.rb")"

echo "== Minitest without Rails =="
# Regression: `test/` proves a test directory exists, not that Rails does.
# Resolving this to `bundle exec rails test` produced a command that cannot run.
N="$TMP/plainmini"; plain_minitest_app "$N"
check "file -> ruby -Itest, not rails test" \
  "$N	bundle exec ruby -Itest test/catalog_test.rb"  "$(run "$N/test/catalog_test.rb")"
check "suite -> rake test, not rails test" \
  "$N	bundle exec rake test"                         "$(run --suite "$N/test/catalog_test.rb")"
check "a line number cannot target plain minitest, so run the file" \
  "$N	bundle exec ruby -Itest test/catalog_test.rb"  "$(run "$N/test/catalog_test.rb" 9)"
check "Rails minitest still uses rails test" \
  "$M	bundle exec rails test test/models/book_test.rb" "$(run "$M/test/models/book_test.rb")"

echo "== relative paths (the script is on PATH, not only called by Zed) =="
R2="$TMP/relative"; rspec_app "$R2"
check "relative path resolves like an absolute one" \
  "$R2	bundle exec rspec spec/models/book_spec.rb" \
  "$(cd "$R2" && ZED_RUBY_TEST_DRY_RUN=1 "$SUT" ./spec/models/book_spec.rb 2>/dev/null)"
check "relative path from a parent directory" \
  "$R2	bundle exec rspec spec/models/book_spec.rb" \
  "$(cd "$TMP" && ZED_RUBY_TEST_DRY_RUN=1 "$SUT" relative/spec/models/book_spec.rb 2>/dev/null)"

echo "== monorepo: the Rails root is not the worktree root =="
# This is the real shape: ~/worktrees/<repo>/<type>/<name>/backend is the Rails
# app, and the worktree root above it has no Gemfile at all.
W="$TMP/wt/feat/thing"; mkdir -p "$W/web"; rspec_app "$W/backend"
check "walks up to the nearest Gemfile" \
  "$W/backend	bundle exec rspec spec/models/book_spec.rb" \
  "$(run "$W/backend/spec/models/book_spec.rb")"
check "path is relative to the Rails root, not the worktree" \
  "$W/backend	bundle exec rspec spec/models/book_spec.rb:7" \
  "$(run "$W/backend/spec/models/book_spec.rb" 7)"

echo "== RSpec wins when a project has both spec/ and test/ =="
B="$TMP/both"; rspec_app "$B"; mkdir -p "$B/test/models"; touch "$B/test/models/book_test.rb"
check "prefers rspec" "$B	bundle exec rspec spec/models/book_spec.rb" "$(run "$B/spec/models/book_spec.rb")"

echo "== failure modes =="
N="$TMP/nogemfile"; mkdir -p "$N/lib"; touch "$N/lib/thing.rb"
check_status "no Gemfile above the file -> non-zero"     1 env ZED_RUBY_TEST_DRY_RUN=1 "$SUT" "$N/lib/thing.rb"
F="$TMP/noframework"; mkdir -p "$F/lib"; touch "$F/Gemfile" "$F/lib/thing.rb"
check_status "Gemfile but no spec/ or test/ -> non-zero" 1 env ZED_RUBY_TEST_DRY_RUN=1 "$SUT" "$F/lib/thing.rb"
check_status "a non-test file is not a test file"        1 env ZED_RUBY_TEST_DRY_RUN=1 "$SUT" "$R/app/models/book.rb"
check_status "missing file argument -> non-zero"         1 env ZED_RUBY_TEST_DRY_RUN=1 "$SUT"
check_status "file that does not exist -> non-zero"      1 env ZED_RUBY_TEST_DRY_RUN=1 "$SUT" "$TMP/ghost.rb"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
