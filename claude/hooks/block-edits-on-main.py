#!/usr/bin/env python3
"""PreToolUse guard: block Edit/Write/NotebookEdit on main/master inside a protected root.

Enforces the "never work on main" rule without depending on anyone remembering to
branch. Fails OPEN on any error so it can never block legitimate editing.

Scope (all must hold to block):
  - The target file is under one of PROTECTED_ROOTS.
  - Its git repo's current branch is `main` or `master`.
  - The path is NOT under `docs/` (quick spec/roadmap edits on main stay allowed), except for
    the DOCS_EXEMPTION_DENYLIST below.
Anything else is allowed.

Symlinks are resolved, so the live ~/.claude config is protected too. The config repo's own root
is not hard-coded: it is derived from where this file really lives (see config_root), so a
checkout is guarded whatever it is named.

There is deliberately no CLAUDE_*_SKIP for this hook, and settings.json is itself behind it.
Bash writes are detected after the turn by uncommitted-on-main.py (Stop hook).

The roots are a tuple, not two constants, so protecting a third repo is data rather than
code. They are deliberately NOT overridable by an environment variable: this is the one
guard whose job is to constrain the agent deterministically instead of by compliance, and
an env override would be a one-line self-bypass. Its test patches the module in-process
instead -- see test_block_edits_on_main.py.
"""
import json
import os
import subprocess
import sys

GUARDED_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
PROTECTED_BRANCHES = {"main", "master"}
# Paths under docs/ that the docs/** convenience exemption must NOT cover. `ai-profile.md` is
# not a spec: it is what authorizes sending a repo's artifacts to a second AI provider, and
# codex-audit reads it to decide whether a gate may run or must record a skip. An authorization
# record gets a branch and a review like any other decision.
DOCS_EXEMPTION_DENYLIST = frozenset({"ai-profile.md"})

def _git(dirpath, *args):
    """git with GIT_* stripped from the env (a parent hook's GIT_DIR must not redirect it)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", dirpath, *args],
        capture_output=True, text=True, timeout=5, env=env,
    )


def config_root():
    """The config repo's main working tree, derived from this file's real location, or None.

    Duplicated in uncommitted-on-main.py (each hook is standalone). Only a layout of
    <repo>/claude/hooks with <repo> a git work tree root counts; a nested dir or a copied file
    derives nothing. From a linked worktree the root is the main checkout. A submodule or
    --separate-git-dir layout stays on the work tree itself instead of a wrong parent.
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


def allow():
    sys.exit(0)


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)  # exit 2 = PreToolUse "block", stderr is shown to the agent


def nearest_existing_dir(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return d or None


def under(path, root):
    """True when `path` is `root` or sits inside it.

    Two checks, because neither alone is enough:

    1. A textual one, which works for a path that does not exist yet (a Write creating a new
       file). commonpath is component-aware, so "~/Projects-evil" is correctly not under
       "~/Projects" -- a startswith() here would over-block. It raises on inputs sharing no
       anchor, which reads as "not under", i.e. allow.
    2. An identity one, because the textual check is bypassable by CASING on the default macOS
       volume: ~/Repo and ~/repo are the same directory, realpath does not canonicalise
       case, and commonpath then returns ~/ instead of the root. Comparing (st_ino, st_dev) of
       the root against each existing ancestor of the path closes that, and closes symlinked
       ancestors with it. Walking up handles the not-yet-created leaf.
    """
    try:
        if os.path.commonpath([path, root]) == root:
            return True
    except ValueError:
        pass

    try:
        rs = os.stat(root)
        root_id = (rs.st_ino, rs.st_dev)
    except OSError:
        return False        # a root that is not on this machine guards nothing

    d = path
    while True:
        try:
            st = os.stat(d)
            if (st.st_ino, st.st_dev) == root_id:
                return True
        except OSError:
            pass            # this ancestor does not exist yet; keep walking up
        parent = os.path.dirname(d)
        if parent == d:
            return False    # reached the filesystem root
        d = parent


def git(dirpath, *args):
    return _git(dirpath, *args)


def roots_for_humans():
    """Render the roots from the tuple itself, so the message cannot drift from the data."""
    home = os.path.realpath(os.path.expanduser("~"))
    names = [("~" + r[len(home):]) if under(r, home) else r for r in PROTECTED_ROOTS]
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()

    if data.get("tool_name", "") not in GUARDED_TOOLS:
        allow()

    ti = data.get("tool_input", {}) or {}
    fp = ti.get("file_path") or ti.get("notebook_path") or ""
    if not fp:
        allow()

    fp = os.path.realpath(os.path.expanduser(fp))

    # Only guard inside a protected root.
    if not any(under(fp, root) for root in PROTECTED_ROOTS):
        allow()

    d = nearest_existing_dir(fp)
    if not d:
        allow()

    try:
        branch = git(d, "rev-parse", "--abbrev-ref", "HEAD")
        if branch.returncode != 0:
            allow()  # not a git repo
        branch = branch.stdout.strip()
        if branch not in PROTECTED_BRANCHES:
            allow()

        root = git(d, "rev-parse", "--show-toplevel")
        if root.returncode != 0:
            allow()
        root = os.path.realpath(root.stdout.strip())
    except Exception:
        allow()

    rel = os.path.relpath(fp, root)
    # Matched on the casefolded BASENAME, not the exact relative path: "docs/AI-profile.md" is the
    # same file on a case-insensitive volume, and a nested "docs/config/ai-profile.md" is the same
    # kind of record. An exact-string denylist protecting an authorization file had two side doors.
    in_docs = rel == "docs" or rel.startswith("docs" + os.sep)
    if in_docs and os.path.basename(rel).casefold() not in DOCS_EXEMPTION_DENYLIST:
        allow()  # docs/** exemption

    repo = os.path.basename(root)
    block(
        f"Blocked: editing `{rel}` while `{repo}` is on `{branch}`.\n"
        f"Your rule is never to work on main. Create a branch or worktree first "
        f"(start via the feature-workflow skill, or `git worktree add`), then retry.\n"
        f"(docs/** is exempt; this guard covers {roots_for_humans()}.)"
    )


if __name__ == "__main__":
    main()
