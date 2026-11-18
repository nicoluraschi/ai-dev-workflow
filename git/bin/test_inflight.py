#!/usr/bin/env python3
"""Tests for inflight.

Run: python3 git/bin/test_inflight.py

Each case builds real repos under a temp dir: a bare origin, a main checkout and linked
worktrees under $INFLIGHT_ROOT, the way ~/worktrees is laid out. A fake gh on PATH stands in
for GitHub: `gh search prs` prints $FAKE_GH/search.json, and `gh pr list` prints
$FAKE_GH/<repo>.json, <repo> being the main checkout's directory name. A missing file makes
the fake exit 1, which is how a gh failure for one repo is simulated.

inflight is loaded in-process and main() is called directly, so coverage sees it; git and gh
still run as real subprocesses.
"""
import contextlib, importlib.machinery, importlib.util, io, json, os, subprocess, sys
import tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("inflight", os.path.join(HERE, "inflight"))
spec = importlib.util.spec_from_loader("inflight", loader)
inflight = importlib.util.module_from_spec(spec)
loader.exec_module(inflight)

FAKE_GH = """#!/usr/bin/env python3
import os, subprocess, sys
d = os.environ["FAKE_GH"]
if sys.argv[1:3] == ["search", "prs"]:
    name = "search"
else:
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    name = os.path.basename(os.path.dirname(common))
path = os.path.join(d, name + ".json")
if not os.path.exists(path):
    sys.exit(1)
sys.stdout.write(open(path).read())
"""

results = []
DAY = 86400


def check(label, cond, detail=""):
    results.append(cond)
    print(("  ok   " if cond else "  FAIL ") + label + ("" if cond else f"\n       {detail}"))


def sh(cwd, *args, env=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


class Lab:
    def __init__(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.root = os.path.join(self.tmp, "worktrees")
        self.gh = os.path.join(self.tmp, "gh")
        os.makedirs(self.root)
        os.makedirs(self.gh)
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "gh"), "w") as f:
            f.write(FAKE_GH)
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        os.environ.update({
            "INFLIGHT_ROOT": self.root, "FAKE_GH": self.gh,
            "PATH": bindir + os.pathsep + os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        })
        self.write("search.json", [])

    def repo(self, name):
        origin = os.path.join(self.tmp, name + ".git")
        main = os.path.join(self.tmp, "src", name)
        sh(self.tmp, "git", "init", "-q", "--bare", "-b", "main", origin)
        sh(self.tmp, "git", "clone", "-q", origin, main)
        sh(main, "git", "commit", "-q", "--allow-empty", "-m", "init")
        sh(main, "git", "push", "-q", "origin", "main")
        return main

    def worktree(self, main, branch, age_days=0, push=True, dirty=0, unpushed=0):
        repo = os.path.basename(main)
        path = os.path.join(self.root, repo, branch)
        sh(main, "git", "worktree", "add", "-q", "-b", branch, path)
        env = dict(os.environ, GIT_COMMITTER_DATE=f"@{int(time.time() - age_days * DAY)} +0000")
        sh(path, "git", "commit", "-q", "--allow-empty", "-m", "work", env=env)
        if push:
            sh(path, "git", "push", "-q", "-u", "origin", branch)
        for i in range(unpushed):
            sh(path, "git", "commit", "-q", "--allow-empty", "-m", f"local {i}", env=env)
        for i in range(dirty):
            with open(os.path.join(path, f"dirt{i}.txt"), "w") as f:
                f.write("x")
        return path

    def write(self, name, data):
        with open(os.path.join(self.gh, name), "w") as f:
            json.dump(data, f)

    def run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = inflight.main()
        return code, out.getvalue()


def head(path):
    return sh(path, "git", "rev-parse", "HEAD")


def line_for(out, path):
    rel = path.split("/worktrees/", 1)[1]
    hits = [l for l in out.splitlines() if rel + " " in l]
    return hits[0] if hits else ""


def pr(n, state, branch, sha="0" * 40, repo="o/app", fork=False):
    return {"number": n, "state": state, "headRefName": branch, "headRefOid": sha,
            "isCrossRepository": fork, "url": f"https://github.com/{repo}/pull/{n}"}


def test_merged_pr_is_stale():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "feat/done")
    lab.write("app.json", [pr(5, "MERGED", "feat/done", head(wt))])
    code, out = lab.run()
    line = line_for(out, wt)
    check("merged PR: exit 0", code == 0, f"code={code}")
    check("merged PR: shows merged #5", "merged #5" in line, line)
    check("merged PR: marked STALE", line.startswith("STALE"), line)
    check("merged PR at HEAD: no warning", "check before removing" not in line, line)


def test_commits_after_merge_warn():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "fix/typo")
    merged_at = head(wt)
    sh(wt, "git", "commit", "-q", "--allow-empty", "-m", "reused branch, new work")
    lab.write("app.json", [pr(12, "MERGED", "fix/typo", merged_at)])
    _, out = lab.run()
    line = line_for(out, wt)
    check("commits past the PR head: warned",
          line.startswith("STALE") and "commits not on GitHub" in line, line)


