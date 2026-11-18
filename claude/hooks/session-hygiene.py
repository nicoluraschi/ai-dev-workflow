#!/usr/bin/env python3
"""UserPromptSubmit notice: say when a session has outgrown the work it was opened for.

CLAUDE.md already says "one session per worktree — end the session when the work ends".
Long sessions carry far more context per message and produce less. Thresholds sit where
compaction happens (500 msgs) and at a working day (8h), plus a concurrency and PR-opened notice.

So this hook reports two things it can measure exactly -- how many messages this session has
and how long it has been open -- at the moment the human starts the next piece of work, which
is when the answer can still change anything.

Enforcement level: `notify`, never `block`. This follows the doctrine in audit-guard.py -- a
path signal may block, a heuristic may only notify. "This session is getting long" is a
judgement about how someone is working, and blocking mid-feature would be actively harmful:
the whole point is to finish the PR in flight and THEN stop. A false positive you cannot
dismiss is how a gate dies.

The size notice fires at most ONCE per session, on whichever trigger -- size or span -- crosses
first.
Concurrency is a trigger of its own, also once per session. The count is approximate both ways
(see below): an idle open session is missed, a session closed in the last 30 minutes is
counted. It is shown to the developer as well, since closing sessions is theirs to do.
An opened PR is the third trigger, also once per session. A Bash `gh pr create` whose result
holds a `/pull/<n>` URL marks the moment the next piece of work should start fresh. It is shown to the
developer too, since /clear is theirs to run.
Fails OPEN on any error, like block-edits-on-main.py -- it must never wedge a session.

Escape hatches (the HUMAN's; this hook prints no recipe, and gate-state-guard.py denies the agent
writing the state dir):
  1. touch "$STATE/<session_id>.skip.session-hygiene"  -- silence for SKIP_TTL_SECONDS.
  2. CLAUDE_SESSION_HYGIENE_SKIP=1                     -- disable entirely.
A silencer EXPIRES, for the same reason audit-guard's does: a session is not a unit of time,
so "just for now" would otherwise quietly become "for the rest of the week".
"""
import json
import os
import re
import sys
import time
from datetime import datetime

# Where compaction happens.
MSG_THRESHOLD = 500
# A session older than a working day is not one piece of work any more.
SPAN_THRESHOLD_H = 8
# Other sessions with RECENT ACTIVITY -- not "open sessions", which is the thing we would rather
# know and cannot get from disk: a session left open but idle stops touching every file it owns
# (state AND transcript), so it is indistinguishable from a closed one without process inspection.
# Set so the notice fires past the 4-session ceiling in CLAUDE.md: 4 others means 5 in all.
CONCURRENT_THRESHOLD = 4
# Bounds how stale a "live" session may look: a crashed session leaves its marker behind.
CONCURRENT_WINDOW_MIN = 30
# Same as audit-guard, for the same reason.
SKIP_TTL_SECONDS = 4 * 3600

SKILL = "session-hygiene"
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")


def allow():
    sys.exit(0)


def state_dir():
    d = os.environ.get("CLAUDE_AUDIT_STATE_DIR") or os.path.expanduser("~/.claude/.audit-state")
    os.makedirs(d, exist_ok=True)
    return d


def safe_session(raw):
    """Session ids are validated before use in filenames; invalid ids collapse to `unknown` so
    they never escape the state dir. Validating once covers the state file, the tmp file and the silencer
    together, which is why it is done here rather than at each sink."""
    s = str(raw or "")
    if not s or len(s) > 128 or not all(c.isalnum() or c in "._-" for c in s) or s.strip(".") == "":
        return "unknown"
    return s


def state_path(session):
    return os.path.join(state_dir(), f"{session}.hygiene.json")


def inside_state(path):
    """Guard the delete below: session_id arrives in the payload and is interpolated into the
    filename, so a traversing id ("../../x") would otherwise aim os.remove anywhere on disk.
    Same containment audit-guard.py uses, for the same reason."""
    d = os.path.realpath(state_dir())
    try:
        return os.path.commonpath([d, os.path.realpath(path)]) == d
    except ValueError:
        return False


def live_skip(session):
    """True while a silencer is in force. Deletes it once it has aged out, so a gate turned
    off on purpose comes back on its own."""
    p = os.path.join(state_dir(), f"{session}.skip.{SKILL}")
    try:
        age = time.time() - os.path.getmtime(p)
    except OSError:
        return False
    if age <= SKIP_TTL_SECONDS:
        return True
    if inside_state(p):
        try:
            os.remove(p)
        except OSError:
            pass
    return False


def load(session):
    try:
        with open(state_path(session)) as f:
            s = json.load(f)
        if isinstance(s, dict):
            return s
    except Exception:
        pass
    return {}


def save(session, s):
    tmp = state_path(session) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, state_path(session))


