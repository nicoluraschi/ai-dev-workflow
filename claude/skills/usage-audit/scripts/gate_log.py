#!/usr/bin/env python3
"""gate-log: an append-only record of what each workflow gate found.

    gate-log add --gate 5s --lane workflow --tier B --slug <spec> --found 0,1,2 ...
    gate-log add --ledger <codex ledger>      # what codex-audit calls after each gate
    gate-log import-codex <repo-path>         # backfill from a repo's existing ledgers

One JSON object per line in ~/.claude/gate-log.jsonl (docs/design/2026-10-gate-scorecard.md
section 5). usage-audit's analyze.py imports this module for the gate list and the validation,
so the format has exactly one definition.

The log path is the GATE_LOG environment variable or the default, and nothing else: no option
names a file this tool writes, because the command is allowlisted and an agent can reach every
argument without a permission prompt.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

GATES = ("1s", "1b", "2s", "2d-data", "2d-perf", "2b", "5s", "5-data", "5-migration",
         "5-perf", "5-obs", "5-ui", "5q", "6-review", "6b", "trivial-check")
LANES = ("workflow", "light", "trivial")
TIERS = ("routine", "B", "A")
SOURCES = ("claude", "codex", "import")
SEVERITIES = ("blocker", "major", "minor")

# A slug or repo name ends up in a report and in the log's line framing. A newline would forge
# a record and an escape byte would reach the developer's terminal, so both are refused.
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
TRIPLE = re.compile(r"^-?\d+,-?\d+,-?\d+$")
# A trigger is the feature-workflow clause quoted to name a Tier A/B: a sentence, not a spec.
TRIGGER_MAX = 300

# Same shape codex-audit accepts for a thread id read back from a ledger.
THREAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# codex-audit writes the ledgers, so it is the only thing that counts them (design D9):
# gate-log runs its read-only `scorecard` mode and maps the answer. The path is resolved from
# this file's real location, so a `gate-log` symlink on PATH finds it too.
CODEX_AUDIT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.realpath(__file__)))))), "codex", "bin", "codex-audit")


class GateLogError(Exception):
    """A record that must not be written. The message always names the field."""

    def __init__(self, field, message):
        super().__init__(f"invalid {field}: {message}")


def log_path():
    return os.environ.get("GATE_LOG") or os.path.expanduser("~/.claude/gate-log.jsonl")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_triple(field, text):
    if not TRIPLE.match(text):
        raise GateLogError(field, f"{text!r} is not blocker,major,minor counts, e.g. 0,1,2")
    return dict(zip(SEVERITIES, (int(part) for part in text.split(","))))


def _count(field, value, nullable=False):
    if value is None and nullable:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GateLogError(field, f"{value!r} is not a non-negative count")


def _triple(field, value, nullable=False):
    if not isinstance(value, dict) or set(value) != set(SEVERITIES):
        raise GateLogError(field, "expected {blocker, major, minor}")
    for sev in SEVERITIES:
        _count(f"{field}.{sev}", value[sev], nullable=nullable)
    return value


def validate_record(rec):
    """Raise GateLogError for anything the spec's section 5 does not allow."""
    for field, allowed in (("gate", GATES), ("lane", LANES), ("source", SOURCES)):
        if rec.get(field) not in allowed:
            raise GateLogError(field, f"{rec.get(field)!r} is not one of {', '.join(allowed)}")
    tier = rec.get("tier")
    if tier is None:
        # A Codex ledger has no tier; a manual record always does.
        if rec["source"] == "claude":
            raise GateLogError("tier", f"required, one of {', '.join(TIERS)}")
    elif tier not in TIERS:
        raise GateLogError("tier", f"{tier!r} is not one of {', '.join(TIERS)}")
    if "trigger" in rec:
        trigger = rec["trigger"]
        if tier not in ("A", "B"):
            raise GateLogError("trigger", "only a Tier A or B record quotes a trigger")
        if (not isinstance(trigger, str) or not trigger or len(trigger) > TRIGGER_MAX
                or CONTROL.search(trigger)):
            raise GateLogError("trigger", f"must be one line of at most {TRIGGER_MAX} "
                                          "characters without control characters")
    for field in ("slug", "repo"):
        value = rec.get(field)
        if not isinstance(value, str) or not value or CONTROL.search(value):
            raise GateLogError(field, "must be a non-empty single line without control characters")
    if "pr" in rec:
        _count("pr", rec["pr"])
    if "thread" in rec and not (isinstance(rec["thread"], str)
                                and THREAD_ID.fullmatch(rec["thread"])):
        raise GateLogError("thread", "must look like a Codex thread id")
    found = _triple("found", rec.get("found"))
    # Only a ledger can leave acceptance unknown (no response table); Claude always triages.
    accepted = _triple("accepted", rec.get("accepted"), nullable=rec["source"] != "claude")
    for field in ("rejected", "deferred", "human"):
        _count(field, rec.get(field))
    if not isinstance(rec.get("skipped"), bool):
        raise GateLogError("skipped", "must be true or false")
    for sev in SEVERITIES:
        if accepted[sev] is not None and accepted[sev] > found[sev]:
            raise GateLogError("accepted", f"{sev} {accepted[sev]} exceeds found {found[sev]}")
    decided = (sum(n or 0 for n in accepted.values())
               + rec["rejected"] + rec["deferred"] + rec["human"])
    if decided > sum(found.values()):
        raise GateLogError("outcome", f"accepted+rejected+deferred+human ({decided}) "
                                      f"exceeds found ({sum(found.values())})")


