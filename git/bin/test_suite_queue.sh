#!/usr/bin/env bash
#
# test_suite_queue.sh — tests for suite-queue.
#
# Run:  bash git/bin/test_suite_queue.sh
#
# HOME points at a temp dir, so the lock directory (~/.cache/suite-queue) is
# private to the run. SUITE_QUEUE_TTY is the seam for the wait message: a
# writable file stands in for /dev/tty, an unopenable path forces the stderr
# fallback. Ordering is proved with an append-only event log, not clocks, and
# a holder keeps its slot until the test touches a release file — never for a
# fixed sleep, which a loaded machine can outrun.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$HERE/suite-queue"

TMP="$(mktemp -d)"
trap 'jobs -p | xargs kill -9 2>/dev/null; rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
mkdir -p "$HOME"
LOCKDIR="$HOME/.cache/suite-queue"
NOTTY="$TMP/no/such/tty"

# The queue tests below run the same command again and again in the same clean
# repo, so verified skip is off for them; the "verified skip" sections turn it
# back on.
export SUITE_QUEUE_FORCE=1

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

# Poll until a file exists and is non-empty (up to ~10 s).
wait_for() {
  local i
  for i in $(seq 1 100); do [[ -s "$1" ]] && return 0; sleep 0.1; done
  return 1
}

events() { tr '\n' ' ' < "$TMP/events" | sed 's/ $//'; }

# --- fixtures --------------------------------------------------------------
make_repo() {
  local dir="$1" branch="$2"
  mkdir -p "$dir"
  git -C "$dir" init -q -b "$branch"
  git -C "$dir" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
}
make_repo "$TMP/repoA" main
make_repo "$TMP/repoB" feature

# Run suite-queue from a directory, fully isolated from the real tty.
sq() { local dir="$1"; shift; (cd "$dir" && SUITE_QUEUE_TTY="$NOTTY" "$SUT" "$@"); }

# Start a holder in the background: logs A-start, records its pid, then keeps
# the slot until release() (capped at 30 s). With a 3rd argument "end" it logs
# A-end before exiting.
start_holder() {
  local kind="$1" dir="$2" end="${3:-}"
  local tail=""
  [[ "$end" == end ]] && tail="; echo A-end >> '$TMP/events'"
  rm -f "$TMP/release"; : > "$TMP/pid"
  sq "$dir" "$kind" sh -c "echo A-start >> '$TMP/events'; echo \$\$ > '$TMP/pid'; i=0; while [ ! -e '$TMP/release' ] && [ \$i -lt 600 ]; do sleep 0.05; i=\$((i+1)); done$tail" \
    >/dev/null 2>&1 &
  wait_for "$TMP/pid" || echo "holder did not start" >&2
}
release() { : > "$TMP/release"; wait; }

# Start a waiter in the background from repoB; its stderr goes to $TMP/err.
# Returns once it has announced the wait, so the slot is proven busy.
start_waiter() {
  local kind="$1"; shift
  : > "$TMP/err"
  (cd "$TMP/repoB" && SUITE_QUEUE_TTY="$NOTTY" SUITE_QUEUE_TIMEOUT=20 "$SUT" "$kind" "$@" >/dev/null 2>"$TMP/err"; echo $? > "$TMP/wstatus") &
  wait_for "$TMP/err" || echo "waiter never announced" >&2
}

echo "== usage errors (9) =="
check_status "unknown kind -> 64"  64 "$SUT" python true
check_status "no command -> 64"    64 "$SUT" js
check_status "no args -> 64"       64 "$SUT"
rm -f "$TMP/ran"
"$SUT" python touch "$TMP/ran" 2>"$TMP/err"; [[ -e "$TMP/ran" ]] && ran=yes || ran=no
check "unknown kind runs nothing" "no" "$ran"
check "usage goes to stderr" "yes" "$(grep -q -i usage "$TMP/err" && echo yes || echo no)"

echo "== bad timeout (7) =="
for t in 0 -5 abc; do
  rm -f "$TMP/ran"
  SUITE_QUEUE_TIMEOUT="$t" "$SUT" js touch "$TMP/ran" >/dev/null 2>&1; s=$?
  [[ -e "$TMP/ran" ]] && ran=yes || ran=no
  check "timeout '$t' -> 64" "64" "$s"
  check "timeout '$t' runs nothing" "no" "$ran"
done

echo "== first run (11, 19) =="
rm -rf "$HOME/.cache"
check "uncontended run creates the dir and runs the command" "hi" "$(sq "$TMP/repoA" js echo hi 2>&1)"
check "lock dir mode is 700" "700" "$(stat -f %Lp "$LOCKDIR")"

echo "== exit status and arguments (3, 4) =="
check_status "true -> 0"        0 sq "$TMP/repoA" js true
check_status "exit 3 -> 3"      3 sq "$TMP/repoA" js sh -c 'exit 3'
check_status "exit 75 from the command is passed through, not retried" 75 sq "$TMP/repoA" js sh -c 'exit 75'
check "argument with spaces and \$ survives" 'a b $HOME "q"' "$(sq "$TMP/repoA" js printf '%s' 'a b $HOME "q"')"
check "stdin reaches the command" "piped" "$(echo piped | sq "$TMP/repoA" js cat)"