def scan(transcript_path, s):
    """Count assistant API responses appended since the last run, cheaply.

    Reads only the bytes added since the stored offset, so the cost tracks one turn rather than
    the whole history. Counts records with `message.usage`, the same unit the audit measured.
    Raises if the transcript cannot be read at all.
    """
    size = os.path.getsize(transcript_path)
    offset = int(s.get("offset") or 0)
    # The transcript was replaced or truncated (a new session at the same path): start over
    # rather than silently undercounting from an offset past the end.
    if size < offset:
        offset, s["msgs"], s["first_ts"] = 0, 0, None
        s["pr_pending"], s["pr_url"] = [], None

    msgs = int(s.get("msgs") or 0)
    first_ts = s.get("first_ts")
    # `gh pr create` tool_use ids still waiting for their result, which may land in a later scan.
    pending = set(s.get("pr_pending") or [])
    pr_url = s.get("pr_url")
    consumed = 0

    # Iterate the file rather than read() it whole. The unread gap is normally one turn, but the
    # first run after this hook is installed sees an ENTIRE existing transcript -- the largest in
    # ~/.claude/projects measures 30MB today, and nothing bounds it going forward. Buffered line
    # iteration keeps memory flat and the byte accounting exact either way.
    with open(transcript_path, "rb") as f:
        f.seek(offset)
        for line in f:
            # A line without a trailing newline is the harness mid-append: stop, and do not
            # consume it, so the next run re-reads it whole.
            if not line.endswith(b"\n"):
                break
            consumed += len(line)
            line = line.strip()
            # tool_result lines are the transcript's largest (file reads, command output): decode
            # one only while a `gh pr create` waits for its result.
            if not line or (b'"usage"' not in line
                            and not (pending and b'"tool_result"' in line)):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue          # a malformed line is skipped, never fatal
            content = (obj.get("message") or {}).get("content")
            blocks = [c for c in content if isinstance(c, dict)] if isinstance(content, list) else []
            if obj.get("type") == "user" and pending:
                for c in blocks:
                    if c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                        pending.discard(c["tool_use_id"])
                        # Bash results are a string; str() of a block list still holds the URL.
                        m = None if c.get("is_error") else PR_URL.search(str(c.get("content") or ""))
                        if m and not pr_url:
                            pr_url = m.group(0)
                continue
            if obj.get("type") != "assistant":
                continue
            for c in blocks:
                if (c.get("type") == "tool_use" and c.get("name") == "Bash"
                        and "gh pr create" in str((c.get("input") or {}).get("command") or "")):
                    pending.add(c.get("id"))
            if not ((obj.get("message") or {}).get("usage")):
                continue
            msgs += 1
            if first_ts is None:
                try:
                    first_ts = datetime.fromisoformat(
                        str(obj.get("timestamp")).replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass

    s["offset"] = offset + consumed
    s["msgs"] = msgs
    s["first_ts"] = first_ts
    s["pr_pending"] = sorted(i for i in pending if isinstance(i, str))
    s["pr_url"] = pr_url
    return s


def concurrent_sessions(session):
    """How many OTHER sessions have touched the state dir recently. Approximate by
    construction -- an abandoned session leaves its marker behind, which is what the
    freshness window bounds."""
    cutoff = time.time() - CONCURRENT_WINDOW_MIN * 60
    others = set()
    try:
        d = state_dir()
        entries = os.listdir(d)
    except OSError:
        return 0
    for name in entries:
        sid = name.split(".")[0]
        if not sid or sid == session:
            continue
        try:
            if os.path.getmtime(os.path.join(d, name)) >= cutoff:
                others.add(sid)
        except OSError:
            continue
    return len(others)


def concurrency_notice(others):
    return (f"{others} other sessions were active in the last {CONCURRENT_WINDOW_MIN} minutes; "
            "more than 4 in parallel overloads the machine and drains the usage window. Close "
            "the ones whose PR is already open.")


def pr_notice(url):
    return (f"PR {url} was opened from this session. If this prompt starts new work, run /clear "
            "or open a new session.")


def build_notice(msgs, span_h, others, size, pr_url=None):
    parts = []
    if size:
        parts.append(
            f"This session is at {msgs} messages, {span_h:.1f}h open. Finish the PR in flight, "
            "then open a fresh session for the next piece of work.")
    if pr_url:
        parts.append(pr_notice(pr_url))
    if others >= CONCURRENT_THRESHOLD:
        parts.append(("Also: " if size else "") + concurrency_notice(others))
    return " ".join(parts)


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            allow()
    except SystemExit:
        raise
    except Exception:
        allow()

    try:
        if data.get("hook_event_name") != "UserPromptSubmit":
            allow()
        if os.environ.get("CLAUDE_SESSION_HYGIENE_SKIP"):
            allow()

        session = safe_session(data.get("session_id"))
        if live_skip(session):
            allow()

        transcript = data.get("transcript_path")
        if not transcript or not os.path.isfile(transcript):
            allow()

        s = scan(transcript, load(session))
        msgs = int(s.get("msgs") or 0)
        first_ts = s.get("first_ts")
        span_h = (time.time() - first_ts) / 3600.0 if first_ts else 0.0

        warned = set(s.get("warned") or [])
        fresh = []
        # Size and span share one notice per session; concurrency has its own.
        if not warned & {"msgs", "span"}:
            if msgs >= MSG_THRESHOLD:
                fresh.append("msgs")
            if span_h >= SPAN_THRESHOLD_H:
                fresh.append("span")
        others = 0 if "concurrent" in warned else concurrent_sessions(session)
        if others >= CONCURRENT_THRESHOLD:
            fresh.append("concurrent")
        if "pr" not in warned and s.get("pr_url"):
            fresh.append("pr")

        if not fresh:
            save(session, s)
            allow()

        # Emit BEFORE recording the trigger as delivered. The reverse order loses the notice
        # for the rest of the session if anything between the two fails -- the 10s timeout in
        # settings.json -- because the outer handler exits 0 and `warned` already claims it
        # was shown.
        out = {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": build_notice(
                msgs, span_h, others, size="msgs" in fresh or "span" in fresh,
                pr_url=s["pr_url"] if "pr" in fresh else None),
        }}
        shown = ([pr_notice(s["pr_url"])] if "pr" in fresh else []) + (
            [concurrency_notice(others)] if "concurrent" in fresh else [])
        if shown:
            out["systemMessage"] = " ".join(shown)
        print(json.dumps(out))
        s["warned"] = sorted(warned | set(fresh))
        save(session, s)
    except SystemExit:
        raise
    except Exception:
        allow()
    allow()


if __name__ == "__main__":
    main()
