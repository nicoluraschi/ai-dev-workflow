#!/usr/bin/env python3
"""Deterministic backstop for the review skills.

Rules in CLAUDE.md and feature-workflow tell the agent to run these skills. Those are
conventions — they depend on the model complying. This hook is the part that does not:
the harness runs it regardless of what the model noticed, and regardless of whether the
developer remembered the skill exists.

Two enforcement levels, matched to how precise the trigger signal is:

  block    A path signal that is unambiguous (a migration, an auth controller). The Stop
           hook refuses to end the turn until the skill has run. Highest cost if missed.
  notify   A content heuristic that can be wrong (a query near a loop). Injects context
           at PostToolUse so the agent is told every time, but never holds the turn
           hostage — a false positive you cannot dismiss is how a gate dies.

An audit counts only if the skill ran AFTER the last triggering edit, so a stale audit
from earlier in the session does not satisfy the gate.

Fails OPEN on any error, matching block-edits-on-main.py — it must never wedge a session.

Escape hatches, in order of preference (2-4 are the HUMAN's, not the agent's; refusals no longer
print them and gate-state-guard.py denies the agent writing the state dir):
  1. Run the skill (the intended path).
  2. touch "$STATE/<session_id>.skip.<skill>"  — silence ONE skill for SKIP_TTL_SECONDS.
  3. touch "$STATE/<session_id>.skip"          — silence all of them for SKIP_TTL_SECONDS.
  4. CLAUDE_AUDIT_SKIP=1 in the environment    — disable the gate entirely.
Per-skill overrides exist so that one noisy gate cannot silently disable the others.
After MAX_BLOCKS refusals it releases on its own, so it can never trap you in a loop.

A silencer EXPIRES. It was scoped to "this session", but a session is not a unit of time:
sessions here routinely live for days and across many branches, so "just for now" silently
became "for the rest of the week" — measured, a security-audit skip stayed on for twelve
hours across a session boundary nobody noticed. The file now ages out after
SKIP_TTL_SECONDS and is deleted, so a gate turned off on purpose comes back on its own.
Re-touch the file if you genuinely still want it off; that is a decision, not an oversight.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime

MAX_BLOCKS = 2
# How long a `.skip` file silences a gate. Long enough to cover a working block without
# re-touching it; short enough that it cannot outlive the reason it was created.
SKIP_TTL_SECONDS = 4 * 3600
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
# Before blocking, Stop waits this long and re-reads the transcript once. The record of an audit
# that ran moments earlier can reach the file after the hook has already read it (an audit
# 4s before a block; a replay of the same state released). Only paid
# when about to block; well inside the hook's 10s timeout.
RETRY_SECONDS = 2.0

# A query-ish call and a loop-ish construct in the same written text. Deliberately narrow:
# the classic N+1 is far better caught by reading a plan (feature-workflow gate 2d) or by
# /code-review at phase 6 than by grepping a diff. This is a safety net, not the main net.
QUERY_RE = r"\.where\(|\.find\(|\.find_by|\.pluck\(|\.joins\(|\.includes\(|\bSELECT\s|\.all\b"
LOOP_RE = r"\.each\b|\.map\b|\.flat_map\b|\bfor\s+\w+\s+in\b|\bwhile\b"

# The constraint surface of a model file: associations, validations, enums, callbacks and column
# constraints (Rails), field and constraint declarations (Django, SQLAlchemy, Sequelize, TypeORM).
# A model edit owes data-integrity only when one of these is added OR removed -- phase-5
# data-integrity ran ~33 times on model edits for one minor finding, because a scope or a method is
# not the constraint surface. Options are listed on their own because an edit to a continuation
# line (`  optional: false`) carries no association or validation keyword.
CONSTRAINT_RE = (
    r"\b(belongs_to|has_many|has_one|has_and_belongs_to_many|enum|counter_cache|inverse_of)\b",
    r"\b(has_one_attached|has_many_attached|accepts_nested_attributes_for)\b",
    r"\bvalidates?(_\w+)?\b",
    r"\b(before|after|around)_(validation|save|create|update|destroy|commit|rollback)(_commit)?\b",
    r"\b(dependent|null|nullable|default|server_default|unique|unique_together|constraints|"
    r"foreign_key|primary_key|touch|optional|required|uniqueness|presence|length|inclusion|"
    r"numericality|allow_nil|allow_blank|ondelete|onDelete|allowNull|index)\s*[:=]",
    r"\b\w*Field\(|\b(ForeignKey|UniqueConstraint|CheckConstraint|on_delete)\b",
    r"\b(Column|relationship|mapped_column)\(",
    r"\.(hasMany|hasOne|belongsTo|belongsToMany)\(",
    r"@(ManyToOne|OneToMany|OneToOne|ManyToMany|Column|PrimaryGeneratedColumn|Unique|Index)\b",
)

# ---------------------------------------------------------------------------
# The whole sensitivity surface. Tune here if a gate proves noisy in your repos.
# ---------------------------------------------------------------------------
REQUIREMENTS = [
    {
        "skill": "security-audit",
        "enforce": "block",
        "why": "auth / money / secrets surface",
        "tools": EDIT_TOOLS,
        # NB: `migration` and `schema` deliberately live under data-integrity instead,
        # so an ordinary migration does not also owe a security audit. One on a payments
        # table still matches `payment` here and correctly owes both.
        "paths": ("auth", "session", "login", "signin", "sign_in", "signup", "sign_up",
                  "password", "passwd", "token", "jwt", "oauth", "saml",
                  "crypto", "encrypt", "decrypt", "secret", "credential", "signature",
                  "permission", "policy", "policies", "role", "acl", "tenant", "guard",
                  "admin", "payment", "billing", "invoice", "subscription", "charge",
                  "checkout", "webhook", "middleware", "routes"),
        "suffixes": (".env", ".tf", ".tfvars", ".pem", ".key"),
        # audit-guard.json is matched by name, before any ignore term is cut: see load_ignores().
        "basenames": ("dockerfile", "docker-compose.yml", "docker-compose.yaml", "nginx.conf",
                      "audit-guard.json"),
    },
    {
        "skill": "data-integrity",
        "enforce": "block",
        "why": "schema or migration change",
        "tools": EDIT_TOOLS,
        "paths": ("db/migrate", "migrations/", "schema.rb", "structure.sql", ".prisma"),
    },
    {
        "skill": "data-integrity",
        "enforce": "block",
        "why": "model constraint change",
        "tools": EDIT_TOOLS,
        "paths": ("app/models/", "/models/"),
        "signal_any": CONSTRAINT_RE,
    },
    {
        "skill": "migration-safety",
        "enforce": "block",
        "why": "migration — locking, backfill and reversibility",
        "tools": EDIT_TOOLS,
        "paths": ("db/migrate", "migrations/"),
    },
    {
        "skill": "observability",
        "enforce": "notify",
        "why": "new endpoint, job or service",
        "tools": {"Edit", "Write", "MultiEdit"},
        "paths": ("app/controllers/", "app/jobs/", "app/workers/", "app/services/", "/api/"),
        "content_any": (r"\bdef\s+\w+", r"ApplicationJob", r"Sidekiq::Worker",
                        r"<\s*ApplicationController"),
    },
    {
        "skill": "performance-review",
        "enforce": "notify",
        "why": "a query and a loop in the same change",
        "tools": {"Edit", "Write", "MultiEdit"},
        "content_all": (QUERY_RE, LOOP_RE),
    },
]


def allow():
    sys.exit(0)


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def state_dir():
    d = os.environ.get("CLAUDE_AUDIT_STATE_DIR") or os.path.expanduser("~/.claude/.audit-state")
    os.makedirs(d, exist_ok=True)
    return d


def safe_session(raw):
    """Session ids are validated before use in filenames (<session>.json, its .tmp,
    <session>.skip and <session>.skip.<skill>); invalid ids are hashed so they never escape the
    state dir.

    Each hook in this directory is standalone -- a broken sibling import must never stop a gate
    from running -- so this validator is repeated rather than shared. It is NOT a copy of
    session-hygiene.py's: that one collapses a rejected id to a flat "unknown", which is fine
    there (worst case, one missed notice) and would be wrong here for the reason above. Do not
    "re-sync" the two into agreement; the divergence is the point.
    """
    v = str(raw or "")
    if not v or len(v) > 128 or not all(c.isalnum() or c in "._-" for c in v) or v.strip(".") == "":
        return "unknown-" + hashlib.sha256(v.encode("utf-8", "replace")).hexdigest()[:16]
    return v


def state_path(session):
    return os.path.join(state_dir(), f"{session}.json")


def written_text(ti):
    """Whatever text this tool call actually wrote, across tool shapes."""
    parts = []
    for k in ("content", "new_string", "new_source"):
        v = ti.get(k)
        if isinstance(v, str):
            parts.append(v)
    edits = ti.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                parts.append(e["new_string"])
    return "\n".join(parts)


def changed_text(ti):
    """The lines this tool call added or removed, or None when it carries no text at all. For an
    Edit that is the lines only one side of old_string/new_string has, counting repeats --
    removing a validation is a constraint change too, and an association that is only unchanged
    context is not. A Write or notebook cell has no old side: all of it."""
    parts = [ti[k] for k in ("content", "new_source") if isinstance(ti.get(k), str)]
    seen = bool(parts)
    edits = ti.get("edits")
    pairs = [ti] + ([e for e in edits if isinstance(e, dict)] if isinstance(edits, list) else [])
    for p in pairs:
        old, new = p.get("old_string"), p.get("new_string")
        seen = seen or isinstance(old, str) or isinstance(new, str)
        old = Counter(old.splitlines() if isinstance(old, str) else [])
        new = Counter(new.splitlines() if isinstance(new, str) else [])
        parts += list(((old - new) + (new - old)).elements())
    return "\n".join(parts) if seen else None


# Extensions whose PATH cannot itself carry a security surface. A .md is prose: the content
# requirements still see it, only the keyword-in-path ones are skipped. This is what stopped a
# memory note called `no-edits-on-main-guard.md` from firing the blocking tier.
#
# `.txt` is deliberately NOT here. It looks like prose and is not: plaintext is exactly where
# secrets get parked, so `credentials.txt` or `token.txt` must keep owing an audit on its name.
PROSE_SUFFIXES = (".md", ".rst")


def repo_relative(fp):
    return locate(fp)[1]


def locate(fp):
    """(checkout root, `fp` relative to it) -- or (None, `fp` unchanged) when it is not in one.

    The keywords are matched against this, not the absolute path. Absolute paths carry the branch
    name -- a worktree at ~/worktrees/dotfiles/fix/guard-covers-dotfiles made every one of the 137
    tracked files in that repo owe a blocking security audit, purely because the BRANCH was named
    after what it fixed.

    Falls back to the full path on any failure, which keeps the old over-blocking behaviour rather
    than silently under-blocking -- the conservative direction for a gate.
    """
    d = fp if os.path.isdir(fp) else os.path.dirname(fp)
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=5)
        root = r.stdout.strip()
        if r.returncode != 0 or not root:
            return None, fp
        # realpath BOTH sides: on macOS `git` reports /private/var/... while the payload carries
        # /var/..., and relpath across that symlink produces a ../.. path that looks like an escape.
        rel = os.path.relpath(os.path.realpath(fp), os.path.realpath(root))
        if rel.startswith(".."):
            return None, fp
        # Re-anchor with a leading slash: two patterns are written "/models/" and "/api/", and they
        # only ever matched because the path was absolute. Without this, relativizing turns the
        # BLOCK-tier data-integrity requirement silently off for any repo with a top-level models/.
        return root, "/" + rel
    except Exception:
        return None, fp


def load_ignores(root):
    """{skill: [term, ...]} from <root>/.claude/audit-guard.json, lowercased.

    A repo's own domain can collide with a keyword: an app with a ReadingSession model had
    "session" make 73 of its 81 matching files owe a blocking security audit. A listed term is
    cut out of the path before that skill's keywords are matched, so `reading_sessions_controller`
    stops matching "session" while `reading_session_auth` still matches "auth".

    The file is tracked, so an ignore is a reviewed decision; editing it owes security-audit
    itself. That match is on its basename, never a keyword: the hook runs after the write and
    reads the NEW file, so a keyword match could be cut by the very edit it should gate.
    Anything malformed is treated as no file: the gate fires.
    """
    if not root:
        return {}
    try:
        with open(os.path.join(root, ".claude", "audit-guard.json")) as f:
            raw = json.load(f).get("ignore", {})
        return {skill: [t.lower() for t in terms if isinstance(t, str) and t]
                for skill, terms in raw.items() if isinstance(terms, list)}
    except Exception:
        return {}


def path_hit(req, low, base, ignore=()):
    if "paths" not in req and "suffixes" not in req and "basenames" not in req:
        return None  # this requirement does not constrain by path
    if base in req.get("basenames", ()):
        return True
    if low.endswith(tuple(req.get("suffixes", ()))) if req.get("suffixes") else False:
        return True
    for term in ignore:
        low = low.replace(term, "")
    return any(p in low for p in req.get("paths", ()))


def matches(req, fp, text, tool, rel=None, ignore=(), changed=None):
    """`rel` is repo_relative(fp), computed ONCE by the caller. Resolving it per requirement meant
    five `git rev-parse` subprocesses per edit for an identical answer -- measured 19ms -> 67ms --
    and five independent timeout=5 calls, so a wedged git could stall the hook for 25s.
    `ignore` is this requirement's terms from load_ignores(); `changed` is changed_text()."""
    if tool not in req["tools"]:
        return False
    # Keywords are matched against the path RELATIVE to the checkout, so a branch or session
    # directory name cannot trigger them. Prose skips the path requirements entirely.
    if rel is None:
        rel = repo_relative(fp)
    low = rel.lower()
    if low.endswith(PROSE_SUFFIXES) and ("paths" in req or "basenames" in req):
        # Prose does not satisfy a PATH requirement, full stop. An earlier draft let a requirement
        # that also has a content test fall through to that test -- which is backwards: it made
        # `observability` MORE likely to fire on a .md under app/controllers/, not less. A
        # content-only requirement (performance-review has no `paths`) is unaffected either way,
        # because this branch never applies to it.
        hit = False
    else:
        hit = path_hit(req, low, os.path.basename(low), ignore)
    if hit is False:
        return False
    if "content_any" in req:
        if not text or not any(re.search(p, text) for p in req["content_any"]):
            return False
    if "content_all" in req:
        if not text or not all(re.search(p, text) for p in req["content_all"]):
            return False
    if "signal_any" in req:
        # Unlike content_any, a call carrying no text at all still owes the audit: the gate cannot
        # see what changed, so it errs toward blocking.
        if changed is not None and not any(re.search(p, changed) for p in req["signal_any"]):
            return False
    return True