echo "== serializes one kind across repos (1) =="
for kind in ruby js; do
  : > "$TMP/events"
  start_holder "$kind" "$TMP/repoA" end
  start_waiter "$kind" sh -c "echo B-start >> '$TMP/events'"
  release
  check "$kind: waiter starts after holder ends" "A-start A-end B-start" "$(events)"
done

echo "== kinds are independent (2) =="
: > "$TMP/events"
start_holder ruby "$TMP/repoA" end
SUITE_QUEUE_TIMEOUT=5 sq "$TMP/repoB" js sh -c "echo B-start >> '$TMP/events'; echo B-end >> '$TMP/events'" >/dev/null 2>&1
release
check "js started and ended while ruby was held" "A-start B-start B-end A-end" "$(events)"

echo "== wait message (5, 10, 18) =="
MSG='^suite-queue: waiting for js slot \(held by repoA main since [0-9][0-9]:[0-9][0-9]\)$'

# tty branch: the line goes to the tty file, stderr stays empty.
: > "$TMP/tty"
start_holder js "$TMP/repoA"
(cd "$TMP/repoB" && SUITE_QUEUE_TTY="$TMP/tty" SUITE_QUEUE_TIMEOUT=20 "$SUT" js true 2>"$TMP/err2") &
wait_for "$TMP/tty"
release
check "tty: exactly one line" "1" "$(wc -l < "$TMP/tty" | tr -d ' ')"
check "tty: line format" "yes" "$(grep -Eq "$MSG" "$TMP/tty" && echo yes || echo no)"
check "tty: nothing on stderr" "" "$(cat "$TMP/err2")"

# stderr fallback: tty cannot be opened, so stderr carries the one line.
start_holder js "$TMP/repoA"
start_waiter js true
release
check "stderr: exactly one line" "1" "$(wc -l < "$TMP/err" | tr -d ' ')"
check "stderr: line format" "yes" "$(grep -Eq "$MSG" "$TMP/err" && echo yes || echo no)"

# uncontended: nothing printed anywhere.
: > "$TMP/tty"
out="$(cd "$TMP/repoB" && SUITE_QUEUE_TTY="$TMP/tty" "$SUT" js true 2>&1)"
check "uncontended: no output" "" "$out"
check "uncontended: nothing on tty" "" "$(cat "$TMP/tty")"

# detached holder
git -C "$TMP/repoA" checkout -q --detach
start_holder js "$TMP/repoA"
start_waiter js true
release
check "detached holder shows (detached)" "yes" \
  "$(grep -Eq '^suite-queue: waiting for js slot \(held by repoA \(detached\) since ' "$TMP/err" && echo yes || echo no)"
git -C "$TMP/repoA" checkout -q main

# missing holder file
start_holder js "$TMP/repoA"
rm -f "$LOCKDIR/js.holder"
start_waiter js true
release
check "missing holder file: held by unknown" "suite-queue: waiting for js slot (held by unknown)" "$(head -1 "$TMP/err")"
check "missing holder file: lock still works" "0" "$(cat "$TMP/wstatus")"

# unreadable holder file
start_holder js "$TMP/repoA"
chmod 000 "$LOCKDIR/js.holder"
start_waiter js true
release
chmod 600 "$LOCKDIR/js.holder" 2>/dev/null
check "unreadable holder file: held by unknown" "suite-queue: waiting for js slot (held by unknown)" "$(head -1 "$TMP/err")"
check "unreadable holder file: lock still works" "0" "$(cat "$TMP/wstatus")"

# sanitized holder text: an ESC sequence in the file never reaches the terminal.
start_holder js "$TMP/repoA"
printf 'repoA \033[31mmain since 12:00\n' > "$LOCKDIR/js.holder"
start_waiter js true
release
check "holder text: ESC removed" "no" "$(grep -q $'\033' "$TMP/err" && echo yes || echo no)"
check "holder text: printable remainder kept" "suite-queue: waiting for js slot (held by repoA [31mmain since 12:00)" "$(head -1 "$TMP/err")"

echo "== timeout (6) =="
start_holder js "$TMP/repoA"
rm -f "$TMP/ran"
(cd "$TMP/repoB" && SUITE_QUEUE_TTY="$NOTTY" SUITE_QUEUE_TIMEOUT=1 "$SUT" js touch "$TMP/ran") 2>"$TMP/err"; s=$?
[[ -e "$TMP/ran" ]] && ran=yes || ran=no
release
check "waiter exits 75" "75" "$s"
check "waiter's command never ran" "no" "$ran"
check "timeout message names the kind" "yes" "$(grep -q 'timed out after 1s waiting for js slot' "$TMP/err" && echo yes || echo no)"

echo "== killed suite frees the slot (8) =="
: > "$TMP/events"
start_holder js "$TMP/repoA"
start_waiter js sh -c "echo B-start >> '$TMP/events'"
kill -9 "$(cat "$TMP/pid")"
started=no
for i in $(seq 1 20); do
  if grep -q B-start "$TMP/events"; then started=yes; break; fi
  sleep 0.1
