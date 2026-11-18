#!/usr/bin/env python3
"""PreToolUse guard: deny agent writes to the gate state, the scanner pointer and the extra scanner.

The gates (audit-guard, uncommitted-on-main, main-context-images, session-hygiene) can each be
silenced by a `.skip` file in the audit state dir. Refusals no longer print that recipe, and this
hook stops the agent from creating one itself: it denies

  - the gate state dir: CLAUDE_AUDIT_STATE_DIR when set, and always ~/.claude/.audit-state;
  - the scanner pointer, ~/.config/ai-workflow/extra-scanner;
  - the extra scanner that pointer names, and its directory (a scanner may read files beside itself).

Edit, Write and NotebookEdit are judged by the RESOLVED path (symlinked ancestors, `..` and case
variants included, also for a file that does not exist yet). Bash is judged by TEXT: any command
that contains `.audit-state`, the CLAUDE_AUDIT_STATE_DIR name, or a target rendered as an absolute
path, `~/...`, `$HOME/...` or `${HOME}/...`, in any case, after quotes and backslashes are dropped
and `//` and `/./` collapsed. Reads are denied too; the Read and Grep tools stay the way to read these. No shell
parser, no env override.

SPEED BUMP, NOT A BOUNDARY. Residual: a script written to the scratchpad that touches the state
dir, run by a command that names no target, passes; so do a write reaching the pointer or the
scanner by a cwd-relative path, a glob (`.audit-stat?`), ANSI-C escapes (`$'\\x2e'audit-state`),
renaming a parent directory, and a write through a symlink an earlier command created. This catches drift, not a determined agent.

The silencer is the human's: from the prompt with `!` (see docs/hooks.md for the recipe), never
the agent's. Deny messages name the target class only: never the scanner's path, the pointer's
contents, or the tool input.

Fails OPEN on an unparseable payload. If judging raises, the raw path or command is checked for
the target names before allowing. Stdlib only, standalone like every hook here.
"""
import json
import os
import stat
import sys

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
# One-line change point: how the human silences a gate (docs/hooks.md uses the same phrase).
SILENCER = "from the prompt with `!`"
STATE, POINTER, SCANNER = "the gate state dir", "the scanner pointer", "the extra scanner"
POINTER_MAX = 4096


def deny(cls):
    print(
        f"gate-state-guard: this call names {cls}, which the agent may not change. "
        f"Ask the human to change it themselves {SILENCER}. "
        f"To read one, use the Read or Grep tool; to put such text in a PR, use --body-file.",
        file=sys.stderr,
    )
    sys.exit(2)


def read_pointer(path):
    """The scanner path the pointer names, or None unless the pointer is well formed: a regular
    non-symlink file under 4 KiB with exactly one non-empty line that is an absolute path."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size >= POINTER_MAX:
            return None
        data = os.read(fd, POINTER_MAX).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)
    lines = [ln for ln in data.splitlines() if ln.strip()]
    if len(lines) != 1 or "\x00" in lines[0] or not os.path.isabs(lines[0].strip()):
        return None
    return lines[0].strip()


def forms(p):
    """A path in its literal and realpath form."""
    return {p, os.path.realpath(p)}


def targets():
    """[(class, {forms})] for everything the agent may not touch."""
    home = os.path.expanduser("~")
    out = []
    state = {os.path.join(home, ".claude", ".audit-state")}
    if os.environ.get("CLAUDE_AUDIT_STATE_DIR"):
        state.add(os.path.expanduser(os.environ["CLAUDE_AUDIT_STATE_DIR"]))
    out.append((STATE, set().union(*(forms(s) for s in state))))
    pointer = os.path.join(home, ".config", "ai-workflow", "extra-scanner")
    out.append((POINTER, forms(pointer)))
    scanner = read_pointer(pointer)
    if scanner:
        out.append((SCANNER, forms(scanner) | forms(os.path.dirname(scanner))))
    return out


def under(path, root):
    """True when `path` is `root` or inside it. Textual check on casefolded strings (covers a
    target that does not exist yet and case variants), then an (st_ino, st_dev) walk up the path
    (covers symlinked ancestors). Same technique as block-edits-on-main.py, repeated here."""
    try:
        if os.path.commonpath([path.casefold(), root.casefold()]) == root.casefold():
            return True
    except ValueError:
        pass
    try:
        rs = os.stat(root)
        root_id = (rs.st_ino, rs.st_dev)
    except OSError:
        return False
    d = path
    while True:
        try:
            st = os.stat(d)
            if (st.st_ino, st.st_dev) == root_id:
                return True
        except OSError:
            pass
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def judge_edit(ti):
    p = ti.get("file_path") or ti.get("notebook_path") or ""
    if not p:
        return None
    rp = os.path.realpath(os.path.expanduser(p))
    for cls, fs in targets():
        if any(under(rp, f) for f in fs):
            return cls
    return None


def renderings(p):
    """A path as the agent might write it: absolute, ~/..., $HOME/..., ${HOME}/..."""
    out = {p}
    for home in forms(os.path.expanduser("~")):
        if p == home or p.startswith(home.rstrip("/") + "/"):
            rest = p[len(home):]
            out |= {"~" + rest, "$HOME" + rest, "${HOME}" + rest}
    return out


def normalize(text):
    """Casefold, drop quotes and backslashes, collapse `//` and `/./`, so `"$HOME"/x`,
    `.audit-"state"`, `.audit-\\state` and `~//x` read as their plain forms. Applied to the command
    and to every target rendering alike. String operations only."""
    t = str(text or "").casefold().replace('"', "").replace("'", "").replace("\\", "")
    while "/./" in t or "//" in t:
        t = t.replace("/./", "/").replace("//", "/")
    return t


def judge_bash(ti):
    cmd = normalize(ti.get("command"))
    if ".audit-state" in cmd or "claude_audit_state_dir" in cmd:
        return STATE
    for cls, fs in targets():
        for f in fs:
            if any(normalize(r) in cmd for r in renderings(f)):
                return cls
    return None


def judge(data):
    ti = data.get("tool_input") or {}
    tool = data.get("tool_name")
    if tool in EDIT_TOOLS:
        return judge_edit(ti)
    if tool == "Bash":
        return judge_bash(ti)
    return None


def raw_hit(data):
    """Fallback when judging raised: name checks on the raw text first, then the text check against
    every configured target (which reads the pointer; if that raises too, the name checks stand)."""
    ti = data.get("tool_input") or {}
    text = normalize(ti.get("file_path") or ti.get("notebook_path") or ti.get("command"))
    if ".audit-state" in text or "claude_audit_state_dir" in text:
        return STATE
    if "ai-workflow/extra-scanner" in text:
        return POINTER
    try:
        return judge_bash({"command": text})   # every configured target, by text
    except Exception:
        return None


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)

    try:
        cls = judge(data)
    except Exception:
        try:
            cls = raw_hit(data)
        except Exception:
            cls = None
    if cls:
        deny(cls)
    sys.exit(0)


if __name__ == "__main__":
    main()
