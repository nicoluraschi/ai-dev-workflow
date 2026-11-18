#!/usr/bin/env python3
"""Tests for block-edits-on-main.py.

Run: python3 claude/hooks/test_block_edits_on_main.py

WHY THIS ONE RUNS IN-PROCESS while every other hook test uses subprocess: the guard's
protected roots must be overridable to test them, and the obvious way -- an env var like
CLAUDE_PROTECTED_ROOTS -- would hand the agent a one-line bypass of the one guard whose
entire job is to constrain the agent deterministically rather than by compliance. Unlike
CLAUDE_AUDIT_SKIP, nobody asked for an escape hatch here, and the guard deliberately has
none. So the roots stay hard-coded and the test patches the module instead.

Do not "simplify" this by adding an env override.
"""
import importlib.util, io, json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-edits-on-main.py")
results = []


def load():
    spec = importlib.util.spec_from_file_location("beom", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def repo(parent, name, branch="main", files=("app/thing.py", "docs/spec.md")):
    """A real git repo on `branch`, with the given files committed."""
    root = os.path.join(parent, name)
    for f in files:
        d = os.path.join(root, os.path.dirname(f))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(root, f), "w").close()
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    def g(*a):
        subprocess.run(["git", "-C", root, *a], capture_output=True, env=env, timeout=20)
    subprocess.run(["git", "init", "-q", "-b", "main", root], capture_output=True, env=env, timeout=20)
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("add", "-A"); g("commit", "-qm", "init")
    if branch != "main":
        g("checkout", "-qb", branch)
    return root


def run(roots, file_path, tool="Edit", patch_git=None):
    """Drive the real main() with PROTECTED_ROOTS patched. Returns (exit_code, stderr)."""
    m = load()
    m.PROTECTED_ROOTS = tuple(os.path.realpath(r) for r in roots)
    if patch_git is not None:
        m.git = patch_git
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                          "tool_input": {"file_path": file_path}})
    old_in, old_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(payload), io.StringIO()
    try:
        m.main()
        code = 0
    except SystemExit as e:
        code = e.code or 0
    finally:
        err = sys.stderr.getvalue()
        sys.stdin, sys.stderr = old_in, old_err
    return code, err


def sh(root, *a):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    subprocess.run(["git", "-C", root, *a], capture_output=True, env=env, timeout=20)


def install_hook(hooks_dir):
    """Copy the hook file under test into hooks_dir (a copy, so its own realpath decides the root)."""
    os.makedirs(hooks_dir, exist_ok=True)
    dst = os.path.join(hooks_dir, "block-edits-on-main.py")
    with open(HOOK) as src, open(dst, "w") as out:
        out.write(src.read())
    return dst