done
check "waiter starts within 2 s of kill -9 of the suite" "yes" "$started"
release

echo "== a signalled wrapper stops its suite before freeing the slot =="
rm -f "$TMP/child.pid"
(cd "$TMP/repoA" && SUITE_QUEUE_TTY="$NOTTY" exec "$SUT" js sh -c "echo \$\$ > '$TMP/child.pid'; exec sleep 30") &
wrapper=$!
wait_for "$TMP/child.pid"
kill -TERM "$wrapper"
wait "$wrapper" 2>/dev/null
child_alive=no; kill -0 "$(cat "$TMP/child.pid")" 2>/dev/null && child_alive=yes
check "suite is gone once the wrapper has exited" "no" "$child_alive"
check_status "slot is free afterwards" 0 env SUITE_QUEUE_TIMEOUT=2 SUITE_QUEUE_TTY="$NOTTY" "$SUT" js true

# INT to the wrapper alone is not passed on (Ctrl-C reaches the suite through
# the process group): the wrapper keeps waiting and keeps the slot.
rm -f "$TMP/child.pid"
(cd "$TMP/repoA" && SUITE_QUEUE_TTY="$NOTTY" exec "$SUT" js sh -c "echo \$\$ > '$TMP/child.pid'; exec sleep 30") &
wrapper=$!
wait_for "$TMP/child.pid"
kill -INT "$wrapper"; sleep 0.5
alive=no; kill -0 "$wrapper" 2>/dev/null && kill -0 "$(cat "$TMP/child.pid")" 2>/dev/null && alive=yes
check "INT to the wrapper: wrapper and suite keep running" "yes" "$alive"
check_status "INT to the wrapper: slot stays held" 75 env SUITE_QUEUE_TIMEOUT=1 SUITE_QUEUE_TTY="$NOTTY" "$SUT" js true
kill -TERM "$wrapper"; wait "$wrapper" 2>/dev/null

# QUIT is passed on as TERM, like TERM itself.
rm -f "$TMP/child.pid"
(cd "$TMP/repoA" && SUITE_QUEUE_TTY="$NOTTY" exec "$SUT" js sh -c "echo \$\$ > '$TMP/child.pid'; exec sleep 30") &
wrapper=$!
wait_for "$TMP/child.pid"
kill -QUIT "$wrapper"
wait "$wrapper" 2>/dev/null
child_alive=no; kill -0 "$(cat "$TMP/child.pid")" 2>/dev/null && child_alive=yes
check "QUIT to the wrapper: suite is gone once the wrapper has exited" "no" "$child_alive"

echo "== holder identity: repo from the main repo, branch outside git =="
git -C "$TMP/repoA" worktree add -q -b xyz "$TMP/wt/feat/xyz"
start_holder js "$TMP/wt/feat/xyz"
start_waiter js true
release
check "worktree holder shows the main repo name, not the worktree dir" \
  "yes" "$(grep -Eq '\(held by repoA xyz since ' "$TMP/err" && echo yes || echo no)"

mkdir -p "$TMP/plain"
start_holder js "$TMP/plain"
start_waiter js true
release
check "outside git: dir name and '-' branch" \
  "yes" "$(grep -Eq '\(held by plain - since ' "$TMP/err" && echo yes || echo no)"

echo "== lock dir tightened (19) =="
rm -rf "$HOME/.cache"; mkdir -p "$LOCKDIR"; chmod 755 "$LOCKDIR"
sq "$TMP/repoA" js true
check "pre-existing 755 dir becomes 700" "700" "$(stat -f %Lp "$LOCKDIR")"

echo "== a detached daemon does not keep the slot =="
rm -f "$TMP/daemon.pid"
sq "$TMP/repoA" js sh -c "sleep 31 >/dev/null 2>&1 & echo \$! > '$TMP/daemon.pid'; exit 0" >/dev/null 2>&1
SUITE_QUEUE_TIMEOUT=2 sq "$TMP/repoB" js true >/dev/null 2>&1; s=$?
check "second run acquires while the daemon lives" "0" "$s"
kill -9 "$(cat "$TMP/daemon.pid")" 2>/dev/null

echo "== lockf failures are not mistaken for busy/timeout =="
mkdir -p "$TMP/stub"
printf '#!/bin/sh\nexit 64\n' > "$TMP/stub/lockf"; chmod +x "$TMP/stub/lockf"
rm -f "$TMP/ran"
PATH="$TMP/stub:$PATH" sq "$TMP/repoA" js touch "$TMP/ran" 2>"$TMP/err"; s=$?
[[ -e "$TMP/ran" ]] && ran=yes || ran=no
check "probe failure: exits with lockf's status" "64" "$s"
check "probe failure: message" "suite-queue: lockf failed (64)" "$(cat "$TMP/err")"
check "probe failure: command never ran" "no" "$ran"
# busy on the probe (75), then a real failure while waiting (70)
rm -f "$TMP/count" "$TMP/ran"
printf '#!/bin/sh\nif [ -e "%s" ]; then exit 70; fi\n: > "%s"; exit 75\n' "$TMP/count" "$TMP/count" > "$TMP/stub/lockf"
PATH="$TMP/stub:$PATH" sq "$TMP/repoA" js touch "$TMP/ran" 2>"$TMP/err"; s=$?
[[ -e "$TMP/ran" ]] && ran=yes || ran=no
check "wait failure: exits with lockf's status" "70" "$s"
check "wait failure: reported as lockf failure, not timeout" "yes" \
  "$(grep -q 'lockf failed (70)' "$TMP/err" && ! grep -q 'timed out' "$TMP/err" && echo yes || echo no)"
