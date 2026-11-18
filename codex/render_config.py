#!/usr/bin/env python3
"""Render ~/.codex/config.toml from the tracked base plus an optional per-machine fragment.

  render_config.py --base codex/config.base.toml [--fragment PATH] --home "$HOME"   > config.toml

`{HOME}` in either input becomes the home directory. The fragment (extra trusted project entries)
is optional: a missing file renders the base alone, and it may hold only `[projects."…"]` tables
with a `trust_level`. The result must parse as TOML and a fragment
may not redefine a base table, otherwise nothing is printed and the exit status is 1.
"""
import argparse
import sys
import tomllib
from pathlib import Path


def render(base, fragment, home):
    if not str(home).startswith("/"):
        raise ValueError(f"home must be an absolute path, got {home!r}")
    # {HOME} always sits inside a TOML basic string, so escape what a string cannot hold raw.
    safe_home = str(home).replace("\\", "\\\\").replace('"', '\\"')
    text = base if base.endswith("\n") else base + "\n"
    if fragment:
        try:
            parsed = tomllib.loads(fragment)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"fragment is not valid TOML: {e}") from e
        projects = parsed.get("projects")
        if (set(parsed) != {"projects"} or not isinstance(projects, dict)
                or any(not isinstance(v, dict) or set(v) != {"trust_level"}
                       for v in projects.values())):
            raise ValueError("fragment may hold only [projects.\"…\"] tables with trust_level")
        text += "\n" + fragment
        if not text.endswith("\n"):
            text += "\n"
    text = text.replace("{HOME}", safe_home)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"rendered config is not valid TOML: {e}") from e
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--fragment")
    ap.add_argument("--home", required=True)
    args = ap.parse_args(argv)
    try:
        fragment = None
        if args.fragment and Path(args.fragment).is_file():
            fragment = Path(args.fragment).read_text()
        out = render(Path(args.base).read_text(), fragment, args.home)
    except (OSError, ValueError) as e:
        print(f"render_config: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