def git_common_dir(cwd):
    out = None
    if os.path.isdir(cwd):
        out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             cwd=cwd, capture_output=True, text=True)
    if out is None or out.returncode != 0:
        raise GateLogError("repo", f"{cwd} is not inside a git repository")
    return out.stdout.strip()


def repo_name(cwd):
    """Basename of the main checkout, so every worktree of one repo reports as one repo."""
    return os.path.basename(os.path.dirname(git_common_dir(cwd)))


def append_record(rec, path):
    line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # One write() on an O_APPEND descriptor: the kernel positions and writes it as a single
    # step, so concurrent sessions cannot interleave inside a line.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if os.write(fd, line) != len(line):
            raise OSError("short write")
    finally:
        os.close(fd)


# --- Codex ledgers -------------------------------------------------------------
def read_scorecard(path):
    """`codex-audit scorecard <path>` as a dict, or None when the wrapper cannot answer.

    Nothing here reads the ledger itself, so no finding text can reach the log. The wrapper
    alone knows the file-name grammar: it answers with an empty `gate` for a name that is not
    a ledger's.
    """
    try:
        out = subprocess.run([CODEX_AUDIT, "scorecard", path], capture_output=True, text=True)
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return {key: value for key, _, value in (line.partition("=") for line in out.stdout.splitlines())}


def parse_ledger(path, kv=None):
    """Map a ledger's scorecard onto the ledger-derived part of a record, or None.

    None means there is nothing to record: the wrapper called the ledger unrecordable
    (UNPARSEABLE, no round 1, not a ledger name), failed, or printed something unusable.
    """
    kv = read_scorecard(path) if kv is None else kv
    if not kv or kv.get("status") not in ("ok", "skip"):
        return None
    try:
        # The ledger stamps local time with no zone; the log is UTC.
        ts = (datetime.strptime(kv["date"], "%Y-%m-%d %H:%M")
              .astimezone(timezone.utc).isoformat(timespec="seconds"))
        n = {key: int(kv[key]) for key in (
            "blocker", "major", "minor", "regressions", "accepted_blocker", "accepted_major",
            "rejected", "human", "rounds", "wall_s", "responded")}
        rec = {"ts": ts, "slug": kv["slug"], "gate": kv["gate"]}
        if kv["pr"]:
            rec["pr"] = int(kv["pr"])
    except (KeyError, ValueError):
        return None
    if kv.get("thread"):
        rec["thread"] = kv["thread"]

    if kv["status"] == "skip":
        zeros = dict.fromkeys(SEVERITIES, 0)
        rec.update(found=zeros, accepted=dict(zeros), rejected=0, deferred=0, human=0,
                   skipped=True)
        return rec
    # Each regression is a new major finding; the wrapper already counted it as `human`.
    # Findings with no response table (a one-shot 6b, a round 2 that never ran) were never
    # triaged here: what was accepted is unknown, and zero would read as "all rejected".
    untriaged = not n["responded"] and n["blocker"] + n["major"]
    rec.update(found={"blocker": n["blocker"], "major": n["major"] + n["regressions"],
                      "minor": n["minor"]},
               accepted={"blocker": None if untriaged else n["accepted_blocker"],
                         "major": None if untriaged else n["accepted_major"], "minor": None},
               rejected=n["rejected"], deferred=0, human=n["human"], skipped=False,
               rounds=n["rounds"])
    if n["wall_s"]:
        rec["wall_s"] = n["wall_s"]
    return rec


def classification(tier, trigger):
    """The tier fields of a new record. Old lines may lack a trigger; a new A/B one may not."""
    fields = {"tier": tier}
    if trigger is not None:
        fields["trigger"] = trigger
    elif tier in ("A", "B"):
        raise GateLogError("trigger", "required for Tier A or B: quote the feature-workflow "
                                      "clause that names the tier")
    return fields