check "wait failure: command never ran" "no" "$ran"

unset SUITE_QUEUE_FORCE
echo "== verified skip: fixtures =="
# Each case gets a fresh repo with committed files, a .gitignore and a subdir.
# The command appends a line to a marker file, so "ran" vs "skipped" is counted.
GC=(-c user.name=t -c user.email=t@t)
mk() {
  local d="$TMP/$1"
  make_repo "$d" main
  printf 1 > "$d/a.txt"; mkdir -p "$d/sub"; printf 1 > "$d/sub/b.txt"
  printf 'ignored.txt\n' > "$d/.gitignore"
  git -C "$d" add -A; git -C "$d" "${GC[@]}" commit -q -m files
}
M="$TMP/marker"
msq() { local d="$1"; shift; sq "$d" js sh -c "echo x >> '$M'" "$@"; }
mcount() { [[ -e "$M" ]] && wc -l < "$M" | tr -d ' ' || echo 0; }
recdir() { echo "$1/.git/suite-queue/passed"; }
recs() { find "$(recdir "$1")" -type f 2>/dev/null | wc -l | tr -d ' '; }
SKIP_RE='^suite-queue: skipped js — passed on this exact content at [0-9][0-9]:[0-9][0-9] \(SUITE_QUEUE_FORCE=1 to run\)$'

echo "== records (1, 2) =="
mk r1; rm -f "$M"
msq "$TMP/r1" 2>/dev/null
check "pass: one record exists" "1" "$(recs "$TMP/r1")"
rec="$(find "$(recdir "$TMP/r1")" -type f | head -1)"
check "pass: record is named by the sha256 of its content" "$(basename "$rec")" "$(shasum -a 256 < "$rec" | cut -d' ' -f1)"
mk r2; rm -f "$M"
sq "$TMP/r2" js false 2>/dev/null
check "failure: no record" "0" "$(recs "$TMP/r2")"
failsh="echo x >> '$M'; exit 1"
sq "$TMP/r2" js sh -c "$failsh" 2>/dev/null; sq "$TMP/r2" js sh -c "$failsh" 2>/dev/null
check "failure: the rerun runs the command" "2" "$(mcount)"

echo "== skip on match (3, 13) =="
mk s1; rm -f "$M"
msq "$TMP/s1" 2>/dev/null
msq "$TMP/s1" 2>"$TMP/err"; s=$?
check "second identical run skips the command" "1" "$(mcount)"
check "skip exits 0" "0" "$s"
check "skip prints one line in the agreed format" "yes" "$(grep -Eq "$SKIP_RE" "$TMP/err" && [[ "$(wc -l < "$TMP/err" | tr -d ' ')" == 1 ]] && echo yes || echo no)"
SUITE_QUEUE_FORCE=1 msq "$TMP/s1" 2>/dev/null
check "SUITE_QUEUE_FORCE=1 runs despite a record" "2" "$(mcount)"

echo "== new content runs (4, 5, 6) =="
mk n1; rm -f "$M"
msq "$TMP/n1" 2>/dev/null
printf 2 > "$TMP/n1/a.txt"; msq "$TMP/n1" 2>/dev/null
check "changed tracked file runs" "2" "$(mcount)"
git -C "$TMP/n1" checkout -q a.txt; msq "$TMP/n1" 2>/dev/null
check "restoring the recorded content skips again" "2" "$(mcount)"
printf 1 > "$TMP/n1/new.txt"; msq "$TMP/n1" 2>/dev/null
check "untracked file runs" "3" "$(mcount)"
rm "$TMP/n1/new.txt"
printf 3 > "$TMP/n1/a.txt"; git -C "$TMP/n1" "${GC[@]}" commit -q -am c3; msq "$TMP/n1" 2>/dev/null
check "committing content with no record runs" "4" "$(mcount)"
mk i1; rm -f "$M"; printf 1 > "$TMP/i1/ignored.txt"
msq "$TMP/i1" 2>/dev/null
printf 2 > "$TMP/i1/ignored.txt"; msq "$TMP/i1" 2>/dev/null
check "changed gitignored file still skips" "1" "$(mcount)"
mk d1; rm -f "$M"
msq "$TMP/d1" 2>/dev/null
sq "$TMP/d1" js sh -c "echo y >> '$M'" 2>/dev/null
check "different argv runs" "2" "$(mcount)"
(cd "$TMP/d1/sub" && SUITE_QUEUE_TTY="$NOTTY" "$SUT" js sh -c "echo x >> '$M'") 2>/dev/null
check "same argv from another subdirectory runs" "3" "$(mcount)"
(cd "$TMP/d1/sub" && SUITE_QUEUE_TTY="$NOTTY" "$SUT" js sh -c "echo x >> '$M'") 2>/dev/null
check "same argv from the same subdirectory skips" "3" "$(mcount)"