def test_open_pr_not_stale_and_linked():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "feat/live", age_days=30)
    lab.write("app.json", [pr(3, "MERGED", "feat/live"), pr(9, "OPEN", "feat/live")])
    lab.write("search.json", [
        {"number": 9, "title": "feat: live thing", "isDraft": False,
         "repository": {"nameWithOwner": "o/app"}, "updatedAt": "2026-01-01T00:00:00Z",
         "url": "https://github.com/o/app/pull/9"},
        {"number": 4, "title": "feat: elsewhere", "isDraft": True,
         "repository": {"nameWithOwner": "o/other"}, "updatedAt": "2026-01-01T00:00:00Z",
         "url": "https://github.com/o/other/pull/4"},
    ])
    code, out = lab.run()
    line = line_for(out, wt)
    check("open PR: open wins over an older merged one", "open #9" in line, line)
    check("open PR: not STALE even when old", not line.startswith("STALE"), line)
    live = [l for l in out.splitlines() if "o/app#9" in l]
    other = [l for l in out.splitlines() if "o/other#4" in l]
    check("open PR: listed and marked as having a worktree",
          bool(live) and "[worktree]" in live[0], out)
    check("open PR: one without a worktree is listed unmarked, as a draft",
          bool(other) and "[worktree]" not in other[0] and "draft" in other[0], out)


def test_fork_pr_ignored():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "patch-1")
    lab.write("app.json", [pr(30, "MERGED", "patch-1", head(wt), fork=True)])
    _, out = lab.run()
    line = line_for(out, wt)
    check("fork PR with the same branch name: not matched", "no PR" in line, line)


def test_no_pr_age_rule():
    lab = Lab()
    app = lab.repo("app")
    old = lab.worktree(app, "perf/old", age_days=8)
    fresh = lab.worktree(app, "perf/fresh", age_days=6.9)
    local = lab.worktree(app, "perf/local", age_days=10, push=False)
    lab.write("app.json", [])
    _, out = lab.run()
    o, l = line_for(out, old), line_for(out, local)
    check("no PR, 8d old: STALE", o.startswith("STALE"), o)
    check("no PR, pushed: no warning", "check before removing" not in o, o)
    check("no PR, 6.9d old: not STALE", not line_for(out, fresh).startswith("STALE"),
          line_for(out, fresh))
    check("no PR: says no PR", "no PR" in line_for(out, fresh), line_for(out, fresh))
    check("no PR, never pushed: STALE but warned",
          l.startswith("STALE") and "commits not on GitHub" in l, l)


def test_dirty_and_unpushed_counts():
    lab = Lab()
    app = lab.repo("app")
    stale = lab.worktree(app, "fix/messy", dirty=2)
    live = lab.worktree(app, "fix/busy", dirty=3, unpushed=2)
    local = lab.worktree(app, "fix/local", push=False)
    lab.write("app.json", [pr(1, "CLOSED", "fix/messy", head(stale)), pr(2, "OPEN", "fix/busy")])
    _, out = lab.run()
    s, l = line_for(out, stale), line_for(out, live)
    check("dirty: count shown", "3 dirty" in l, l)
    check("unpushed: count shown", "2 unpushed" in l, l)
    check("dirty + stale: flagged to check before removing",
          s.startswith("STALE") and "check before removing: uncommitted files" in s, s)
    check("not stale: no warning", "check before removing" not in l, l)
    check("no upstream: said so", "no upstream" in line_for(out, local), line_for(out, local))


def test_unreadable_status_not_clean():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "fix/broken")
    lab.write("app.json", [pr(8, "MERGED", "fix/broken", head(wt))])
    index = sh(wt, "git", "rev-parse", "--git-path", "index")
    with open(os.path.join(wt, index), "w") as f:
        f.write("not an index")
    _, out = lab.run()
    line = line_for(out, wt)
    check("unreadable status: shown as ? dirty", "? dirty" in line, line)
    check("unreadable status: warned", "check before removing: status unreadable" in line, line)


def test_detached_head_not_matched():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "validation/recon")
    sh(wt, "git", "checkout", "-q", "--detach")
    # An empty head name must not match anything, even a PR with an empty head.
    lab.write("app.json", [pr(46, "MERGED", "")])
    _, out = lab.run()
    line = line_for(out, wt)
    check("detached: shown as detached", "detached" in line, line)
    check("detached: not matched to a PR", "#46" not in line, line)


def test_deep_branch_names_found():
    lab = Lab()
    app = lab.repo("app")
    wt = lab.worktree(app, "dependabot/npm_and_yarn/web/next-16")
    lab.write("app.json", [pr(7, "OPEN", "dependabot/npm_and_yarn/web/next-16")])
    _, out = lab.run()
    check("deep branch: found and matched", "open #7" in line_for(out, wt), out)


def test_gh_failure_isolated():
    lab = Lab()
    ok = lab.repo("ok")
    bad = lab.repo("bad")
    good_wt = lab.worktree(ok, "feat/a")
    bad_wt = lab.worktree(bad, "feat/b", age_days=30)
    lab.write("ok.json", [pr(1, "OPEN", "feat/a", repo="o/ok")])
    os.remove(os.path.join(lab.gh, "search.json"))     # search fails too
    code, out = lab.run()
    b = line_for(out, bad_wt)
    check("gh failure: exit 0", code == 0, f"code={code}")
    check("gh failure: that repo shows pr ?", "pr ?" in b, b)
    check("gh failure: unknown PR is never STALE", not b.startswith("STALE"), b)
    check("gh failure: other repo still matched", "open #1" in line_for(out, good_wt), out)
    check("gh failure: search failure reported", "gh search failed" in out, out)


def test_command_relays_only():
    with open(os.path.join(HERE, "..", "..", "claude", "commands", "inflight.md")) as f:
        text = f.read()
    check("command: allows only the inflight script", "allowed-tools: Bash(inflight)" in text, text)
    check("command: safe to clear means no warning", "check before removing" in text, text)


for name, fn in sorted(globals().items()):
    if name.startswith("test_") and callable(fn):
        fn()

print(f"\n{results.count(True)} passed, {results.count(False)} failed")
sys.exit(0 if all(results) else 1)
