#!/usr/bin/env python3
"""Tests for notify.py.

Run: python3 claude/hooks/test_notify.py
A fake `osascript` first on PATH records its argv, so no real notification is shown.
"""
import json, os, stat, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notify.py")
results = []

FAKE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_OSASCRIPT_LOG"], "w") as f:
    json.dump(sys.argv[1:], f)
"""


def run(payload, td, home):
    log = os.path.join(td, "argv.json")
    if os.path.exists(log):
        os.remove(log)
    e = dict(os.environ)
    e["PATH"] = os.path.join(td, "bin") + os.pathsep + e["PATH"]
    e["FAKE_OSASCRIPT_LOG"] = log
    e["HOME"] = home
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, HOOK], input=raw,
                       capture_output=True, text=True, timeout=15, env=e)
    argv = json.load(open(log)) if os.path.exists(log) else None
    return p, argv


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -- " + detail) if detail and not cond else ""))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "bin"))
        fake = os.path.join(td, "bin", "osascript")
        with open(fake, "w") as f:
            f.write(FAKE)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        home = os.path.join(td, "home")
        wt = os.path.join(home, "worktrees", "dotfiles", "feat", "notify-hook")
        os.makedirs(wt)

        p, argv = run({"hook_event_name": "Notification", "cwd": wt,
                       "message": "Claude needs your permission to use Bash"}, td, home)
        check("1. calls osascript and exits 0", p.returncode == 0 and argv is not None,
              f"rc={p.returncode} err={p.stderr[:120]}")
        argv = argv or []
        check("2. title is the worktree path under ~/worktrees",
              "dotfiles/feat/notify-hook" in argv, f"argv={argv}")
        check("3. message is passed through unchanged",
              "Claude needs your permission to use Bash" in argv, f"argv={argv}")

        plain = os.path.join(td, "elsewhere", "myrepo"); os.makedirs(plain)
        p, argv = run({"cwd": plain, "message": "Claude is waiting for your input"}, td, home)
        check("4. outside ~/worktrees the title is the folder name",
              argv is not None and "myrepo" in argv, f"argv={argv}")

        hostile = 'x" & (do shell script "touch /tmp/pwned") & "'
        p, argv = run({"cwd": wt, "message": hostile}, td, home)
        script = argv[argv.index("-e") + 1] if argv and "-e" in argv else ""
        check("5. the message is an argv item, never inside the AppleScript source",
              argv is not None and hostile in argv and hostile not in script, f"argv={argv}")

        # osascript parses a dash-led positional as another `-e` statement (probed: it was
        # appended to the script), so the data must sit after a `--`.
        dashed = "-e do shell script \"touch /tmp/pwned\""
        p, argv = run({"cwd": wt, "message": dashed}, td, home)
        check("5b. a dash-led message sits after `--`, so osascript reads it as data",
              argv is not None and "--" in argv and argv[argv.index("--") + 1:][-1] == dashed,
              f"argv={argv}")

        p, argv = run("not json", td, home)
        check("6. fails open on garbage input", p.returncode == 0, f"rc={p.returncode}")

        p, argv = run("[1, 2]", td, home)
        check("6b. a non-object payload exits 0 without notifying",
              p.returncode == 0 and argv is None, f"rc={p.returncode} argv={argv}")

        p, argv = run({"cwd": "/", "message": "m"}, td, home)
        check("6c. cwd at / falls back to a generic title",
              argv is not None and "Claude Code" in argv, f"argv={argv}")

        p, argv = run({"cwd": wt}, td, home)
        check("7. a missing message still notifies with a fallback text",
              p.returncode == 0 and argv is not None and "Claude needs your attention" in argv,
              f"argv={argv}")

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
