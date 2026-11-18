#!/usr/bin/env python3
"""Tests for gate_log.py.

Run: python3 claude/skills/usage-audit/scripts/test_gate_log.py

Every test points GATE_LOG at a temp file and builds throwaway git repos -- the suite
never touches the real ~/.claude/gate-log.jsonl. Ledger fixtures are synthetic; the
sentinel phrases in them prove that no finding text is ever copied into the log.
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "gate_log.py")
INSTALL = os.path.join(HERE, "..", "..", "..", "..", "install.sh")
sys.path.insert(0, HERE)

# Ledger dates are local time; pin the zone so the expected UTC value is fixed.
os.environ["TZ"] = "UTC"
time.tzset()

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if not ok and detail else ""))


def run_cli(args, cwd, log, env_extra=None):
    env = dict(os.environ, GATE_LOG=log, TZ="UTC")
    env.update(env_extra or {})
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=test", *args],
                   cwd=cwd, check=True, capture_output=True)


def make_repo(path):
    os.makedirs(path)
    git(path, "init", "-q")
    git(path, "commit", "-q", "--allow-empty", "-m", "init")


def read_lines(log):
    if not os.path.exists(log):
        return []
    with open(log) as fh:
        return fh.read().splitlines()


def flatten(d):
    """{"--gate": "5s", "--skipped": None} -> ["--gate", "5s", "--skipped"]."""
    out = []
    for key, value in d.items():
        out.append(key)
        if value is not None:
            out.append(value)
    return out


BASE = {"--gate": "5s", "--lane": "workflow", "--tier": "B", "--trigger": "adds a dependency",
        "--slug": "demo", "--found": "0,1,2"}


def args_with(**over):
    """BASE with overrides; a None value drops the key, '--x=..' keys are one token."""
    merged = dict(BASE)
    for key, value in over.items():
        flag = "--" + key.replace("_", "-")
        merged.pop(flag, None)
        if value is not False:
            merged[flag] = value
    return ["add", *flatten(merged)]


# --- ledger fixtures ---------------------------------------------------------
# Shaped like real Codex ledgers (codex/bin/codex-audit writes them). SENTINEL-* marks finding
# text that must never reach the log.
TWO_ROUND = """\
# Gate 1b — demo

<!-- thread_id: t-1 -->
<!-- cwd: /work/demo -->

- **artifact:** `~/work/demo.md`
- **artifact revision:** `abc1234`
- **date:** 2026-10-17 03:01
- **reviewer:** codex `codex-cli 0.152.0`, profile `audit`
- **profile:** /work/docs/ai-profile.md
- **rounds:** 2

## Round 1 — Codex, verbatim

## BLOCKER

None.

## MAJOR

### 1b-F01 — SENTINEL-TITLE first
- evidence: `demo.md:1` — SENTINEL-EVIDENCE
- failure path: SENTINEL-PATH
- smallest fix: SENTINEL-FIX

### 1b-F02 — second
- evidence: `demo.md:2`
- failure path: x
- smallest fix: y

### 1b-F03 — third
- evidence: `demo.md:3`
- failure path: x
- smallest fix: y

### 1b-F04 — fourth
- evidence: `demo.md:4`
- failure path: x
- smallest fix: y

## MINOR

- a minor SENTINEL-MINOR
- another minor
<!-- round 1 wall clock: 256s -->

## Response to round 1 — Claude

| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | MAJOR | accepted | SENTINEL-REASON |
| 1b-F02 | MAJOR | rejected | cannot occur |
| 1b-F03 | MAJOR | human | product call |
| 1b-F04 | MAJOR | rejected | also fine |

## Round 2 — Codex, verbatim

## Verdicts

| id | round-1 severity | response | verdict | note |
|---|---|---|---|---|
| 1b-F01 | MAJOR | accepted | resolved | fine |
| 1b-F02 | MAJOR | rejected | maintain | still real |
| 1b-F03 | MAJOR | human | resolved | fine |

## Regressions

