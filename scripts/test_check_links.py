#!/usr/bin/env python3
"""Tests for scripts/check-links.

Run: python3 scripts/test_check_links.py
Each test builds a throwaway git repo in a temp dir.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check-links"


class CheckLinksTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True, capture_output=True)

    def add(self, rel, text="", track=True):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if track:
            subprocess.run(["git", "add", rel], cwd=self.root, check=True, capture_output=True)
        return p

    def check(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, text=True,
                              capture_output=True, timeout=60)

    def test_resolving_links_pass(self):
        self.add("docs/a.md", "x\n")
        self.add("docs/sub/b.md", "x\n")
        self.add("README.md", "[a](docs/a.md) [dir](docs/sub) [dir2](docs/sub/) "
                              "[anchor](docs/a.md#section) ![img](docs/a.md) [q](docs/a.md?x=1) "
                              "[t](docs/a.md \"title\") [ang](<docs/a.md>)\n")
        self.add("docs/c.md", "[up](../README.md) [sib](a.md) [root](/docs/a.md)\n")
        r = self.check()
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_external_and_anchor_only_links_are_skipped(self):
        self.add("README.md", "[w](https://example.com/x) [h](http://example.com) "
                              "[m](mailto:a@example.com) [self](#top) [t](tel:123) "
                              "[ssh](git@github.com:o/r.git)\n")
        self.assertEqual(self.check().returncode, 0)

    def test_broken_links_are_listed_with_file_and_line_and_exit_1(self):
        self.add("README.md", "ok\n[gone](docs/missing.md)\n[also](nope/x.md#frag)\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("README.md:2: docs/missing.md", r.stdout)
        self.assertIn("README.md:3: nope/x.md", r.stdout)
        self.assertIn("2 broken", r.stdout)

    def test_relative_to_the_file_not_the_root(self):
        self.add("docs/a.md", "x\n")
        self.add("docs/b.md", "[a](docs/a.md)\n")  # would resolve only from the root
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("docs/b.md:1", r.stdout)

    def test_reference_definitions_are_checked(self):
        self.add("README.md", "see [x][ref]\n\n[ref]: docs/missing.md\n[ok]: https://example.com\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("README.md:3: docs/missing.md", r.stdout)

    def test_code_fences_and_inline_code_are_not_links(self):
        self.add("README.md", "```\n[a](nowhere.md)\n```\ntext `[b](nowhere.md)` more\n~~~\n[c](x.md)\n~~~\n")
        self.assertEqual(self.check().returncode, 0)

    def test_only_tracked_markdown_is_checked(self):
        self.add("untracked.md", "[a](nowhere.md)\n", track=False)
        self.add("notes.txt", "[a](nowhere.md)\n")
        self.assertEqual(self.check().returncode, 0)

    def test_a_directory_argument_limits_the_scan(self):
        self.add("a/x.md", "[a](nowhere.md)\n")
        self.add("b/y.md", "fine\n")
        self.assertEqual(self.check("b").returncode, 0)
        self.assertEqual(self.check("a").returncode, 1)

    def test_not_a_git_repo_is_an_internal_error(self):
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run([sys.executable, str(SCRIPT)], cwd=td, text=True, capture_output=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
