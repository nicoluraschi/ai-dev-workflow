#!/usr/bin/env python3
"""Tests for gate-state-guard.py and its registration.

Run: python3 claude/hooks/test_gate_state_guard.py

The guard is a speed bump against agent drift, not a boundary (see its docstring). Every case
that touches the extra scanner uses a FIXTURE pointer and scanner under a temp HOME; nothing here
reads or prints the real pointer or scanner path.
"""
import importlib.util, io, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HOOK = os.path.join(HERE, "gate-state-guard.py")
results = []
STDERRS = []        # every deny message seen, for the "never leaks" checks


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -- " + detail) if detail and not cond else ""))


def payload(tool, **ti):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti}


def run(data, home, state=None):
    """Run the hook as a subprocess under HOME=home. Returns (exit_code, stderr)."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_AUDIT_STATE_DIR"}
    env["HOME"] = home
    if state is not None:
        env["CLAUDE_AUDIT_STATE_DIR"] = state
    raw = data if isinstance(data, str) else json.dumps(data)
    p = subprocess.run([sys.executable, HOOK], input=raw, env=env, capture_output=True, text=True,
                       timeout=30)
    if p.returncode == 2:
        STDERRS.append(p.stderr)
    return p.returncode, p.stderr


def make_home(td, name, pointer="valid"):
    """A fixture HOME: default state dir, a scanner with a sibling file, and a pointer."""
    home = os.path.join(td, name)
    os.makedirs(os.path.join(home, ".claude", ".audit-state"))
    os.makedirs(os.path.join(home, ".config", "ai-workflow"))
    os.makedirs(os.path.join(home, "scanners"))
    scanner = os.path.join(home, "scanners", "scan.py")
    open(scanner, "w").close()
    open(os.path.join(home, "scanners", "dossier.md"), "w").close()
    ptr = os.path.join(home, ".config", "ai-workflow", "extra-scanner")
    if pointer == "valid":
        open(ptr, "w").write(scanner + "\n")
    elif pointer == "symlink":
        real = os.path.join(home, "ptr-real"); open(real, "w").write(scanner + "\n")
        os.symlink(real, ptr)
    elif pointer == "fifo":
        os.mkfifo(ptr)
    elif pointer == "oversized":
        open(ptr, "w").write("/" + "a" * 5000 + "\n")
    elif pointer == "multiline":
        open(ptr, "w").write(scanner + "\n" + scanner + "\n")
    elif pointer == "relative":
        open(ptr, "w").write("scanners/scan.py\n")
    elif pointer == "nul":
        open(ptr, "w").write(scanner + "\x00x\n")
    return home, scanner, ptr


def edit_cases(td):
    home, scanner, ptr = make_home(td, "h1")
    custom = os.path.join(td, "custom-state"); os.makedirs(custom)
    default = os.path.join(home, ".claude", ".audit-state")
    targets = {"env state dir": os.path.join(custom, "s1.skip"),
               "default state dir (env var set)": os.path.join(default, "s1.skip.audit-guard"),
               "pointer": ptr, "extra scanner": scanner,
               "scanner's directory (it reads files beside itself)":
                   os.path.join(home, "scanners", "dossier.md")}
    for label, path in targets.items():
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            c, e = run(payload(tool, **{key: path}), home, custom)
            check(f"8. {tool} to the {label} is denied", c == 2 and "gate-state-guard" in e,
                  f"code={c} err={e[:100]}")

    for label, d in (("env state dir", custom), ("default state dir", default)):
        c, _ = run(payload("Write", file_path=d), home, custom)
        check(f"8. a Write naming the {label} itself is denied", c == 2, f"code={c}")

    c, _ = run(payload("Write", file_path=os.path.join(default, "new", "deep", "f")), home, custom)
    check("8. a not-yet-existing file inside the state dir is denied", c == 2, f"code={c}")

    alias = os.path.join(td, "alias"); os.symlink(custom, alias)
    c, _ = run(payload("Write", file_path=os.path.join(alias, "x.skip")), home, custom)
    check("8. a path through a symlinked ancestor is denied", c == 2, f"code={c}")

    c, _ = run(payload("Write", file_path=os.path.join(home, ".claude", "zz", "..", ".audit-state", "x")),
               home, custom)
    check("8. a path with .. resolving into the state dir is denied", c == 2, f"code={c}")

    c, _ = run(payload("Write", file_path=os.path.join(home, ".CLAUDE", ".AUDIT-STATE", "x")), home, custom)
    check("8. a different-case path into the state dir is denied", c == 2, f"code={c}")

    # Case variants of targets that do not exist yet (pointer absent; env state dir absent).
    bare = os.path.join(td, "bare"); os.makedirs(bare)
    gone = os.path.join(td, "nostate")
    c, _ = run(payload("Write", file_path=os.path.join(bare, ".CONFIG", "AI-Workflow", "extra-scanner")),
               bare, gone)
    check("8. a case variant of an absent pointer is denied", c == 2, f"code={c}")
    c, _ = run(payload("Write", file_path=os.path.join(td, "NOSTATE", "x")), bare, gone)
    check("8. a case variant of an absent CLAUDE_AUDIT_STATE_DIR is denied", c == 2, f"code={c}")

    # 10. allowed
    c, e = run(payload("Write", file_path=os.path.join(home, ".claude", ".audit-state-old", "x")),
               home, custom)
    check("10. Edit-family on a sibling .audit-state-old path is allowed", c == 0 and not e, f"code={c}")
    for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")):
        c, e = run(payload(tool, **{key: os.path.join(td, "unrelated", "f.py")}), home, custom)
        check(f"10. {tool} on an unrelated path is allowed", c == 0 and not e, f"code={c} err={e[:80]}")
    c, _ = run(payload("Bash", command="git status && ls /usr/bin"), home, custom)
    check("10. an unrelated Bash command is allowed", c == 0, f"code={c}")
    for label, path in targets.items():
        c, _ = run(payload("Read", file_path=path), home, custom)
        check(f"10. the Read tool on the {label} is allowed", c == 0, f"code={c}")
    c, _ = run(payload("Grep", pattern="x", path=default), home, custom)
    check("10. the Grep tool on the state dir is allowed", c == 0, f"code={c}")


def bash_cases(td):
    home, scanner, ptr = make_home(td, "h2")
    custom = os.path.join(td, "custom-state2"); os.makedirs(custom)
    default = os.path.join(home, ".claude", ".audit-state")
    cmds = [
        f"touch {custom}/x.skip",
        f"echo hi > {default}/s1.skip",
        f"cp /tmp/a {default}/s1.skip",
        f"touch ~/.claude/.audit-state/x",
        f"touch $HOME/.claude/.audit-state/x",
        "touch ${HOME}/.claude/.audit-state/x",
        "TOUCH ~/.CLAUDE/.AUDIT-STATE/x",
        "touch /tmp/.audit-state-old/x",
        f"cat {default}/s1.skip",
        f"cat {ptr}",
        "cat ~/.config/ai-workflow/extra-scanner",
        "cp /tmp/a $HOME/.config/ai-workflow/extra-scanner",
        "echo x > ${HOME}/.config/ai-workflow/extra-scanner",
        "TOUCH ~/.CONFIG/ai-workflow/EXTRA-SCANNER",
        f"touch {scanner}",
        "touch ~/scanners/scan.py",
        "echo x > $HOME/scanners/dossier.md",
        'touch "$CLAUDE_AUDIT_STATE_DIR/x"',
        'touch "${claude_audit_state_dir}/x"',
        # 5s: quoting and path-noise forms
        'touch "$HOME"/scanners/scan.py',
        'touch "${HOME}"/.config/ai-workflow/extra-scanner',
        "touch '~'/.claude/.audit-state/x",
        "touch ~/.claude/.audit-\"state\"/x",
        "touch ~//scanners//scan.py",
        "touch ~/./.config/./ai-workflow/extra-scanner",
        "touch ~/.claude/.audit-\\state/x",
        "touch ~/.config/ai-workflow/extra-scann\\er",
    ]
    for cmd in cmds:
        c, e = run(payload("Bash", command=cmd), home, custom)
        check(f"9. Bash denied: {cmd.replace(td, '<td>')[:70]}", c == 2 and "gate-state-guard" in e,
              f"code={c} err={e[:80]}")
    # A target whose own path holds a quote still matches the normalized command.
    quoted = os.path.join(td, "o'neil-state"); os.makedirs(quoted)
    cmd = f'touch "{quoted}/x"'
    c, e = run(payload("Bash", command=cmd), home, quoted)
    check("9. Bash denied: a state dir whose path holds a quote", c == 2 and "gate-state-guard" in e,
          f"code={c} err={e[:80]}")


def pointer_cases(td):
    # A NUL in the pointer must not make resolution raise and drop the custom state dir.
    home, _, _ = make_home(td, "p-nul-custom", pointer="nul")
    custom = os.path.join(td, "nul-custom-state"); os.makedirs(custom)
    c, e = run(payload("Write", file_path=os.path.join(custom, "x.skip")), home, custom)
    check("11. nul pointer: a custom state dir is still guarded", c == 2, f"code={c} err={e[:100]}")
    for kind in ("missing", "symlink", "fifo", "oversized", "multiline", "relative", "nul"):
        home, scanner, ptr = make_home(td, "p-" + kind, pointer=kind)
        default = os.path.join(home, ".claude", ".audit-state")
        c, e = run(payload("Write", file_path=os.path.join(default, "x.skip")), home)
        check(f"11. {kind} pointer: the state dir is still guarded", c == 2, f"code={c} err={e[:100]}")
        c, e = run(payload("Write", file_path=ptr), home)
        check(f"11. {kind} pointer: the pointer is still guarded", c == 2, f"code={c} err={e[:100]}")
        c, e = run(payload("Write", file_path=scanner), home)
        check(f"11. {kind} pointer: no scanner target, no error", c == 0 and "Traceback" not in e,
              f"code={c} err={e[:100]}")
        c, e = run(payload("Write", file_path=os.path.join(td, "unrelated", "f")), home)
        check(f"11. {kind} pointer: an unrelated call is allowed", c == 0 and not e, f"code={c}")


def exception_cases(td):
    """12. If Edit path resolution raises, a raw path that names a target still denies."""
    home, scanner, ptr = make_home(td, "h3")
    old = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_AUDIT_STATE_DIR")}
    os.environ["HOME"] = home
    os.environ.pop("CLAUDE_AUDIT_STATE_DIR", None)

    def drive(path):
        spec = importlib.util.spec_from_file_location("gsg", HOOK)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)

        def boom(*a, **k):
            raise OSError("resolution failed")
        m.judge_edit = boom
        oi, oe = sys.stdin, sys.stderr
        sys.stdin = io.StringIO(json.dumps(payload("Write", file_path=path)))
        sys.stderr = io.StringIO()
        try:
            m.main(); code = 0
        except SystemExit as ex:
            code = ex.code or 0
        finally:
            err = sys.stderr.getvalue(); sys.stdin, sys.stderr = oi, oe
        return code, err
    try:
        c, e = drive(os.path.join(home, ".claude", ".audit-state", "x"))
        check("12. a resolution failure still denies a raw path naming the state dir",
              c == 2 and "gate-state-guard" in e, f"code={c} err={e[:100]}")
        c, e = drive("~/.config/ai-workflow/extra-scanner")
        check("12. ... and one naming the pointer", c == 2, f"code={c}")
        c, e = drive(scanner)
        check("12. ... and one naming the extra scanner", c == 2, f"code={c}")
        c, e = drive(os.path.join(home, "scanners", "dossier.md"))
        check("12. ... and one inside the scanner's directory", c == 2, f"code={c}")
        custom = os.path.join(td, "custom-state3"); os.makedirs(custom)
        os.environ["CLAUDE_AUDIT_STATE_DIR"] = custom
        c, e = drive(os.path.join(custom, "x.skip"))
        check("12. ... and one inside a custom CLAUDE_AUDIT_STATE_DIR", c == 2, f"code={c}")
        os.environ.pop("CLAUDE_AUDIT_STATE_DIR", None)
        c, e = drive(os.path.join(td, "unrelated", "f"))
        check("12. ... but an unrelated raw path is allowed", c == 0, f"code={c}")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def message_cases(td):
    home, scanner, ptr = make_home(td, "h4")
    custom = os.path.join(td, "custom-state4"); os.makedirs(custom)
    token = "ZZ-UNIQUE-TOKEN-ZZ"
    c, e = run(payload("Bash", command=f"touch {scanner} {token}"), home, custom)
    check("13. the message names the target class, not the path",
          c == 2 and "the extra scanner" in e and scanner not in e and token not in e, e[:200])
    check("13. it names the silencer, the Read/Grep tools and --body-file",
          "from the prompt with `!`" in e and "Read or Grep" in e and "--body-file" in e, e[:300])
    c, e = run(payload("Write", file_path=ptr), home, custom)
    check("13. the pointer class is named", "the scanner pointer" in e, e[:200])
    c, e = run(payload("Write", file_path=os.path.join(custom, "x")), home, custom)
    check("13. the state dir class is named", "the gate state dir" in e, e[:200])
    leaks = [s for s in STDERRS if scanner in s or ptr in s or "/scanners" in s]
    check("13. no deny message contains the fixture scanner path, the pointer path or its contents",
          not leaks, str(leaks[:1])[:200])

    c, _ = run("not json", home, custom)
    check("unparseable payload is allowed", c == 0, f"code={c}")
    c, _ = run(payload("Glob", pattern="*"), home, custom)
    check("another tool is allowed", c == 0, f"code={c}")
    c, _ = run("[]", home, custom)
    check("a non-object payload is allowed", c == 0, f"code={c}")
    c, _ = run(payload("Write"), home, custom)
    check("an Edit-family call with no path is allowed", c == 0, f"code={c}")


def settings_cases():
    with open(os.path.join(ROOT, "claude", "settings.json")) as f:
        raw = f.read()
    s = json.loads(raw)
    # 7. the security context names the config repo's checkout, not a hard-coded path
    check("7. settings.json security context says 'this config repo's checkout'",
          "this config repo's checkout" in raw and "~/dotfiles" not in raw)

    # 16. the guard is registered on every tool it judges
    entries = [e for e in s["hooks"]["PreToolUse"]
               if any("gate-state-guard.py" in h["command"] for h in e["hooks"])]
    for tool in ("Edit", "Write", "NotebookEdit", "Bash"):
        check(f"16. a PreToolUse matcher registering the guard matches {tool}",
              any(re.fullmatch(e["matcher"], tool) for e in entries), str([e["matcher"] for e in entries]))
    cmds = [h["command"] for e in entries for h in e["hooks"] if "gate-state-guard.py" in h["command"]]
    check("16. its command points at the hook file",
          bool(cmds) and all(c == 'python3 "$HOME/.claude/hooks/gate-state-guard.py"' for c in cmds)
          and os.path.isfile(os.path.join(HERE, "gate-state-guard.py")), str(cmds))


def main():
    settings_cases()
    with tempfile.TemporaryDirectory() as td:
        edit_cases(td)
        bash_cases(td)
        pointer_cases(td)
        exception_cases(td)
        message_cases(td)
    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
