#!/usr/bin/env python3
"""Is this Jira site one of the developer's own boards?

  own_site.py <site-or-url> [--file PATH]     prints "own" (exit 0) or "ask" (exit 1)

The own hosts are listed one per line in ~/.config/ai-workflow/jira-own-sites (comments with #).
The match is exact on the URL's hostname, lowercased with a trailing dot stripped, so a lookalike
host or `https://own@evil.example/` never counts. A missing, unreadable or empty file lists no
site: the answer is always "ask", the safe side.
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse


def default_file(home=None):
    return Path(home or Path.home()) / ".config/ai-workflow/jira-own-sites"


def host_of(site):
    site = site.strip()
    if not site:
        return None
    try:
        host = urlparse(site if "://" in site else "//" + site).hostname
    except ValueError:
        return None
    return host.rstrip(".").lower() if host else None


def own_hosts(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return set()
    hosts = {host_of(line.split("#", 1)[0]) for line in lines}
    hosts.discard(None)
    return hosts


def is_own_site(site, path=None):
    host = host_of(site)
    return host is not None and host in own_hosts(path or default_file())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("site")
    ap.add_argument("--file", help="own-sites file (default: ~/.config/ai-workflow/jira-own-sites)")
    args = ap.parse_args(argv)
    own = is_own_site(args.site, args.file)
    print("own" if own else "ask")
    return 0 if own else 1


if __name__ == "__main__":
    sys.exit(main())