### R01 — a new problem (from 1b-F01)
- evidence: `demo.md:9`
- failure path: x
- smallest fix: y
<!-- round 2 wall clock: 83s -->

## For the human

These did not close.

| id | severity | why it is open | note |
|---|---|---|---|
| 1b-F02 | MAJOR | Codex maintains it | still real |
| 1b-F03 | MAJOR | product decision, not the models' | — |
| regression | — | introduced by the fixes | R01 — a new problem |

## Metrics

| | |
|---|---|
| round-1 findings (BLOCKER+MAJOR) | 3 |
"""

CLEAN_2B = """\
# Gate 2b — clean

<!-- thread_id: t-2 -->

- **artifact:** `~/work/clean.md`
- **date:** 2026-10-15 11:29
- **rounds:** 1
- **outcome:** no BLOCKER/MAJOR — round 2 not required (design §4.2)

## Round 1 — Codex, verbatim

## BLOCKER

None.

## MAJOR

None.

## MINOR

- first minor
- second minor
<!-- round 1 wall clock: 147s -->
"""

BLOCKER_6B = """\
# Gate 6b — feature-x

- **date:** 2026-10-16 09:00
- **rounds:** 1

## Round 1 — Codex, verbatim

## BLOCKER

### 6b-F01 — a blocker
- evidence: `x.rb:1`

## MAJOR

### 6b-F02 — a major
- evidence: `x.rb:2`

## MINOR

None.
<!-- round 1 wall clock: 10s -->
"""

SKIPPED = """\
# Gate 1b — skipme

- **skipped:** reviewer disabled by profile (codex_reviewer: no)
- **date:** 2026-10-14 08:30
- **artifact:** `~/work/skipme.md`

This gate did not run.
"""

UNPARSEABLE = """\
# Gate 1b — bad

- **date:** 2026-10-13 08:30
- **rounds:** 1
- **outcome:** UNPARSEABLE — the output does not follow the contract's format, so
  the finding count is meaningless. Not recorded as clean; read it yourself.

## Round 1 — Codex, verbatim

I reviewed the spec and found some things.
"""

NO_ROUND = """\
# Gate 2b — noround

- **date:** 2026-10-12 08:30
- **rounds:** 1
"""

# The counting rules themselves are tested against `codex-audit scorecard` in
# codex/bin/test_codex_audit.sh. Here only the end-to-end record shape is checked.

# Codex placed F01 under BLOCKER; Claude's table labelled it MAJOR.
MISLABELLED = """\
# Gate 1b — mislabel

<!-- thread_id: t-m -->

- **date:** 2026-10-09 08:30
- **rounds:** 1

## Round 1 — Codex, verbatim

## BLOCKER

### 1b-F01 — really a blocker

## MAJOR

None.

## MINOR

None.

## Response to round 1 — Claude

| id | severity | status | change / reason |
|---|---|---|---|
| 1b-F01 | MAJOR | accepted | fixed |
"""

# A bare "## " heading used to raise IndexError and stop the whole import.
BARE_HEADING = """\
# Gate 1b — bare

<!-- thread_id: t-b -->

- **date:** 2026-10-08 08:30
- **rounds:** 1

## Round 1 — Codex, verbatim

## MAJOR

### 1b-F01 — one
## BARE

## MINOR