def load_state(session):
    try:
        with open(state_path(session)) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else None
    except Exception:
        return None


def save_state(session, s):
    tmp = state_path(session) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, state_path(session))


# A `context: fork` skill (security-audit) runs in the background: its tool_result only says it
# launched, and its result arrives later as a <task-notification> naming the same tool-use-id.
# Counting the launch would release the gate before, or without, any audit -- a fork that
# returns "⚪ not run" for a missing input did no audit at all.
FORKED_MARK = "forked execution"
# A fork with no notice after this long was killed, not slow: an audit takes minutes.
INFLIGHT_MAX_SECONDS = 30 * 60
NOT_RUN_MARK = "⚪ not run"
# A completed fork counts only if its result carries an audit verdict. Fails closed: a not-run,
# a crash message or any wrapping of either has no verdict, while a real audit that merely
# quotes the not-run marker still has one.
VERDICT_MARKS = ("🟢", "🔴")
NOTICE_BLOCK_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
NOTICE_TID_RE = re.compile(r"<tool-use-id>\s*(\S+?)\s*</tool-use-id>")
NOTICE_STATUS_RE = re.compile(r"<status>\s*(\w+)\s*</status>")


def notices_in(content):
    """{tool-use-id: counts?} from a harness notice's text, else {}.

    The caller passes only a harness row's text: a user row's content, or a harness
    queued_command attachment's prompt (see queued_notice). Either must be a string opening
    with <task-notification>. Notice-shaped text anywhere else -- the assistant's own words, a system-reminder
    echoing a file or diff (this hook's tests hold such strings) -- is not."""
    if not isinstance(content, str) or not content.lstrip().startswith("<task-notification>"):
        return {}
    found = {}
    for block in NOTICE_BLOCK_RE.findall(content):
        tid, status = NOTICE_TID_RE.search(block), NOTICE_STATUS_RE.search(block)
        if tid and status:  # a status-less progress note is not an outcome
            found[tid.group(1)] = (status.group(1) == "completed"
                                   and any(m in block for m in VERDICT_MARKS))
    return found


