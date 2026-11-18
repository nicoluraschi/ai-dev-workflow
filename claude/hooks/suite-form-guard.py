#!/usr/bin/env python3
"""PreToolUse guard: in a repo whose lefthook pre-push queues a suite through `suite-queue`,
run that suite only in the form the push can skip.

suite-queue skips the push's suite when the same argv already passed on the same content
(docs/design/2026-10-suite-queue-verified-skip.md). Agents ran suites in forms the pre-push
skip could not match, so pushes re-ran them and invited hook bypasses.

Denies, per shell segment of a Bash command:
- a full RSpec/Jest/Vitest run (npm or pnpm) of a queued suite: no file, pattern or subset flag;
- `git push` with `LEFTHOOK_EXCLUDE`, `LEFTHOOK=0`, `--no-verify` or `-c core.hooksPath=`, in a
  repo that queues suites and in any checkout of the public repo (public_checkout.py), where
  that hook is the privacy guard.
Subsets stay allowed: they are the review-round evidence `verification-before-completion`
asks for. The human can still bypass with `! git push --no-verify`; this sees only Claude's
Bash calls.

Fails open: any payload, shell or file it cannot read means no decision.
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_checkout  # noqa: E402

LEFTHOOK_FILES = ("lefthook.yml", ".lefthook.yml", "lefthook.yaml", ".lefthook.yaml")
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&"}
# Flags that run less than the whole suite, or (--listTests) nothing at all.
SUBSET_FLAGS = {"-o", "--onlyChanged", "--onlyFailures", "-f", "--lastCommit", "--listTests",
                "--only-failures", "--next-failure", "--changed"}
SUBSET_PREFIXES = ("--changedSince", "--changed=")
PNPM_VALUE_FLAGS = {"--filter", "-F", "-C", "--dir"}
# Arguments that name the whole suite rather than a subset of it.
WHOLE_SUITE = {".", "spec", "test"}
# LEFTHOOK_OUTPUT restores the runner's output where lefthook.yml sets `output: [failure]`, which
# prints nothing for a green job: no summary to show, and none for no-commit-on-red to read.
FORM = ("SUITE_QUEUE_FORCE=1 LEFTHOOK_OUTPUT=summary,success,execution,execution_out "
        "lefthook run pre-push --force --no-tty --command {name}")


def allow():
    sys.exit(0)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def queued_suites(cwd):
    """{family: lefthook command name} for pre-push commands run through suite-queue."""
    d = os.path.abspath(cwd)
    while True:
        for name in LEFTHOOK_FILES:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return parse_lefthook(path)
        if os.path.exists(os.path.join(d, ".git")) or os.path.dirname(d) == d:
            return {}
        d = os.path.dirname(d)


def queued_family(run_line):
    """The runner family a `run:` line queues, by the same matcher agents' commands go through."""
    m = re.search(r"suite-queue\s+\w+\s+(.*)", run_line)
    try:
        return runner(split_env(shlex.split(m.group(1).split(";")[0]))[1])[0] if m else None
    except ValueError:
        return None


def parse_lefthook(path):
    # A line scan, not YAML: no dependency, and only `pre-push.commands.<name>.run` matters.
    suites, in_pre_push, commands_indent, name_indent, name = {}, False, None, None, None
    with open(path) as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                in_pre_push = line.startswith("pre-push:")
                commands_indent = name_indent = name = None
                continue
            if not in_pre_push:
                continue
            key = line.strip().split(":", 1)[0]
            if commands_indent is None:
                if key == "commands":
                    commands_indent = indent
                continue
            if indent <= commands_indent:
                commands_indent = name_indent = name = None
                continue
            if name_indent is None or indent == name_indent:
                name_indent, name = indent, key
                continue
            if key == "run" and name:
                fam = queued_family(line)
                if fam:
                    suites.setdefault(fam, name)
    return suites


def segments(command):
    """(tokens, separator before it) per shell segment; an unquoted newline separates too."""
    lexer = shlex.shlex(public_checkout.newlines_to_semicolons(command), posix=True,
                        punctuation_chars=True)
    lexer.whitespace_split = True
    seg, sep = [], None
    for tok in lexer:
        if tok in SEPARATORS:
            if seg:
                yield seg, sep
            seg, sep = [], tok
        else:
            seg.append(tok)
    if seg:
        yield seg, sep


