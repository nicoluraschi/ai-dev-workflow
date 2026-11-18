#!/usr/bin/env python3
"""Tests for own_site.py.

Run: python3 claude/skills/jira-backlog/test_own_site.py
Fixture hosts use example.atlassian.net; the real own host lives only in a local overlay.
"""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "own_site.py"
spec = importlib.util.spec_from_file_location("own_site", SCRIPT)
own_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(own_site)

OWN = "example.atlassian.net"


class OwnSiteTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.file = Path(self._td.name) / "jira-own-sites"
        self.file.write_text(f"# my boards\n\n{OWN}\nJira.Example.com.\n")

    def own(self, site):
        return own_site.is_own_site(site, self.file)

    def test_own_host_bare_and_as_url(self):
        self.assertTrue(self.own(OWN))
        self.assertTrue(self.own(f"https://{OWN}/browse/ABC-1"))

    def test_case_and_trailing_dot_variants_match(self):
        self.assertTrue(self.own("EXAMPLE.Atlassian.NET"))
        self.assertTrue(self.own(f"{OWN}."))
        self.assertTrue(self.own("jira.example.com"))  # listed with caps and a dot

    def test_lookalike_hosts_do_not_match(self):
        for host in (f"{OWN}.evil.com", f"evil-{OWN}", f"evil{OWN}", OWN[1:],
                     f"{OWN}:evil@evil.example", "atlassian.net"):
            self.assertFalse(self.own(host), host)

    def test_userinfo_naming_the_own_host_does_not_match(self):
        self.assertFalse(self.own(f"https://{OWN}@evil.example/"))
        self.assertFalse(self.own(f"{OWN}@evil.example"))

    def test_port_is_not_part_of_the_host(self):
        self.assertTrue(self.own(f"https://{OWN}:443/"))

    def test_empty_or_malformed_input_is_not_own(self):
        self.assertFalse(self.own(""))
        self.assertFalse(self.own("   "))
        self.assertFalse(self.own("https://[::1/"))

    def test_missing_file_means_ask(self):
        self.assertFalse(own_site.is_own_site(OWN, self.file.with_name("absent")))

    def test_unreadable_file_means_ask(self):
        self.file.chmod(0)
        self.addCleanup(self.file.chmod, 0o600)
        if os.access(self.file, os.R_OK):
            self.skipTest("running as a user that ignores file modes")
        self.assertFalse(self.own(OWN))

    def test_directory_in_place_of_the_file_means_ask(self):
        self.file.unlink()
        self.file.mkdir()
        self.assertFalse(self.own(OWN))

    def test_empty_file_means_ask(self):
        self.file.write_text("")
        self.assertFalse(self.own(OWN))

    def test_default_path_is_under_home_config(self):
        self.assertEqual(own_site.default_file(Path("/h")),
                         Path("/h/.config/ai-workflow/jira-own-sites"))


class CliTests(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = own_site.main(list(args))
        return code, out.getvalue().strip()

    def test_exit_zero_and_own_for_a_listed_host(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "sites"
            f.write_text(OWN + "\n")
            self.assertEqual(self.run_main(OWN, "--file", str(f)), (0, "own"))
            self.assertEqual(self.run_main("client.example.com", "--file", str(f)), (1, "ask"))

    def test_missing_file_prints_ask_and_exits_one(self):
        self.assertEqual(self.run_main(OWN, "--file", "/nonexistent/sites"), (1, "ask"))


if __name__ == "__main__":
    unittest.main()
