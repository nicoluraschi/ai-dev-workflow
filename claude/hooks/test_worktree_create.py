#!/usr/bin/env python3
"""Tests for worktree-create.sh -- the node_modules refresh after the copy.

Run: python3 claude/hooks/test_worktree_create.py

The hook copies node_modules from the main checkout, which is pulled but rarely reinstalled,
so the copy can predate the lockfile. These tests build a real repo whose only dependency is a
local `file:` package, so `npm ci` runs offline. HOME points into the temp dir, so the worktree
lands at worktrees/<repo>/<branch> under that fake home and nothing touches the real ~/worktrees.
"""
import json, os, shutil, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worktree-create.sh")
results = []
# asdf shims resolve through $HOME, which the tests replace; put the real node bin dir first.
# Without asdf (CI), npm on PATH is already the real one.
NPM = (shutil.which("asdf") and subprocess.run(["asdf", "which", "npm"], capture_output=True,
                                               text=True).stdout.strip()) or shutil.which("npm")
NODE_BIN = os.path.dirname(NPM or "/usr/bin/npm")


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  -- " + detail) if detail and not cond else ""))


def env_for(td, path_prefix=None):
    env = dict(os.environ, HOME=os.path.join(td, "home"),
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
               npm_config_cache=os.path.join(td, "npm-cache"))
    env["PATH"] = NODE_BIN + os.pathsep + env["PATH"]
    if path_prefix:
        env["PATH"] = path_prefix + os.pathsep + env["PATH"]
    return env


def repo(td, installed):
    """A main checkout with web/ depending on a local `dep`. `installed` decides whether its
    web/node_modules is current (npm install ran) or stale (a folder without `dep`)."""
    root = os.path.join(td, "repo")
    web = os.path.join(root, "web")
    os.makedirs(os.path.join(web, "dep"))
    with open(os.path.join(web, "dep", "package.json"), "w") as f:
        json.dump({"name": "dep", "version": "1.0.0"}, f)
    with open(os.path.join(web, "package.json"), "w") as f:
        json.dump({"name": "web", "version": "1.0.0", "dependencies": {"dep": "file:./dep"}}, f)
    env = env_for(td)
    subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=web, env=env,
                   capture_output=True, timeout=120, check=True)
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("node_modules/\n")
    g = lambda *a: subprocess.run(["git", "-C", root, *a], env=env, capture_output=True,
                                  timeout=20, check=True)
    g("init", "-q", "-b", "main"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("add", "-A"); g("commit", "-qm", "init")
    nm = os.path.join(web, "node_modules")
    if not installed:
        subprocess.run(["rm", "-rf", nm], check=True)
        os.makedirs(os.path.join(nm, "other"))
    open(os.path.join(nm, "marker.txt"), "w").close()
    return root


def run(td, root, path_prefix=None):
    payload = json.dumps({"hook_event_name": "WorktreeCreate", "cwd": root,
                          "name": "t-x", "branch_name": "t/x"})
    return subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True,
                          env=env_for(td, path_prefix), timeout=180)


def dest(td):
    return os.path.join(td, "home", "worktrees", "repo", "t/x")


def main():
    # 1. a stale copy is reinstalled from the lockfile
    with tempfile.TemporaryDirectory() as td:
        root = repo(td, installed=False)
        p = run(td, root)
        dep = os.path.join(dest(td), "web", "node_modules", "dep")
        check("stale node_modules gets the missing package", os.path.exists(dep),
              f"rc={p.returncode} err={p.stderr[-300:]}")

    # 2. a current copy is left alone
    with tempfile.TemporaryDirectory() as td:
        root = repo(td, installed=True)
        p = run(td, root)
        marker = os.path.join(dest(td), "web", "node_modules", "marker.txt")
        check("current node_modules is not reinstalled", os.path.exists(marker),
              f"rc={p.returncode} err={p.stderr[-300:]}")

    # 3. a failing npm never breaks creation: path on stdout, exit 0
    with tempfile.TemporaryDirectory() as td:
        root = repo(td, installed=False)
        fake = os.path.join(td, "fakebin"); os.makedirs(fake)
        with open(os.path.join(fake, "npm"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(fake, "npm"), 0o755)
        p = run(td, root, path_prefix=fake)
        check("failed npm ci still prints the path and exits 0",
              p.returncode == 0 and p.stdout.strip() == dest(td),
              f"rc={p.returncode} out={p.stdout!r} err={p.stderr[-300:]}")

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