echo "== verify before commit (7, 8) =="
mk v1; rm -f "$M"
printf 2 > "$TMP/v1/a.txt"
msq "$TMP/v1" 2>/dev/null; msq "$TMP/v1" 2>/dev/null
check "dirty tree: runs every time" "2" "$(mcount)"
git -C "$TMP/v1" "${GC[@]}" commit -q -am c2; msq "$TMP/v1" 2>/dev/null
check "after committing that exact content, the next run skips" "2" "$(mcount)"
mk v2; rm -f "$M"
printf 9 > "$TMP/v2/new.txt"
msq "$TMP/v2" 2>/dev/null
git -C "$TMP/v2" add new.txt; git -C "$TMP/v2" "${GC[@]}" commit -q -m new; msq "$TMP/v2" 2>/dev/null
check "new file verified then committed: skips" "1" "$(mcount)"

echo "== racy edit is seen, not hashed from stale stat data (4) =="
# An edit that keeps the size and lands in the same second as the index write is
# only caught by git's racy check, which compares entries with the index file's
# own mtime. The temporary index must keep that mtime, or the old blob is reused
# and the edited content skips as the passed one. ctime is pinned out of the way.
mk rc; rm -f "$M"
git -C "$TMP/rc" config core.trustctime false
touch -t 202001010000 "$TMP/rc/a.txt"; git -C "$TMP/rc" update-index --refresh -q
touch -t 202001010000 "$TMP/rc/.git/index"
msq "$TMP/rc" 2>/dev/null
printf 2 > "$TMP/rc/a.txt"; touch -t 202001010000 "$TMP/rc/a.txt" "$TMP/rc/.git/index"
msq "$TMP/rc" 2>/dev/null
check "same-size edit in the index's second runs" "2" "$(mcount)"

echo "== edited mid-run is not recorded (9) =="
mk e1; sq "$TMP/e1" js sh -c 'echo y >> a.txt' 2>/dev/null
check "tracked file edited: no record" "0" "$(recs "$TMP/e1")"
mk e2; sq "$TMP/e2" js sh -c 'echo y > added.txt' 2>/dev/null
check "file added: no record" "0" "$(recs "$TMP/e2")"
mk e3; sq "$TMP/e3" js sh -c 'rm a.txt' 2>/dev/null
check "file removed: no record" "0" "$(recs "$TMP/e3")"

echo "== skip doesn't wait (10) =="
mk w1; rm -f "$M"
msq "$TMP/w1" 2>/dev/null
start_holder js "$TMP/w1"
rm -f "$TMP/wskip"
(cd "$TMP/w1" && SUITE_QUEUE_TTY="$NOTTY" SUITE_QUEUE_TIMEOUT=20 "$SUT" js sh -c "echo x >> '$M'" >/dev/null 2>&1; echo $? > "$TMP/wskip") &
skipper=$!
done_in_time=no
for i in $(seq 1 10); do [[ -s "$TMP/wskip" ]] && { done_in_time=yes; break; }; sleep 0.1; done
check "matching run returns within 1 s while the slot is held" "yes" "$done_in_time"
check "and did not run the command" "1" "$(mcount)"
release

echo "== red rerun clears the pass (11) =="
mk x1; rm -f "$M" "$TMP/hold" "$TMP/fail"
script="echo x >> '$M'; i=0; while [ -e '$TMP/hold' ] && [ \$i -lt 600 ]; do sleep 0.05; i=\$((i+1)); done; [ ! -e '$TMP/fail' ]"
sq "$TMP/x1" js sh -c "$script" 2>/dev/null
check "setup: pass recorded" "1" "$(recs "$TMP/x1")"
: > "$TMP/hold"; : > "$TMP/fail"
(SUITE_QUEUE_FORCE=1 sq "$TMP/x1" js sh -c "$script" >/dev/null 2>&1) &
forced=$!
for i in $(seq 1 100); do [[ "$(mcount)" == 2 ]] && break; sleep 0.1; done
check "forced rerun in flight: record already gone" "0" "$(recs "$TMP/x1")"
SUITE_QUEUE_TIMEOUT=1 sq "$TMP/x1" js sh -c "$script" 2>"$TMP/err"
check "concurrent normal run does not skip" "no" "$(grep -q skipped "$TMP/err" && echo yes || echo no)"
rm -f "$TMP/hold"; wait "$forced"
check "red forced rerun leaves no record" "0" "$(recs "$TMP/x1")"
sq "$TMP/x1" js sh -c "$script" 2>/dev/null
check "next normal run executes" "3" "$(mcount)"

