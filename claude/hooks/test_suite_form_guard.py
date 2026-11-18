#!/usr/bin/env python3
"""Tests for suite-form-guard.py.

Run: python3 claude/hooks/test_suite_form_guard.py

suite-queue only skips a push's suite when the same argv already passed on the same content.
Agents ran suites in forms the pre-push skip could not match, so pushes re-ran them and
invited hook bypasses. The guard denies both, only in repos whose lefthook pre-push queues that suite.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "suite-form-guard.py")

LEFTHOOK = """\
pre-commit:
  commands:
    rubocop:
      run: bin/rubocop {staged_files}

pre-push:
  parallel: true
  commands:
    rspec:
      root: "backend/"
      run: if command -v suite-queue >/dev/null; then suite-queue ruby bundle exec rspec --tag ~slow; else bundle exec rspec --tag ~slow; fi
    brakeman:
      run: bin/brakeman --no-pager
    jest:
      root: "web/"
      run: if command -v suite-queue >/dev/null; then suite-queue js npm test -- --coverage --maxWorkers=2; else npm test -- --coverage --maxWorkers=2; fi
"""

FAILED = []


def repo(lefthook=LEFTHOOK):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "backend"))
    os.makedirs(os.path.join(d, "web"))
    if lefthook is not None:
        with open(os.path.join(d, "lefthook.yml"), "w") as f:
            f.write(lefthook)
    return d


QUEUED = repo()
UNQUEUED = repo(LEFTHOOK.replace("suite-queue ruby ", "").replace("suite-queue js ", ""))
NO_LEFTHOOK = repo(None)


EMPTY_HOME_ENV = {**os.environ, "HOME": tempfile.mkdtemp()}  # never the real $HOME


def run(command, cwd, env=None):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
               "tool_input": {"command": command}}
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), text=True,
                          capture_output=True, env=env or EMPTY_HOME_ENV)


def decision(proc):
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)["hookSpecificOutput"]
    except Exception:
        return None


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILED.append(name)


def denies(name, command, cwd=QUEUED, mentions=None):
    p = run(command, cwd)
    d = decision(p)
    ok = d is not None and d.get("permissionDecision") == "deny"
    reason = (d or {}).get("permissionDecisionReason", "")
    if ok and mentions:
        ok = mentions in reason
    check(name, ok, f"stdout={p.stdout!r} stderr={p.stderr!r}")


def allows(name, command, cwd=QUEUED):
    p = run(command, cwd)
    check(name, p.returncode == 0 and not p.stdout.strip(),
          f"rc={p.returncode} stdout={p.stdout!r} stderr={p.stderr!r}")


print("full suites run directly are denied")
denies("npx jest", "npx jest 2>&1 | tail -5", os.path.join(QUEUED, "web"), "--command jest")
denies("npm test", "npm test", os.path.join(QUEUED, "web"))
denies("npm run test with flags", "npm run test -- --silent", os.path.join(QUEUED, "web"))
denies("jest coverage run", "npx jest --coverage --coverageReporters=json-summary",
       os.path.join(QUEUED, "web"))
denies("bundle exec rspec", "bundle exec rspec", os.path.join(QUEUED, "backend"), "--command rspec")
denies("rspec with a tag value", "bundle exec rspec --tag ~slow 2>&1 | tail -3",
       os.path.join(QUEUED, "backend"))
denies("env prefix", "DATABASE_URL=postgres://x bundle exec rspec", os.path.join(QUEUED, "backend"))
denies("cd into the repo first", f"cd {QUEUED}/web && npx jest", "/")
denies("repo root found from a subdirectory", "bin/rspec",
       os.path.join(QUEUED, "backend"))
denies("rspec spec/ is the whole suite", "bundle exec rspec spec/", os.path.join(QUEUED, "backend"))
denies("jest . is the whole suite", "npx jest .", os.path.join(QUEUED, "web"))
denies("reason names the lefthook form", "npx jest", os.path.join(QUEUED, "web"),
       "SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out "
       "lefthook run pre-push --force --no-tty --command jest")

print("subsets and the lefthook form are allowed")
allows("jest on a file", "npx jest src/foo.test.tsx 2>&1 | tail -5", os.path.join(QUEUED, "web"))
allows("jest on a pattern", 'npx jest "books/\\[id\\]/book-hero"', os.path.join(QUEUED, "web"))
allows("jest with a flag then a file", "npx jest --silent src/foo.test.tsx",
       os.path.join(QUEUED, "web"))
allows("jest findRelatedTests", "npx jest --findRelatedTests src/lib/a.ts",
       os.path.join(QUEUED, "web"))
allows("npm test with a file", "npm test -- src/foo.test.tsx", os.path.join(QUEUED, "web"))
allows("rspec on spec files", "bundle exec rspec spec/models/book_spec.rb",
       os.path.join(QUEUED, "backend"))
allows("rspec on a line", "bundle exec rspec spec/models/book_spec.rb:12",
       os.path.join(QUEUED, "backend"))
allows("jest listTests runs nothing", "npx jest --listTests", os.path.join(QUEUED, "web"))
allows("rspec only-failures", "bundle exec rspec --only-failures", os.path.join(QUEUED, "backend"))
allows("lefthook form", "SUITE_QUEUE_FORCE=1 lefthook run pre-push --force --no-tty --command jest")
LHO = ("SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out "
       "lefthook run pre-push --force --no-tty --command ")
allows("output-forcing lefthook form", LHO + "jest")
allows("output-forcing form piped", LHO + "rspec 2>&1 | tail -40", os.path.join(QUEUED, "backend"))
allows("suite-queue directly", "suite-queue js npm test -- --coverage --maxWorkers=2",
       os.path.join(QUEUED, "web"))
allows("grep for a runner name", "grep -n 'npx jest' AGENTS.md")
allows("echo mentioning rspec", "echo bundle exec rspec")

print("push with the hook disabled is denied")
denies("LEFTHOOK_EXCLUDE", "LEFTHOOK_EXCLUDE=jest git push -u origin feat/x", QUEUED, "push")
denies("LEFTHOOK=0", "LEFTHOOK=0 git push", QUEUED)
denies("--no-verify", "git push --no-verify", QUEUED)
denies("exported LEFTHOOK=0", "export LEFTHOOK=0; git push", QUEUED)
denies("exported LEFTHOOK_EXCLUDE", "export LEFTHOOK_EXCLUDE=jest && git push", QUEUED)
denies("hooksPath override", "git -c core.hooksPath=/dev/null push", QUEUED)
allows("unrelated -c", "git -c color.ui=never push", QUEUED)
denies("git -C into the repo", f"LEFTHOOK_EXCLUDE=jest,rspec git -C {QUEUED} push", "/")
allows("plain push", "git push -u origin feat/x", QUEUED)
allows("LEFTHOOK_OUTPUT does not disable the hook",
       "LEFTHOOK_OUTPUT=summary,success,execution,execution_out git push", QUEUED)
allows("dry-run -n is not no-verify", "git push -n", QUEUED)

print("only where the pre-push queues that suite")
allows("unqueued repo: jest", "npx jest", os.path.join(UNQUEUED, "web"))
allows("unqueued repo: push bypass", "git push --no-verify", UNQUEUED)
allows("no lefthook.yml", "bundle exec rspec", NO_LEFTHOOK)
only_rspec = repo(LEFTHOOK.replace("suite-queue js ", ""))
allows("jest not queued while rspec is", "npx jest", os.path.join(only_rspec, "web"))
denies("rspec still queued", "bundle exec rspec", os.path.join(only_rspec, "backend"))

print("pnpm and Vitest")
PNPM = repo("""\
pre-push:
  parallel: true
  commands:
    typecheck:
      run: pnpm typecheck
    test:
      run: if command -v suite-queue >/dev/null; then suite-queue js pnpm test --maxWorkers=2; else pnpm test --maxWorkers=2; fi
