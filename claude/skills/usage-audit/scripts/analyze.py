#!/usr/bin/env python3
"""Measure token and wall-clock cost across Claude Code session transcripts.

Emits JSON on stdout. It computes; it does not judge -- ranking findings and
weighing them against quality is the model's job (see ../SKILL.md).

Read-only: it opens transcripts and config files and writes nothing.

The transcript format is undocumented and changes between CLI releases, so every
field is read through a guarded accessor and anything unrecognised is counted
into the `drift` section rather than silently dropped. A report whose `drift`
counters are non-zero should be treated as suspect, not rounded off.

THE RULE THAT MATTERS: one API response is written to the transcript as N lines,
one per content block, and EVERY line repeats the full `usage` object. Summing
usage per line overcounts tokens by 2-9x. Usage is therefore accumulated once
per unique `message.id`.

THE SAME RULE APPLIES TO TOOL CALLS: two calls issued in parallel arrive as two
lines sharing one `message.id`, so counting "lines carrying more than one
tool_use" reports 0% parallelism on a corpus whose real rate is ~7%. The
`adherence` block counts distinct tool_use ids grouped by `message.id`.
"""
import argparse
import bisect
import json
import os
import re
import shlex
import statistics
import sys
from datetime import datetime, timedelta, timezone

import gate_log   # the gate-log record format and gate list have one definition

BLOCK_HOURS = 5
DEFAULT_ROOT = os.path.expanduser("~/.claude/projects")
DEFAULT_CODEX = os.path.expanduser("~/.codex/sessions")

# Records we understand. Anything else lands in drift.unknown_types so that a
# new record type introduced by a CLI release shows up as a visible gap.
KNOWN_TYPES = {
    "assistant", "user", "system", "summary", "attachment", "pr-link",
    "ai-title", "permission-mode", "mode", "bridge-session", "last-prompt",
    "agent-name", "file-history-snapshot", "queue-operation", "cost-state",
    "progress", "atis-latch", "file-history-delta", "worktree-state",
    "relocated", "fork-context-ref", "frame-link", "artifact-comment-monitor",
    "artifact-autoreact-ledger", "session-owner",
    # The request log: what was sent, not what it cost. Assistant usage already
    # measures it, and its blobs hold raw prompt and tool text, so its content is
    # never read (only the generic timestamp, like every other record) -- except
    # api-request-shape, which is sized for .fixed_context_measured, never quoted.
    "api-request-shape", "api-request-blob", "api-request", "tools-used",
}

# Tools whose toolUseResult is a local record far larger than what the model is
# sent: Edit/Write keep originalFile, oldString/newString, structuredPatch (Write:
# content), ~4 KB mean, while the model gets only the tool_result block's content
# (~150-220 B). Their result_bytes size that content instead.
SENT_SIZED = {"Edit", "Write"}

# Gaps longer than this are the human reading, thinking or away -- not the agent
# working. Used to separate a session's elapsed span from the time it consumed.
IDLE_GAP_MINUTES = 5

# Adherence heuristics: they measure habits, not correctness, and a few percent of
# error does not change a verdict. A command is tokenized once with shlex, with an
# unquoted newline as a separator, so quotes, continuations and operators mean what
# the shell means by them. Only a simple command that is a reader counts, and only
# the files it names: after a pipe it pages someone else's output, `cat > f` writes
# f, and `cat <<EOF` reads stdin.
READERS = {"cat", "head", "tail", "nl"}
SEPARATOR_CHARS = set(";&|\n")
WRITES = {">", ">>", ">|", "&>", "&>>"}
REDIRECTS = WRITES | {">&", "<"}
NOT_A_FILE = {"/dev/null", "/dev/stdout", "/dev/stderr"}
HEREDOC_START = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
# Longest extension first, or `settings.json` truncates to `settings.js`. The prefix
# takes dotted segments lazily: the obvious `[\w./@-]+\.` overlaps its own delimiter
# and backtracks polynomially (458 ms on one 8k-char command, against 0.1 ms here).
FILE_REF = re.compile(r"[\w/@#-]+(?:\.[\w/@#-]+)*?"
                      r"\.(?:jsonl|json|scss|tsx|jsx|yaml|erb|css|sql|yml|rb|md|py|ts|js)\b")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value):
    """Parse a transcript timestamp, tolerating absence and trailing Z."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A timestamp with neither Z nor an offset parses naive, and a naive value
    # cannot be compared with the aware ones -- one such record used to abort
    # the entire audit. Assume UTC, which is what the writers emit.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _num(value):
    """Coerce to a non-negative int; anything odd becomes 0.

    Floats are accepted: a release emitting durations as floats would otherwise
    zero a measured time split while still reporting it as measured.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value) if value >= 0 else 0


def _dig(obj, *path):
    """Walk nested dict keys, returning None the moment the shape disagrees."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _sizeof(value):
    """Byte size of a tool result of any shape.

    toolUseResult is a dict for Bash (stdout/stderr) and Read (file), a list for
    some tools, and a bare string for others. Re-serialising is shape-agnostic
    and survives shapes that do not exist yet.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8", "replace"))
    try:
        return len(json.dumps(value, default=str).encode("utf-8", "replace"))
    except (TypeError, ValueError):
        return 0