# A pass that lands while a red rerun of the same content waits for the slot
# must not survive the red result.
# Same argv for both runs (so the same key): it passes on its first invocation
# and fails on its second, counted through the marker file.
mk x2; rm -f "$M" "$TMP/hold"
nth="echo x >> '$M'; i=0; while [ -e '$TMP/hold' ] && [ \$i -lt 600 ]; do sleep 0.05; i=\$((i+1)); done; [ \"\$(wc -l < '$M')\" -eq 1 ]"
: > "$TMP/hold"
(sq "$TMP/x2" js sh -c "$nth" >/dev/null 2>&1) &
passer=$!
for i in $(seq 1 100); do [[ "$(mcount)" == 1 ]] && break; sleep 0.1; done
(SUITE_QUEUE_TIMEOUT=20 sq "$TMP/x2" js sh -c "$nth" >/dev/null 2>"$TMP/err2") &
red=$!
wait_for "$TMP/err2"
rm -f "$TMP/hold"; wait "$passer"; wait "$red"
check "setup: the red rerun really ran second" "2" "$(mcount)"
check "pass recorded while a red rerun waited is gone after the red run" "0" "$(recs "$TMP/x2")"

# A run that never executes (timed out waiting) leaves a valid pass alone.
mk x3; rm -f "$M"
msq "$TMP/x3" 2>/dev/null
start_holder js "$TMP/x3"
SUITE_QUEUE_FORCE=1 SUITE_QUEUE_TIMEOUT=1 msq "$TMP/x3" 2>/dev/null; s=$?
release
check "timed-out run: exit 75" "75" "$s"
msq "$TMP/x3" 2>/dev/null
check "timed-out run: the earlier pass still skips" "1" "$(mcount)"

echo "== worktrees share records (12) =="
mk t1; rm -f "$M"
git -C "$TMP/t1" worktree add -q --detach "$TMP/t1wt"
msq "$TMP/t1" 2>/dev/null
msq "$TMP/t1wt" 2>/dev/null
check "second worktree on the same content skips" "1" "$(mcount)"

echo "== hook in a linked worktree's subdir =="
# git exports GIT_DIR, without GIT_WORK_TREE, to a hook run from a linked worktree;
# lefthook's root: then runs suite-queue in a subdirectory.
mk t2; rm -f "$M"
git -C "$TMP/t2" worktree add -q --detach "$TMP/t2wt"
hookdir="$(git -C "$TMP/t2wt" rev-parse --path-format=absolute --git-dir)"
msq "$TMP/t2wt/sub" 2>/dev/null
GIT_DIR="$hookdir" msq "$TMP/t2wt/sub" 2>/dev/null
check "hook env in a worktree subdir: a shell pass skips" "1" "$(mcount)"
printf 2 > "$TMP/t2wt/a.txt"; git -C "$TMP/t2wt" "${GC[@]}" commit -q -am c2
GIT_DIR="$hookdir" msq "$TMP/t2wt/sub" 2>/dev/null
check "hook env in a worktree subdir: changed content runs" "2" "$(mcount)"
GIT_DIR="$hookdir" SUITE_QUEUE_FORCE=1 sq "$TMP/t2wt/sub" js sh -c "printf '%s' \"\$GIT_DIR\" > '$TMP/childenv'" 2>/dev/null
check "hook env in a worktree subdir: the suite keeps the caller's GIT_DIR" "$hookdir" "$(cat "$TMP/childenv")"

echo "== outside git (14) =="
mkdir -p "$TMP/plain2"; rm -f "$M"
msq "$TMP/plain2" 2>/dev/null; msq "$TMP/plain2" 2>/dev/null
check "outside git: always runs" "2" "$(mcount)"
check "outside git: nothing recorded" "0" "$(find "$TMP/plain2" -type f | wc -l | tr -d ' ')"

echo "== index untouched (15) =="
mk ix; printf 2 > "$TMP/ix/a.txt"; git -C "$TMP/ix" add a.txt; printf 3 > "$TMP/ix/sub/b.txt"; printf 4 > "$TMP/ix/new.txt"
cp "$TMP/ix/.git/index" "$TMP/index.before"
msq "$TMP/ix" 2>/dev/null
check "real index is byte-identical after a run" "same" "$(cmp -s "$TMP/index.before" "$TMP/ix/.git/index" && echo same || echo different)"
check "staged state is unchanged" "a.txt" "$(git -C "$TMP/ix" diff --cached --name-only)"

echo "== age (16) =="
mk g1; rm -f "$M"
msq "$TMP/g1" 2>/dev/null
rec="$(find "$(recdir "$TMP/g1")" -type f | head -1)"
touch -t 202001010000 "$rec"
oldfake="$(recdir "$TMP/g1")/$(printf 'a%.0s' $(seq 1 64))"
printf junk > "$oldfake"; touch -t 202001010000 "$oldfake"
msq "$TMP/g1" 2>/dev/null
check "7-day-old record does not skip" "2" "$(mcount)"
check "stale record replaced by a fresh one" "yes" "$([[ -z "$(find "$rec" -mtime +7 2>/dev/null)" ]] && echo yes || echo no)"
check "old record of another key deleted on write" "no" "$([[ -e "$oldfake" ]] && echo yes || echo no)"
msq "$TMP/g1" 2>/dev/null
check "fresh record skips" "2" "$(mcount)"
# Validity and pruning agree: a record 7.5 days old is invalid, so it is pruned.
halfweek="$(recdir "$TMP/g1")/$(printf 'b%.0s' $(seq 1 64))"
printf junk > "$halfweek"; touch -t "$(date -v-180H +%Y%m%d%H%M)" "$halfweek"
printf 5 > "$TMP/g1/a.txt"; git -C "$TMP/g1" "${GC[@]}" commit -q -am c5; msq "$TMP/g1" 2>/dev/null
check "7.5-day-old record is pruned on write" "no" "$([[ -e "$halfweek" ]] && echo yes || echo no)"