""")
denies("pnpm test", "pnpm test 2>&1 | tail -5", PNPM, "--command test")
denies("pnpm run test", "pnpm run test", PNPM)
denies("pnpm -r test", "pnpm -r test", PNPM)
denies("pnpm test with a flag", "pnpm test --maxWorkers=2", PNPM)
denies("npx vitest", "npx vitest", PNPM)
denies("npx vitest run", "npx vitest run --coverage", PNPM)
denies("pnpm exec vitest run", "pnpm exec vitest run", PNPM)
denies("pnpm vitest", "pnpm vitest run", PNPM)
allows("vitest run on a file", "npx vitest run src/a.test.ts", PNPM)
allows("vitest related", "npx vitest related src/a.ts", PNPM)
allows("vitest changed", "pnpm exec vitest run --changed", PNPM)
allows("pnpm filter", "pnpm --filter core test", PNPM)
allows("pnpm filter=", "pnpm --filter=core test", PNPM)
allows("pnpm test on a file", "pnpm test -- src/a.test.ts", PNPM)
allows("pnpm typecheck", "pnpm typecheck", PNPM)
denies("pnpm -C dir is not a subset", "pnpm -C apps/web test", PNPM)
denies("pnpm run with flags", "pnpm run -r test", PNPM)
denies("pnpm filter wildcard", 'pnpm --filter "*" test', PNPM)
allows("pnpm test -- pattern", "pnpm test -- Button", PNPM)
allows("jest --filter is not pnpm's", "npx jest src/a.test.ts --filter x", PNPM)
denies("jest --filter alone is full", "npx jest --filter=./f.js", os.path.join(QUEUED, "web"))
unit = repo(LEFTHOOK.replace("suite-queue js npm test -- --coverage --maxWorkers=2",
                             "suite-queue js pnpm test:unit"))
allows("a script the matcher can't run is not queued", "npm test", os.path.join(unit, "web"))
denies("pnpm push bypass", "LEFTHOOK_EXCLUDE=test git push", PNPM)

print("a public checkout denies the push bypass even with no queued suites")


def git_repo(path, *args):
    subprocess.run(["git", "-C", path, *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "n", "GIT_COMMITTER_NAME": "n",
                        "GIT_AUTHOR_EMAIL": "n@example.com", "GIT_COMMITTER_EMAIL": "n@example.com"})


FAKE_HOME = tempfile.mkdtemp()
os.makedirs(os.path.join(FAKE_HOME, ".config/ai-workflow"))
PUBLIC = tempfile.mkdtemp()
git_repo(PUBLIC, "init", "-q", "-b", "main")
git_repo(PUBLIC, "commit", "-q", "--allow-empty", "-m", "init")
WORKTREE = os.path.join(tempfile.mkdtemp(), "wt")
git_repo(PUBLIC, "worktree", "add", "-q", "-b", "feat", WORKTREE)
PLAIN = tempfile.mkdtemp()
git_repo(PLAIN, "init", "-q", "-b", "main")
with open(os.path.join(FAKE_HOME, ".config/ai-workflow/public-repo"), "w") as f:
    f.write(PUBLIC + "\n")
PUBLIC_ENV = {**os.environ, "HOME": FAKE_HOME}


def public_denies(name, command, cwd):
    p = run(command, cwd, PUBLIC_ENV)
    d = decision(p)
    check(name, d is not None and d.get("permissionDecision") == "deny"
          and "public" in d.get("permissionDecisionReason", ""), f"stdout={p.stdout!r}")


def public_allows(name, command, cwd):
    p = run(command, cwd, PUBLIC_ENV)
    check(name, p.returncode == 0 and not p.stdout.strip(), f"stdout={p.stdout!r}")


public_denies("--no-verify", "git push --no-verify", PUBLIC)
public_denies("LEFTHOOK=0", "LEFTHOOK=0 git push origin main", PUBLIC)
public_denies("LEFTHOOK_EXCLUDE", "LEFTHOOK_EXCLUDE=public-guard git push", PUBLIC)
public_denies("hooksPath", "git -c core.hooksPath=/dev/null push", PUBLIC)
public_denies("exported LEFTHOOK", "export LEFTHOOK=0; git push", PUBLIC)
public_denies("a worktree of the public clone", "git push --no-verify", WORKTREE)
public_denies("git -C into the public clone", f"git -C {PUBLIC} push --no-verify", PLAIN)
public_denies("cd into the public clone", f"cd {PUBLIC} && git push --no-verify", PLAIN)
public_denies("--no-pager before push", "git --no-pager push --no-verify", PUBLIC)
public_denies("-P before push", "git -P push --no-verify", PUBLIC)
public_denies("-C then --no-pager", f"git -C {PUBLIC} --no-pager push --no-verify", PLAIN)
public_denies("glued -c", "git -ccore.hooksPath=/dev/null push", PUBLIC)
public_denies("glued -C", f"git -C{PUBLIC} push --no-verify", PLAIN)
public_denies("--git-dir=", f"git --git-dir={PUBLIC}/.git push --no-verify", PLAIN)
public_denies("--git-dir value", f"git --git-dir {PUBLIC}/.git push --no-verify", PLAIN)
public_denies("--work-tree=", f"git --work-tree={PUBLIC} push --no-verify", PLAIN)
public_denies("git by absolute path", "/usr/bin/git push --no-verify", PUBLIC)
public_denies("absolute git with options", "/usr/bin/git --no-pager -c a=b push --no-verify", PUBLIC)
for var in ("HOME=/tmp/x", "PATH=/tmp/x", "GIT_CONFIG_GLOBAL=/tmp/x", "GIT_CONFIG_COUNT=1",
            "GIT_CONFIG_KEY_0=core.hooksPath", "LEFTHOOK_VERBOSE=1", "LEFTHOOK_CONFIG=/tmp/x"):
    public_denies(f"inline {var.split('=')[0]}", f"{var} git push origin main", PUBLIC)
    public_denies(f"exported {var.split('=')[0]}", f"export {var}; git push origin main", PUBLIC)
public_denies("env tampering on an absolute git with options", "HOME=/tmp/x /usr/bin/git -P push", PUBLIC)
public_denies("any env prefix on a push is denied (deny by default)", "FOO=1 git push origin main", PUBLIC)
public_allows("env tampering outside a public checkout", "HOME=/tmp/x git push origin main", PLAIN)
public_denies("an option before push is denied (deny by default)", "git --no-pager push origin main", PUBLIC)

print("deny by default: in a public checkout only a plain `git push` passes")
for name, cmd, cwd in (
        ("alias", "git -c alias.p=push p --no-verify", PUBLIC),
        ("alias with hooksPath", "git -c alias.p=push -c core.hooksPath=/x p", PUBLIC),
        ("--config-env", "git --config-env=core.hooksPath=HOME push", PUBLIC),
        ("env wrapper", "env LEFTHOOK=0 git push", PUBLIC),
        ("env wrapper, plain push", "env git push", PUBLIC),
        ("command wrapper", "command git push --no-verify", PUBLIC),
        ("command wrapper, plain push", "command git push", PUBLIC),
        ("exec", "exec git push", PUBLIC),
        ("eval", "eval git push", PUBLIC),
        ("eval string", "eval 'git push --no-verify'", PUBLIC),
        ("xargs", "echo origin | xargs git push", PUBLIC),
        ("nohup", "nohup git push", PUBLIC),
        ("time", "time git push", PUBLIC),
        ("bash -c", "bash -c 'git push --no-verify'", PUBLIC),
        ("bash -c plain push", "bash -c 'git push'", PUBLIC),
        ("sh -c", "sh -c 'git push'", PUBLIC),
        ("zsh -c", "zsh -c 'git push'", PUBLIC),
        ("behind a pipe", "echo x | git push", PUBLIC),
        ("-C", "git -C . push", PUBLIC),
        ("--git-dir", "git --git-dir=x push", PUBLIC),
        ("--force is not on the list", "git push --force", PUBLIC),
        ("export before", "export FOO=1; git push", PUBLIC),
        ("bare assignment before", "FOO=1; git push", PUBLIC),
        ("XDG_CONFIG_HOME", "XDG_CONFIG_HOME=/tmp/x git push", PUBLIC),
        ("git config persists hooksPath", "git config core.hooksPath /dev/null", PUBLIC),
        ("git config alias to push", "git config alias.p push", PUBLIC),
        ("newline separated", "git status\ngit push --no-verify", PUBLIC),
        ("pushd +N", "pushd +1 && git push --no-verify", PLAIN),
        ("cd with a variable", "D=x; cd $D && git push --no-verify", PLAIN),
        ("cd -", "cd - && git push --no-verify", PLAIN),
        ("CDPATH inline", "CDPATH=/x cd y; git push --no-verify", PLAIN),
        ("CDPATH exported", "export CDPATH=/x; cd y; git push --no-verify", PLAIN),
        ("GIT_DIR inline", f"GIT_DIR={PUBLIC}/.git git push --no-verify", PLAIN),
        ("GIT_WORK_TREE inline", f"GIT_WORK_TREE={PUBLIC} git push --no-verify", PLAIN),
        ("GIT_DIR exported", f"export GIT_DIR={PUBLIC}/.git; git push", PLAIN),
        ("GIT_DIR behind env", f"env GIT_DIR={PUBLIC}/.git git push", PLAIN),
        ("-C public with an alias", f"git -C {PUBLIC} -c alias.p=push p --no-verify", PLAIN),
        ("cd var, bash -c", "cd $D && bash -c 'git push'", PLAIN)):
    public_denies(name, cmd, cwd)
for name, cmd, cwd in (
        ("plain", "git push", PUBLIC),
        ("remote and branch", "git push origin main", PUBLIC),
        ("-u", "git push -u origin feat", PUBLIC),
        ("--set-upstream", "git push --set-upstream origin feat", PUBLIC),
        ("--tags", "git push --tags", PUBLIC),
        ("--follow-tags", "git push --follow-tags", PUBLIC),
        ("--force-with-lease", "git push --force-with-lease", PUBLIC),
        ("--force-with-lease=", "git push --force-with-lease=main:abc123 origin main", PUBLIC),
        ("--dry-run", "git push --dry-run", PUBLIC),
        ("-v", "git push -v origin main", PUBLIC),
        ("git by absolute path", "/usr/bin/git push origin main", PUBLIC),
        ("after other commands", "git status && git push", PUBLIC),
        ("redirected output", "git push origin main 2>&1", PUBLIC),
        ("piped output", "git push origin main | tail -1", PUBLIC),
        ("a cd into the public clone", f"cd {PUBLIC} && git push origin main", PLAIN),
        ("pushd into the public clone", f"pushd {PUBLIC} && git push origin main", PLAIN),
        ("an unresolvable cwd with a plain push", "cd $D && git push origin main", PLAIN),
        ("the word in a commit message", "git commit -m 'push notes'", PUBLIC),
        ("a refspec", "git push origin HEAD:refs/heads/feat", PUBLIC)):
    public_allows(name, cmd, cwd)
public_allows("a push outside any public checkout keeps the old behaviour",
              "env FOO=1 git push --no-verify", PLAIN)
denies("--no-pager before a --no-verify push in a queued repo", "git --no-pager push --no-verify",
       QUEUED, "suite-queue")
denies("absolute git in a queued repo", "/usr/bin/git -C . push --no-verify", QUEUED)
public_allows("a normal push", "git push origin main", PUBLIC)
public_allows("a non-public repo is unchanged", "git push --no-verify", PLAIN)

print("re-audit #2: ANSI-C quoting, plumbing pushes, a push naming the public URL")
public_denies("$'…' hides hooksPath and push",
              "git -c core.hooks$'P'ath=/dev/null $'push'", PUBLIC)
public_denies("$\"…\" hides push and --no-verify", "git $\"push\" --no-ver$'i'fy", PUBLIC)
public_denies("send-pack pushes without the hook",
              "git send-pack git@github.com:nicoluraschi/ai-dev-workflow.git HEAD:refs/heads/x",
              PUBLIC)
public_denies("http-push", "git http-push https://example.com/r.git main", PUBLIC)
for url in ("git@github.com:nicoluraschi/ai-dev-workflow.git",
            "https://github.com/nicoluraschi/ai-dev-workflow"):
    public_denies(f"--no-verify to the public URL from a private repo ({url[:15]})",
                  f"git push --no-verify {url} HEAD:refs/heads/x", PLAIN)
print("re-audit #3: a push naming the public repo from anywhere but its checkout")
for url in ("git@github.com:nicoluraschi/ai-dev-workflow.git",
            "ssh://github.com/nicoluraschi/ai-dev-workflow", "https://www.github.com/nicoluraschi/ai-dev-workflow",
            "--repo=ssh://git@github.com:22/nicoluraschi/ai-dev-workflow.git"):
    public_denies(f"plain push to {url[:22]}… from a private repo",
                  f"git push {url} HEAD:refs/heads/x", PLAIN)
public_denies("cd from the public checkout into a private one, then push to it",
              f"cd {PLAIN} && git push git@github.com:nicoluraschi/ai-dev-workflow.git main", PUBLIC)
print("re-audit #4: a cd that may not take effect leaves the cwd unknown")
URL = "git@github.com:nicoluraschi/ai-dev-workflow.git"
for pre in (f"(cd {PUBLIC}); ", f"cd {PUBLIC} | true; ", f"cd {PUBLIC} & ",
            f"false && cd {PUBLIC}; ", f"true || cd {PUBLIC}; "):
    public_denies(f"`{pre.replace(PUBLIC, 'pub').strip()}` then a push to the public URL",
                  f"{pre}git push {URL} HEAD:refs/heads/x", PLAIN)
public_denies("a subshell cd out of the public checkout then --no-verify",
              f"(cd {PLAIN}); git push --no-verify", PUBLIC)
print("re-audit #5: a wrapped cd out of the public checkout leaves the cwd unknown")
for pre in (f"{{ cd {PLAIN}; }} && ", f"builtin cd {PLAIN} && ", f"command cd {PLAIN} && ",
            f"time cd {PLAIN} && ", f"chdir {PLAIN} && "):
    public_denies(f"`{pre.replace(PLAIN, 'other').strip()}` then a push to the public URL",
                  f"{pre}git push {URL} HEAD:refs/heads/x", PUBLIC)
print("re-audit #7: a computed command name may be a cd")
for pre in (f"$'cd' {PUBLIC} && ", f"`echo cd` {PUBLIC} && ", f"$'\\x63d' {PUBLIC} && ",
            f'C=cd; "$C" {PUBLIC} && '):
    public_denies(f"`{pre.replace(PUBLIC, 'pub').strip()}` then --no-verify",
                  f"{pre}git push --no-verify", PLAIN)
public_allows("cd into the public checkout chained with && then a plain push",
              f"cd {PUBLIC} && git push {URL} main", PLAIN)
public_allows("a plain push to the public repo from its own checkout",
              "git push git@github.com:nicoluraschi/ai-dev-workflow.git main", PUBLIC)
no_config = {**os.environ, "HOME": tempfile.mkdtemp()}
p = run("git push --no-verify", PUBLIC, no_config)
check("no config and no origin: nothing is public", p.returncode == 0 and not p.stdout.strip(),
      p.stdout)

print("fails open")
p = subprocess.run([sys.executable, HOOK], input="not json", text=True, capture_output=True)
check("bad payload", p.returncode == 0 and not p.stdout.strip(), p.stdout)
allows("unparseable shell", "npx jest 'unterminated", os.path.join(QUEUED, "web"))
allows("cwd that does not exist", "npx jest", "/nonexistent/dir")

print()
if FAILED:
    print(f"{len(FAILED)} failed")
    sys.exit(1)
print("all passed")
