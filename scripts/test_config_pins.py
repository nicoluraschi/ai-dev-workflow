#!/usr/bin/env python3
"""Pins on tracked config: the exact Bash allowlist and exact-version MCP package runners."""
import json
import os
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETTINGS = REPO / "claude/settings.json"
MCP = REPO / "mcp/mcpServers.json"

EXPECTED_ALLOW = [
    "Bash(mkdir:*)", "Bash(find:*)", "Bash(grep:*)",
    "Bash(npm test:*)", "Bash(npm run:*)", "Bash(yarn test:*)", "Bash(yarn run:*)",
    "Bash(ls:*)", "Bash(cd:*)", "Bash(touch:*)", "Bash(codex-audit:*)", "Bash(gate-log:*)",
]
FORBIDDEN_ALLOW = ["Bash", "Bash(*)", "Bash(npm:*)", "Bash(yarn:*)", "Bash(mv:*)",
                   "Bash(cp:*)", "Bash(uv:*)"]

DIRECT = {"npx", "pnpx", "bunx", "uvx"}
VIA_SUBCOMMAND = {"pnpm": {"dlx"}, "yarn": {"dlx"}, "bun": {"x"}, "npm": {"exec", "x"}}
EXACT = re.compile(r"^(@[^/@]+/)?[^/@]+@\d+\.\d+\.\d+$")

# Fail closed: every argument the runner itself reads goes through one parser, and a flag not
# listed here is reported, so no flag can carry a package past the check. The runner reads its
# options before the subcommand, and after it up to the first positional (the package, or the
# command when a naming flag gave the package) — except npm exec/x, which reads options up to
# `--`. The naming flags replace the positional as the package; uvx's --with/-w add one beside
# it; uvx's -p is --python, whose value is skipped.
BOOL_FLAGS = ("-y", "--yes", "-q", "--quiet", "--silent")
NAMING_FLAGS = {"uvx": ("--from",), None: ("--package", "-p")}
EXTRA_FLAGS = {"uvx": ("--with", "-w"), None: ()}
VALUE_FLAGS = {"uvx": ("--python", "-p"), None: ()}


