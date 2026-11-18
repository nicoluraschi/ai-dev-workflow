#!/usr/bin/env python3
"""Tests for uncommitted-on-main.py.

Run: python3 claude/hooks/test_uncommitted_on_main.py

In-process, like test_block_edits_on_main.py and for the same reason: the protected roots must be
overridable to test them, and an env override would be a one-line bypass of a blocking gate. The
roots stay hard-coded and the test patches the module.

Case 13 is the one that justifies the whole design: writes made by sed, a heredoc and inline
python must each be caught, and the hook contains no pattern for any of them.
"""
import importlib.util, io, json, os, re, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uncommitted-on-main.py")
results = []
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def load():
    spec = importlib.util.spec_from_file_location("uom", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def repo(parent, name, branch="main"):
    root = os.path.join(parent, name)
    for f in ("app/thing.py", "docs/spec.md"):
        os.makedirs(os.path.join(root, os.path.dirname(f)), exist_ok=True)
        open(os.path.join(root, f), "w").close()
    def g(*a):
        subprocess.run(["git", "-C", root, *a], capture_output=True, env=GIT_ENV, timeout=20)
    subprocess.run(["git", "init", "-q", "-b", "main", root],
                   capture_output=True, env=GIT_ENV, timeout=20)
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("add", "-A"); g("commit", "-qm", "init")
    if branch != "main":
        g("checkout", "-qb", branch)
    return root


def run(m_roots, cwd, state_dir, session="s1", always=(), env_extra=None):
    """Drive the real main() at Stop. Returns (exit_code, stderr)."""
    m = load()
    m.PROTECTED_ROOTS = tuple(os.path.realpath(r) for r in m_roots)
    m.ALWAYS_CHECK = tuple(os.path.realpath(r) for r in always)
    old_env = os.environ.get("CLAUDE_AUDIT_STATE_DIR")
    os.environ["CLAUDE_AUDIT_STATE_DIR"] = state_dir
    for k, v in (env_extra or {}).items():
        os.environ[k] = v
    payload = json.dumps({"hook_event_name": "Stop", "session_id": session, "cwd": cwd})
    oi, oe = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(payload), io.StringIO()
    try:
        m.main(); code = 0
    except SystemExit as e:
        code = e.code or 0
    finally:
        err = sys.stderr.getvalue()
        sys.stdin, sys.stderr = oi, oe
        for k in (env_extra or {}):
            os.environ.pop(k, None)
        if old_env is None:
            os.environ.pop("CLAUDE_AUDIT_STATE_DIR", None)
        else:
            os.environ["CLAUDE_AUDIT_STATE_DIR"] = old_env
    return code, err


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -- " + detail) if detail and not cond else ""))


def stop_via(hook_path, home, cwd, state):
    """Run the hook as a subprocess through `hook_path` at Stop. Returns (exit_code, stderr)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=home, CLAUDE_AUDIT_STATE_DIR=state)
    env.pop("CLAUDE_MAIN_DIRTY_SKIP", None)
    p = subprocess.run([sys.executable, hook_path], cwd=cwd, env=env, capture_output=True, text=True,
                       timeout=30, input=json.dumps(
                           {"hook_event_name": "Stop", "session_id": "sx", "cwd": cwd}))
    return p.returncode, p.stderr


def install_hook(hooks_dir):
    os.makedirs(hooks_dir, exist_ok=True)
    with open(HOOK) as src, open(os.path.join(hooks_dir, "uncommitted-on-main.py"), "w") as out:
        out.write(src.read())


def commit_all(root):
    for a in (("add", "-A"), ("commit", "-qm", "hook")):
        subprocess.run(["git", "-C", root, *a], capture_output=True, env=GIT_ENV, timeout=20)


def config_root_cases(td):
    """B5: ALWAYS_CHECK and the protected roots follow the hook file's real checkout."""
    home = os.path.join(td, "home"); os.makedirs(os.path.join(home, ".claude"))
    outside = os.path.join(td, "nowhere"); os.makedirs(outside)
    link = os.path.join(home, ".claude", "hooks")
    for n, (parent, name) in enumerate(((os.path.join(td, "elsewhere"), "ai-dev-workflow"),
                                        (home, "dotfiles"))):
        os.makedirs(parent, exist_ok=True)
        r = repo(parent, name)
        install_hook(os.path.join(r, "claude", "hooks"))
        commit_all(r)       # the copied hook itself must not count as dirt
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(os.path.join(r, "claude", "hooks"), link)
        hook = os.path.join(link, "uncommitted-on-main.py")
        c, e = stop_via(hook, home, outside, sd(td, f"cr{n}a"))
        check(f"B5-6. {name}: a clean derived repo is silent from an outside cwd", c == 0, f"code={c} err={e[:160]}")
        open(os.path.join(r, "app/new_thing.py"), "w").write("x = 1\n")
        c, e = stop_via(hook, home, outside, sd(td, f"cr{n}b"))
        check(f"B5-6b. {name}: an uncommitted non-docs file on main blocks from an outside cwd",
              c == 2 and name in e, f"code={c} err={e[:200]}")

    # 4. hooks run from a linked worktree: the main checkout's dirt blocks
    # (a fresh HOME, so no other repo under it can be what blocks)
    home2 = os.path.join(td, "home2"); os.makedirs(home2)
    main_co = repo(os.path.join(td, "wtsrc"), "ai-dev-workflow")
    wt = os.path.join(td, "wtree")
    subprocess.run(["git", "-C", main_co, "worktree", "add", "-q", "-b", "feat/x", wt],
                   capture_output=True, env=GIT_ENV, timeout=20)
    install_hook(os.path.join(wt, "claude", "hooks"))
    open(os.path.join(main_co, "app/new_thing.py"), "w").write("x = 1\n")
    c, e = stop_via(os.path.join(wt, "claude", "hooks", "uncommitted-on-main.py"), home2, outside,
                    sd(td, "cr-wt"))
    check("B5-4. hooks in a linked worktree check the main checkout", c == 2 and "new_thing.py" in e,
          f"code={c} err={e[:200]}")

    # 5. a nested claude/hooks and a copied layout derive no root: a dirty repo outside ~/Projects
    # that would be the derived root is NOT examined
    dirty = repo(os.path.join(td, "dirtyland"), "outer")
    open(os.path.join(dirty, "app/new_thing.py"), "w").write("x = 1\n")
    for label, hooks_dir in (("nested", os.path.join(dirty, "nested", "claude", "hooks")),
                             ("copied", os.path.join(td, "copiedhooks", "hooks"))):
        install_hook(hooks_dir)
        c, e = stop_via(os.path.join(hooks_dir, "uncommitted-on-main.py"), home2, dirty,
                        sd(td, f"cr-{label}"))
        check(f"B5-5. a {label} layout derives no root", c == 0, f"code={c} err={e[:160]}")

    # 7. no hard-coded ~/dotfiles in the hook file
    with open(HOOK) as f:
        check("B5-7. the hook file does not contain ~/dotfiles", "~/dotfiles" not in f.read())


def sd(td, n):
    d = os.path.join(td, "state", n); os.makedirs(d); return d


def main():
    with tempfile.TemporaryDirectory() as td:
        projects = os.path.join(td, "Projects"); os.makedirs(projects)
        roots = (projects,)

        # 1. clean repo on main
        r1 = repo(projects, "clean")
        c, e = run(roots, r1, sd(td, "t1"))
        check("1. a clean repo on main is silent", c == 0 and not e.strip(), f"code={c} err={e[:120]}")

        # 2. modified code on main
        r2 = repo(projects, "dirty")
        open(os.path.join(r2, "app/thing.py"), "w").write("x = 1\n")
        c, e = run(roots, r2, sd(td, "t2"))
        check("2. modified code on main blocks", c == 2, f"code={c}")
        check("2b. and it names the repo, branch and path",
              "dirty" in e and "main" in e and "app/thing.py" in e, e[:220])

        # 3. docs-only change keeps the same exemption as the edit guard
        r3 = repo(projects, "docsonly")
        open(os.path.join(r3, "docs/spec.md"), "w").write("# x\n")
        c, e = run(roots, r3, sd(td, "t3"))
        check("3. a docs/** change on main does not block", c == 0, f"code={c} err={e[:160]}")

        # 4. docs + code -> blocks, naming only the code
        r4 = repo(projects, "both")
        open(os.path.join(r4, "docs/spec.md"), "w").write("# x\n")
        open(os.path.join(r4, "app/thing.py"), "w").write("x = 1\n")
        c, e = run(roots, r4, sd(td, "t4"))
        check("4. docs plus code blocks", c == 2, f"code={c}")
        check("4b. and lists only the code path", "app/thing.py" in e and "docs/spec.md" not in e,
              e[:220])

        # 5. feature branch is never this hook's business
        r5 = repo(projects, "onbranch", branch="feat/x")
        open(os.path.join(r5, "app/thing.py"), "w").write("x = 1\n")
        c, e = run(roots, r5, sd(td, "t5"))
        check("5. a dirty feature branch is allowed", c == 0, f"code={c} err={e[:160]}")

        # 6. outside every protected root
        outside = repo(td, "elsewhere")
        open(os.path.join(outside, "app/thing.py"), "w").write("x = 1\n")
        c, e = run(roots, outside, sd(td, "t6"))
        check("6. a dirty repo outside the roots is allowed", c == 0, f"code={c} err={e[:160]}")

        # 7. an untracked file is an unreviewed change too
        r7 = repo(projects, "untracked")
        open(os.path.join(r7, "app/new_thing.py"), "w").write("x = 1\n")
        c, e = run(roots, r7, sd(td, "t7"))
        check("7. an untracked file on main blocks", c == 2 and "new_thing.py" in e,
              f"code={c} err={e[:200]}")

        # 8. cwd is not a repo, but ALWAYS_CHECK still gets checked
        plain = os.path.join(td, "notarepo"); os.makedirs(plain)
        r8 = repo(projects, "always")
        open(os.path.join(r8, "app/thing.py"), "w").write("x = 1\n")
        c, e = run(roots, plain, sd(td, "t8"), always=(r8,))
        check("8. a non-repo cwd still gets ALWAYS_CHECK examined", c == 2 and "always" in e,
              f"code={c} err={e[:200]}")
        c, e = run(roots, plain, sd(td, "t8b"))
        check("8b. and with nothing to always-check it is silent", c == 0, f"code={c}")

        # 9. fails OPEN
        m9 = load()
        m9.PROTECTED_ROOTS = (os.path.realpath(projects),)
        m9.ALWAYS_CHECK = ()
        def boom(*a, **k):
            raise OSError("git is gone")
        m9.git = boom
        os.environ["CLAUDE_AUDIT_STATE_DIR"] = sd(td, "t9")
        oi, oe = sys.stdin, sys.stderr
        sys.stdin, sys.stderr = io.StringIO(json.dumps(
            {"hook_event_name": "Stop", "session_id": "s9", "cwd": r2})), io.StringIO()
        try:
            m9.main(); c = 0
        except SystemExit as ex:
            c = ex.code or 0
        finally:
            err = sys.stderr.getvalue(); sys.stdin, sys.stderr = oi, oe
        check("9. git blowing up allows, never blocks", c == 0 and "Traceback" not in err,
              f"code={c} err={err[:160]}")

        oi, oe = sys.stdin, sys.stderr
        sys.stdin, sys.stderr = io.StringIO("not json"), io.StringIO()
        try:
            load().main(); c = 0
        except SystemExit as ex:
            c = ex.code or 0
        finally:
            sys.stdin, sys.stderr = oi, oe
        check("9b. garbage stdin allows", c == 0, f"code={c}")

        # 10. the skip file, and its expiry
        s10 = sd(td, "t10")
        skip = os.path.join(s10, "s10.skip.uncommitted-on-main")
        open(skip, "w").close()
        c, _ = run(roots, r2, s10, session="s10")
        check("10. a fresh skip file silences it", c == 0, f"code={c}")
        old = time.time() - (5 * 3600)
        os.utime(skip, (old, old))
        c, _ = run(roots, r2, s10, session="s10")
        check("10b. an expired skip file no longer silences it", c == 2, f"code={c}")
        check("10c. and the expired file is deleted", not os.path.exists(skip))

        # 11. the env escape hatch
        c, _ = run(roots, r2, sd(td, "t11"), env_extra={"CLAUDE_MAIN_DIRTY_SKIP": "1"})
        check("11. CLAUDE_MAIN_DIRTY_SKIP=1 silences it", c == 0, f"code={c}")

        # 12. it can never trap a turn
        s12 = sd(td, "t12")
        codes = [run(roots, r2, s12, session="s12")[0] for _ in range(4)]
        check("12. it releases after MAX_BLOCKS refusals", codes[:2] == [2, 2] and codes[2] == 0,
              f"codes={codes}")

        # 13. THE POINT: three write mechanisms the hook knows nothing about.
        for i, (label, cmd) in enumerate([
            ("sed -i", "sed -i '' 's/$/# touched/' app/thing.py"),
            ("heredoc", "cat > app/thing.py <<'EOF'\nx = 2\nEOF"),
            ("python open()", "python3 -c \"open('app/thing.py','w').write('x = 3')\""),
        ]):
            r = repo(projects, f"mech{i}")
            # The fixture file must have a line in it: `repo()` creates it empty, and
            # `sed 's/$/.../'` over a file with no lines produces no change, so 13.0 passed
            # vacuously against a hook that was working.
            open(os.path.join(r, "app/thing.py"), "w").write("x = 1\n")
            subprocess.run(["git", "-C", r, "commit", "-qam", "seed"],
                           capture_output=True, env=GIT_ENV, timeout=20)
            subprocess.run(cmd, shell=True, cwd=r, capture_output=True, timeout=20)
            c, e = run(roots, r, sd(td, f"t13{i}"))
            check(f"13.{i} a write via {label} blocks", c == 2 and "thing.py" in e,
                  f"code={c} err={e[:160]}")

        # 14. F1: docs/** is exempt, but ai-profile.md is not -- it authorizes sending a repo to a
        # second AI provider, and block-edits-on-main.py already refuses to exempt it. The comment
        # claiming parity with that hook was false.
        r14 = repo(projects, "aiprof")
        os.makedirs(os.path.join(r14, "docs"), exist_ok=True)
        open(os.path.join(r14, "docs/ai-profile.md"), "w").write("trusted\n")
        c, e = run(roots, r14, sd(td, "t14"))
        check("14. an uncommitted docs/ai-profile.md on main blocks", c == 2 and "ai-profile" in e,
              f"code={c} err={e[:180]}")

        # 15. F2: the real workflow runs from ~/worktrees/<repo>/<branch>, which is OUTSIDE both
        # protected roots. The gate must still reach the MAIN checkout it belongs to, or it only
        # ever fires in the situation the worktree rule already forbids.
        r15 = repo(projects, "viaworktree")
        wt_parent = os.path.join(td, "worktrees", "viaworktree"); os.makedirs(wt_parent)
        wt = os.path.join(wt_parent, "feat-x")
        subprocess.run(["git", "-C", r15, "worktree", "add", "-q", "-b", "feat/x", wt],
                       capture_output=True, env=GIT_ENV, timeout=20)
        open(os.path.join(r15, "app/thing.py"), "w").write("x = 1\n")   # main checkout is dirty
        c, e = run(roots, wt, sd(td, "t15"))
        check("15. a session in a worktree still sees its dirty main checkout",
              c == 2 and "viaworktree" in e, f"code={c} err={e[:200]}")
        subprocess.run(["git", "-C", r15, "checkout", "-q", "--", "."],
                       capture_output=True, env=GIT_ENV, timeout=20)
        c, e = run(roots, wt, sd(td, "t15b"))
        check("15b. and is silent once that checkout is clean", c == 0, f"code={c} err={e[:160]}")

        # 16. F3: the printed remedy must not leave the main checkout on a feature branch, and must
        # cover untracked files -- case 7 blocks on those and plain `git stash` does not take them.
        c, e = run(roots, r2, sd(td, "t16"))
        # Assert the INSTRUCTION, not the substring: the message legitimately mentions
        # `git switch -c` in order to warn against it, and a bare `"switch -c" not in e`
        # cannot tell prescribing from prohibiting.
        prescribes = [l for l in e.splitlines()
                      if ("switch -c" in l or "checkout -b" in l) and "NOT" not in l.upper()]
        check("16. the remedy does not tell me to switch the main checkout's branch",
              prescribes == [], f"prescribing lines={prescribes}")
        check("16b. and it covers untracked files or points at a worktree",
              ("stash -u" in e or "worktree" in e), e[:260])

        # 17. F4/F5: a rename is judged on BOTH sides, and quoting is handled per path.
        r17 = repo(projects, "renamed")
        subprocess.run(["git", "-C", r17, "mv", "app/thing.py", "docs/thing.py"],
                       capture_output=True, env=GIT_ENV, timeout=20)
        c, e = run(roots, r17, sd(td, "t17"))
        check("17. moving a tracked file OUT of the tree on main blocks", c == 2,
              f"code={c} err={e[:180]}")
        r17b = repo(projects, "renamed2")
        subprocess.run(["git", "-C", r17b, "mv", "docs/spec.md", "docs/\u00f1.md"],
                       capture_output=True, env=GIT_ENV, timeout=20)
        c, e = run(roots, r17b, sd(td, "t17b"))
        check("17b. a docs-only rename with a non-ASCII name does NOT block", c == 0,
              f"code={c} err={e[:180]}")

        # 18. F6: a blocking gate's env escape must require "1", like its two siblings.
        c, _ = run(roots, r2, sd(td, "t18"), env_extra={"CLAUDE_MAIN_DIRTY_SKIP": "0"})
        check("18. CLAUDE_MAIN_DIRTY_SKIP=0 does NOT disable a blocking gate", c == 2, f"code={c}")
        c, _ = run(roots, r2, sd(td, "t18b"), env_extra={"CLAUDE_MAIN_DIRTY_SKIP": "1"})
        check("18b. but =1 still does", c == 0, f"code={c}")

        # 19. F7: the counter must reset when the tree goes clean, or the gate dies for the session.
        s19 = sd(td, "t19")
        r19 = repo(projects, "reopen")
        open(os.path.join(r19, "app/thing.py"), "w").write("x = 1\n")
        codes = [run(roots, r19, s19, session="s19")[0] for _ in range(3)]
        subprocess.run(["git", "-C", r19, "checkout", "-q", "--", "."],
                       capture_output=True, env=GIT_ENV, timeout=20)
        run(roots, r19, s19, session="s19")                       # clean pass resets
        open(os.path.join(r19, "app/thing.py"), "w").write("x = 2\n")
        c, _ = run(roots, r19, s19, session="s19")
        check("19. a later violation in the same session blocks again",
              codes[:2] == [2, 2] and c == 2, f"first={codes} later={c}")

        # 20. B9: the refusal names the gate and asks the human; no recipe, no state dir path
        s20 = sd(td, "t20")
        c, e = run(roots, r2, s20, session="s20")
        low = e.lower()
        check("20. the refusal asks the human to silence the gate, with no recipe or state path",
              c == 2 and "ask the human" in low and "uncommitted-on-main" in e
              and "touch" not in low and ".skip" not in low and s20 not in e, e[-240:])
        with open(HOOK) as f:
            sites = [ln for ln in f.read().splitlines() if re.match(r"\s+(block|deny)\(", ln)]
        check("20b. exactly one refusal call site, the one driven above", len(sites) == 1, str(sites))

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
