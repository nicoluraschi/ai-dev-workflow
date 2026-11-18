#!/usr/bin/env python3
"""Tests for ruby-session-reminder.py.

Run: python3 claude/hooks/test_ruby_session_reminder.py
The hook never blocks; it injects context at most once per session.
"""
import hashlib, json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ruby-session-reminder.py")
results = []


def run(cmd, cwd, state_dir, session="s1"):
    e = dict(os.environ); e["CLAUDE_AUDIT_STATE_DIR"] = state_dir
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": cmd}, "cwd": cwd, "session_id": session}
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=15, env=e)


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -- " + detail) if detail and not cond else ""))


def main():
    with tempfile.TemporaryDirectory() as td:
        ruby = os.path.join(td, "rubyproj"); os.makedirs(ruby)
        open(os.path.join(ruby, "Gemfile"), "w").close()
        nested = os.path.join(ruby, "app", "models"); os.makedirs(nested)
        plain = os.path.join(td, "plain"); os.makedirs(plain)

        sd = os.path.join(td, "s1"); os.makedirs(sd)
        p = run("bundle exec rspec spec/", ruby, sd)
        check("1. ruby command in a ruby project injects", p.returncode == 0
              and "ruby-version-manager" in p.stdout, f"rc={p.returncode} out={p.stdout[:120]}")
        check("2. it no longer names the removed ruby-resource-map",
              "ruby-resource-map" not in p.stdout, p.stdout[:160])

        p2 = run("bundle exec rubocop", ruby, sd)
        check("3. only once per session", "ruby-version-manager" not in p2.stdout, p2.stdout[:120])

        sd = os.path.join(td, "s2"); os.makedirs(sd)
        p = run("ls -la", ruby, sd)
        check("4. non-ruby command does not inject", "ruby-version-manager" not in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s3"); os.makedirs(sd)
        p = run("bundle exec rspec", plain, sd)
        check("5. ruby command outside a ruby project does not inject",
              "ruby-version-manager" not in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s4"); os.makedirs(sd)
        p = run("rails console", nested, sd)
        check("6. Gemfile found from a nested cwd", "ruby-version-manager" in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s5"); os.makedirs(sd)
        e = dict(os.environ); e["CLAUDE_AUDIT_STATE_DIR"] = sd
        p = subprocess.run([sys.executable, HOOK], input="not json",
                           capture_output=True, text=True, timeout=15, env=e)
        check("7. fails open on garbage input", p.returncode == 0, f"rc={p.returncode}")

        sd = os.path.join(td, "s6"); os.makedirs(sd)
        p = run("echo 'bundle is a word here'", ruby, sd)
        check("8. the word bundle inside a string does not trigger",
              "ruby-version-manager" not in p.stdout, p.stdout[:120])

        # 12-18. Precision: a `|` inside a quoted pattern is not a pipe, and a .tool-versions
        # marks a Ruby project only when it pins ruby (~/.tool-versions pinned only nodejs, so every
        # directory under home looked like one).
        node = os.path.join(td, "nodeproj"); os.makedirs(node)
        with open(os.path.join(node, ".tool-versions"), "w") as f:
            f.write("nodejs 26.5.0\n")
        rbtv = os.path.join(td, "rbtv"); os.makedirs(rbtv)
        with open(os.path.join(rbtv, ".tool-versions"), "w") as f:
            f.write("nodejs 26.5.0\nruby 3.4.1\n")

        sd = os.path.join(td, "s12"); os.makedirs(sd)
        p = run("bundle exec rspec", node, sd)
        check("12. a .tool-versions without ruby is not a ruby project",
              "ruby-version-manager" not in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s13"); os.makedirs(sd)
        p = run("bundle exec rspec", rbtv, sd)
        check("13. a .tool-versions with a ruby line is a ruby project",
              "ruby-version-manager" in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s14"); os.makedirs(sd)
        p = run('grep -nE "npm|bundle|rspec" Gemfile', ruby, sd)
        check("14. a ruby word after a quoted | does not trigger",
              "ruby-version-manager" not in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s15"); os.makedirs(sd)
        p = run("cd app && bundle exec rspec", ruby, sd)
        check("15. a ruby command after && triggers", "ruby-version-manager" in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s16"); os.makedirs(sd)
        p = run("echo $(rails -v)", ruby, sd)
        check("16. a ruby command inside $( ) triggers", "ruby-version-manager" in p.stdout, p.stdout[:120])

        sd = os.path.join(td, "s17"); os.makedirs(sd)
        p = run("echo 'unterminated; bundle", ruby, sd)
        check("17. unbalanced quotes fail open without a reminder", p.returncode == 0
              and "ruby-version-manager" not in p.stdout, f"rc={p.returncode} out={p.stdout[:120]}")

        sd = os.path.join(td, "s18"); os.makedirs(sd)
        p = run("bundle exec rails runner - <<EOF\nit's\nEOF", ruby, sd)
        check("18. unbalanced quotes still see a leading ruby command",
              "ruby-version-manager" in p.stdout, p.stdout[:120])

        # 9-11. session_id arrives in the payload and is interpolated into the marker filename, so
        # a traversing id wrote outside the state dir. Third instance of the class (#12 closed
        # session-hygiene.py, #14 closed audit-guard.py); this is the one that closes it.
        sd = os.path.join(td, "s9"); os.makedirs(sd)
        parent = os.path.dirname(os.path.realpath(sd))
        escaped = os.path.join(parent, "escaped.ruby-reminded")
        if os.path.exists(escaped):
            os.remove(escaped)
        p = run("bundle exec rspec", ruby, sd, session="../escaped")
        check("9. a traversing session id writes nothing outside the state dir",
              not os.path.exists(escaped), f"wrote {escaped}")
        check("9b. and it still injects, rather than being waved through",
              "ruby-version-manager" in p.stdout, p.stdout[:120])

        # The marker gates a reminder, not an audit, so a shared fallback bucket would only cost a
        # missed reminder. Hashing anyway: it is one line, it needs no per-hook consequence
        # analysis, and a missed version-manager reminder fails in ways that look like app bugs.
        # Each of these gets its OWN parent, so a marker leaked by one test can never be found by
        # another. Pre-fix, test 10's escape landed in the shared parent and test 11 then resolved
        # to that same leaked file, making its assertion hold without exercising anything.
        home10 = os.path.join(td, "h10"); sd = os.path.join(home10, "st"); os.makedirs(sd)
        run("bundle exec rspec", ruby, sd, session="../evil-one")
        p = run("bundle exec rspec", ruby, sd, session="../evil-two")
        markers = sorted(f for f in os.listdir(sd) if f.endswith(".ruby-reminded"))
        check("10. two different hostile ids get two different markers",
              len(markers) == 2, f"markers={markers}")
        check("10b. so the second session is still reminded",
              "ruby-version-manager" in p.stdout, p.stdout[:120])
        # NB: do NOT assert containment by testing names from listdir(sd) -- those are bare entry
        # names, so any commonpath/startswith check over them is TRUE for every possible input and
        # catches nothing. The stray lands OUTSIDE sd, where listdir(sd) cannot see it. Sweep the
        # parent instead, and pin the exact name the validator should have produced.
        strays = [f for f in os.listdir(home10) if f.endswith(".ruby-reminded")]
        check("10c. nothing leaked into the parent directory", strays == [], f"strays={strays}")
        expected = sorted("unknown-" + hashlib.sha256(v.encode()).hexdigest()[:16]
                          + ".ruby-reminded" for v in ("../evil-one", "../evil-two"))
        check("10d. and the marker names are exactly the hashed fallbacks",
              markers == expected, f"got={markers} want={expected}")

        home11 = os.path.join(td, "h11"); sd = os.path.join(home11, "st"); os.makedirs(sd)
        run("bundle exec rspec", ruby, sd, session="../evil-three")
        p = run("bundle exec rubocop", ruby, sd, session="../evil-three")
        # Assert on the filesystem, not only on stdout: one marker means the id mapped to the same
        # name twice, which is the actual property. Checking stdout alone passed pre-fix purely
        # because a marker leaked by another test happened to be on the resolved path.
        markers = [f for f in os.listdir(sd) if f.endswith(".ruby-reminded")]
        check("11. the same hostile id maps to one stable marker", len(markers) == 1,
              f"markers={markers}")
        check("11b. so it still fires only once",
              "ruby-version-manager" not in p.stdout, p.stdout[:120])
        strays = [f for f in os.listdir(home11) if f.endswith(".ruby-reminded")]
        check("11c. and nothing leaked out", strays == [], f"strays={strays}")

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
