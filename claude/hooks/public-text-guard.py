#!/usr/bin/env python3
"""PreToolUse guard: nothing private reaches GitHub text of the public repo.

Bash, in a public checkout (see public_checkout.py: the clone named in
~/.config/ai-workflow/public-repo, its worktrees, or an origin that is the public repo), or when
-R/--repo, a URL, an API path or GH_REPO names the public repo. Deny by default: a gh call that
is not read-only (view, list, status, diff, checks, `gh api` GET with no body fields) has all its
text (titles, bodies, subjects, descriptions, comments, notes, label and branch names, every
argument, and the files behind --body-file, -F, --notes-file, --input, release assets and gist
files) sent through `scripts/privacy-check --private --stdin` of the configured public clone.
Denied on a hit or a non-zero exit, on a form whose text cannot be resolved ($(...), backticks,
$VAR, heredocs, `-` as a file, `bash -c`, a gh behind a pipe, `;`, `&&`, `||`, a subshell or a
wrapper, a script run from the public checkout that contains gh) and on a gh write it has no
extractor for. Run each gh call on its own, with its text inline or in a file.

Everywhere, public or not: Write/Edit/NotebookEdit, Bash redirections, rm, mv, cp, ln, tee and
touch aimed at ~/.config/ai-workflow/ are denied, and in a public checkout so is writing
lefthook-local.yml (it could switch the pre-push guard off). A backstop for a prompt-injected
model, not a sandbox: the human edits those files by hand.

Everything else is allowed silently. Inside the guarded cases any internal error denies; a payload
this hook cannot read is allowed.
"""
import json
import os
import re
import shlex
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_checkout as pcx  # noqa: E402

SEPARATORS = set(";&|()")
READ_VERBS = {"view", "list", "status", "diff", "checks"}
TEXT_GROUPS = {"pr", "issue", "release", "gist", "label", "discussion"}
TEXT_REPO_VERBS = {"create", "edit", "fork", "rename"}
UPLOAD_GROUPS = {"release", "gist"}
KNOWN_GROUPS = TEXT_GROUPS | {"repo", "run", "workflow", "project", "auth", "cache", "secret",
                              "variable", "ruleset", "codespace", "org", "ssh-key", "gpg-key",
                              "extension", "search", "browse", "config", "alias", "attestation"}
# Flags whose value is text, not a file operand.
TEXT_VALUE_FLAGS = {"-t", "--title", "-n", "--notes", "-d", "--description", "--desc", "-b", "--body",
                    "-m", "--message", "--subject", "-c", "--comment", "-l", "--label",
                    "--add-label", "--remove-label", "-a", "--assignee", "--add-assignee",
                    "--remove-assignee", "-R", "--repo", "--target", "--tag", "--head", "--base",
                    "-B", "-H", "--milestone", "-p", "--project", "-r", "--reviewer",
                    "--notes-start-tag", "--discussion-category", "--filename", "-f", "--homepage"}
FILE_FLAGS = {"--body-file", "-F", "--notes-file", "--input"}
API_BODY_FLAGS = {"-f", "-F", "--field", "--raw-field"}
API_VALUE_FLAGS = {"-H", "--header", "-q", "--jq", "-t", "--template", "--hostname", "--cache",
                   "-p", "--preview"}