def separators(command):
    """Every shell separator in the command, parentheses included."""
    lexer = shlex.shlex(public_checkout.newlines_to_semicolons(command), posix=True,
                        punctuation_chars=True)
    lexer.whitespace_split = True
    return {tok for tok in lexer if tok in SEPARATORS}


def split_env(seg):
    env = {}
    while seg and re.match(r"^[A-Za-z_]\w*=", seg[0]):
        k, v = seg[0].split("=", 1)
        env[k] = v
        seg = seg[1:]
    return env, seg


def drop_redirects(seg):
    out, skip = [], False
    for tok in seg:
        if skip:
            skip = False
        elif set(tok) <= set("<>&") and ("<" in tok or ">" in tok):
            if out and out[-1].isdigit():
                out.pop()  # the fd in `2>&1`
            skip = True
        else:
            out.append(tok)
    return out


def runner(seg):
    """(family, args) when the segment invokes a test runner, else (None, None).
    args is None for a run already known to be a subset (a pnpm --filter)."""
    if seg[:2] == ["npx", "jest"]:
        return "js", seg[2:]
    if seg[:1] == ["jest"]:
        return "js", seg[1:]
    if seg[:2] == ["npx", "vitest"]:
        return "js", vitest_args(seg[2:])
    if seg[:1] == ["vitest"]:
        return "js", vitest_args(seg[1:])
    if seg[:1] == ["pnpm"]:
        return pnpm(seg[1:])
    if seg[:2] == ["npm", "test"] or seg[:3] == ["npm", "run", "test"]:
        rest = seg[2:] if seg[1] == "test" else seg[3:]
        return "js", rest[rest.index("--") + 1:] if "--" in rest else []
    if seg[:3] == ["bundle", "exec", "rspec"]:
        return "ruby", seg[3:]
    if seg[:1] in (["rspec"], ["bin/rspec"]):
        return "ruby", seg[1:]
    return None, None


def vitest_args(args):
    # `run`/`watch` pick a mode, not tests; `related <files>` stays, as a subset.
    return args[1:] if args[:1] in (["run"], ["watch"]) else args


def pnpm_flags(rest):
    """Skip pnpm's own flags; True when a --filter picks packages (a wildcard picks all)."""
    filtered = False
    while rest and rest[0].startswith("-") and rest[0] != "--":
        flag, n = rest[0], 1
        if "=" in flag:
            flag, value = flag.split("=", 1)
        elif flag in PNPM_VALUE_FLAGS:
            value, n = (rest[1] if len(rest) > 1 else ""), 2
        else:
            value = ""
        if flag in ("--filter", "-F") and value and "*" not in value:
            filtered = True
        rest = rest[n:]
    return rest, filtered


def pnpm(rest):
    rest, filtered = pnpm_flags(rest)
    if rest[:1] == ["run"]:
        rest, more = pnpm_flags(rest[1:])
        filtered = filtered or more
        if rest[:1] != ["test"]:
            return None, None
    if rest[:1] == ["test"]:
        args = rest[1:]
    elif rest[:1] == ["vitest"]:
        args = vitest_args(rest[1:])
    elif rest[:2] == ["exec", "vitest"]:
        args = vitest_args(rest[2:])
    else:
        return None, None
    if args[:1] == ["--"]:
        args = args[1:]
    return "js", None if filtered else args


def is_full(args):
    prev = None
    for tok in args:
        if tok in SUBSET_FLAGS or tok.startswith(SUBSET_PREFIXES):
            return False
        if not tok.startswith("-") and tok.rstrip("/") not in WHOLE_SUITE:
            value_of_flag = prev is not None and prev.startswith("-") and "=" not in prev
            if not value_of_flag or "/" in tok or "." in tok:
                return False
        prev = tok
    return True


GIT_VALUE_OPTIONS = ("--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix",
                     "--config-env")