echo "== index flags and submodules give no key =="
mk au; rm -f "$M"
msq "$TMP/au" 2>/dev/null
git -C "$TMP/au" update-index --assume-unchanged a.txt
printf 2 > "$TMP/au/a.txt"
msq "$TMP/au" 2>/dev/null
check "assume-unchanged file edited after a pass: the run executes" "2" "$(mcount)"
check "assume-unchanged: nothing recorded for the edited content" "1" "$(recs "$TMP/au")"
mk sw; rm -f "$M"
msq "$TMP/sw" 2>/dev/null
git -C "$TMP/sw" update-index --skip-worktree a.txt
printf 2 > "$TMP/sw/a.txt"
msq "$TMP/sw" 2>/dev/null
check "skip-worktree file edited after a pass: the run executes" "2" "$(mcount)"
mk gl; rm -f "$M"
git -C "$TMP/gl" update-index --add --cacheinfo "160000,$(git -C "$TMP/gl" rev-parse HEAD),mod"
git -C "$TMP/gl" "${GC[@]}" commit -q -m gitlink
msq "$TMP/gl" 2>/dev/null; msq "$TMP/gl" 2>/dev/null
check "repo with a submodule: runs every time" "2" "$(mcount)"
check "repo with a submodule: nothing recorded" "0" "$(recs "$TMP/gl")"

echo "== key is taken again once the slot is ours (11) =="
mk z1; rm -f "$M" "$TMP/flag" "$TMP/err3"
zs="echo x >> '$M'; [ ! -e '$TMP/flag' ]"
sq "$TMP/z1" js sh -c "$zs" 2>/dev/null
check "setup: pass recorded on content Y" "1" "$(recs "$TMP/z1")"
SUITE_QUEUE_FORCE=1 start_holder js "$TMP/repoA"
printf 2 > "$TMP/z1/a.txt"
(cd "$TMP/z1" && SUITE_QUEUE_TTY="$NOTTY" SUITE_QUEUE_TIMEOUT=20 SUITE_QUEUE_FORCE=1 "$SUT" js sh -c "$zs" >/dev/null 2>"$TMP/err3") &
wait_for "$TMP/err3"
git -C "$TMP/z1" checkout -q a.txt
: > "$TMP/flag"
release
check "setup: the waiting run executed" "2" "$(mcount)"
check "red run on the content it really tested clears that record" "0" "$(recs "$TMP/z1")"
sq "$TMP/z1" js sh -c "$zs" 2>/dev/null
check "next run on that content executes" "3" "$(mcount)"

echo "== fails safe (17) =="
mk f1; rm -f "$M"
msq "$TMP/f1" 2>/dev/null
rm -rf "$TMP/f1/.git/suite-queue/passed"; chmod 500 "$TMP/f1/.git/suite-queue"
msq "$TMP/f1" 2>/dev/null; msq "$TMP/f1" 2>/dev/null
check "records dir unwritable: the command runs every time" "3" "$(mcount)"
sq "$TMP/f1" js sh -c 'exit 3' 2>/dev/null; s=$?
check "records dir unwritable: own exit status" "3" "$s"
chmod 700 "$TMP/f1/.git/suite-queue"
mkdir -p "$TMP/gstub"; REALGIT="$(command -v git)"
printf '#!/bin/sh\ncase " $* " in *" write-tree "*) exit 1;; esac\nexec "%s" "$@"\n' "$REALGIT" > "$TMP/gstub/git"; chmod +x "$TMP/gstub/git"
mk f2; rm -f "$M"
PATH="$TMP/gstub:$PATH" msq "$TMP/f2" 2>/dev/null; PATH="$TMP/gstub:$PATH" msq "$TMP/f2" 2>/dev/null
check "write-tree fails: the command runs every time" "2" "$(mcount)"
check "write-tree fails: nothing recorded" "0" "$(recs "$TMP/f2")"
PATH="$TMP/gstub:$PATH" sq "$TMP/f2" js sh -c 'exit 3' 2>/dev/null; s=$?
check "write-tree fails: own exit status" "3" "$s"

echo "== forged records (22) =="
mk q1; rm -f "$M"
msq "$TMP/q1" 2>/dev/null
rec="$(find "$(recdir "$TMP/q1")" -type f | head -1)"
cp "$rec" "$TMP/rec.copy"
printf junk > "$rec"
msq "$TMP/q1" 2>/dev/null
check "right name, wrong content: runs" "2" "$(mcount)"
rm -f "$rec"; cp "$TMP/rec.copy" "$(recdir "$TMP/q1")/$(printf 'b%.0s' $(seq 1 64))"
msq "$TMP/q1" 2>/dev/null
check "right content, wrong name: runs" "3" "$(mcount)"