WRAPPERS = {"env", "command", "exec", "time", "nohup", "nice", "builtin"}
NON_EXEC_HEADS = {"which", "type", "echo", "printf", "grep", "rg", "man", "brew", "ls", "cat",
                  "head", "tail", "command"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
INTERPRETERS = SHELLS | {"python", "python3", "node", "ruby", "perl"}
CONFIG_WRITERS = {"rm", "mv", "cp", "ln", "tee", "touch"}
GH_WORD = re.compile(r"(?<![\w./-])gh(?![\w-])")
LEFTHOOK_LOCAL = re.compile(r"^\.?lefthook-local\.(ya?ml|json|toml)$")
SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(|<<")
MAX_FILE = 5_000_000
GUARDED = [False]  # set once a guarded case applies; an error after that denies


class Deny(Exception):
    pass


class Unresolvable(Deny):
    def __init__(self, what):
        super().__init__(
            f"public-text-guard: {what}, so its text cannot be resolved and checked. Run this gh "
            "call on its own, with its text inline or in a file passed to --body-file.")


def emit_deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


# --- config dir and lefthook-local ---------------------------------------------------------------

def config_dir():
    return pcx.config_dir()


def protected_roots():
    """The config dir, plus the resolved target of every entry in it: a link there points at the
    real file, and writing the real file changes what the guards trust."""
    base = config_dir()
    roots = {os.path.normpath(base), os.path.realpath(base)}
    try:
        names = os.listdir(base)
    except OSError:
        names = []
    roots |= {os.path.realpath(os.path.join(base, n)) for n in names}
    return roots


def under_config(path):
    cands = {os.path.normpath(path), os.path.realpath(path)}
    return any(c == r or c.startswith(r + os.sep) for c in cands for r in protected_roots())


def expand(token, cwd):
    home = os.path.expanduser("~")
    token = token.replace("${HOME}", home).replace("$HOME", home)
    if "$" in token:
        return None
    return os.path.join(cwd, os.path.expanduser(token))


def existing_parent(path):
    d = os.path.dirname(path)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    return d or "/"


def config_denial(path):
    return (f"public-text-guard: {path} is under {config_dir()}, which holds the trusted "
            "public-repo, denylist and login lists. Edit it by hand (`! ...`), not through the agent.")


def lefthook_local_denial():
    return ("public-text-guard: lefthook-local.yml could switch the public repo's pre-push guard "
            "off; do not write it from the agent.")


def check_edit(ti, cwd):
    path = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(path, str) or not path:
        return
    full = os.path.join(cwd, os.path.expanduser(path))
    if under_config(full):
        raise Deny(config_denial(full))
    if LEFTHOOK_LOCAL.match(os.path.basename(full)) and pcx.is_public(existing_parent(full)):
        raise Deny(lefthook_local_denial())


# --- shell parsing -------------------------------------------------------------------------------

def parse(command):
    """([(tokens, separator before)], set of separators seen)."""
    lexer = shlex.shlex(pcx.newlines_to_semicolons(command), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segs, cur, sep, seen = [], [], None, set()
    for tok in lexer:
        if set(tok) <= SEPARATORS:
            if cur:
                segs.append((cur, sep))
                cur = []
            sep = tok
            seen.add(tok)
        else:
            cur.append(tok)
    if cur:
        segs.append((cur, sep))
    return segs, seen


def split_env(tokens):
    env = {}
    while tokens and re.match(r"^[A-Za-z_]\w*=", tokens[0]):
        k, v = tokens[0].split("=", 1)
        env[k] = v
        tokens = tokens[1:]
    return env, tokens


def split_redirects(tokens):
    """(words, [(operator, target)])."""
    words, redirs, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        if ("<" in tok or ">" in tok) and set(tok) <= set("<>&|"):
            if words and words[-1].isdigit():
                words.pop()  # the fd in `2>file`
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            redirs.append((tok, target))
            i += 2
        else:
            words.append(tok)
            i += 1
    return words, redirs


def strip_wrappers(words):
    while words and os.path.basename(words[0]) in WRAPPERS:
        words = split_env(words[1:])[1]
        while words and words[0].startswith("-") and len(words[0]) > 1 and words[0] not in ("-v", "-V"):
            words = words[1:]
    return words


class Seg:
    def __init__(self, tokens, sep, cwd):
        self.env, rest = split_env(tokens)
        self.words, self.redirs = split_redirects(rest)
        self.sep = sep
        self.cwd = cwd
        self.head_words = strip_wrappers(self.words)
        self.head = os.path.basename(self.head_words[0]) if self.head_words else ""

    @property
    def is_gh(self):
        return self.head == "gh"

    @property
    def wraps_gh(self):
        if self.is_gh or self.head in NON_EXEC_HEADS or self.head == "":
            return False
        if self.head == "-v" or self.head_words[:1] == ["-v"]:
            return False
        return any(os.path.basename(w) == "gh" for w in self.head_words[1:])


CD_COMMANDS = pcx.CD_COMMANDS


def build_segments(command, cwd):
    """(segments, separators seen, final cwd of the prefix, index of the main segment, whether a
    cd/pushd/popd target could not be resolved)."""
    pieces, seen = parse(command)
    segs, main, exported = [], None, {}
    unresolved = pcx.cd_untrusted([t for t, _ in pieces],
                                  [Seg(t, s, cwd).head for t, s in pieces], seen)
    for tokens, sep in pieces:
        seg = Seg(tokens, sep, cwd)
        if seg.head in CD_COMMANDS:
            target = pcx.cd_target(seg.head, seg.head_words[1:])
            if target is None or "CDPATH" in seg.env or "CDPATH" in exported:
                unresolved = True  # CDPATH can send a relative `cd` anywhere
            else:
                cwd = os.path.join(cwd, os.path.expanduser(target))
        elif seg.head == "export":
            exported.update(split_env(seg.words[1:])[0])
        seg.exported = dict(exported)
        segs.append(seg)
        if main is None and seg.head_words and seg.head not in CD_COMMANDS + ("export",):
            main = len(segs) - 1
            seg.cwd = cwd
    return segs, seen, cwd, main, unresolved


# --- Bash: config dir ----------------------------------------------------------------------------

def check_bash_config(segs):
    for seg in segs:
        for op, target in seg.redirs:
            if ">" in op:
                full = expand(target, seg.cwd) if target else None
                if full and under_config(full):
                    raise Deny(config_denial(full))
                if full and LEFTHOOK_LOCAL.match(os.path.basename(full)) \
                        and pcx.is_public(existing_parent(full)):
                    raise Deny(lefthook_local_denial())
        if seg.head in CONFIG_WRITERS:
            for arg in seg.head_words[1:]:
                full = expand(arg, seg.cwd)
                if full and under_config(full):
                    raise Deny(config_denial(full))
                if full and LEFTHOOK_LOCAL.match(os.path.basename(full)) \
                        and pcx.is_public(existing_parent(full)):
                    raise Deny(lefthook_local_denial())


# --- Bash: gh ------------------------------------------------------------------------------------

def read_file(path, cwd):
    if path == "-":
        raise Unresolvable("`-` (stdin) as a file")
    full = os.path.join(cwd, os.path.expanduser(path))
    try:
        st = os.stat(full)
        if not stat.S_ISREG(st.st_mode):  # a FIFO or device would block or never end
            raise Unresolvable(f"the file {path} is not a regular file")
        if st.st_size > MAX_FILE:
            raise Unresolvable(f"the file {path} is too large to check")
        with open(full, "rb") as f:
            data = f.read()
    except OSError:
        raise Unresolvable(f"the file {path} cannot be read")
    try:
        if b"\0" in data:
            raise ValueError
        return data.decode("utf-8")
    except ValueError:
        raise Unresolvable(f"the file {path} is not UTF-8 text")


def positionals(args, limit=2):
    pos, i = [], 0
    while i < len(args) and len(pos) < limit:
        tok = args[i]
        if tok in ("-R", "--repo", "--hostname"):
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        pos.append(tok)
        i += 1
    return pos


def classify_api(args, cwd):
    method, has_body, texts, i = None, False, [], 0
    while i < len(args):
        tok = args[i]
        name, eq, inline = tok.partition("=") if tok.startswith("--") else (tok, "", "")
        value = inline if eq else None
        if not tok.startswith("--") and tok[:2] in API_BODY_FLAGS | {"-X", "-H", "-q", "-t", "-p"} \
                and len(tok) > 2:
            name, value = tok[:2], tok[2:]  # attached short value: -fkey=val
        if name in ("-X", "--method"):
            if value is None:
                value, i = (args[i + 1] if i + 1 < len(args) else ""), i + 1
            method = value
        elif name in API_BODY_FLAGS:
            if value is None:
                value, i = (args[i + 1] if i + 1 < len(args) else ""), i + 1
            has_body = True
            texts.append(value)
            if name in ("-F", "--field") and "=@" in value:
                texts.append(read_file(value.split("=@", 1)[1], cwd))
        elif name == "--input":
            if value is None:
                value, i = (args[i + 1] if i + 1 < len(args) else ""), i + 1
            has_body = True
            texts.append(read_file(value, cwd))
        elif name in API_VALUE_FLAGS and value is None:
            i += 1
        i += 1
    write = has_body or (method is not None and method.upper() != "GET")
    return ("write", texts) if write else ("read", None)


def classify(args, cwd):
    """('read', None) or ('write', [texts]) for the arguments after `gh`."""
    pos = positionals(args)
    if not pos:
        return "read", None  # `gh --version`, `gh --help`
    group, verb = pos[0], pos[1] if len(pos) > 1 else None
    if group == "api":
        return classify_api(args[args.index("api") + 1:], cwd)
    if group in KNOWN_GROUPS and verb in READ_VERBS:
        return "read", None
    # A single word, an unknown group (an alias can stand for anything) and every other write
    # with no text extractor are denied; `alias set|import` land here too.
    if verb is not None and (group in TEXT_GROUPS or (group == "repo" and verb in TEXT_REPO_VERBS)):
        return "write", extract_texts(args, cwd, upload=group in UPLOAD_GROUPS)
    raise Deny(f"public-text-guard: no text extractor for `gh {group}{' ' + verb if verb else ''}`; "
               "it is denied in a public checkout. Run it yourself with `! ...` if it is meant.")


def has_glob(token):
    return any(c in token for c in "*?[")


def extract_texts(args, cwd, upload):
    """Every text a write carries. For release and gist (`upload`), bare operands after the
    group and verb are files: read as text, never a glob, a FIFO or binary."""
    texts, i, bare, prev = [], 0, 0, ""
    while i < len(args):
        tok = args[i]
        value_of_text_flag = prev in TEXT_VALUE_FLAGS
        prev = tok
        if tok == "--editor":
            raise Unresolvable("--editor")
        if tok in FILE_FLAGS:
            path = args[i + 1] if i + 1 < len(args) else ""
            if has_glob(path):
                raise Unresolvable("a glob pattern in a file argument")
            texts.append(read_file(path, cwd))
            prev = ""
            i += 2
            continue
        if tok.startswith("--") and "=" in tok:
            name, value = tok.split("=", 1)
            if name in FILE_FLAGS:
                if has_glob(value):
                    raise Unresolvable("a glob pattern in a file argument")
                texts.append(read_file(value, cwd))
            else:
                texts.append(value)
        elif tok.startswith("-F") and len(tok) > 2 and not tok.startswith("--"):
            if has_glob(tok[2:]):
                raise Unresolvable("a glob pattern in a file argument")
            texts.append(read_file(tok[2:], cwd))
        elif tok.startswith("--") or tok in ("-R",):
            pass
        elif tok.startswith("-") and tok != "-":
            if len(tok) > 2:
                texts.append(tok[2:])
        else:
            if tok == "-":
                raise Unresolvable("`-` (stdin) as a file")
            texts.append(tok)
            if not value_of_text_flag:
                bare += 1
                if bare > 2 and upload:  # past the group and verb: an operand, i.e. a file
                    if has_glob(tok):
                        raise Unresolvable("a glob pattern in a file argument")
                    if os.path.lexists(os.path.join(cwd, tok)):
                        texts.append(read_file(tok, cwd))
                elif not upload and os.path.isfile(os.path.join(cwd, tok)):
                    texts.append(read_file(tok, cwd))
        i += 1
    return texts


def privacy_check(texts, root):
    script = os.path.join(root, "scripts", "privacy-check") if root else None
    if not script or not os.path.isfile(script):
        raise Deny("public-text-guard: scripts/privacy-check was not found in the public checkout, "
                   "so the text cannot be checked.")
    try:
        r = subprocess.run([sys.executable, "-I", script, "--private", "--stdin"], cwd=root,
                           input="\n".join(texts) + "\n", capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError) as e:
        raise Deny(f"public-text-guard: privacy-check could not run ({type(e).__name__}).")
    if r.returncode != 0:
        detail = (r.stdout + r.stderr).strip()[-600:]
        raise Deny(f"public-text-guard: privacy-check refused this text for the public repo "
                   f"(exit {r.returncode}):\n{detail}")


def script_file(seg):
    """The script file a segment runs, or None."""
    words = seg.head_words
    if not words:
        return None
    cmd = os.path.basename(words[0])
    if words[0] in ("source", "."):  # sourced into the current shell: a script like any other
        args = [a for a in words[1:] if not a.startswith("-")]
        if args and ("/" in args[0] or os.path.isfile(os.path.join(seg.cwd, args[0]))):
            return args[0]
        return None
    if cmd in INTERPRETERS:
        args = words[1:]
        if any(re.match(r"^-[a-z]*c[a-z]*$", a) for a in args if a.startswith("-") and a != "--"):
            return None
        files = [a for a in args if not a.startswith("-")]
        if files and ("/" in files[0] or os.path.isfile(os.path.join(seg.cwd, files[0]))):
            return files[0]
        return None
    return words[0] if "/" in words[0] and cmd not in WRAPPERS else None


def shell_c_payload(seg):
    """The string a `bash -c` or `eval` will run, or None."""
    words = seg.head_words
    if words[:1] == ["eval"]:
        return " ".join(words[1:])
    if not words or os.path.basename(words[0]) not in SHELLS:
        return None
    for i, a in enumerate(words[1:], 1):
        if re.match(r"^-[a-z]*c[a-z]*$", a):
            return words[i + 1] if i + 1 < len(words) else ""
    return None


def reads_stdin_script(seg):
    """A shell with no script file and no -c, fed by a pipe or a `<` redirect."""
    words = seg.head_words
    if not words or os.path.basename(words[0]) not in SHELLS or shell_c_payload(seg) is not None:
        return False
    if [a for a in words[1:] if not a.startswith("-")]:
        return False  # runs a named file
    return seg.sep in ("|", "|&") or any("<" in op for op, _ in seg.redirs)


def check_bash_gh(command, cwd):
    segs, seen, final_cwd, main, cwd_unresolved = build_segments(command, cwd)
    check_bash_config(segs)
    gh_segs = [s for s in segs if s.is_gh]
    wrapped = [s for s in segs if s.wraps_gh]
    shellc = [s for s in segs if (shell_c_payload(s) or "") and GH_WORD.search(shell_c_payload(s))]
    scripts = [s for s in segs if script_file(s)]
    stdin_shells = [s for s in segs if reads_stdin_script(s)]
    if not (gh_segs or wrapped or shellc or scripts or stdin_shells):
        return
    if cwd_unresolved and (gh_segs or wrapped or shellc):
        # Which repo the gh call runs in is unknowable, so it cannot be judged public or not.
        raise Unresolvable("a cd, pushd or popd target with a variable, substitution, `-` or ~user "
                           "before a gh call")
    env = {}
    for s in segs:
        env.update(s.exported)
        env.update(s.env)
    all_words = [w for s in segs for w in s.words]
    # gh asks git for the repo, and GIT_DIR / GIT_WORK_TREE redirect that answer.
    git_roots = [os.path.join(final_cwd, os.path.expanduser(env[k]))
                 for k in ("GIT_DIR", "GIT_WORK_TREE") if env.get(k)]
    cwd_public = pcx.is_public(final_cwd) or any(pcx.is_public(p) for p in git_roots)
    names_public = pcx.repo_flag_names_public(all_words, env)
    if not (cwd_public or names_public):
        return
    GUARDED[0] = True

    if cwd_public:
        for s in scripts:
            check_script(s)
    if stdin_shells:
        raise Unresolvable("a shell fed a script on stdin")
    if not (gh_segs or wrapped or shellc):
        return
    if wrapped or shellc:
        raise Unresolvable("a gh call behind a wrapper, `bash -c` or `eval`" if wrapped
                           else "`bash -c` or `eval`")
    main_seg = segs[main] if main is not None else None
    if len(gh_segs) != 1 or gh_segs[0] is not main_seg or seen & set("()"):
        raise Unresolvable("a gh call behind a pipe, `;`, `&&`, `||` or in a subshell")
    seg = gh_segs[0]
    kind, texts = classify(seg.head_words[1:], seg.cwd)
    if kind == "read":
        return
    if SUBSTITUTION.search(command) or any("$" in w for w in seg.head_words) \
            or any("<" in op for op, _ in seg.redirs):
        raise Unresolvable("a command substitution, variable, heredoc or input redirection")
    root = pcx.public_root(final_cwd) if cwd_public else None
    root = root or pcx.configured_path()
    privacy_check(texts, root)


def check_script(seg):
    """In a public cwd every script a command runs is inspected, wherever it lives: a script
    outside the checkout can call gh just as well. Compiled binaries are not scripts; a missing
    file outside the checkout is the shell's problem, one inside it is denied."""
    name = script_file(seg)
    path = os.path.realpath(os.path.join(seg.cwd, name))
    roots = {os.path.realpath(r) for r in (pcx.public_root(seg.cwd), pcx.configured_path()) if r}
    inside = any(path == r or path.startswith(r + os.sep) for r in roots)
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            raise Unresolvable(f"the script {name} is not a regular file")
        with open(path, "rb") as f:
            data = f.read(MAX_FILE)
    except OSError:
        if inside:
            raise Unresolvable(f"the script {name} cannot be read")
        return
    if b"\0" in data:
        return
    if GH_WORD.search(data.decode("utf-8", errors="replace")):
        raise Unresolvable(f"the script {name} contains gh")


def check_bash(ti, cwd):
    command = ti.get("command")
    if not isinstance(command, str) or not command.strip():
        return
    try:
        check_bash_gh(command, cwd)
    except ValueError:  # shlex could not parse it
        if "ai-workflow" in command:
            raise Deny(config_denial("a path in this command"))
        if GH_WORD.search(command) and (pcx.is_public(cwd)
                                        or pcx.repo_flag_names_public(command.split(), {})):
            raise Unresolvable("a command line that cannot be parsed")


def main():
    try:
        data = json.load(sys.stdin)
        tool = data.get("tool_name")
        cwd = data.get("cwd") or os.getcwd()
        ti = data.get("tool_input") or {}
        if not isinstance(ti, dict):
            return
    except Exception:
        return
    try:
        if tool in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
            check_edit(ti, cwd)
        elif tool == "Bash":
            check_bash(ti, cwd)
    except Deny as e:
        emit_deny(str(e))
    except Exception as e:
        # Fail closed only where a guard applied; an error before that point means no decision.
        if GUARDED[0]:
            emit_deny(f"public-text-guard: internal error ({type(e).__name__}); denied.")


if __name__ == "__main__":
    main()