def git_push(seg, cwd, exported):
    """(repo dir, hook disabled, env) when the segment is a `git push` (git by any path, any
    leading git options), else None."""
    inline, seg = split_env(seg)
    env = {**exported, **inline}
    if not seg or os.path.basename(seg[0]) != "git":
        return None
    rest, d, configs = seg[1:], cwd, []
    while rest and rest[0].startswith("-") and rest[0] != "--":
        opt = rest[0]
        if opt in ("-C", "-c") or opt in GIT_VALUE_OPTIONS:
            value, step = (rest[1] if len(rest) > 1 else ""), 2
        elif opt[:2] in ("-C", "-c") and len(opt) > 2:
            opt, value, step = opt[:2], opt[2:], 1
        elif opt.split("=", 1)[0] in GIT_VALUE_OPTIONS:
            opt, value, step = opt.split("=", 1)[0], opt.split("=", 1)[1], 1
        else:
            opt, value, step = None, "", 1  # --no-pager, -p, -P, --bare, ...
        if opt == "-C":
            d = os.path.join(d, value)
        elif opt == "-c":
            configs.append(value)
        elif opt in ("--git-dir", "--work-tree"):
            d = os.path.join(cwd, value)
        rest = rest[step:]
    if rest[:1] != ["push"]:
        return None
    disabled = ("LEFTHOOK_EXCLUDE" in env or env.get("LEFTHOOK") in ("0", "false")
                or "--no-verify" in rest
                or any(c.lower().startswith("core.hookspath=") for c in configs))
    return d, disabled, env


# --- the public checkout: deny by default ---------------------------------------------------------
# Enumerating the ways to switch the pre-push guard off never ends (aliases, wrappers, env,
# --config-env, XDG_CONFIG_HOME, a cd the hook cannot follow...). In a public checkout, or when
# the command's repo cannot be told, anything that mentions a push is denied unless it is exactly
# a plain `git push`.
SHELL_HEADS = {"bash", "sh", "zsh", "dash", "ksh", "eval"}
CD_COMMANDS = public_checkout.CD_COMMANDS
PUSH_MARKERS = ("--no-verify", "hookspath", "lefthook", "--config-env", "xdg_config_home",
                "send-pack", "http-push", "receive-pack")
PLAIN_PUSH_FLAGS = {"-u", "--set-upstream", "--tags", "--follow-tags", "--force-with-lease",
                    "--dry-run", "-v"}


def mentions_push(tokens):
    """The word `push` as a token, or a marker of switching the hook off, anywhere in the segment
    (inside a `bash -c` / `eval` string or an alias definition too)."""
    rest = split_env(tokens)[1]
    head = os.path.basename(rest[0]) if rest else ""
    words = []
    for tok in tokens:
        words.append(tok)
        if head in SHELL_HEADS or tok.lower().startswith("alias.") or \
                re.match(r"^[A-Za-z_]\w*=.*\s", tok):
            words += re.split(r"[\s=;&|()!]+", tok)
    if rest and rest[0][:1] in ("$", "`"):
        return True  # the command itself is a variable or a substitution
    # shlex reads bash's $'…' and $"…" as a literal `$`: `$'push'` arrives as `$push`.
    words = [w.replace("$", "") for w in words]
    return any(w == "push" or any(m in w.lower() for m in PUSH_MARKERS) for w in words)


def candidate_dirs(tokens, cwd, env):
    """(directories the segment may act on, whether one of them is unknowable)."""
    dirs, unknown, i = [cwd], False, 0
    values = [env[k] for k in ("GIT_DIR", "GIT_WORK_TREE") if env.get(k)]
    while i < len(tokens):
        tok, nxt = tokens[i], (tokens[i + 1] if i + 1 < len(tokens) else "")
        if tok in ("-C", "--git-dir", "--work-tree"):
            values.append(nxt)
        elif tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
            values.append(tok.split("=", 1)[1])
        elif tok.startswith("-C") and len(tok) > 2 and not tok.startswith("--"):
            values.append(tok[2:])
        else:
            m = re.match(r"^GIT_(?:DIR|WORK_TREE)=(.*)$", tok)
            if m:
                values.append(m.group(1))
        i += 1
    for v in values:
        if "$" in v or "`" in v:
            unknown = True
        dirs.append(os.path.join(cwd, os.path.expanduser(v)))
    return dirs, unknown