def _scan(name, args, family, stop_at_positional):
    """Read runner options from args. Returns (package tokens, first positional, named, problems)."""
    naming, value_flags = NAMING_FLAGS[family], VALUE_FLAGS[family]
    package_flags = naming + EXTRA_FLAGS[family]
    tokens, first, named, bad, i = [], None, False, [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            # Options end here; a package not yet seen is the next argument.
            if first is None and i + 1 < len(args):
                first = args[i + 1]
            break
        flag, eq, value = a.partition("=")
        if not a.startswith("-"):
            if first is None:
                first = a
                if stop_at_positional:
                    break
        elif a in BOOL_FLAGS:
            pass
        elif flag in value_flags or flag in package_flags:
            if not eq:
                i += 1
                if i >= len(args):
                    bad.append(f"{name}: {a} without a value")
                    break
                value = args[i]
            if flag in package_flags:
                tokens.append(value)
                named = named or flag in naming
        else:
            bad.append(f"{name}: unknown flag {a}")
        i += 1
    return tokens, first, named, bad


def unpinned(servers):
    """Package tokens of package-runner servers that lack an exact x.y.z version, and any
    runner flag the check does not know."""
    bad = []
    for name, srv in servers.items():
        runner = os.path.basename(srv.get("command", ""))
        args = list(srv.get("args", []))
        family = "uvx" if runner == "uvx" else None
        tokens, named = [], False
        if runner in VIA_SUBCOMMAND:
            # Any argument naming the subcommand counts, so a flag value before it fails closed.
            sub = next((j for j, a in enumerate(args) if a in VIA_SUBCOMMAND[runner]), None)
            if sub is None:
                continue
            t, stray, n, problems = _scan(name, args[:sub], family, stop_at_positional=False)
            tokens, named, bad = tokens + t, named or n, bad + problems
            if stray is not None:
                bad.append(f"{name}: unexpected argument {stray} before {args[sub]}")
            args = args[sub + 1:]
        elif runner not in DIRECT:
            continue
        t, first, n, problems = _scan(name, args, family, stop_at_positional=runner != "npm")
        tokens, named, bad = tokens + t, named or n, bad + problems
        if not named and first is not None:
            tokens.append(first)
        bad += [f"{name}: {t}" for t in tokens if not EXACT.match(t)]
    return bad


def one(command, *args):
    return {"s": {"command": command, "args": list(args)}}


class AllowlistTests(unittest.TestCase):
    def setUp(self):
        self.perms = json.loads(SETTINGS.read_text())["permissions"]

    def test_allow_is_exactly_the_agreed_list(self):
        self.assertEqual(sorted(self.perms["allow"]), sorted(EXPECTED_ALLOW))

    def test_allow_has_no_duplicates(self):
        allow = self.perms["allow"]
        self.assertEqual(len(allow), len(set(allow)))

    def test_broad_entries_are_absent(self):
        for entry in FORBIDDEN_ALLOW:
            self.assertNotIn(entry, self.perms["allow"])

    def test_deny_and_ask_unchanged(self):
        self.assertEqual(self.perms["deny"], [])
        self.assertEqual(self.perms["ask"], ["Bash(codex-audit *--rerun*)"])


class McpPinTests(unittest.TestCase):
    def test_chrome_devtools_is_pinned(self):
        servers = json.loads(MCP.read_text())["mcpServers"]
        self.assertEqual(servers["chrome-devtools"]["args"], ["-y", "chrome-devtools-mcp@1.12.0"])

    def test_real_file_has_no_unpinned_package(self):
        self.assertEqual(unpinned(json.loads(MCP.read_text())["mcpServers"]), [])


class UnpinnedTests(unittest.TestCase):
    def test_flagged(self):
        cases = [
            ("npx", "-y", "x@latest"), ("npx", "x@^1.2.0"), ("npx", "x@next"), ("npx", "x"),
            ("npx", "@s/x"), ("npx", "@s/x@latest"), ("npx", "--package=x@latest", "cmd"),
            ("npx", "-p", "x@latest", "cmd"),
            ("npx", "--package=a@1.2.3", "--package=b@latest", "cmd"),
            ("/opt/homebrew/bin/npx", "x"), ("pnpx", "x"), ("bunx", "x"),
            ("bun", "x", "x"), ("pnpm", "dlx", "x"), ("yarn", "dlx", "x"), ("uvx", "x"),
            ("pnpm", "--silent", "dlx", "x@latest"), ("yarn", "--silent", "dlx", "x"),
            ("bun", "--silent", "x", "x"),
            ("uvx", "--with=evil", "x@1.2.3"), ("uvx", "--with", "evil", "x@1.2.3"),
            ("uvx", "--with=a@1.2.3", "x"), ("uvx", "--from=evil", "x"),
            ("uvx", "--from", "evil", "x"),
            ("npm", "exec", "x@latest"), ("npm", "x", "x"),
            ("pnpm", "--filter", "foo", "dlx", "evil@latest"),
            ("npm", "--prefix", "/tmp", "exec", "evil@latest"),
            ("uvx", "-p", "cpython@3.12.1", "evil@latest"),
            ("uvx", "--python", "cpython@3.12.1", "evil@latest"),
            ("uvx", "--python=cpython@3.12.1", "evil"),
            ("npm", "--prefix", "a@1.2.3", "exec", "evil@latest"),
            ("pnpm", "--dir", "a@1.2.3", "dlx", "evil@latest"),
            ("uvx", "-w", "a@1.2.3", "evil"), ("uvx", "--cache-dir", "a@1.2.3", "evil"),
            ("npx", "--cache", "a@1.2.3", "evil"), ("npx", "--package"),
            ("pnpm", "--package=evil@latest", "dlx", "a@1.2.3"),
            ("npm", "--package=evil@latest", "exec", "a@1.2.3"),
            ("npm", "exec", "a@1.2.3", "--package=evil@latest"),
            ("npm", "exec", "a@1.2.3", "--cache", "x"),
            ("npm", "exec", "--", "evil@latest"), ("npx", "--", "evil@latest"),
            ("npx", "-y", "--", "evil@latest"), ("pnpm", "dlx", "--", "evil@latest"),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertTrue(unpinned(one(*case)), case)

    def test_clean(self):
        cases = [
            ("npx", "-y", "x@1.2.3"), ("npx", "@s/x@1.2.3"),
            ("npx", "--package=x@1.2.3", "cmd"),
            ("npx", "-p", "a@1.2.3", "-p", "b@4.5.6", "cmd"),
            ("uvx", "--from", "x@1.2.3", "cmd"), ("uvx", "--with=a@1.2.3", "x@4.5.6"),
            ("pnpm", "--silent", "dlx", "x@1.2.3"), ("npm", "exec", "x@1.2.3"),
            ("uvx", "-p", "3.12", "x@1.2.3"),
            ("npx", "-y", "x@1.2.3", "--isolated", "--port", "9"),
            ("pnpm", "--package=a@1.2.3", "dlx", "cmd"),
            ("npm", "exec", "x@1.2.3", "--", "--port", "9"),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(unpinned(one(*case)), [])

    def test_non_runner_is_not_inspected(self):
        self.assertEqual(unpinned(one("node", "server.js")), [])
        self.assertEqual(unpinned(one("npm", "run", "build")), [])


if __name__ == "__main__":
    unittest.main()