def load_at(path, home):
    """Load the hook from `path` (possibly a symlinked path) with HOME=home, as it is at import."""
    old = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        spec = importlib.util.spec_from_file_location("beom_at", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        os.environ["HOME"] = old


def drive(m, file_path):
    """Run main() of an already-loaded module with its roots as imported. Returns (code, stderr)."""
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": file_path}})
    old_in, old_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(payload), io.StringIO()
    try:
        m.main()
        code = 0
    except SystemExit as e:
        code = e.code or 0
    finally:
        err = sys.stderr.getvalue()
        sys.stdin, sys.stderr = old_in, old_err
    return code, err


def config_root_cases(td):
    """B5: the config root follows where the hook file really lives, whatever the checkout's name."""
    home = os.path.join(td, "cfghome")
    os.makedirs(os.path.join(home, ".claude"))
    os.makedirs(os.path.join(home, "Projects"))
    projects = os.path.realpath(os.path.join(home, "Projects"))
    link = os.path.join(home, ".claude", "hooks")

    # 1. a clone with an arbitrary name, reached through the ~/.claude/hooks symlink
    adw = repo(os.path.join(td, "elsewhere"), "ai-dev-workflow")
    install_hook(os.path.join(adw, "claude", "hooks"))
    os.symlink(os.path.join(adw, "claude", "hooks"), link)
    m = load_at(os.path.join(link, "block-edits-on-main.py"), home)
    c, e = drive(m, os.path.join(adw, "app/thing.py"))
    check("B5-1. an ai-dev-workflow clone behind the symlink is guarded, message names it",
          c == 2 and "ai-dev-workflow" in e and os.path.realpath(adw) in e, f"code={c} err={e[:200]}")

    # 2. the same set-up with the repo at <home>/dotfiles
    os.remove(link)
    dot = repo(home, "dotfiles")
    install_hook(os.path.join(dot, "claude", "hooks"))
    os.symlink(os.path.join(dot, "claude", "hooks"), link)
    m = load_at(os.path.join(link, "block-edits-on-main.py"), home)
    c, e = drive(m, os.path.join(dot, "app/thing.py"))
    check("B5-2. a clone at <home>/dotfiles is still guarded", c == 2 and "Blocked" in e,
          f"code={c} err={e[:200]}")

    # 3. ~/Projects still guarded, outside every root allowed
    proj = repo(projects, "app")
    c, _ = drive(m, os.path.join(proj, "app/thing.py"))
    check("B5-3. ~/Projects/<repo> on main is still blocked", c == 2, f"code={c}")
    out = repo(td, "outside-cfg")
    c, _ = drive(m, os.path.join(out, "app/thing.py"))
    check("B5-3b. a path outside every root is allowed", c == 0, f"code={c}")

    # 4. a linked worktree: the main checkout is the guarded root, not the worktree
    main_co = repo(os.path.join(td, "wtsrc"), "ai-dev-workflow")
    wt = os.path.join(td, "wtree")
    sh(main_co, "worktree", "add", "-q", "-b", "feat/x", wt)
    install_hook(os.path.join(wt, "claude", "hooks"))
    m = load_at(os.path.join(wt, "claude", "hooks", "block-edits-on-main.py"), home)
    check("B5-4. from a linked worktree the root is the main checkout",
          os.path.realpath(main_co) in m.PROTECTED_ROOTS and os.path.realpath(wt) not in m.PROTECTED_ROOTS,
          f"roots={m.PROTECTED_ROOTS}")
    c, _ = drive(m, os.path.join(main_co, "app/thing.py"))
    check("B5-4b. an edit in that main checkout is blocked", c == 2, f"code={c}")

    # 5. a nested claude/hooks (git root is not two levels up), and a copied layout: no derived root
    nested = repo(os.path.join(td, "nest"), "outer", files=("app/thing.py", "nested/claude/x"))
    install_hook(os.path.join(nested, "nested", "claude", "hooks"))
    m = load_at(os.path.join(nested, "nested", "claude", "hooks", "block-edits-on-main.py"), home)
    check("B5-5. a nested claude/hooks derives no root", m.PROTECTED_ROOTS == (projects,),
          f"roots={m.PROTECTED_ROOTS}")
    homerepo = repo(os.path.join(td, "cfghome2"), "x")
    install_hook(os.path.join(td, "copied", "hooks"))
    m = load_at(os.path.join(td, "copied", "hooks", "block-edits-on-main.py"), home)
    check("B5-5b. a copied (non claude/hooks) layout derives no root; ~/Projects still guarded",
          m.PROTECTED_ROOTS == (projects,), f"roots={m.PROTECTED_ROOTS}")
    c, _ = drive(m, os.path.join(homerepo, "app/thing.py"))
    check("B5-5c. and a repo elsewhere is not guarded", c == 0, f"code={c}")

    # 6. a --separate-git-dir layout: the git dir's parent is not a work tree, so the root stays the
    # checkout holding the hook instead of a wrong parent directory
    sep = os.path.join(td, "sep", "work"); os.makedirs(os.path.join(sep, "app"))
    open(os.path.join(sep, "app", "thing.py"), "w").close()
    subprocess.run(["git", "init", "-q", "-b", "main", "--separate-git-dir",
                    os.path.join(td, "sep", "gitdir"), sep],
                   capture_output=True, env=dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null"), timeout=20)
    install_hook(os.path.join(sep, "claude", "hooks"))
    m = load_at(os.path.join(sep, "claude", "hooks", "block-edits-on-main.py"), home)
    check("B5-6. a separate-git-dir checkout is its own root",
          os.path.realpath(sep) in m.PROTECTED_ROOTS, f"roots={m.PROTECTED_ROOTS}")

    # 7. no hard-coded ~/dotfiles in the hook file
    with open(HOOK) as f:
        check("B5-7. the hook file does not contain ~/dotfiles", "~/dotfiles" not in f.read())


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  -- " + detail) if detail and not cond else ""))


def main():
    with tempfile.TemporaryDirectory() as td:
        projects = os.path.join(td, "Projects"); os.makedirs(projects)
        dotfiles_parent = os.path.join(td, "home"); os.makedirs(dotfiles_parent)
        dotfiles = repo(dotfiles_parent, "dotfiles")          # ~/dotfiles IS the repo
        roots = (projects, dotfiles)

        proj_repo = repo(projects, "app")
        feat_repo = repo(projects, "api", branch="feat/x")
        outside = repo(td, "elsewhere")
        plain = os.path.join(td, "notgit"); os.makedirs(plain)
        open(os.path.join(plain, "x.py"), "w").close()

        # 1. no regression: a repo under ~/Projects on main is still blocked
        c, e = run(roots, os.path.join(proj_repo, "app/thing.py"))
        check("1. code on main under ~/Projects is blocked", c == 2 and "Blocked" in e,
              f"code={c} err={e[:120]}")

        # 2. THE FIX: ~/dotfiles was the one repo where this was silently allowed
        c, e = run(roots, os.path.join(dotfiles, "app/thing.py"))
        check("2. code on main under ~/dotfiles is blocked", c == 2 and "Blocked" in e,
              f"code={c} err={e[:120]}")

        # 3. the docs/** exemption survives, under both roots
        c, _ = run(roots, os.path.join(proj_repo, "docs/spec.md"))
        check("3. docs/** on main stays allowed (~/Projects)", c == 0, f"code={c}")
        c, _ = run(roots, os.path.join(dotfiles, "docs/spec.md"))
        check("3b. docs/** on main stays allowed (~/dotfiles)", c == 0, f"code={c}")

        # 4. a feature branch is never the guard's business
        c, _ = run(roots, os.path.join(feat_repo, "app/thing.py"))
        check("4. a feature branch is allowed", c == 0, f"code={c}")

        # 5. outside every protected root
        c, _ = run(roots, os.path.join(outside, "app/thing.py"))
        check("5. a repo on main outside every protected root is allowed", c == 0, f"code={c}")

        # 6. not a git repo at all. NB: the directory must sit INSIDE a protected root, or the
        # case exits at the root check and passes without ever reaching the git branch check.
        inside_plain = os.path.join(projects, "notgit"); os.makedirs(inside_plain)
        open(os.path.join(inside_plain, "x.py"), "w").close()
        c, _ = run(roots, os.path.join(inside_plain, "x.py"))
        check("6. a non-git directory inside a protected root is allowed", c == 0, f"code={c}")
        c, _ = run(roots, os.path.join(plain, "x.py"))
        check("6b. and one outside every root is allowed too", c == 0, f"code={c}")

        # 6c. a payload carrying no path at all
        m6 = load(); m6.PROTECTED_ROOTS = tuple(os.path.realpath(r) for r in roots)
        oi, oe = sys.stdin, sys.stderr
        sys.stdin = io.StringIO(json.dumps({"tool_name": "Edit", "tool_input": {}}))
        sys.stderr = io.StringIO()
        try:
            m6.main(); c = 0
        except SystemExit as ex:
            c = ex.code or 0
        finally:
            sys.stdin, sys.stderr = oi, oe
        check("6c. a payload with no file_path is allowed", c == 0, f"code={c}")

        # 5b. docs/** is exempt, but ai-profile.md is not a spec: it authorizes sending this
        # repo's artifacts to a second AI provider, which codex-audit reads to decide whether a
        # gate may run at all. An authorization record does not belong in a convenience exemption.
        ai = repo(dotfiles_parent, "dots2", files=("docs/ai-profile.md", "docs/spec.md",
                                                   "app/thing.py"))
        r2 = (projects, ai)
        c, e = run(r2, os.path.join(ai, "docs/ai-profile.md"))
        check("5b. docs/ai-profile.md is NOT covered by the docs/** exemption",
              c == 2 and "Blocked" in e, f"code={c} err={e[:140]}")
        c, _ = run(r2, os.path.join(ai, "docs/spec.md"))
        check("5c. other docs/** files stay exempt", c == 0, f"code={c}")

        # 5d. the denylist must not have casing or nesting side doors: the file it protects is an
        # authorization record, and "docs/AI-profile.md" is the same file on APFS.
        ai2 = repo(dotfiles_parent, "dots3",
                   files=("docs/AI-profile.md", "docs/config/ai-profile.md", "docs/spec.md"))
        r3 = (projects, ai2)
        c, _ = run(r3, os.path.join(ai2, "docs/AI-profile.md"))
        check("5d. docs/AI-profile.md (different case) is also blocked", c == 2, f"code={c}")
        c, _ = run(r3, os.path.join(ai2, "docs/config/ai-profile.md"))
        check("5e. a nested ai-profile.md is also blocked", c == 2, f"code={c}")

        # 6d. containment must not be a string prefix. "Projects-evil" starts with "Projects",
        # so a startswith() implementation would wrongly guard a repo that is not under the root
        # at all -- over-blocking, the worst direction for a guard meant to stay invisible.
        sibling = repo(td, "Projects-evil")
        c, _ = run(roots, os.path.join(sibling, "app/thing.py"))
        check("6d. a sibling sharing the root's name prefix is NOT guarded", c == 0, f"code={c}")

        # 6e/6f. A case-insensitive volume (APFS default) makes ~/Dotfiles and ~/dotfiles the SAME
        # directory with different strings, so a purely textual containment check is bypassable with
        # one keystroke. Skipped where the volume is genuinely case-sensitive.
        probe = os.path.join(td, "CaseProbe"); open(probe, "w").close()
        case_insensitive = os.path.exists(os.path.join(td, "caseprobe"))
        if case_insensitive:
            variant = os.path.join(projects, "APP", "app/thing.py")
            c, _ = run(roots, variant)
            check("6e. a case-variant path does not bypass the guard", c == 2, f"code={c}")
            dvar = os.path.join(dotfiles_parent, "DotFiles", "app/thing.py")
            c, _ = run(roots, dvar)
            check("6f. nor does a case-variant of the dotfiles root", c == 2, f"code={c}")
        else:
            check("6e. (skipped: case-sensitive volume)", True)
            check("6f. (skipped: case-sensitive volume)", True)

        # 7. fails OPEN: git blowing up must never wedge an edit
        def boom(*a, **k):
            raise OSError("git is not installed")
        c, e = run(roots, os.path.join(proj_repo, "app/thing.py"), patch_git=boom)
        check("7. git failing means allow, not block", c == 0 and "Traceback" not in e,
              f"code={c} err={e[:120]}")

        m = load()
        old_in, old_err = sys.stdin, sys.stderr
        sys.stdin, sys.stderr = io.StringIO("not json"), io.StringIO()
        try:
            m.main(); c = 0
        except SystemExit as ex:
            c = ex.code or 0
        finally:
            sys.stdin, sys.stderr = old_in, old_err
        check("7b. garbage stdin is allowed", c == 0, f"code={c}")

        # 8. the message must not still claim it covers ~/Projects only
        c, e = run(roots, os.path.join(dotfiles, "app/thing.py"))
        # NB: not `"dotfiles" in e` -- the temp path itself contains "dotfiles", so that passed
        # even if roots_for_humans() returned nothing. Render from a module patched with the SAME
        # roots the message was produced under, or this compares two different tuples.
        m8 = load(); m8.PROTECTED_ROOTS = tuple(os.path.realpath(r) for r in roots)
        rendered = m8.roots_for_humans()
        check("8. the block message names both roots, not '~/Projects only'",
              "~/Projects only" not in e and rendered in e, f"rendered={rendered!r} err={e[:200]}")

        # 9. every guarded tool, and the notebook path key
        for tool in ("Write", "NotebookEdit", "MultiEdit"):
            key = "notebook_path" if tool == "NotebookEdit" else "file_path"
            mm = load(); mm.PROTECTED_ROOTS = tuple(os.path.realpath(r) for r in roots)
            payload = json.dumps({"tool_name": tool,
                                  "tool_input": {key: os.path.join(dotfiles, "app/thing.py")}})
            oi, oe = sys.stdin, sys.stderr
            sys.stdin, sys.stderr = io.StringIO(payload), io.StringIO()
            try:
                mm.main(); c = 0
            except SystemExit as ex:
                c = ex.code or 0
            finally:
                sys.stdin, sys.stderr = oi, oe
            check(f"9. {tool} is guarded under ~/dotfiles too", c == 2, f"code={c}")

        # 10. an unguarded tool is invisible to the guard
        c, _ = run(roots, os.path.join(dotfiles, "app/thing.py"), tool="Read")
        check("10. a non-editing tool is allowed", c == 0, f"code={c}")

        # 10b. under() is new code: pin all three of its outcomes directly. commonpath raises
        # ValueError on a mix of absolute and relative paths, and that must read as "not under".
        u = load().under
        check("10b. under() is true for a path inside the root",
              u(os.path.join(projects, "a/b"), projects) is True)
        check("10c. under() is false for a sibling", u(os.path.join(td, "other"), projects) is False)
        check("10d. under() returns False instead of raising on unmixable paths",
              u("relative/path", projects) is False)

        # 11. THE SHIPPED CONFIGURATION, not just the mechanism.
        # Every case above patches PROTECTED_ROOTS, so none of them would notice a root being
        # removed from the tuple -- mutation-tested: deleting "~/dotfiles" left all of 1-10
        # green. The point of this guard is *which* roots it covers, so assert that directly.
        shipped = load().PROTECTED_ROOTS
        # The config root is derived from this very file, so it is the checkout holding the hook
        # under test (the main working tree, even from a linked worktree).
        here_repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(HOOK))))
        common = subprocess.run(["git", "-C", here_repo, "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True).stdout.strip()
        want_root = os.path.realpath(os.path.dirname(common))
        for label, real in (("~/Projects", os.path.realpath(os.path.expanduser("~/Projects"))),
                            ("the derived config root", want_root)):
            check(f"11. {label} is in the shipped PROTECTED_ROOTS", real in shipped,
                  f"shipped={shipped}")
        # 11a: membership alone is not enough. realpath() passes non-existent components straight
        # through, so a machine whose clone lives elsewhere would ship a root that guards nothing
        # and still satisfy the check above. Require each root to actually be there.
        # A CI runner (CI is set) has neither ~/Projects nor ~/dotfiles, so the public repo's CI
        # skips this; on the owner's machine it still runs.
        for r in () if os.environ.get("CI") else shipped:
            check(f"11a. shipped root {os.path.basename(r)} exists on disk", os.path.isdir(r), r)
        # 11b: assert the rendering is derived, not that it equals one machine's layout. A clone at
        # ~/Projects/dotfiles is a legitimate setup and would render differently.
        rendered = load().roots_for_humans()
        home = os.path.realpath(os.path.expanduser("~"))
        check("11b. every shipped root appears in the rendered message",
              all((("~" + r[len(home):]) if r.startswith(home) else r) in rendered for r in shipped),
              f"rendered={rendered!r} shipped={shipped}")
        check("11c. the rendering shows no absolute $HOME", home not in rendered, rendered)

    with tempfile.TemporaryDirectory() as td:
        config_root_cases(td)

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