None.
""".replace("## BARE", "## ")

LEDGER_FILES = {
    "demo-1b.md": TWO_ROUND,
    "clean-2b.md": CLEAN_2B,
    "feature-x-6b-pr2.md": BLOCKER_6B,
    "skipme-1b.md": SKIPPED,
    "bad-1b.md": UNPARSEABLE,
    "noround-2b.md": NO_ROUND,
    # An archive of a --rerun-replaced review: its own run, told apart by its thread.
    "demo-1b.md.superseded-20261017T000000Z.md": TWO_ROUND.replace("t-1", "t-0"),
    "aaa-bare-1b.md": BARE_HEADING,
    # Not a ledger at all: skipped without a word, unlike a ledger that cannot be recorded.
    "NOTES.md": "just some notes\n",
    "demo-1b.events.jsonl": '{"type":"thread.started"}\n',
}

SECTION5_KEYS = {"ts", "repo", "slug", "lane", "tier", "trigger", "gate", "pr", "thread", "found", "accepted",
                 "rejected", "deferred", "human", "skipped", "rounds", "wall_s", "source"}


def write_ledgers(folder):
    os.makedirs(folder, exist_ok=True)
    for name, text in LEDGER_FILES.items():
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(text)


def main():
    with tempfile.TemporaryDirectory() as td:
        repo = os.path.join(td, "acme")
        make_repo(repo)
        wt = os.path.join(td, "acme-wt")
        git(repo, "worktree", "add", "-q", wt)

        # --- Task 1: gate-log add ----------------------------------------------
        # AC1
        log = os.path.join(td, "ac1.jsonl")
        r = run_cli(["add", "--gate", "5s", "--lane", "workflow", "--tier", "B",
                     "--trigger", "adds a dependency", "--slug", "demo", "--pr", "2", "--found", "0,1,2",
                     "--accepted", "0,1,0", "--rejected", "1", "--human", "1"], repo, log)
        lines = read_lines(log)
        rec = json.loads(lines[0]) if lines else {}
        check("1a. a valid add exits 0 and appends exactly one line",
              r.returncode == 0 and len(lines) == 1, f"rc={r.returncode} {r.stderr}")
        check("1b. the tool fills ts, repo and source",
              rec.get("repo") == "acme" and rec.get("source") == "claude"
              and rec.get("ts", "").endswith("+00:00"), json.dumps(rec))
        check("1c. the record carries the arguments as given",
              rec.get("gate") == "5s" and rec.get("lane") == "workflow"
              and rec.get("tier") == "B" and rec.get("trigger") == "adds a dependency"
              and rec.get("slug") == "demo" and rec.get("pr") == 2
              and rec.get("found") == {"blocker": 0, "major": 1, "minor": 2}
              and rec.get("accepted") == {"blocker": 0, "major": 1, "minor": 0}
              and (rec.get("rejected"), rec.get("deferred"), rec.get("human")) == (1, 0, 1)
              and rec.get("skipped") is False, json.dumps(rec))

        log = os.path.join(td, "ac1-light.jsonl")
        r = run_cli(args_with(lane="light", tier="routine", trigger=False), repo, log)
        lines = read_lines(log)
        check("1d. the light lane is a valid lane",
              r.returncode == 0 and len(lines) == 1
              and json.loads(lines[0]).get("lane") == "light", f"rc={r.returncode} {r.stderr}")
        check("1e. a routine record carries no trigger",
              lines and "trigger" not in json.loads(lines[0]), lines[0] if lines else "")

        # AC2: each bad call exits non-zero, names the field, and leaves the log alone.
        log = os.path.join(td, "ac2.jsonl")
        with open(log, "w") as fh:
            fh.write('{"existing": true}\n')
        before = open(log, "rb").read()
        cases = [
            ("unknown gate", args_with(gate="nope"), "gate"),
            ("unknown lane", args_with(lane="nope"), "lane"),
            ("unknown tier", args_with(tier="nope"), "tier"),
            ("tier omitted on a manual add", args_with(tier=False), "tier"),
            # The tier is named by quoting its clause; no clause to quote means routine.
            ("Tier B with no trigger", args_with(trigger=False), "trigger"),
            ("Tier A with no trigger", args_with(tier="A", trigger=False), "trigger"),
            ("a trigger on a routine record", args_with(tier="routine"), "trigger"),
            ("a trigger with a newline", args_with(trigger="a\nb"), "trigger"),
            ("a trigger with an escape byte", args_with(trigger="a\x1bb"), "trigger"),
            ("a trigger over 300 characters", args_with(trigger="x" * 301), "trigger"),
            ("negative found", args_with(**{"found": False}) + ["--found=-1,0,0"], "found"),
            ("a triple of two", args_with(found="1,2"), "found"),
            ("negative rejected", args_with(rejected="-1"), "rejected"),
            ("accepted above found for one severity",
             args_with(found="0,1,0", accepted="0,2,0"), "accepted"),
            ("outcomes summing above found",
             args_with(found="0,1,0", accepted="0,1,0", rejected="1"), "outcome"),
        ]
        for label, argv, field in cases:
            r = run_cli(argv, repo, log)
            check(f"2. {label}: non-zero and names '{field}'",
                  r.returncode != 0 and f"invalid {field}" in r.stderr,
                  f"rc={r.returncode} stderr={r.stderr!r}")
        check("2. none of them wrote anything", open(log, "rb").read() == before)

        # AC3
        log = os.path.join(td, "ac3.jsonl")
        run_cli(args_with(), wt, log)
        rec = json.loads((read_lines(log) or ["{}"])[0])
        check("3. from a linked worktree repo is the main checkout's basename",
              rec.get("repo") == "acme", str(rec.get("repo")))

        # AC4
        log = os.path.join(td, "missing", "dir", "gate-log.jsonl")
        r = run_cli(args_with(), repo, log)
        check("4a. a missing log directory is created", r.returncode == 0
              and len(read_lines(log)) == 1, r.stderr)
        first = read_lines(log)[0]
        run_cli(args_with(slug="second"), repo, log)
        after = read_lines(log)
        check("4b. a pre-existing line survives another add",
              len(after) == 2 and after[0] == first)

        # AC5: lines far larger than a pipe buffer, from 8 writers at once.
        log = os.path.join(td, "ac5.jsonl")
        pad = "x" * 3000

        def worker(n):
            for i in range(25):
                run_cli(args_with(slug=f"w{n}-{i}-{pad}"), repo, log)

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(worker, range(8)))
        lines = read_lines(log)
        slugs = set()
        for line in lines:
            try:
                slugs.add(json.loads(line)["slug"])
            except (ValueError, KeyError):
                pass
        check("5. 8 processes x 25 adds leave 200 intact JSON lines",
              len(lines) == 200 and len(slugs) == 200,
              f"lines={len(lines)} intact={len(slugs)}")

        # AC18
        log = os.path.join(td, "ac18.jsonl")
        stray = os.path.join(td, "stray.jsonl")
        for flag in ("--log", "--output", "--bogus"):
            r = run_cli(args_with() + [flag, stray], repo, log)
            check(f"18. {flag} exits non-zero and writes nothing",
                  r.returncode != 0 and not os.path.exists(log) and not os.path.exists(stray),
                  f"rc={r.returncode}")

        # AC19
        log = os.path.join(td, "ac19.jsonl")
        for label, slug in (("a newline", "a\nb"), ("an escape byte", "a\x1bb")):
            r = run_cli(args_with(slug=slug), repo, log)
            check(f"19. a slug with {label} is rejected, nothing written",
                  r.returncode != 0 and "invalid slug" in r.stderr and not os.path.exists(log),
                  f"rc={r.returncode} {r.stderr!r}")
        bad_repo = os.path.join(td, "bad\nrepo")
        make_repo(bad_repo)
        r = run_cli(args_with(), bad_repo, log)
        check("19. a repo name with a newline is rejected, nothing written",
              r.returncode != 0 and "invalid repo" in r.stderr and not os.path.exists(log),
              f"rc={r.returncode} {r.stderr!r}")

        # Outside a git repo there is no repo to name.
        plain = os.path.join(td, "plain")
        os.makedirs(plain)
        log = os.path.join(td, "nogit.jsonl")
        r = run_cli(args_with(), plain, log)
        check("3b. outside a git repository the add fails and writes nothing",
              r.returncode != 0 and not os.path.exists(log), f"rc={r.returncode}")

        # --- Task 2: the ledger parser, add --ledger, import-codex --------------
        import gate_log  # noqa: E402  (imported late so task 1's tests run without it)

        led_dir = os.path.join(td, "ledgers")
        write_ledgers(led_dir)

        def parse(name):
            return gate_log.parse_ledger(os.path.join(led_dir, name))

        # AC7: two rounds, a response table, one regression.
        rec = parse("demo-1b.md")
        check("7a. a two-round ledger: round-1 findings plus the regression as a major",
              rec and rec["found"] == {"blocker": 0, "major": 5, "minor": 2},
              json.dumps(rec))
        # The round-2 verdicts table repeats the same ids with the same "accepted" column; a
        # parser that reads every table would report 2 here.
        check("7b. accepted per severity from the response table only, minor unknown",
              rec and rec["accepted"] == {"blocker": 0, "major": 1, "minor": None}, json.dumps(rec))
        # F02 (maintained) and F03 (human) are escalated, so they leave rejected; the
        # regression is a third row of the For-the-human table. Only F04 stays rejected.
        check("7c. human is the For-the-human rows; escalated ids leave rejected",
              rec and (rec["rejected"], rec["deferred"], rec["human"]) == (1, 0, 3),
              json.dumps(rec))
        check("7c2. the ledger's thread id is kept for the run key",
              rec and rec.get("thread") == "t-1", json.dumps(rec))
        check("7e. gate and slug from the filename; ts from the date header, as UTC",
              rec and rec["gate"] == "1b" and rec["slug"] == "demo" and "pr" not in rec
              and rec["ts"] == "2026-10-17T03:01:00+00:00", json.dumps(rec))
        check("7f. rounds from the header; wall_s sums every round's clock",
              rec and rec["rounds"] == 2 and rec["wall_s"] == 339, json.dumps(rec))
        check("7g. a ledger that holds a review is not a skip",
              rec and rec["skipped"] is False)

        rec = parse("clean-2b.md")
        check("7h. a clean one-round ledger maps to zero outcomes and null minor acceptance",
              rec and rec["found"] == {"blocker": 0, "major": 0, "minor": 2}
              and rec["accepted"] == {"blocker": 0, "major": 0, "minor": None}
              and (rec["rejected"], rec["deferred"], rec["human"]) == (0, 0, 0)
              and rec["rounds"] == 1 and rec["wall_s"] == 147, json.dumps(rec))

        rec = parse("feature-x-6b-pr2.md")
        check("7i. a -pr2 suffix becomes pr 2 and the slug stays clean",
              rec and rec["pr"] == 2 and rec["slug"] == "feature-x" and rec["gate"] == "6b",
              json.dumps(rec))
        check("7j. findings with no response table: acceptance unknown, not zero",
              rec and rec["found"] == {"blocker": 1, "major": 1, "minor": 0}
              and rec["accepted"] == {"blocker": None, "major": None, "minor": None},
              json.dumps(rec))
        claude_null = {"ts": "2026-10-17T00:00:00+00:00", "repo": "r", "slug": "s",
                       "lane": "workflow", "tier": "B", "gate": "5s",
                       "found": {"blocker": 0, "major": 1, "minor": 0},
                       "accepted": {"blocker": 0, "major": None, "minor": 0},
                       "rejected": 0, "deferred": 0, "human": 0, "skipped": False,
                       "source": "claude"}
        try:
            gate_log.validate_record(claude_null)
            refused = False
        except gate_log.GateLogError:
            refused = True
        check("7k. a Claude record may never leave acceptance unknown", refused)

        # AC8
        rec = parse("skipme-1b.md")
        check("8a. a skip ledger yields skipped true and zero counts",
              rec and rec["skipped"] is True and rec["found"] == {"blocker": 0, "major": 0, "minor": 0}
              and rec["ts"] == "2026-10-14T08:30:00+00:00" and "rounds" not in rec,
              json.dumps(rec))
        check("8b. an UNPARSEABLE ledger is not recorded", parse("bad-1b.md") is None)
        check("8c. a ledger with no round 1 is not recorded", parse("noround-2b.md") is None)

        # A ledger whose table label disagrees with Codex's section still yields a valid record.
        mis = os.path.join(td, "mislabel-1b.md")
        with open(mis, "w") as fh:
            fh.write(MISLABELLED)
        try:
            rec = gate_log.ledger_record(mis, "acme", "import")
        except gate_log.GateLogError as exc:
            rec = {"error": str(exc)}
        check("2b. a mislabelled response row yields a valid record, bucketed by section",
              rec.get("found", {}).get("blocker") == 1 and rec.get("accepted", {}).get("blocker") == 1,
              json.dumps(rec))

        # add --ledger
        log = os.path.join(td, "ledger-add.jsonl")
        r = run_cli(["add", "--ledger", os.path.join(led_dir, "demo-1b.md")], repo, log)
        lines = read_lines(log)
        rec = json.loads(lines[0]) if lines else {}
        check("7k. add --ledger writes one codex record from the ledger",
              r.returncode == 0 and len(lines) == 1 and rec.get("source") == "codex"
              and rec.get("tier") is None and rec.get("lane") == "workflow"
              and rec.get("repo") == "acme" and rec.get("gate") == "1b", f"{r.stderr} {rec}")
        r = run_cli(["add", "--ledger", os.path.join(led_dir, "bad-1b.md")], repo, log)
        check("8d. add --ledger on an unrecordable ledger fails loudly and writes nothing",
              r.returncode != 0 and "bad-1b.md" in r.stderr and len(read_lines(log)) == 1,
              f"rc={r.returncode} {r.stderr!r}")
        r = run_cli(["add", "--ledger", os.path.join(led_dir, "demo-1b.md"), "--gate", "5s"],
                    repo, log)
        check("7l. add --ledger refuses record fields given by hand",
              r.returncode != 0 and "invalid ledger" in r.stderr and len(read_lines(log)) == 1,
              f"rc={r.returncode} {r.stderr!r}")
        r = run_cli(["add", "--ledger", os.path.join(led_dir, "demo-1b.md"), "--tier", "B",
                     "--trigger", "adds a dependency"], repo, log)
        lines = read_lines(log)
        rec = json.loads(lines[-1]) if len(lines) == 2 else {}
        check("7o. add --ledger records the tier and trigger codex-audit passes on",
              r.returncode == 0 and rec.get("tier") == "B"
              and rec.get("trigger") == "adds a dependency" and rec.get("source") == "codex",
              f"rc={r.returncode} {r.stderr!r} {rec}")
        r = run_cli(["add", "--ledger", os.path.join(led_dir, "demo-1b.md"), "--tier", "B"],
                    repo, log)
        check("7p. add --ledger applies the same tier/trigger rule as a manual add",
              r.returncode != 0 and "invalid trigger" in r.stderr and len(read_lines(log)) == 2,
              f"rc={r.returncode} {r.stderr!r}")

        # A record written before `trigger` existed must stay readable by the scorecard.
        legacy = dict(claude_null, accepted={"blocker": 0, "major": 1, "minor": 0})
        try:
            gate_log.validate_record(legacy)
            legacy_ok = True
        except gate_log.GateLogError as exc:
            legacy_ok = str(exc)
        check("7q. a Tier B record with no trigger (written before it existed) still validates",
              legacy_ok is True, str(legacy_ok))
        try:
            gate_log.validate_record(dict(legacy, trigger="a\x1bb"))
            refused = False
        except gate_log.GateLogError:
            refused = True
        check("7r. validate_record refuses a trigger with control characters", refused)

        # import-codex
        imp = os.path.join(td, "imp")
        make_repo(imp)
        write_ledgers(os.path.join(imp, ".git", "codex-audit"))
        log = os.path.join(td, "import.jsonl")
        r = run_cli(["import-codex", imp], td, log)
        recs = [json.loads(line) for line in read_lines(log)]
        names = sorted((x["slug"], x["gate"], x.get("pr")) for x in recs)
        check("7m. import-codex records each parseable ledger and skip, nothing else",
              r.returncode == 0 and names == [("aaa-bare", "1b", None), ("clean", "2b", None),
                                             ("demo", "1b", None), ("demo", "1b", None),
                                             ("feature-x", "6b", 2), ("skipme", "1b", None)],
              f"rc={r.returncode} {names} {r.stderr!r}")
        check("1a. a --rerun archive is imported as its own run, told apart by thread",
              sorted(x.get("thread", "") for x in recs if x["slug"] == "demo") == ["t-0", "t-1"],
              str([x.get("thread") for x in recs]))
        check("4b. a bare '## ' ledger imports with no traceback, and later ledgers follow",
              "Traceback" not in r.stderr and any(x["slug"] == "feature-x" for x in recs),
              r.stderr)
        check("7n. imported records are source import, repo from the path, tier null",
              recs and all(x["source"] == "import" and x["repo"] == "imp" and x["tier"] is None
                           for x in recs))
        check("8e. the unrecordable ledgers are reported on stderr",
              "bad-1b.md" in r.stderr and "noround-2b.md" in r.stderr, r.stderr)
        check("8g. a .md file that is not a ledger is skipped silently",
              "NOTES.md" not in r.stderr and "skipped 2" in r.stdout, r.stderr + r.stdout)
        r = run_cli(["import-codex", plain], td, os.path.join(td, "never.jsonl"))
        check("8f. import-codex on a non-repository fails and writes nothing",
              r.returncode != 0 and not os.path.exists(os.path.join(td, "never.jsonl")))

        # A ledger the wrapper cannot read is reported once and does not stop the import.
        unr = os.path.join(td, "unr")
        make_repo(unr)
        udir = os.path.join(unr, ".git", "codex-audit")
        os.makedirs(udir)
        for fname in ("locked-1b.md", "ok-2b.md"):
            with open(os.path.join(udir, fname), "w") as fh:
                fh.write(CLEAN_2B)
        os.chmod(os.path.join(udir, "locked-1b.md"), 0)
        ulog = os.path.join(td, "unr.jsonl")
        r = run_cli(["import-codex", unr], td, ulog)
        os.chmod(os.path.join(udir, "locked-1b.md"), 0o644)
        check("1b. an unreadable ledger is reported once; the readable one is still imported",
              r.returncode == 0 and r.stderr.count("locked-1b.md") == 1
              and len(read_lines(ulog)) == 1, f"rc={r.returncode} {r.stderr!r}")

        # AC6: run the real installer against a throwaway HOME so it links into a temp tree.
        fake_home = os.path.join(td, "home")
        os.makedirs(fake_home)
        r = subprocess.run(["bash", INSTALL], env=dict(os.environ, HOME=fake_home),
                           capture_output=True, text=True)
        link = os.path.join(fake_home, ".local", "bin", "gate-log")
        check("6a. install.sh links gate-log onto ~/.local/bin, pointing at the script",
              os.path.islink(link) and os.path.realpath(link) == os.path.realpath(SCRIPT),
              f"rc={r.returncode} {r.stderr[-200:]}")
        check("6b. the linked script is executable and starts with a python shebang",
              os.access(link, os.X_OK) and open(SCRIPT).readline().startswith("#!/usr/bin/env python3"))

        # AC22
        with open(os.path.join(HERE, "..", "..", "..", "settings.json")) as fh:
            allow = json.load(fh)["permissions"]["allow"]
        check("22. settings.json allowlists exactly Bash(gate-log:*) and nothing broader",
              [e for e in allow if "gate-log" in e] == ["Bash(gate-log:*)"]
              and "Bash(*)" not in allow and "Bash" not in allow, str(allow))

        # AC21
        text = open(log).read()
        check("21a. no finding text, evidence or reason reaches the log",
              "SENTINEL" not in text)
        check("21b. every record carries only section-5 keys",
              all(set(x) <= SECTION5_KEYS for x in recs), str([set(x) - SECTION5_KEYS for x in recs]))

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