echo "== pruning stays in its lane (23) =="
mk p1; rm -f "$M"
mkdir -p "$(recdir "$TMP/p1")"
pd="$(recdir "$TMP/p1")"
h64="$(printf 'c%.0s' $(seq 1 64))"
printf x > "$pd/$h64"
printf x > "$pd/notes.txt"
printf x > "$pd/$(printf 'd%.0s' $(seq 1 63))"
printf x > "$pd/$(printf 'e%.0s' $(seq 1 65))"
printf x > "$pd/$(printf 'F%.0s' $(seq 1 64))"
printf x > "$pd/$h64.tmp.1"
printf x > "$pd/$h64.tmp.x"
for f in "$pd"/*; do touch -t 202001010000 "$f"; done
printf x > "$pd/$(printf '9%.0s' $(seq 1 64)).tmp.2"
msq "$TMP/p1" 2>/dev/null
check "old 64-hex record pruned" "no" "$([[ -e "$pd/$h64" ]] && echo yes || echo no)"
check "old <64 hex>.tmp.<digits> leftover pruned" "no" "$([[ -e "$pd/$h64.tmp.1" ]] && echo yes || echo no)"
check "fresh <64 hex>.tmp.<digits> (a write in flight) survives" "yes" "$([[ -e "$pd/$(printf '9%.0s' $(seq 1 64)).tmp.2" ]] && echo yes || echo no)"
survivors=0
for n in notes.txt "$(printf 'd%.0s' $(seq 1 63))" "$(printf 'e%.0s' $(seq 1 65))" "$(printf 'F%.0s' $(seq 1 64))" "$h64.tmp.x"; do
  [[ -e "$pd/$n" ]] && survivors=$((survivors + 1))
done
check "other old files survive" "5" "$survivors"

echo "== private records dir (24) =="
mk m1
msq "$TMP/m1" 2>/dev/null
check "passed/ is mode 700" "700" "$(stat -f %Lp "$(recdir "$TMP/m1")")"
mk m2; mkdir -p "$(recdir "$TMP/m2")"; chmod 755 "$(recdir "$TMP/m2")"
msq "$TMP/m2" 2>/dev/null
check "pre-existing 755 passed/ becomes 700" "700" "$(stat -f %Lp "$(recdir "$TMP/m2")")"

echo "== end to end through lefthook (18) =="
if command -v lefthook >/dev/null 2>&1; then
  mk lh; E2E_LOG="$TMP/e2e.log"; rm -f "$E2E_LOG"
  printf 'pre-push:\n  commands:\n    t:\n      run: %s js sh -c "echo run >> %s"\n' "$SUT" "$E2E_LOG" > "$TMP/lh/lefthook.yml"
  git -C "$TMP/lh" add lefthook.yml; git -C "$TMP/lh" "${GC[@]}" commit -q -m hook
  printf 2 > "$TMP/lh/a.txt"
  (cd "$TMP/lh" && SUITE_QUEUE_TTY="$NOTTY" SUITE_QUEUE_FORCE=1 lefthook run pre-push --force --no-tty --command t) >/dev/null 2>&1
  git -C "$TMP/lh" "${GC[@]}" commit -q -am c2
  (cd "$TMP/lh" && SUITE_QUEUE_TTY="$NOTTY" lefthook run pre-push --force --no-tty --command t) >/dev/null 2>&1
  check "verify, commit, push: the suite executes exactly once" "1" "$(wc -l < "$E2E_LOG" 2>/dev/null | tr -d ' ')"

  # `output: [failure]` hides a green job; the Verify form's LEFTHOOK_OUTPUT brings it back
  # without changing the argv the push skips on.
  mk lho; E2E_LOG="$TMP/e2e-out.log"; rm -f "$E2E_LOG"
  printf 'output:\n  - failure\npre-push:\n  commands:\n    t:\n      run: %s js sh -c "echo run >> %s; echo verify-marker"\n' "$SUT" "$E2E_LOG" > "$TMP/lho/lefthook.yml"
  git -C "$TMP/lho" add lefthook.yml; git -C "$TMP/lho" "${GC[@]}" commit -q -m hook
  printf 2 > "$TMP/lho/a.txt"
  out=$(cd "$TMP/lho" && SUITE_QUEUE_TTY="$NOTTY" SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out lefthook run pre-push --force --no-tty --command t 2>&1)
  check "output: [failure]: the Verify form prints the green job's output" "yes" "$([[ "$out" == *verify-marker* ]] && echo yes || echo no)"
  git -C "$TMP/lho" "${GC[@]}" commit -q -am c2
  (cd "$TMP/lho" && SUITE_QUEUE_TTY="$NOTTY" lefthook run pre-push --force --no-tty --command t) >/dev/null 2>&1
  check "output: [failure]: verify, commit, push: the suite executes exactly once" "1" "$(wc -l < "$E2E_LOG" 2>/dev/null | tr -d ' ')"
else
  echo "  skip lefthook not on PATH: end-to-end case not run"
fi

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