def _has_image(value, depth=0):
    """True if a tool result carries image data.

    An image is tokenised by its dimensions, not by the length of its base64
    payload, so its bytes are a bad proxy for context cost and are kept apart.
    """
    if depth > 6:
        return False
    if isinstance(value, dict):
        if value.get("isImage") is True or value.get("type") == "image":
            return True
        return any(_has_image(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_has_image(v, depth + 1) for v in value)
    return False


def _weighted(usage):
    """Price-weighted tokens: input 1, cache read 0.1, 5m write 1.25, 1h write 2,
    output 5. Ratios, not prices -- identical across current Claude models, so
    weighted tokens are comparable where raw cache tokens are not.
    """
    split = usage.get("cache_creation")
    five = _num(_dig(split, "ephemeral_5m_input_tokens"))
    hour = _num(_dig(split, "ephemeral_1h_input_tokens"))
    if not (five or hour):     # no split: every cache write counts at 1.25
        five = _num(usage.get("cache_creation_input_tokens"))
    return (_num(usage.get("input_tokens"))
            + 0.1 * _num(usage.get("cache_read_input_tokens"))
            + 1.25 * five + 2 * hour
            + 5 * _num(usage.get("output_tokens")))


def _blank_drift():
    return {
        "unparseable_lines": 0,
        "assistant_without_usage": 0,
        "records_without_timestamp": 0,
        "messages_without_id": 0,
        "subagents_without_meta": 0,
        "unmeasured_resumes": 0,
        "unknown_types": {},
    }


def _path_key(path):
    """Last two segments. Not the basename: `specs/x.md` and `plans/x.md` are
    different files. Not the absolute path: the same file edited from a worktree
    and from the main checkout must collapse."""
    return "/".join([p for p in path.split("/") if p][-2:])


def _blank_adherence():
    return {"calls_by_message": {}, "edits_per_file": {}, "files_seen": set(),
            "redundant_reads": 0, "read_calls": 0, "read_file_refs": 0}


def _note_read(state, basename):
    state["read_file_refs"] += 1
    if basename in state["files_seen"]:
        state["redundant_reads"] += 1     # already in context when read again
    else:
        state["files_seen"].add(basename)


def _track_adherence(state, name, tool_input):
    """Reads, writes and edits, for the adherence block. Reads are keyed by
    basename because a shell command's file reference carries no reliable dir."""
    path = tool_input.get("file_path")
    if name in ("Edit", "Write") and isinstance(path, str) and path:
        if name == "Edit":
            key = _path_key(path)
            state["edits_per_file"][key] = state["edits_per_file"].get(key, 0) + 1
        # A file this session wrote is in context from then on, so reading it
        # again is exactly the habit being measured.
        state["files_seen"].add(os.path.basename(path))
    elif name == "Read" and isinstance(path, str) and path:
        state["read_calls"] += 1
        _note_read(state, os.path.basename(path))
    elif name == "Bash":
        command = tool_input.get("command")
        refs = _shell_read_refs(command) if isinstance(command, str) else None
        if refs is not None:
            state["read_calls"] += 1
            for ref in refs:
                _note_read(state, ref)


def _shell_read_refs(command):
    """Basenames of the files a shell command reads, or None if it reads none."""
    lex = shlex.shlex(_drop_heredoc_bodies(command).replace("\\\n", " "),
                      posix=True, punctuation_chars=";&|<>\n")
    lex.whitespace = lex.whitespace.replace("\n", "")
    lex.commenters = ""             # bash keeps `#` literal inside a word
    lex.wordchars += "#@%+,:"       # and these are ordinary file-name characters
    try:
        tokens = list(lex)
    except ValueError:              # unbalanced quotes: don't guess
        return None
    refs, reads, segment, after_pipe = set(), False, [], False
    for tok in tokens + [";"]:
        if not set(tok) <= SEPARATOR_CHARS:
            segment.append(tok)
            continue
        files = None if after_pipe else _segment_reads(segment)
        if files is not None:
            reads = True
            refs.update(files)
        segment, after_pipe = [], tok.strip("\n") == "|"
    return refs if reads else None


def _drop_heredoc_bodies(command):
    """Heredoc bodies are data, not commands. Linear in the number of lines: an
    unterminated `<<` (C++ or Ruby inside `-c`) must not rescan the rest."""
    lines = command.split("\n")
    where = {}
    for i, line in enumerate(lines):
        where.setdefault(line.strip(), []).append(i)
    kept, skip_to = [], -1
    for i, line in enumerate(lines):
        if i <= skip_to:
            continue
        kept.append(line)
        m = HEREDOC_START.search(line)
        if m:
            ends = where.get(m.group(1), [])
            j = bisect.bisect_right(ends, i)
            if j < len(ends):
                skip_to = ends[j]
    return "\n".join(kept)


def _segment_reads(tokens):
    """Files one simple command reads, or None if it is not a read."""
    if not tokens or not (tokens[0] in READERS or (tokens[0] == "sed" and "-n" in tokens)):
        return None
    if any(t.startswith("<<") for t in tokens):
        return None                 # reads a heredoc on stdin, not a file
    args, i = [], 1
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok.isdigit() and nxt in REDIRECTS:
            if nxt in WRITES and tok == "1" and tokens[i + 2:i + 3] != ["/dev/null"]:
                return None         # 1> f: stdout goes to a file
            i += 3                  # 2> err.log redirects another stream
            continue
        if tok in REDIRECTS:
            if tok in WRITES and nxt not in NOT_A_FILE:
                return None         # the output is written to a file
            if tok == "<" and nxt:
                args.append(nxt)    # `cat < f` reads f
            i += 2
            continue
        if not tok.startswith("-"):
            args.append(tok)
        i += 1
    if tokens[0] == "sed" and args:
        args = args[1:]             # the first operand is the sed script
    return {os.path.basename(m) for a in args for m in FILE_REF.findall(a)}


def _adherence_report(state):
    """The execution habits as a scoreboard. See area 9 in ../SKILL.md."""
    groups = state["calls_by_message"]
    parallel = sum(1 for ids in groups.values() if len(ids) > 1)
    edits = state["edits_per_file"]
    return {
        "messages_with_tool_calls": len(groups),
        "messages_issuing_several": parallel,
        "parallel_rate": round(parallel / len(groups), 4) if groups else 0.0,
        "read_calls": state["read_calls"],
        # Redundancy is per file reference: one command naming five files adds
        # five, so compare it with read_file_refs, never with read_calls.
        "read_file_refs": state["read_file_refs"],
        "redundant_reads_approx": state["redundant_reads"],
        "max_edits_one_file": max(edits.values()) if edits else 0,
        "edits_per_file_top": [{"file": f, "edits": n} for f, n in
                               sorted(edits.items(), key=lambda kv: -kv[1])[:5]],
    }


def _combine_adherence(reports):
    """Main session plus its subagents. Counts add up per context -- each agent
    has its own context, so a file one of them read is not in another's."""
    total = {k: sum(r[k] for r in reports) for k in (
        "messages_with_tool_calls", "messages_issuing_several", "read_calls",
        "read_file_refs", "redundant_reads_approx")}
    groups = total["messages_with_tool_calls"]
    total["parallel_rate"] = (round(total["messages_issuing_several"] / groups, 4)
                              if groups else 0.0)
    total["max_edits_one_file"] = max(r["max_edits_one_file"] for r in reports)
    total["edits_per_file_top"] = sorted(
        (e for r in reports for e in r["edits_per_file_top"]),
        key=lambda e: -e["edits"])[:5]
    return total


def _blank_tool():
    return {"calls": 0, "result_bytes": 0, "results": 0,
            "image_bytes": 0, "image_results": 0}


def _merge_drift(into, other):
    for key in ("unparseable_lines", "assistant_without_usage",
                "records_without_timestamp", "messages_without_id",
                "subagents_without_meta", "unmeasured_resumes"):
        into[key] += other[key]
    for key, count in other["unknown_types"].items():
        into["unknown_types"][key] = into["unknown_types"].get(key, 0) + count
    return into


def iter_records(path):
    """Yield (record_or_None, raw_line). A None record means the line was junk."""
    try:
        with open(path, "r", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, RecursionError):
                    yield None, line
                    continue
                yield (record, line) if isinstance(record, dict) else (None, line)
    except (OSError, UnicodeError):
        return


def five_hour_blocks(events):
    """Reconstruct the rolling usage windows that drive subscription limits.

    A block opens at the first message, floored to the hour, and stays open for
    five hours. A message past the window -- or more than five hours after the
    previous one -- opens a new block. This mirrors ccusage's `blocks`; it is
    reimplemented here so the skill needs no Node dependency.
    """
    # Accepts bare timestamps or {"ts", "output", "billed"} message events.
    # Blocks are built from deduped MESSAGES, not from every record: a window's
    # weight is the API calls in it, and saturation is judged on tokens.
    parsed = []
    for event in events:
        if isinstance(event, dict):
            moment = parse_ts(event.get("ts"))
            weight = (_num(event.get("output")), _num(event.get("billed")))
        else:
            moment, weight = parse_ts(event), (0, 0)
        if moment:
            parsed.append((moment, weight))
    parsed.sort(key=lambda pair: pair[0])
    blocks = []
    for moment, (out_tokens, billed) in parsed:
        current = blocks[-1] if blocks else None
        if (current is None
                or moment >= current["_start"] + timedelta(hours=BLOCK_HOURS)
                or moment - current["_last"] > timedelta(hours=BLOCK_HOURS)):
            start = moment.replace(minute=0, second=0, microsecond=0)
            blocks.append({"_start": start, "_last": moment, "messages": 1,
                           "output": out_tokens, "billed_input": billed})
        else:
            current["_last"] = moment
            current["messages"] += 1
            current["output"] += out_tokens
            current["billed_input"] += billed
    return [{
        "start": b["_start"].isoformat(),
        "end": (b["_start"] + timedelta(hours=BLOCK_HOURS)).isoformat(),
        "last_activity": b["_last"].isoformat(),
        "messages": b["messages"],
        "output": b["output"],
        "billed_input": b["billed_input"],
    } for b in blocks]


def analyze_session(path):
    """Metrics for one transcript. Never raises on malformed input."""
    drift = _blank_drift()
    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    models, skills, tools = {}, {}, {}
    seen_messages = set()
    tool_names = {}          # tool_use id -> tool name
    counted_tools = set()    # tool_use ids already counted (dedup safety)
    counted_results = set()  # tool_use ids whose result was already sized
    timestamps = []
    message_events = []      # one per deduped message, for the 5-hour blocks
    events = []              # record-ordered msg / use / result, for the handoff
    seen_results = set()     # tool_use ids whose tool_result was already recorded
    prs, branches = [], []
    agent_ms = 0
    turn_durations = 0
    cost_state = None
    adherence = _blank_adherence()
    boundaries = 0
    summaries = 0
    session_id = None
    shapes = []              # sizes of each api-request-shape, never its text

    for record, _ in iter_records(path):
        if record is None:
            drift["unparseable_lines"] += 1
            continue

        rtype = record.get("type")
        if rtype not in KNOWN_TYPES:
            key = str(rtype)
            drift["unknown_types"][key] = drift["unknown_types"].get(key, 0) + 1

        session_id = session_id or record.get("sessionId")
        stamp = record.get("timestamp")
        if parse_ts(stamp):
            timestamps.append(stamp)
        elif rtype in ("assistant", "user"):
            drift["records_without_timestamp"] += 1

        branch = record.get("gitBranch")
        if isinstance(branch, str) and branch and branch not in branches:
            branches.append(branch)

        if rtype == "api-request-shape":
            shapes.append(_shape_size(record))
            continue

        if rtype == "cost-state":
            # Cumulative and rewritten as the session proceeds: the last wins.
            cost_state = record
            continue

        if rtype == "pr-link":
            repo, number = record.get("prRepository"), record.get("prNumber")
            if repo and number is not None:
                tag = f"{repo}#{number}"
                if tag not in prs:
                    prs.append(tag)
            continue

        if rtype == "system":
            if record.get("subtype") == "turn_duration":
                agent_ms += _num(record.get("durationMs"))
                turn_durations += 1
            elif record.get("subtype") == "compact_boundary":
                boundaries += 1
            continue

        if rtype == "user":
            if record.get("isCompactSummary") is True:
                summaries += 1
            # A background subagent returns through a peer hand-back, not a tool_result.
            origin = record.get("origin")
            if (isinstance(origin, dict) and origin.get("kind") == "peer"
                    and origin.get("handback") is True and isinstance(origin.get("from"), str)):
                events.append(("handback", origin["from"]))
            blocks = _dig(record, "message", "content")
            for block in blocks if isinstance(blocks, list) else []:
                ref = block.get("tool_use_id") if isinstance(block, dict) else None
                if (isinstance(block, dict) and block.get("type") == "tool_result"
                        and ref and ref not in seen_results):
                    seen_results.add(ref)
                    events.append(("result", ref))
            result = record.get("toolUseResult")
            if result is not None:
                content = _dig(record, "message", "content")
                ref, sent = None, None
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            ref, sent = block.get("tool_use_id"), block.get("content")
                            break
                if ref is not None:
                    if ref in counted_results:
                        continue     # the same result written more than once
                    counted_results.add(ref)
                name = tool_names.get(ref, "<unknown tool>")
                entry = tools.setdefault(name, _blank_tool())
                if name in SENT_SIZED:
                    result = sent
                if _has_image(result):
                    entry["image_bytes"] += _sizeof(result)
                    entry["image_results"] += 1
                else:
                    entry["result_bytes"] += _sizeof(result)
                    entry["results"] += 1
            continue

        if rtype != "assistant":
            continue

        message = record.get("message")
        if not isinstance(message, dict):
            drift["assistant_without_usage"] += 1
            continue

        # Tool calls are per content block and must survive message dedup, so
        # they are keyed by the tool_use id rather than the message id.
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name") or "<unnamed tool>"
                ref = block.get("id")
                if ref:
                    tool_names[ref] = name
                    if ref in counted_tools:
                        continue
                    counted_tools.add(ref)
                # Only the routing key is kept, never the input: prompts and
                # commands must not reach the report.
                inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                target = inp.get("skill") if name == "Skill" else inp.get("to")
                events.append(("use", message.get("id") or record.get("requestId"),
                               ref, name, target if isinstance(target, str) else None))
                entry = tools.setdefault(name, _blank_tool())
                entry["calls"] += 1
                # Keyed like usage, so parallel calls split across lines are
                # recognised as one message issuing several calls.
                msg_key = message.get("id") or record.get("requestId") or record.get("uuid")
                adherence["calls_by_message"].setdefault(msg_key, set()).add(ref)
                _track_adherence(adherence, name, inp)

        usage = message.get("usage")
        # requestId is 1:1 with message.id (see references/schema.md) and stands
        # in when the id is absent. Without a key every content-block line would
        # re-add the full usage object -- the overcount this module exists to
        # prevent -- so a record with neither key is counted once and flagged.
        mid = message.get("id") or record.get("requestId")
        if not isinstance(usage, dict):
            drift["assistant_without_usage"] += 1
            continue
        if mid is None:
            drift["messages_without_id"] += 1
            mid = "uuid:%s" % (record.get("uuid") or len(seen_messages))
        if mid in seen_messages:      # same response, another content block
            continue
        seen_messages.add(mid)

        counts = {
            "input": _num(usage.get("input_tokens")),
            "output": _num(usage.get("output_tokens")),
            "cache_read": _num(usage.get("cache_read_input_tokens")),
            "cache_creation": _num(usage.get("cache_creation_input_tokens")),
        }
        for key, value in counts.items():
            tokens[key] += value

        if stamp:
            message_events.append({
                "ts": stamp,
                "output": counts["output"],
                "billed": counts["input"] + counts["cache_read"]
                          + counts["cache_creation"],
            })

        model = message.get("model") or "<unknown>"
        bucket = models.setdefault(
            model, {"messages": 0, "input": 0, "output": 0,
                    "cache_read": 0, "cache_creation": 0, "weighted": 0.0})
        bucket["messages"] += 1
        bucket["weighted"] += _weighted(usage)
        events.append(("msg", mid, model, _weighted(usage)))
        for key, value in counts.items():
            bucket[key] += value

        skill = record.get("attributionSkill")
        if isinstance(skill, str) and skill:
            bucket = skills.setdefault(skill, {"messages": 0, "output": 0, "cache_read": 0})
            bucket["messages"] += 1
            bucket["output"] += counts["output"]
            bucket["cache_read"] += counts["cache_read"]

    messages = len(seen_messages)
    billed_input = tokens["input"] + tokens["cache_read"] + tokens["cache_creation"]
    ordered = sorted(t for t in (parse_ts(x) for x in timestamps) if t)
    span_ms = int((ordered[-1] - ordered[0]).total_seconds() * 1000) if len(ordered) > 1 else 0
    # Active time: elapsed span minus every gap long enough to be the human.
    # Spans are NOT additive across sessions (a session left open overnight
    # spans hours it never consumed), so the two are always reported apart.
    active_ms = sum(
        int((b - a).total_seconds() * 1000)
        for a, b in zip(ordered, ordered[1:])
        if (b - a) <= timedelta(minutes=IDLE_GAP_MINUTES)
    )
    if not turn_durations:
        agent_ms = active_ms

    # A cost-state record carries measured API and tool duration. Prefer it:
    # everything else here is inference.
    api_ms = tool_ms = idle_ms = session_ms = None
    cost = {"usd": None, "lines_added": 0, "lines_removed": 0}
    model_usage = {}
    if isinstance(cost_state, dict):
        api_ms = _num(cost_state.get("totalAPIDuration"))
        tool_ms = _num(cost_state.get("totalToolDuration"))
        session_ms = _num(cost_state.get("totalDuration"))
        # Everything that was neither the model nor a tool. NOT the same as
        # "time the human spent thinking": totalDuration is the session's
        # elapsed span, so a session left open overnight lands almost entirely
        # here. Treat it as idle-or-human and use active_ms for a bounded view.
        # Clamped: a malformed record must not produce negative idle time.
        idle_ms = max(0, session_ms - api_ms - tool_ms)
        usd = cost_state.get("totalCostUSD")
        cost = {
            "usd": float(usd) if isinstance(usd, (int, float)) else None,
            "lines_added": _num(cost_state.get("totalLinesAdded")),
            "lines_removed": _num(cost_state.get("totalLinesRemoved")),
        }
        if isinstance(cost_state.get("modelUsage"), dict):
            model_usage = cost_state["modelUsage"]

    if cost_state is not None:
        time_source = "cost-state"
    elif turn_durations:
        time_source = "turn_duration"
    else:
        time_source = "timestamps"

    return {
        "session_id": session_id or os.path.splitext(os.path.basename(path))[0],
        "path": path,
        "messages": messages,
        "tokens": tokens,
        "cache_hit_ratio": (tokens["cache_read"] / billed_input) if billed_input else 0.0,
        "context_per_message": (tokens["cache_read"] + tokens["cache_creation"]) // messages
                               if messages else 0,
        "models": models,
        "skills": skills,
        "tools": tools,
        "prs": prs,
        "branches": branches,
        "compactions": max(boundaries, summaries),
        "time": {
            "api_ms": api_ms,
            "tool_ms": tool_ms,
            "idle_ms": idle_ms,
            "session_ms": session_ms,
            "agent_ms": agent_ms,
            "span_ms": span_ms,
            "active_ms": active_ms,
            "source": time_source,
            "turns": turn_durations,
        },
        "cost": cost,
        "model_usage": model_usage,
        "first_ts": ordered[0].isoformat() if ordered else None,
        "last_ts": ordered[-1].isoformat() if ordered else None,
        "timestamps": timestamps,
        "message_events": message_events,
        "events": events,
        "shapes": shapes,
        "subagents": {"sessions": 0, "messages": 0, "input": 0, "output": 0,
                      "cache_read": 0, "cache_creation": 0},
        "adherence": _adherence_report(adherence),
        "drift": drift,
    }


def _subagent_paths(folders):
    """Subagent transcripts live at <project>/<session-id>/subagents/*.jsonl.

    Takes every such directory for one session: after EnterWorktree they sit
    under the worktree's project slug, not the parent's.
    """
    return sorted(os.path.join(folder, n)
                  for folder in folders if os.path.isdir(folder)
                  for n in os.listdir(folder) if n.endswith(".jsonl"))


def _subagent_meta(jsonl_path):
    """Read the sibling <agent-id>.meta.json. Only agentType and toolUseId are
    read: `description` and prompt text are never surfaced in the report.
    """
    stem = os.path.splitext(os.path.basename(jsonl_path))[0]
    agent_id = stem[len("agent-"):] if stem.startswith("agent-") else stem
    meta = None
    try:
        with open(os.path.splitext(jsonl_path)[0] + ".meta.json", "r") as handle:
            meta = json.load(handle)
    except (OSError, ValueError, RecursionError, UnicodeError):
        pass
    if not isinstance(meta, dict):
        meta = {}
    kind, use = meta.get("agentType"), meta.get("toolUseId")
    return {"agent_type": kind if isinstance(kind, str) and kind else "unknown",
            "tool_use_id": use if isinstance(use, str) else None,
            "agent_id": agent_id,
            "background": meta.get("requestShape") == "background"}


def _norm_model(key):
    """Drop a trailing [...] variant suffix: claude-opus-5-5[1m] -> claude-opus-5-5.

    The one sanctioned join between `message.model` and cost-state model keys.
    """
    key = str(key)
    return key[:key.rindex("[")] if key.endswith("]") and "[" in key else key


def _rates(session):
    """Recorded cost per weighted token, per normalized model, for one session.

    cost-state carries costUSD per session with subagents included, so it is
    split across the main transcript and its subagents by price weight. Returns
    (rates, unallocated): a model with cost but no weight cannot be split and is
    reported as unallocated rather than divided by zero.
    """
    recorded = {}
    for key, entry in session["model_usage"].items():
        cost = _dig(entry, "costUSD")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            model = _norm_model(key)
            recorded[model] = recorded.get(model, 0.0) + cost
    weight = {}
    for part in [session] + session.get("parts", []):
        for model, bucket in part["models"].items():
            model = _norm_model(model)
            weight[model] = weight.get(model, 0.0) + bucket["weighted"]
    rates = {m: cost / weight[m] for m, cost in recorded.items() if weight.get(m, 0) > 0}
    unallocated = sum(cost for m, cost in recorded.items() if weight.get(m, 0) <= 0)
    return rates, unallocated


# A window (the main session re-checking an implementer's work) ends at the
# first of these phase-5 audit skills.
AUDIT_SKILLS = {"security-audit", "data-integrity", "migration-safety",
                "performance-review", "observability", "ui-review"}


def _handoff_row(session, window, closed_by, rates):
    per_model, cost = {}, 0.0
    for model, weighted in window["msgs"].values():
        per_model[model] = per_model.get(model, 0) + 1
        rate = rates.get(_norm_model(model))
        cost = None if (cost is None or rate is None) else cost + weighted * rate
    return {
        "session": session["session_id"], "agent_id": window["agent_id"],
        "closed_by": closed_by, "messages": per_model,
        "opus_messages": sum(n for m, n in per_model.items() if "opus" in m),
        "weighted_tokens": sum(w for _, w in window["msgs"].values()),
        "cost_usd": cost,
    }


def implementer_handoff(session, metas):
    """Main-session messages between an implementer returning and the next audit.

    One row per implementer spawn return. A foreground spawn returns in its
    tool_result; a background one there only acknowledges the launch and
    returns later through a peer hand-back, whose first occurrence opens the
    window. A `SendMessage` resume is counted in drift, not measured: its
    transcript shape has not been observed.
    """
    implementers = [m for m in metas
                    if m["agent_type"] == "implementer" and m["tool_use_id"]]
    uses = {m["tool_use_id"]: m["agent_id"] for m in implementers}
    foreground = {m["tool_use_id"] for m in implementers if not m["background"]}
    background = {m["agent_id"] for m in implementers if m["background"]}
    ids = set(uses.values())
    rates, _ = _rates(session)
    rows, window, returned = [], None, set()

    def open_window(agent_id):
        nonlocal window
        close("next_implementer")
        window = {"agent_id": agent_id, "msgs": {}}

    def close(closed_by, mid=None):
        nonlocal window
        if window is not None:
            window["msgs"].pop(mid, None)      # the closing message is not in it
            rows.append(_handoff_row(session, window, closed_by, rates))
            window = None

    for event in session["events"]:
        kind = event[0]
        if kind == "msg" and window is not None:
            window["msgs"][event[1]] = (event[2], event[3])
        elif kind == "result" and event[1] in foreground:
            open_window(uses[event[1]])
        elif kind == "handback" and event[1] in background and event[1] not in returned:
            returned.add(event[1])             # a later hand-back follows a resume
            open_window(event[1])
        elif kind == "use":
            _, mid, ref, name, target = event
            if name == "Skill" and target in AUDIT_SKILLS:
                close(target, mid)
            elif name == "Agent" and ref in uses:
                close("next_implementer", mid)
            elif name == "SendMessage" and target in ids:
                session["drift"]["unmeasured_resumes"] += 1
                close("next_implementer", mid)
    close("session_end")
    return rows


def _handoff_totals(rows):
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    opus = [r["opus_messages"] for r in rows]
    return {
        "returns": len(rows), "opus_messages": sum(opus),
        "weighted_tokens": sum(r["weighted_tokens"] for r in rows),
        "cost_usd": sum(costs) if costs else None,
        "unpriced_returns": len(rows) - len(costs),
        "median_opus_messages": statistics.median(opus) if opus else None,
    }


def _add_subagent_rows(rows, session_rates, sub):
    """Fold one subagent transcript into the (agent_type, model) rows."""
    for model, bucket in sub["models"].items():
        row = rows.setdefault((sub["meta"]["agent_type"], _norm_model(model)), {
            "agent_type": sub["meta"]["agent_type"], "model": _norm_model(model),
            "spawns": 0, "messages": 0, "input": 0, "output": 0, "cache_read": 0,
            "cache_creation": 0, "weighted_tokens": 0.0, "cost_usd": None,
            "unpriced_messages": 0})
        row["spawns"] += 1
        row["messages"] += bucket["messages"]
        for key in ("input", "output", "cache_read", "cache_creation"):
            row[key] += bucket[key]
        row["weighted_tokens"] += bucket["weighted"]
        rate = session_rates.get(_norm_model(model))
        if rate is not None:
            row["cost_usd"] = (row["cost_usd"] or 0.0) + rate * bucket["weighted"]
        else:
            row["unpriced_messages"] += bucket["messages"]


def _listdir(path):
    """List a directory, treating an unreadable one as empty.

    A single locked or concurrently-removed project directory must not abort
    the whole audit.
    """
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def analyze_corpus(root, days=None, project=None):
    """Walk every project under `root` and aggregate per session."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    sessions = []
    totals_drift = _blank_drift()
    subagent_count = 0
    orphans = {"sessions": 0, "messages": 0, "input": 0, "output": 0,
               "cache_read": 0, "cache_creation": 0}
    orphan_events = []
    shapes = []          # every in-window api-request-shape size, main and subagent
    rows = {}

    def keep_shapes(kind, found):
        # Per shape, not per session: a resumed session carries shapes older than the window.
        # The file decides the kind; agentId on the record is not relied on.
        shapes.extend(dict(s, kind=kind) for s in found
                      if not cutoff or (s["ts"] and s["ts"] >= cutoff))          # (agent_type, model) -> subagents_by_type row
    unallocated = 0.0    # recorded cost that had no weight to be split by
    handoffs = []        # implementer_handoff rows, every session

    projects =[d for d in _listdir(root)
                if os.path.isdir(os.path.join(root, d))]

    # Index every project folder first: a subagent directory belongs to the
    # session <id>.jsonl wherever that file lives, not to the folder it sits in.
    parents = set()      # session ids that have a main transcript somewhere
    subdirs = {}         # session id -> every <folder>/<id>/subagents dir
    for name in projects:
        folder = os.path.join(root, name)
        for entry in _listdir(folder):
            if entry.endswith(".jsonl"):
                parents.add(entry[:-len(".jsonl")])
            subs = os.path.join(folder, entry, "subagents")
            if os.path.isdir(subs):
                subdirs.setdefault(entry, []).append(subs)

    for name in projects:
        if project and project not in name:
            continue
        folder = os.path.join(root, name)
        for entry in _listdir(folder):
            if not entry.endswith(".jsonl"):
                continue
            session = analyze_session(os.path.join(folder, entry))
            last = parse_ts(session["last_ts"])
            if cutoff and (last is None or last < cutoff):
                continue
            session["project"] = name
            for sub_path in _subagent_paths(subdirs.get(entry[:-len(".jsonl")], [])):
                sub = analyze_session(sub_path)
                sub["meta"] = _subagent_meta(sub_path)
                if sub["meta"]["agent_type"] == "unknown":
                    session["drift"]["subagents_without_meta"] += 1
                session.setdefault("parts", []).append(sub)
                subagent_count += 1
                session["subagents"]["sessions"] += 1
                session["subagents"]["messages"] += sub["messages"]
                for key in ("input", "output", "cache_read", "cache_creation"):
                    session["subagents"][key] += sub["tokens"][key]
                session["timestamps"].extend(sub["timestamps"])
                session["message_events"].extend(sub["message_events"])
                keep_shapes("subagent", sub["shapes"])
                _merge_drift(session["drift"], sub["drift"])
            session["adherence_all"] = _combine_adherence(
                [session["adherence"]] + [p["adherence"] for p in session.get("parts", [])])
            rates, loose = _rates(session)
            unallocated += loose
            for sub in session.get("parts", []):
                _add_subagent_rows(rows, rates, sub)
            handoffs.extend(implementer_handoff(
                session, [p["meta"] for p in session.get("parts", [])]))
            _merge_drift(totals_drift, session["drift"])
            keep_shapes("main", session["shapes"])
            sessions.append(session)

        # Subagent transcripts outlive their parent: 13% of real ones have no
        # surviving <session>.jsonl. Attributing them to nobody understated
        # subagent tokens by ~18%, so they are collected separately instead.
        for candidate in _listdir(folder):
            subs = os.path.join(folder, candidate, "subagents")
            # A parent anywhere under the root owns its subagents; one filtered
            # out by --project/--days takes them with it. Only true orphans count.
            if candidate in parents or not os.path.isdir(subs):
                continue
            for leaf in _listdir(subs):
                if not leaf.endswith(".jsonl"):
                    continue
                path = os.path.abspath(os.path.join(subs, leaf))
                sub = analyze_session(path)
                last = parse_ts(sub["last_ts"])
                if cutoff and (last is None or last < cutoff):
                    continue
                subagent_count += 1
                orphans["sessions"] += 1
                orphans["messages"] += sub["messages"]
                for key in ("input", "output", "cache_read", "cache_creation"):
                    orphans[key] += sub["tokens"][key]
                orphan_events.extend(sub["message_events"])
                keep_shapes("subagent", sub["shapes"])
                _merge_drift(totals_drift, sub["drift"])
                sub["meta"] = _subagent_meta(path)
                if sub["meta"]["agent_type"] == "unknown":
                    totals_drift["subagents_without_meta"] += 1
                _add_subagent_rows(rows, {}, sub)     # tokens only: no cost to split

    totals = {
        "sessions": len(sessions),
        "subagent_sessions": subagent_count,
        "messages": sum(s["messages"] for s in sessions),
        "tokens": {k: sum(s["tokens"][k] for s in sessions)
                   for k in ("input", "output", "cache_read", "cache_creation")},
        "subagent_tokens": {
            k: sum(s["subagents"][k] for s in sessions) + orphans[k]
            for k in ("input", "output", "cache_read", "cache_creation")},
        "orphan_subagents": orphans["sessions"],
        "orphan_subagent_tokens": orphans,
        "compactions": sum(s["compactions"] for s in sessions),
        "time": {
            # Summed only over sessions that carry a measured split, with the
            # denominator alongside so partial coverage is never mistaken for
            # a whole-corpus figure.
            "api_ms": sum(s["time"]["api_ms"] or 0 for s in sessions),
            "tool_ms": sum(s["time"]["tool_ms"] or 0 for s in sessions),
            "idle_ms": sum(s["time"]["idle_ms"] or 0 for s in sessions),
            "active_ms": sum(s["time"]["active_ms"] for s in sessions),
            "measured_sessions": sum(
                1 for s in sessions if s["time"]["api_ms"] is not None),
        },
        "cost_usd": sum(s["cost"]["usd"] or 0.0 for s in sessions),
        "unallocated_cost_usd": unallocated,
        "lines_added": sum(s["cost"]["lines_added"] for s in sessions),
        "lines_removed": sum(s["cost"]["lines_removed"] for s in sessions),
    }
    # Per-PR rollup. A session that opened several PRs has its cost SPLIT
    # evenly across them: charging each PR the whole session multiplies the
    # total (one observed session links 31 PRs). The split is an allocation,
    # not a measurement, and every PR fed by such a session says so.
    per_pr = {}
    unattributed = {"sessions": 0, "messages": 0, "output": 0, "cache_read": 0,
                    "api_ms": 0, "tool_ms": 0, "usd": 0.0, "lines_added": 0}
    for session in sessions:
        links = session["prs"]
        if not links:
            unattributed["sessions"] += 1
            unattributed["messages"] += session["messages"]
            unattributed["output"] += session["tokens"]["output"]
            unattributed["cache_read"] += session["tokens"]["cache_read"]
            unattributed["api_ms"] += session["time"]["api_ms"] or 0
            unattributed["tool_ms"] += session["time"]["tool_ms"] or 0
            unattributed["usd"] += session["cost"]["usd"] or 0.0
            unattributed["lines_added"] += session["cost"]["lines_added"]
            continue
        share = len(links)
        for tag in links:
            bucket = per_pr.setdefault(tag, {
                "sessions": 0, "messages": 0, "output": 0, "cache_read": 0,
                "api_ms": 0, "tool_ms": 0, "usd": 0.0, "lines_added": 0,
                "allocation": "exact"})
            bucket["sessions"] += 1
            bucket["messages"] += session["messages"] // share
            bucket["output"] += session["tokens"]["output"] // share
            bucket["cache_read"] += session["tokens"]["cache_read"] // share
            bucket["api_ms"] += (session["time"]["api_ms"] or 0) // share
            bucket["tool_ms"] += (session["time"]["tool_ms"] or 0) // share
            bucket["usd"] += (session["cost"]["usd"] or 0.0) / share
            bucket["lines_added"] += session["cost"]["lines_added"] // share
            if share > 1:
                bucket["allocation"] = "split"

    every_stamp = [e for s in sessions for e in s["message_events"]] + orphan_events
    return {
        "per_pr": per_pr,
        "unattributed": unattributed,
        "generated_at": now_iso(),
        "root": root,
        "window_days": days,
        "totals": totals,
        "blocks": five_hour_blocks(every_stamp),
        # Priced rows first (by cost), unpriced last -- None is never compared.
        "subagents_by_type": sorted(rows.values(), key=lambda r: (
            r["cost_usd"] is None, -(r["cost_usd"] or 0), -r["weighted_tokens"])),
        "implementer_handoff": {"returns": handoffs, "totals": _handoff_totals(handoffs)},
        "sessions": sessions,
        "fixed_context_measured": measured_fixed_context(shapes),
        "drift": totals_drift,
    }


# --- Fixed per-session context cost ----------------------------------------
# Characters are converted to tokens at 4 chars/token. That is an estimate, not
# a measurement: it is reported as `est_tokens` everywhere and must be presented
# as approximate. What it is good for is relative weight -- which surfaces
# dominate the standing cost -- not an exact budget.
CHARS_PER_TOKEN = 4


def _measure(path):
    try:
        with open(path, "r", errors="replace") as handle:
            chars = len(handle.read())
    except (OSError, UnicodeError):
        return {"chars": 0, "est_tokens": 0, "path": path, "present": False}
    return {"chars": chars, "est_tokens": chars // CHARS_PER_TOKEN,
            "path": path, "present": True}


def _description_of(skill_md):
    """Extract the YAML frontmatter description -- the part loaded every session.

    The SKILL.md body is read only when the skill fires, so counting the body
    here would overstate the standing cost by an order of magnitude.
    """
    try:
        with open(skill_md, "r", errors="replace") as handle:
            text = handle.read()
    except (OSError, UnicodeError):
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    block = text[3:end if end != -1 else len(text)]
    lines, collecting, out = block.splitlines(), False, []
    for line in lines:
        if line.startswith("description:"):
            collecting = True
            out.append(line.split(":", 1)[1].strip())
        elif collecting:
            # A new top-level key ends the description; indented lines continue it.
            if line and not line[0].isspace():
                break
            out.append(line.strip())
    return " ".join(p for p in out if p)


def fixed_context_cost(claude_home, project_dir=None):
    """What every session pays before the first word of work.

    Each subagent re-pays most of this, so the effective cost is this figure
    multiplied by (1 + subagents spawned).
    """
    report = {"global_claude_md": _measure(os.path.join(claude_home, "CLAUDE.md"))}

    descriptions, count = 0, 0
    skills_dir = os.path.join(claude_home, "skills")
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, name, "SKILL.md")
            if os.path.isfile(skill_md):
                descriptions += len(_description_of(skill_md))
                count += 1
    report["skill_descriptions"] = {
        "count": count, "chars": descriptions,
        "est_tokens": descriptions // CHARS_PER_TOKEN,
    }

    # A slash command or agent definition loads its BODY only when invoked,
    # exactly like a skill. Only the frontmatter description is standing cost;
    # counting whole files overstated this slice roughly 40x.
    for key, folder in (("commands", "commands"), ("agents", "agents")):
        chars, body, items = 0, 0, 0
        path = os.path.join(claude_home, folder)
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(path, name)
                described = len(_description_of(full))
                chars += described
                body += max(0, _measure(full)["chars"] - described)
                items += 1
        report[key] = {"count": items, "chars": chars,
                       "est_tokens": chars // CHARS_PER_TOKEN,
                       "body_chars": body,
                       "body_est_tokens": body // CHARS_PER_TOKEN}

    report["project_claude_md"] = (
        _measure(os.path.join(project_dir, "CLAUDE.md")) if project_dir
        else {"chars": 0, "est_tokens": 0, "path": None, "present": False})

    report["total_est_tokens"] = sum(
        report[k]["est_tokens"] for k in
        ("global_claude_md", "skill_descriptions", "commands", "agents",
         "project_claude_md"))
    report["note"] = (
        "Estimated at %d chars/token. Every subagent re-pays the global share."
        % CHARS_PER_TOKEN)
    return report


# --- Measured fixed context ------------------------------------------------
# An api-request-shape record holds the real system prompt and tool schemas
# sent with a request. Only their sizes are kept: the text holds prompt and
# config content and must never reach the report.
SHAPE_FIELDS = ("system_chars", "eager_tool_chars", "deferred_tool_chars",
                "eager_tools", "deferred_tools", "est_tokens")


def _shape_size(record):
    system = _dig(record, "shape", "system")
    tools = _dig(record, "shape", "tools")
    if isinstance(system, str):          # the API also takes a bare string
        system = [{"text": system}]
    system_chars = sum(len(b["text"]) for b in system if isinstance(b, dict)
                       and isinstance(b.get("text"), str)) if isinstance(system, list) else 0
    tools = [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else []
    # A defer_loading tool is sent but stays out of context until it is fetched.
    eager = [t for t in tools if t.get("defer_loading") is not True]
    deferred = [t for t in tools if t.get("defer_loading") is True]
    eager_chars = sum(len(json.dumps(t)) for t in eager)
    return {
        "ts": parse_ts(record.get("timestamp")),
        "system_chars": system_chars,
        "eager_tool_chars": eager_chars,
        "deferred_tool_chars": sum(len(json.dumps(t)) for t in deferred),
        "eager_tools": len(eager),
        "deferred_tools": len(deferred),
        "est_tokens": (system_chars + eager_chars) // CHARS_PER_TOKEN,
    }


def measured_fixed_context(shapes):
    """System prompt and tool schema sizes as actually sent, per thread kind.

    Mostly disjoint from fixed_context_cost: CLAUDE.md and the skill listing
    arrive as message attachments, not in the system prompt. Only the agent
    descriptions overlap, inside the Agent tool's schema.
    """
    report = {}
    for kind in ("main", "subagent"):
        part = [s for s in shapes if s["kind"] == kind]
        if not part:
            report[kind] = {"shapes": 0, "latest": None, "median": None}
            continue
        newest = max(part, key=lambda s: s["ts"] or datetime.min.replace(tzinfo=timezone.utc))
        report[kind] = {
            "shapes": len(part),
            "latest": {f: newest[f] for f in SHAPE_FIELDS},
            "median": {f: statistics.median_low([s[f] for s in part]) for f in SHAPE_FIELDS},
        }
    report["note"] = (
        "Measured sizes, tokens estimated at %d chars/token over system + eager tools. "
        "The median is over distinct shapes, not weighted by requests. "
        "Complements .fixed_context: CLAUDE.md and skill listings are not in the "
        "system prompt; agent descriptions overlap via the Agent tool." % CHARS_PER_TOKEN)
    return report


# --- Codex cross-check cost --------------------------------------------------
def codex_summary(root, days=None, project=None):
    """Wall-clock and token cost of Codex audit runs.

    Measures what the cross-checks COST. Whether they were worth it is a
    judgement the model makes in the report, not a number this script can produce.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    sessions, total_wall, drift = [], 0, _blank_drift()
    tokens = {"input": 0, "output": 0, "cached_input": 0, "total": 0}

    for folder, _, files in os.walk(root) if os.path.isdir(root) else []:
        for name in sorted(files):
            if not (name.startswith("rollout-") and name.endswith(".jsonl")):
                continue
            path = os.path.join(folder, name)
            stamps, latest, cwd = [], None, None
            for record, _ in iter_records(path):
                if record is None:
                    drift["unparseable_lines"] += 1
                    continue
                moment = parse_ts(record.get("timestamp"))
                if moment:
                    stamps.append(moment)
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("session_id") and not cwd:
                    cwd = payload.get("cwd")
                if payload.get("type") == "token_count":
                    usage = _dig(payload, "info", "total_token_usage")
                    if isinstance(usage, dict):
                        latest = usage       # cumulative; the last one wins
            if not stamps:
                continue
            stamps.sort()
            if cutoff and stamps[-1] < cutoff:
                continue
            # A single-repo audit must not be charged the whole Codex corpus.
            if project and project not in (cwd or ""):
                continue
            wall = int((stamps[-1] - stamps[0]).total_seconds() * 1000)
            total_wall += wall
            if latest:
                tokens["input"] += _num(latest.get("input_tokens"))
                tokens["output"] += _num(latest.get("output_tokens"))
                tokens["cached_input"] += _num(latest.get("cached_input_tokens"))
                tokens["total"] += _num(latest.get("total_tokens"))
            sessions.append({
                "path": path, "cwd": cwd, "wall_ms": wall,
                "started": stamps[0].isoformat(), "ended": stamps[-1].isoformat(),
                "tokens": latest or {},
            })

    return {"sessions": len(sessions), "wall_ms": total_wall,
            "tokens": tokens, "runs": sessions, "drift": drift}


# --- Gate scorecard ----------------------------------------------------------
def read_gate_log(log_path):
    """([(moment, record)], unparseable) in file order. A missing log is no records."""
    records, unparseable = [], 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            gate_log.validate_record(rec)
            moment = parse_ts(rec.get("ts"))
        except (ValueError, TypeError, AttributeError, RecursionError, gate_log.GateLogError):
            unparseable += 1
            continue
        if moment is None:
            unparseable += 1
        else:
            records.append((moment, rec))
    return records, unparseable


def gate_units(log_path, days=None, project=None):
    """One row per unit (repo, slug) with its tier and the clause quoted for it, plus the mix.

    Returns (units, mix): mix is {lane: {tier or "unknown": units}}. A unit takes the last
    record written that carries a tier, since feature-workflow restates the tier where it
    changes. File order, not `ts`: a round-2 record keeps round 1's ledger date. The window
    picks which units appear, not which records classify them. A unit no record classified
    (Codex gates before codex-audit took --tier) is `unknown`.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    units = {}
    records, _ = read_gate_log(log_path)
    for moment, rec in records:
        if project and project not in rec["repo"]:
            continue
        unit = units.setdefault((rec["repo"], rec["slug"]), {
            "repo": rec["repo"], "slug": rec["slug"], "lane": rec["lane"], "tier": None,
            "trigger": None, "records": 0})
        if rec.get("tier") is not None:
            unit["tier"], unit["trigger"] = rec["tier"], rec.get("trigger")
        if not (cutoff and moment < cutoff):
            unit["lane"] = rec["lane"]
            unit["records"] += 1
    units = [unit for unit in units.values() if unit["records"]]
    mix = {}
    for unit in units:
        lane = mix.setdefault(unit["lane"], {})
        tier = unit["tier"] or "unknown"
        lane[tier] = lane.get(tier, 0) + 1
    return units, mix


def gate_scorecard(log_path, days=None, project=None):
    """Roll the gate log up into one row per (gate, lane).

    Returns (rows, unparseable). It counts what gates found and what triage did with it; it
    does not say whether a gate was worth its cost -- that is the model's judgement (SKILL.md
    area 10). A missing log is an empty scorecard, and a line that is not a valid record is
    counted and skipped, never fatal.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)) if days else None
    claude, keyed, skips = [], {}, {}
    records, unparseable = read_gate_log(log_path)
    for moment, rec in records:
        if rec["source"] == "claude":
            # A delta re-audit is its own run, so its clean result must not erase the first
            # audit's findings: every Claude record counts.
            claude.append((moment, rec))
        else:
            base = (rec["repo"], rec["slug"], rec["gate"], rec.get("pr"))
            if rec["skipped"]:
                # Kept apart: a skip shares no thread with a review, so in one dict it could
                # replace a threadless legacy review that came before it.
                skips[base] = (moment, rec)
            else:
                # A Codex record is cumulative for its ledger, so the last one for a run is
                # the complete one; file order is the order they were written. The thread
                # tells a --rerun (a new review of the same artifact) from round 2, which
                # resumes round 1's thread. A ledger from before threads were recorded falls
                # back to its own date, which still tells an archive from its live ledger.
                keyed[base + (rec.get("thread") or rec["ts"],)] = (moment, rec)
    # A skip ledger is overwritten by the review that follows it, so drop a skip when a review
    # of the same gate run is as late or later. A skip recorded after a review never overwrote
    # it (codex-audit refuses), and stays counted.
    reviewed = {}
    for k, (moment, _) in keyed.items():
        reviewed[k[:4]] = max(moment, reviewed.get(k[:4], moment))
    skips = [v for base, v in skips.items() if not (base in reviewed and reviewed[base] >= v[0])]

    rows = {}
    for moment, rec in claude + list(keyed.values()) + skips:
        if (cutoff and moment < cutoff) or (project and project not in rec["repo"]):
            continue
        row = rows.setdefault((rec["gate"], rec["lane"]), {
            "gate": rec["gate"], "lane": rec["lane"], "runs": 0, "skipped": 0,
            "runs_with_findings": 0, "found": dict.fromkeys(gate_log.SEVERITIES, 0),
            "accepted": dict.fromkeys(gate_log.SEVERITIES, 0),
            "untriaged": dict.fromkeys(gate_log.SEVERITIES, 0), "rejected": 0, "deferred": 0,
            "human": 0, "wall_s": None, "_acceptance_known": set()})
        if rec["skipped"]:
            row["skipped"] += 1
            continue
        row["runs"] += 1
        row["runs_with_findings"] += 1 if sum(rec["found"].values()) else 0
        for sev in gate_log.SEVERITIES:
            row["found"][sev] += rec["found"][sev]
            if rec["accepted"][sev] is None:
                row["untriaged"][sev] += rec["found"][sev]
            else:
                row["_acceptance_known"].add(sev)
                row["accepted"][sev] += rec["accepted"][sev]
        for field in ("rejected", "deferred", "human"):
            row[field] += rec[field]
        if isinstance(rec.get("wall_s"), int):
            row["wall_s"] = (row["wall_s"] or 0) + rec["wall_s"]

    order = {gate: i for i, gate in enumerate(gate_log.GATES)}
    out = []
    for key in sorted(rows, key=lambda k: (order[k[0]], k[1])):
        row = rows[key]
        known = row.pop("_acceptance_known")
        # The rate is over triaged findings only: an untriaged one (a one-shot 6b) is neither
        # accepted nor rejected, so it leaves the denominator and is reported as `untriaged`.
        for sev in gate_log.SEVERITIES:
            if sev not in known:
                row["accepted"][sev] = None
        row["accept_rate"] = {}
        for sev in gate_log.SEVERITIES:
            triaged = row["found"][sev] - row["untriaged"][sev]
            row["accept_rate"][sev] = (row["accepted"][sev] / triaged
                                       if row["accepted"][sev] is not None and triaged else None)
        out.append(row)
    return out, unparseable


