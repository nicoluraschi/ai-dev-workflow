#!/usr/bin/env python3
"""Stop hook: refuse to end a turn with uncommitted changes on main in a protected repo.

block-edits-on-main.py guards the EDIT TOOLS. About half of file mutations go through Bash
instead (sed -i, cat/tee heredocs, > and >> redirects, inline open(...,'w') in `python3 -`,
--write/--fix formatters, cp/mv/install, mutating git, mkdir/touch); this hook catches those.

The obvious fix -- parse Bash commands for write intent -- was measured and rejected: ten distinct
mechanisms, many compound in a single command, and most redirects target /tmp or the scratchpad
rather than repo files, so a parser would also have to resolve every target against the cwd or fire
on nearly everything. At ~80 such commands a day, a heuristic is noise.

`git status` needs no parser. It does not care how the bytes arrived, so it covers all ten
mechanisms and any future one for free. The cost is that this DETECTS rather than PREVENTS -- the
write already happened -- but it catches it while the remedy still costs seconds, which is the
outcome the "never work on main" rule actually wants.

Blocking tier is justified here in a way a command parser never would be: `git` reporting a modified
file is an unambiguous signal, not a heuristic. Same doctrine as audit-guard.py.

No session baseline: pre-existing dirt on main is also a violation. It gets reported.

MAX_BLOCKS releases after two refusals so this can never trap a turn.

Escape hatches (2 and 3 are the HUMAN's; the refusal does not print them and gate-state-guard.py
denies the agent writing the state dir):
  1. Commit it, or move it to a branch (the intended path).
  2. touch "$STATE/<session_id>.skip.uncommitted-on-main"  -- silence for SKIP_TTL_SECONDS.
  3. CLAUDE_MAIN_DIRTY_SKIP=1                              -- disable entirely.

Fails OPEN on any error, like every hook here: it must never wedge a session.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

MAX_BLOCKS = 2
SKIP_TTL_SECONDS = 4 * 3600
PROTECTED_BRANCHES = {"main", "master"}
# Kept identical to block-edits-on-main.py's, for the same reason: an authorization record does not
# belong in a convenience exemption.
DOCS_EXEMPTION_DENYLIST = frozenset({"ai-profile.md"})
SKILL = "uncommitted-on-main"

def _git(dirpath, *args):
    """git with GIT_* stripped from the env (a parent hook's GIT_DIR must not redirect it)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", dirpath, *args],
                          capture_output=True, text=True, timeout=5, env=env)


