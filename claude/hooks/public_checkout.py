"""Shared by public-text-guard.py and suite-form-guard.py: is a directory a public checkout?

A checkout is public when its resolved `git rev-parse --git-common-dir` equals that of the path
in $HOME/.config/ai-workflow/public-repo (so every worktree of the clone counts), or when its
normalized `origin` is the public repo. The config lives outside any tree, so nothing inside a
repo can switch a guard off. No file and no matching origin means nothing is public.

A gh command also counts as public-bound when any argument names the public repo (-R/--repo, a
URL, an API path) or GH_REPO does. Stdlib only; every function answers "not public" on any error.
"""
import os
import re
import subprocess

PUBLIC_REPO = "nicoluraschi/ai-dev-workflow"
REMOTE = re.compile(r"^(?:https?://(?:[^@/]+@)?|ssh://git@|git@)github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
                    re.I)


def config_dir():
    return os.path.join(os.path.expanduser("~"), ".config", "ai-workflow")


def normalize_remote(url):
    """'owner/repo' (lowercase) for a github.com ssh, scp or https remote, else None."""
    m = REMOTE.match((url or "").strip())
    return f"{m.group(1)}/{m.group(2)}".lower() if m else None


def _git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _common_dir(path):
    out = _git(path, "rev-parse", "--git-common-dir")
    return os.path.realpath(os.path.join(path, out)) if out else None


def configured_path():
    try:
        with open(os.path.join(config_dir(), "public-repo")) as f:
            return f.readline().strip() or None
    except OSError:
        return None


def remote_repos(cwd):
    """Normalized owner/repo of every remote's fetch and push URL, whatever the remote is named."""
    out = _git(cwd, "config", "--get-regexp", r"^remote\..*\.(pushurl|url)$") or ""
    return {normalize_remote(line.split(None, 1)[1]) for line in out.splitlines()
            if len(line.split(None, 1)) == 2} - {None}


def is_public(cwd):
    try:
        mine = _common_dir(cwd)
        if not mine:
            return False
        path = configured_path()
        if path and _common_dir(path) == mine:
            return True
        return PUBLIC_REPO in remote_repos(cwd)
    except Exception:
        return False


def public_root(cwd):
    """Where to run the public repo's own scripts: the configured clone first (a worktree on an
    outsider's branch may carry a modified script), else the toplevel of an origin-matched
    checkout. None when nothing is public."""
    path = configured_path()
    if path and _git(path, "rev-parse", "--git-common-dir") is not None and is_public(cwd):
        return _git(path, "rev-parse", "--show-toplevel")
    if is_public(cwd):
        return _git(cwd, "rev-parse", "--show-toplevel")
    return None


def newlines_to_semicolons(command):
    """Unquoted newlines separate commands; shlex would read them as plain whitespace."""
    out, quote, esc = [], None, False
    for ch in command:
        if esc:
            esc = False
        elif ch == "\\" and quote != "'":
            esc = True
        elif quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = " ; "
        out.append(ch)
    return "".join(out)


CD_COMMANDS = ("cd", "pushd", "popd", "chdir")  # chdir: zsh, which the Bash tool runs in


def cd_untrusted(token_lists, heads, seps):
    """True when a cd may not take effect as written: one that is not its segment's head
    (`{ cd x; }`, `builtin cd`, `time cd`), or any cd in a command that is not a pure `&&` chain
    (a subshell, a pipe, the background, `;` or `||` can run the next command without it).
    A computed command name (`$'cd'`, `` `echo cd` ``, `"$C"`) may be a cd too."""
    if any("$" in head or "`" in head for head in heads):
        return True
    all_cds = sum(tok in CD_COMMANDS for tokens in token_lists for tok in tokens)
    head_cds = sum(head in CD_COMMANDS for head in heads)
    return all_cds > head_cds or (all_cds > 0 and bool(set(seps) - {"&&"}))


def cd_target(head, args):
    """The directory a cd/pushd/popd moves to, or None when it cannot be known statically: `-`,
    popd, a bare pushd, `pushd +N`/`-N`, `~user`, anything with a substitution or variable."""
    if head == "popd":
        return None
    args = [a for a in args if a == "-" or not a.startswith("-") or re.fullmatch(r"-\d+", a)]
    if not args:
        return None if head == "pushd" else "~"
    target = args[0]
    if target == "-" or "$" in target or "`" in target or re.fullmatch(r"[+-]\d+", target):
        return None
    if target.startswith("~") and target != "~" and not target.startswith("~/"):
        return None
    return target


def repo_flag_names_public(args, env):
    """True when GH_REPO or any gh argument names the public repo."""
    if (env or {}).get("GH_REPO", "").strip().lower().rstrip("/").endswith(PUBLIC_REPO):
        return True
    for tok in args:
        low = tok.lower()
        if re.search(re.escape(PUBLIC_REPO) + r"(?![\w-])", low):
            return True
    return False