def ledger_record(path, repo, source, kv=None, tier=None, trigger=None):
    parsed = parse_ledger(path, kv)
    if parsed is None:
        raise GateLogError("ledger", f"{os.path.basename(path)} has no round-1 review to record "
                                     "(UNPARSEABLE, no round 1, unreadable, or not a ledger name)")
    rec = {"ts": parsed.pop("ts"), "repo": repo, "slug": parsed.pop("slug"), "lane": "workflow",
           **classification(tier, trigger), "gate": parsed.pop("gate")}
    rec.update(parsed)
    rec["source"] = source
    validate_record(rec)
    return rec


# --- commands --------------------------------------------------------------------
def manual_record(args):
    for field in ("gate", "lane", "tier", "slug"):
        if getattr(args, field) is None:
            raise GateLogError(field, "required")
    rec = {"ts": now_iso(), "repo": repo_name(os.getcwd()), "slug": args.slug,
           "lane": args.lane, **classification(args.tier, args.trigger), "gate": args.gate}
    if args.pr is not None:
        rec["pr"] = args.pr
    rec["found"] = parse_triple("found", args.found or "0,0,0")
    rec["accepted"] = parse_triple("accepted", args.accepted or "0,0,0")
    rec.update(rejected=args.rejected or 0, deferred=args.deferred or 0, human=args.human or 0,
               skipped=args.skipped, source="claude")
    return rec


# What a ledger supplies. The tier and its trigger are not in a ledger: codex-audit passes them.
RECORD_FIELDS = ("gate", "lane", "slug", "pr", "found", "accepted", "rejected", "deferred",
                 "human")


def cmd_add(args):
    if args.ledger:
        given = [f for f in RECORD_FIELDS if getattr(args, f) is not None]
        if args.skipped:
            given.append("skipped")
        if given:
            raise GateLogError("ledger", "the ledger supplies the whole record; remove --"
                                         + ", --".join(given))
        rec = ledger_record(args.ledger, repo_name(os.getcwd()), "codex",
                            tier=args.tier, trigger=args.trigger)
    else:
        rec = manual_record(args)
        validate_record(rec)
    append_record(rec, log_path())


def cmd_import(args):
    repo = repo_name(args.repo_path)
    folder = os.path.join(git_common_dir(args.repo_path), "codex-audit")
    names = [n for n in (os.listdir(folder) if os.path.isdir(folder) else [])
             if n.endswith(".md")]
    imported = skipped = 0
    for name in sorted(names):
        path = os.path.join(folder, name)
        kv = read_scorecard(path)
        if kv is None:              # the wrapper could not answer (unreadable, missing)
            print(f"gate-log: skipped {name}: codex-audit scorecard could not read it",
                  file=sys.stderr)
            skipped += 1
            continue
        if kv.get("gate") == "":
            continue                # not a ledger at all (notes, a README): nothing to say
        try:
            rec = ledger_record(path, repo, "import", kv)
        except Exception as exc:    # one malformed ledger must not stop the others
            print(f"gate-log: skipped {name}: {exc}", file=sys.stderr)
            skipped += 1
        else:
            append_record(rec, log_path())
            imported += 1
    print(f"imported {imported} ledger(s), skipped {skipped}")


def build_parser():
    parser = argparse.ArgumentParser(prog="gate-log", allow_abbrev=False,
                                     description="Append gate results to the gate log.")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", allow_abbrev=False, help="record one gate run")
    add.add_argument("--gate")
    add.add_argument("--lane")
    add.add_argument("--tier")
    add.add_argument("--trigger", help="Tier A/B only: the feature-workflow clause quoted")
    add.add_argument("--slug")
    add.add_argument("--pr", type=int)
    add.add_argument("--found", help="blocker,major,minor (default 0,0,0)")
    add.add_argument("--accepted", help="blocker,major,minor (default 0,0,0)")
    add.add_argument("--rejected", type=int)
    add.add_argument("--deferred", type=int)
    add.add_argument("--human", type=int)
    add.add_argument("--skipped", action="store_true")
    add.add_argument("--ledger", help="record this Codex ledger instead of the fields above")
    imp = sub.add_parser("import-codex", allow_abbrev=False,
                         help="backfill from a repo's Codex ledgers")
    imp.add_argument("repo_path")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        {"add": cmd_add, "import-codex": cmd_import}[args.command](args)
    except GateLogError as exc:
        print(f"gate-log: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"gate-log: cannot write {log_path()}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