def is_plain_push(tokens, sep, any_env):
    """Exactly `git [path/]git push [remote] [refspec] [-u|--set-upstream|--tags|--follow-tags|
    --force-with-lease[=…]|--dry-run|-v]`, not behind a pipe, with no env prefix or export anywhere
    in the command, no git option, no wrapper and no alias."""
    if any_env or sep in ("|", "|&"):
        return False
    if len(tokens) < 2 or os.path.basename(tokens[0]) != "git" or tokens[1] != "push":
        return False
    return all(not a.startswith("-") or a in PLAIN_PUSH_FLAGS or a.startswith("--force-with-lease=")
               for a in tokens[2:])


def main():
    try:
        data = json.load(sys.stdin)
        cwd = data.get("cwd") or os.getcwd()
        command = data["tool_input"]["command"]
        pieces = list(segments(command))
    except Exception:
        allow()

    any_env = any(split_env(tokens)[0] or tokens[:1] == ["export"] for tokens, _ in pieces)
    exported = {}
    cwd_unresolved = public_checkout.cd_untrusted(
        [t for t, _ in pieces], [(split_env(drop_redirects(t))[1] or [""])[0] for t, _ in pieces],
        separators(command))
    for tokens, sep in pieces:
        seg = drop_redirects(tokens)
        inline, bare = split_env(seg)
        env = {**exported, **inline}
        if mentions_push(seg):
            dirs, unknown = candidate_dirs(seg, cwd, env)
            in_public = any(public_checkout.is_public(d) for d in dirs)
            # git runs the hook of the repo pushed FROM: a push to the public repo from any other
            # checkout skips its guard. A substring, so no URL spelling or alias form escapes.
            repo_name = public_checkout.PUBLIC_REPO.split("/")[1]
            if any(repo_name in t.lower() for t in seg) and \
                    (cwd_unresolved or unknown or not in_public):
                deny("A push naming the public repo from outside its checkout. git runs the "
                     "pre-push hook of the repo pushed from, so the public guard would not run. "
                     "Push from the public checkout itself.")
            if cwd_unresolved or unknown or in_public:
                if not is_plain_push(seg, sep, any_env):
                    deny("Push (or a way to switch the pre-push hook off) in a public checkout, "
                         "or where the repo cannot be told. There the hook is the privacy guard "
                         "(gitleaks, the scanner, the denylist), so the only push the agent runs "
                         "is a plain `git push [remote] [refspec] [-u|--tags|--follow-tags|"
                         "--force-with-lease|--dry-run|-v]` as its own command: no env, export, "
                         "git option, alias, wrapper or pipe. If the human wants more, they run "
                         "it themselves.")
                continue
        if bare[:1] and bare[0] in CD_COMMANDS:
            target = public_checkout.cd_target(bare[0], bare[1:])
            if target is None or "CDPATH" in env:
                cwd_unresolved = True
            else:
                cwd = os.path.join(cwd, os.path.expanduser(target))
            continue
        if bare[:1] == ["export"]:
            exported.update(split_env(bare[1:])[0])
            if "CDPATH" in exported:
                cwd_unresolved = True
            continue
        if not bare:  # a bare assignment (`D=x;`) sets shell variables for later segments
            exported.update(inline)
            if "CDPATH" in inline:
                cwd_unresolved = True
            continue
        push = git_push(seg, cwd, exported)
        repo = push[0] if push else None
        if push and push[1] and queued_suites(repo):
            deny("Push with the pre-push hook enabled. suite-queue skips a suite that already "
                 "passed on this exact content, so a Verify run in the lefthook form makes the "
                 "push cheap; disabling the hook (LEFTHOOK_EXCLUDE, LEFTHOOK=0, --no-verify) "
                 "pushes untested. If the human wants it, they run `! git push --no-verify`.")
        fam, args = runner(split_env(seg)[1])
        if fam and args is not None and is_full(args):
            name = queued_suites(cwd).get(fam)
            if name:
                deny(f"This repo's pre-push runs `{name}` through suite-queue, which only "
                     "skips the push's run when the same command already passed on the same "
                     f"content. Run the full suite as `{FORM.format(name=name)}` from the repo "
                     "root, and read coverage from the files that run writes. Subsets "
                     "(files, patterns, --findRelatedTests, pnpm --filter) run directly.")
    allow()


if __name__ == "__main__":
    main()