def queued_notice(obj):
    """The notice text of a harness notice delivered mid-turn, else None.

    A notice that arrives while the session is busy is written as a queued_command attachment,
    not a user row (checked live). Prompts you queue and subagent hand-backs (model
    output) share that row type, so only the harness's own commandMode and origin count."""
    att = obj.get("attachment")
    if obj.get("type") != "attachment" or not isinstance(att, dict):
        return None
    origin = att.get("origin")
    if (att.get("type") == "queued_command" and att.get("commandMode") == "task-notification"
            and isinstance(origin, dict) and origin.get("kind") == "task-notification"):
        return att.get("prompt")
    return None


def audits_from(transcript_path):
    """({skill: latest epoch of a run that counts}, {skill: latest epoch of a fork in flight}).

    An inline Skill call counts when invoked. A forked one counts only once its notice says
    `completed` with a verdict; until a notice arrives it is in flight. Raises if the
    transcript is unreadable."""
    if not transcript_path or not os.path.isfile(transcript_path):
        raise IOError("transcript not readable")
    calls, forked, notices = [], set(), {}
    with open(transcript_path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or ("Skill" not in line and "task-notification" not in line):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get("message") or {}
            content = msg.get("content")
            if obj.get("type") == "user" and msg.get("role") == "user":
                notices.update(notices_in(content))
            notices.update(notices_in(queued_notice(obj)))
            parts = content if isinstance(content, list) else []
            for i in parts:
                if (isinstance(i, dict) and i.get("type") == "tool_result"
                        and FORKED_MARK in str(i.get("content", ""))):
                    forked.add(i.get("tool_use_id"))
            skills = [(i.get("id"), str((i.get("input") or {}).get("skill", "")))
                      for i in parts
                      if isinstance(i, dict) and i.get("type") == "tool_use"
                      and i.get("name") == "Skill"]
            if not skills:
                continue
            try:
                epoch = datetime.fromisoformat(
                    str(obj.get("timestamp")).replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            for tid, sk in skills:
                name = sk.split(":")[-1].strip()
                if name:
                    calls.append((tid, name, epoch))
    seen, inflight = {}, {}
    for tid, name, epoch in calls:
        if tid in forked and tid not in notices:
            if time.time() - epoch > INFLIGHT_MAX_SECONDS:
                continue  # killed without a notice (an interrupt): no audit, gate stays owed
            bucket = inflight
        elif tid in forked and not notices[tid]:
            continue
        else:
            bucket = seen
        if name not in bucket or epoch > bucket[name]:
            bucket[name] = epoch
    return seen, inflight


# Silencers that aged out during this invocation, so the block message can say so. A gate
# that comes back without explanation reads as a bug; one that says why reads as a design.
EXPIRED = []


def inside_state(path):
    """Guard the delete below: session_id arrives in the payload and is interpolated into
    the filename, so a traversing id ("../../x") would otherwise aim os.remove anywhere on
    disk. Exploiting it needs control of the harness payload, but a delete primitive in the
    file that IS the security backstop is not worth leaving open for two lines."""
    d = os.path.realpath(state_dir())
    return os.path.commonpath([d, os.path.realpath(path)]) == d


def live_skip(path):
    """True while this silencer is inside its TTL. Past it, delete it and return False."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if time.time() - st.st_mtime <= SKIP_TTL_SECONDS:
        return True
    try:
        if inside_state(path):
            os.remove(path)
    except (OSError, ValueError):
        pass  # a skip we cannot delete is still expired; it just gets re-checked next time
    # Named by the gate it silenced, never by the file: the message must not show the recipe.
    name = os.path.basename(path).partition(".skip.")[2] or "all gates"
    if name not in EXPIRED:
        EXPIRED.append(name)
    return False


def silenced(session, skill):
    if os.environ.get("CLAUDE_AUDIT_SKIP") == "1":
        return True
    d = state_dir()
    # Both are evaluated, never short-circuited: an expired file must be cleaned up even
    # when the other silencer is still live, or it lingers to confuse the next session.
    live_all = live_skip(os.path.join(d, f"{session}.skip"))
    live_one = live_skip(os.path.join(d, f"{session}.skip.{skill}"))
    return live_all or live_one


def handle_post_tool_use(data):
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    fp = ti.get("file_path") or ti.get("notebook_path") or ""
    if not fp:
        allow()
    text = written_text(ti)
    changed = changed_text(ti)

    session = safe_session(data.get("session_id"))
    s = load_state(session) or {}
    owed = s.get("owed") if isinstance(s.get("owed"), dict) else {}

    notify_now = []
    root, rel = locate(fp)   # resolved ONCE, not per requirement
    ignores = load_ignores(root)
    for req in REQUIREMENTS:
        if not matches(req, fp, text, tool, rel, ignores.get(req["skill"], ()), changed):
            continue
        skill = req["skill"]
        if silenced(session, skill):
            continue
        entry = owed.get(skill) or {"files": []}
        base = os.path.basename(fp)
        files = [f for f in entry.get("files", []) if f != base] + [base]
        owed[skill] = {"ts": time.time(), "files": files[-10:],
                       "why": req["why"], "enforce": req["enforce"]}
        if req["enforce"] == "notify":
            notify_now.append((skill, req["why"], base))

    if owed:
        s["owed"] = owed
        s.setdefault("blocks", 0)
        s["blocks"] = 0  # a new triggering edit reopens the gate
        try:
            save_state(session, s)
        except Exception:
            allow()

    if notify_now:
        lines = [f"`{sk}` — {why} (`{base}`)" for sk, why, base in notify_now]
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "Automatic gate: this edit matched " + str(len(lines)) + " review skill(s) you "
                "should run on it before finishing:\n- " + "\n- ".join(lines) +
                "\nThese are advisory (they will not block the turn), but they are part of the "
                "definition of done — run them now rather than deferring."),
        }}))
    allow()


def handle_stop(data):
    session = safe_session(data.get("session_id"))
    s = load_state(session)
    if not s or not isinstance(s.get("owed"), dict) or not s["owed"]:
        allow()

    blocks = s.get("blocks", 0)
    if not isinstance(blocks, int) or blocks >= MAX_BLOCKS:
        allow()

    def pending():
        done, inflight = audits_from(data.get("transcript_path") or "")
        outstanding, advisory = [], []
        for skill, e in s["owed"].items():
            if silenced(session, skill):
                continue
            ran = done.get(skill)
            if ran is not None and ran >= float(e.get("ts", 0)):
                continue
            # A fork launched after the edit and not yet finished: its notice wakes the session,
            # and the Stop that follows checks it again. Blocking now would only invite a rerun.
            if inflight.get(skill, -1) >= float(e.get("ts", 0)):
                continue
            (advisory if e.get("enforce") == "notify" else outstanding).append((skill, e))
        return outstanding, advisory

    try:
        outstanding, advisory = pending()
        if outstanding:
            time.sleep(float(os.environ.get("CLAUDE_AUDIT_RETRY_SECONDS", RETRY_SECONDS)))
            outstanding, advisory = pending()
    except Exception:
        allow()  # cannot verify -> fail open rather than wedge the session

    if not outstanding:
        allow()  # notify-tier alone never blocks

    s["blocks"] = blocks + 1
    try:
        save_state(session, s)
    except Exception:
        pass

    lines = []
    for skill, e in outstanding:
        files = ", ".join(e.get("files", [])[:4]) or "changed files"
        lines.append(f"  - `{skill}` — {e.get('why','required')} ({files})\n"
                     f"    to skip just this one, ask the human to silence `{skill}`")
    extra = ""
    if advisory:
        extra = ("\nAlso advisory, not blocking: "
                 + ", ".join(f"`{sk}`" for sk, _ in advisory) + ".")
    if EXPIRED:
        extra += ("\nNote: a silencer expired and was removed (" + ", ".join(EXPIRED)
                  + "). Skips last " + str(SKIP_TTL_SECONDS // 3600) + "h by design, so one "
                  "cannot be left on and forgotten. Ask the human to silence it again if they still want it off.")
    if any(sk == "security-audit" for sk, _ in outstanding):
        extra += ("\nA forked security-audit that returned \"" + NOT_RUN_MARK + "\", or ended "
                  "without a verdict, is no audit: re-invoke it with the inputs it named.")
    block(
        "Blocked: this session made changes that oblige review skills which have not run since.\n"
        + "\n".join(lines) + extra +
        "\nRun each skill on the changed code and report its findings. Resolve anything Critical "
        "before finishing. These gates are mandatory by your own rules — not optional."
    )


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
        ev = data.get("hook_event_name", "")
        if ev == "PostToolUse":
            handle_post_tool_use(data)
        elif ev == "Stop":
            handle_stop(data)
        allow()
    except SystemExit:
        raise
    except Exception:
        allow()


if __name__ == "__main__":
    main()