def config_root():
    """The config repo's main working tree, derived from this file's real location, or None.

    Duplicated from block-edits-on-main.py rather than shared: each hook here is standalone so a
    broken sibling import can never stop a gate from running. Only <repo>/claude/hooks with <repo>
    a git work tree root counts; from a linked worktree the root is the main checkout.
    """
    try:
        here = os.path.dirname(os.path.realpath(__file__))
        if os.path.basename(here) != "hooks" or os.path.basename(os.path.dirname(here)) != "claude":
            return None
        cand = os.path.dirname(os.path.dirname(here))
        top = _git(cand, "rev-parse", "--show-toplevel")
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != cand:
            return None
        common = _git(cand, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode != 0 or not common.stdout.strip():
            return cand
        main = os.path.realpath(os.path.dirname(common.stdout.strip()))
        mtop = _git(main, "rev-parse", "--show-toplevel")
        if mtop.returncode == 0 and os.path.realpath(mtop.stdout.strip()) == main:
            return main
        return cand
    except Exception:
        return None


_CONFIG_ROOT = config_root()
PROTECTED_ROOTS = tuple(
    os.path.realpath(os.path.expanduser(p)) for p in ("~/Projects",)
) + ((_CONFIG_ROOT,) if _CONFIG_ROOT else ())
# Checked on every Stop regardless of cwd. The config repo is one repo and it is where a stray write
# to ~/.claude/** lands from anywhere, since that tree symlinks into it.
ALWAYS_CHECK = (_CONFIG_ROOT,) if _CONFIG_ROOT else ()


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
    """session_id reaches two filenames below and arrives in the payload. Same validator as the
    sibling hooks, repeated for the same standalone reason. A rejected id is hashed so two hostile
    ids cannot share a block counter."""
    v = str(raw or "")
    if not v or len(v) > 128 or not all(c.isalnum() or c in "._-" for c in v) or v.strip(".") == "":
        return "unknown-" + hashlib.sha256(v.encode("utf-8", "replace")).hexdigest()[:16]
    return v


def inside_state(path):
    d = os.path.realpath(state_dir())
    try:
        return os.path.commonpath([d, os.path.realpath(path)]) == d
    except ValueError:
        return False


def live_skip(session):
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


def counter_path(session):
    return os.path.join(state_dir(), f"{session}.{SKILL}.blocks")


def bump_blocks(session):
    p, n = counter_path(session), 0
    try:
        with open(p) as f:
            n = int(f.read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    n += 1
    try:
        with open(p, "w") as f:
            f.write(str(n))
    except OSError:
        pass
    return n


def reset_blocks(session):
    """Without this the counter only ever climbs, so after MAX_BLOCKS the gate is dead for the whole
    session -- a violation 40 minutes later would ship unreported. audit-guard.py resets on the same
    reasoning ("a new triggering edit reopens the gate")."""
    p = counter_path(session)
    if inside_state(p):
        try:
            os.remove(p)
        except OSError:
            pass


def git(dirpath, *args):
    return subprocess.run(["git", "-C", dirpath, *args],
                          capture_output=True, text=True, timeout=10)


def under(path, root):
    try:
        if os.path.commonpath([path, root]) == root:
            return True
    except ValueError:
        pass
    try:
        rs = os.stat(root)
    except OSError:
        return False
    d = path
    while True:
        try:
            if os.stat(d).st_ino == rs.st_ino and os.stat(d).st_dev == rs.st_dev:
                return True
        except OSError:
            pass
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def repo_root(dirpath):
    r = git(dirpath, "rev-parse", "--show-toplevel")
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def main_checkout(dirpath):
    """The repo's MAIN working tree, even when dirpath is a linked worktree.

    This is the difference between a gate that works and one that never fires. Sessions run from
    ~/worktrees/<repo>/<branch>, which is outside every protected root, so resolving only the cwd's
    own root meant a ~/Projects repo was examined solely when the cwd sat in ~/Projects -- i.e. only
    in the state the worktree rule already forbids. --git-common-dir points at the main .git even
    from a linked worktree; its parent is the checkout we actually want to inspect.
    """
    r = git(dirpath, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    root = os.path.realpath(os.path.dirname(r.stdout.strip()))
    return root if os.path.isdir(os.path.join(root, ".git")) or os.path.isdir(root) else None


def exempt(rel):
    """docs/** is exempt, matching block-edits-on-main.py -- including its one exception.
    ai-profile.md is not a spec: it authorizes sending a repo's artifacts to a second AI provider,
    and codex-audit reads it. Matched on the casefolded basename, like the sibling."""
    if not (rel == "docs" or rel.startswith("docs/")):
        return False
    return os.path.basename(rel).casefold() not in DOCS_EXEMPTION_DENYLIST


def offending(root):
    """Non-docs paths with uncommitted changes, when the repo is on a protected branch.

    Uses --porcelain -z: NUL-separated records need no unquoting, so a path with a quote, a
    newline or a non-ASCII byte is reported as itself instead of as C-style octal escapes. A
    rename arrives as two records (new NUL old) and BOTH sides count -- judging only the
    destination let `git mv app/thing.py docs/thing.py` remove a file from the tree unreported.
    """
    b = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if b.returncode != 0:
        return None, []
    branch = b.stdout.strip()
    if branch not in PROTECTED_BRANCHES:
        return branch, []
    st = git(root, "status", "--porcelain", "-z")
    if st.returncode != 0:
        return branch, []

    fields = st.stdout.split("\0")
    paths, i = [], 0
    while i < len(fields):
        rec = fields[i]
        i += 1
        if not rec or len(rec) < 4:
            continue
        code, rel = rec[:2], rec[3:]
        sides = [rel]
        if "R" in code or "C" in code:      # rename/copy: the ORIGIN follows as its own record
            if i < len(fields) and fields[i]:
                sides.append(fields[i])
                i += 1
        for side in sides:
            if side and not exempt(side):
                paths.append(side)
    return branch, sorted(set(paths))


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
        if data.get("hook_event_name") != "Stop":
            allow()
        if os.environ.get("CLAUDE_MAIN_DIRTY_SKIP") == "1":
            allow()

        session = safe_session(data.get("session_id"))
        if live_skip(session):
            allow()

        cwd = data.get("cwd") or os.getcwd()
        roots = []
        for r in ALWAYS_CHECK:
            if os.path.isdir(r) and repo_root(r) and repo_root(r) not in roots:
                roots.append(repo_root(r))
        real_cwd = os.path.realpath(os.path.expanduser(cwd))
        # Resolve the MAIN checkout first: a session in ~/worktrees/... is outside every protected
        # root, but the checkout it belongs to is not.
        for cand in (main_checkout(real_cwd), repo_root(real_cwd)):
            if not cand or cand in roots:
                continue
            if any(under(cand, p) for p in PROTECTED_ROOTS):
                roots.append(cand)

        dirty = []
        for root in roots:
            branch, paths = offending(root)
            if paths:
                dirty.append((root, branch, paths))
        if not dirty:
            reset_blocks(session)   # a clean tree reopens the gate for the rest of the session
            allow()

        if bump_blocks(session) > MAX_BLOCKS:
            allow()   # never trap a turn

        lines = ["Blocked: uncommitted changes on a protected branch."]
        for root, branch, paths in dirty:
            shown = ", ".join(paths[:6]) + (f" (+{len(paths) - 6} more)" if len(paths) > 6 else "")
            lines.append(f"  {os.path.basename(root)} on `{branch}`: {shown}")
        lines.append("Your rule is never to work on main, and the main checkout must STAY on main")
        lines.append("-- a feature branch checked out there pins the working tree. So:")
        lines.append("  1. git stash -u          (-u is required: untracked files count here)")
        lines.append("  2. create/enter a worktree via the EnterWorktree tool, then: git stash pop")
        lines.append("Do NOT `git switch -c` in this checkout -- that just moves the violation.")
        lines.append("docs/** is exempt, except docs/ai-profile.md.")
        lines.append(f"To silence this gate ({SKILL}), ask the human to silence it.")
        block("\n".join(lines))
    except SystemExit:
        raise
    except Exception:
        allow()
    allow()


if __name__ == "__main__":
    main()
