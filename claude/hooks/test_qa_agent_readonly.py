#!/usr/bin/env python3
"""Tests for qa-agent-readonly.py.

Run: python3 claude/hooks/test_qa_agent_readonly.py

Exit 0 = allow, exit 2 = block. The two properties that matter: the guard blocks
every way Bash can write while agent_type == "qa", and it is completely invisible
everywhere else. A guard that fires outside its agent gets disabled, and then it
protects nothing.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa-agent-readonly.py")

FAILED = []


def run(payload):
    return subprocess.run(
        [sys.executable, HOOK], input=json.dumps(payload), text=True, capture_output=True
    )


def pre(cmd, agent="qa", tool="Bash", **extra):
    return {
        "hook_event_name": "PreToolUse",
        "agent_type": agent,
        "tool_name": tool,
        "tool_input": {"command": cmd},
        **extra,
    }


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILED.append(name)


def blocks(name, cmd, **kw):
    p = run(pre(cmd, **kw))
    check(name, p.returncode == 2, f"rc={p.returncode} out={p.stderr[:120]!r}")


def allows(name, cmd, **kw):
    p = run(pre(cmd, **kw))
    check(name, p.returncode == 0, f"rc={p.returncode} out={p.stderr[:120]!r}")


print("blocked — git writes")
blocks("git commit", "git commit -m 'fix'")
blocks("git add", "git add -A")
blocks("git -C <path> commit", "git -C /Users/x/proj commit -m x")
blocks("git push", "git push origin main")
blocks("git checkout", "git checkout -b qa/fix")
blocks("git stash", "git stash")
blocks("git reset", "git reset --hard HEAD~1")
blocks("chained after a read", "git status && git commit -m x")
blocks("chained with ;", "ls ; git add .")

print("blocked — in-place edits and redirection")
blocks("sed -i", "sed -i '' 's/a/b/' app/models/user.rb")
blocks("perl -i", "perl -i -pe 's/a/b/' file.rb")
blocks("redirect >", "echo hi > app/models/user.rb")
blocks("redirect >>", "echo hi >> config/routes.rb")
blocks("tee", "echo hi | tee app/x.rb")

print("blocked — filesystem mutation without a redirection (found by the security audit)")
blocks("rm on the repo", "rm -rf app/models")
blocks("mv onto a tracked file", "mv /tmp/x app/models/user.rb")
blocks("cp onto a tracked file", "cp /tmp/x app/models/user.rb")
blocks("touch in the repo", "touch app/models/new.rb")
blocks("chmod in the repo", "chmod +x bin/thing")
blocks("rails runner File.write", 'bin/rails runner "File.write(%q(app/x.rb), %q(hi))"')
blocks("python open for write", """python3 -c "open('app/x.rb','w').write('hi')" """)
blocks("node writeFileSync", """node -e "require('fs').writeFileSync('app/x.js','hi')" """)
blocks("redirect with >|", "echo hi >| app/x.rb")

print("allowed — the false positives that would get this guard switched off")
allows("npm install", "cd web && npm install")
allows("bundle install", "cd backend && bundle install")
allows("mkdir in /tmp", "mkdir -p /tmp/qa-shots")
allows("rm in /tmp", "rm -f /tmp/qa-shots/a.png")
allows("rails runner read", 'bin/rails runner "puts Event.count"')
allows("dev data for an edge case", 'bin/rails runner "Event.create!(name: %q(x))"')

print("blocked — quoted operands (found by /code-review high)")
blocks("quoted redirect target", 'echo hi > "app/models/user.rb"')
blocks("quoted rm path", 'rm -rf "app/models"')
blocks("quoted mv destination", 'mv /tmp/x "app/models/user.rb"')
blocks("quoted cp destination", "cp /tmp/x 'app/x.rb'")

print("blocked — combined short flags and other redirect forms")
blocks("perl -pi -e", """perl -pi -e 's/a/b/' app/models/user.rb""")
blocks("sed -Ei", """sed -Ei 's/a/b/' app/models/user.rb""")
blocks("sed --in-place", """sed --in-place 's/a/b/' app/models/user.rb""")
blocks("&> redirect", "curl -s http://x &> app/x.html")
blocks("absolute git path", "/usr/bin/git commit -m x")
blocks("git --git-dir then commit", "git --git-dir /tmp/g commit -m x")
blocks("curl -o into the repo", "curl -o app/captured.html http://localhost:3000")
blocks("wget -O into the repo", "wget -O app/captured.html http://localhost:3000")

print("allowed — reads, never mistaken for writes")
allows("python open for read", """python3 -c "print(open('/tmp/out.json','r').read())" """)
allows("pathlib read", """python3 -c "import pathlib; print(pathlib.Path('config/routes.rb').read_text())" """)
allows("Pathname read", 'bin/rails runner "puts Pathname.new(Rails.root).to_s"')
allows("chmod with a mode", "chmod 755 /tmp/qa/x.sh")
allows("dd with if=/of=", "dd if=/tmp/a of=/tmp/b")
allows("grep for the word touch", "grep -rn touch docs/")
allows("docker cp", "docker cp c:/x /tmp/y")
allows("curl -o into /tmp", "curl -o /tmp/captured.html http://localhost:3000")

print("allowed — reads and QA work")
allows("git status", "git status")
allows("git log", "git log --oneline -10")
allows("git diff", "git diff HEAD~1")
allows("git show", "git show abc123:docs/specs/x.md")
allows("curl", "curl -s -i http://localhost:3002/api/v1/events")
allows("curl with > inside JSON", """curl -d '{"q": "a > b"}' http://localhost:3002/api/v1/search""")
allows("grep for the word commit", "grep -rn 'git commit' docs/")
allows("rspec", "cd backend && bundle exec rspec spec/requests")
allows("rails runner read", 'bin/rails runner "puts Event.count"')
allows("tail a log", "tail -n 50 log/development.log")
allows("redirect to /tmp", "curl -s http://localhost:3003 > /tmp/page.html")
allows("redirect to /dev/null", "bin/dev > /dev/null 2>&1 &")
allows("stderr dup", "bundle exec rspec 2>&1 | tail -5")

print("allowed — outside the qa agent (the guard must be invisible)")
allows("main session commit", "git commit -m 'feat: x'", agent=None)
allows("other subagent commit", "git commit -m 'feat: x'", agent="Explore")
allows("qa agent, non-Bash tool", "irrelevant", tool="Read")

print("allowed — scratchpad redirection")
allows(
    "scratchpad",
    "curl -s http://localhost:3003 > /Users/x/scratch/out.html",
    scratchpad_dir="/Users/x/scratch",
)

print("fails open")
p = subprocess.run([sys.executable, HOOK], input="not json", text=True, capture_output=True)
check("malformed stdin allows", p.returncode == 0, f"rc={p.returncode}")
p = run({"hook_event_name": "PreToolUse", "agent_type": "qa", "tool_name": "Bash"})
check("missing tool_input allows", p.returncode == 0, f"rc={p.returncode}")

print()
if FAILED:
    print(f"{len(FAILED)} failing: {', '.join(FAILED)}")
    sys.exit(1)
print("all passing")