def build_report(root, days=None, project=None, claude_home=None, codex_root=None,
                 project_dir=None, gate_log_path=None):
    """Assemble the full JSON report the skill reads."""
    report = analyze_corpus(root, days=days, project=project)
    for session in report["sessions"]:
        session.pop("timestamps", None)     # working state, not a metric
        session.pop("message_events", None)
        session.pop("parts", None)
        session.pop("events", None)
        session.pop("shapes", None)
    report["fixed_context"] = fixed_context_cost(
        claude_home or os.path.expanduser("~/.claude"), project_dir=project_dir)
    report["codex"] = codex_summary(codex_root or DEFAULT_CODEX, days=days,
                                    project=project)
    report["gates"], bad = gate_scorecard(gate_log_path or gate_log.log_path(),
                                          days=days, project=project)
    report["drift"]["gate_log_unparseable"] = bad
    report["gate_units"], report["tier_mix"] = gate_units(
        gate_log_path or gate_log.log_path(), days=days, project=project)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure token and time cost across Claude Code sessions.")
    parser.add_argument("--days", type=int, default=30,
                        help="only sessions active in the last N days (0 = all)")
    parser.add_argument("--project", default=None,
                        help="substring filter on the project directory name")
    parser.add_argument("--root", default=DEFAULT_ROOT,
                        help="transcript root (default: ~/.claude/projects)")
    parser.add_argument("--claude-home", default=os.path.expanduser("~/.claude"))
    parser.add_argument("--codex-root", default=DEFAULT_CODEX)
    parser.add_argument("--project-dir", default=None,
                        help="repo checkout whose CLAUDE.md adds to the fixed cost")
    parser.add_argument("--gate-log", default=None,
                        help="gate log to read (default: $GATE_LOG or ~/.claude/gate-log.jsonl)")
    args = parser.parse_args(argv)

    report = build_report(args.root, days=args.days or None, project=args.project,
                          claude_home=args.claude_home, codex_root=args.codex_root,
                          project_dir=args.project_dir, gate_log_path=args.gate_log)
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
