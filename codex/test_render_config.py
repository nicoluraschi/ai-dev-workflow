#!/usr/bin/env python3
"""Tests for render_config.py.

Run: python3 codex/test_render_config.py
The equivalence test against the tracked codex/config.toml runs only while both that file and the
overlay fragment (config/codex-projects.toml) exist, i.e. with a local overlay.
"""
import contextlib
import importlib.util
import io
import tempfile
import tomllib
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("render_config", HERE / "render_config.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

BASE = 'model = "m"\n\n[projects."{HOME}/Projects"]\ntrust_level = "trusted"\n'
FRAGMENT = '[projects."{HOME}/Projects/extra"]\ntrust_level = "trusted"\n'


class RenderTests(unittest.TestCase):
    def test_home_placeholder_is_expanded_in_base_and_fragment(self):
        out = tomllib.loads(rc.render(BASE, FRAGMENT, "/h"))
        self.assertEqual(sorted(out["projects"]), ["/h/Projects", "/h/Projects/extra"])

    def test_without_a_fragment_only_the_base_paths_remain(self):
        out = tomllib.loads(rc.render(BASE, None, "/h"))
        self.assertEqual(list(out["projects"]), ["/h/Projects"])
        self.assertEqual(out["model"], "m")

    def test_a_home_with_quote_or_backslash_stays_valid_toml(self):
        out = tomllib.loads(rc.render(BASE, None, '/we"ird\\home'))
        self.assertEqual(list(out["projects"]), ['/we"ird\\home/Projects'])

    def test_a_fragment_that_redefines_a_base_table_is_rejected(self):
        with self.assertRaises(ValueError):
            rc.render(BASE, '[projects."{HOME}/Projects"]\ntrust_level = "untrusted"\n', "/h")

    def test_a_fragment_with_anything_but_project_trust_entries_is_rejected(self):
        for frag in ('[mcp_servers.x]\ncommand = "sh"\n',
                     'sandbox_mode = "danger-full-access"\n',
                     '[projects."/x"]\ntrust_level = "trusted"\ncommand = "sh"\n'):
            with self.subTest(frag=frag), self.assertRaises(ValueError):
                rc.render(BASE, frag, "/h")

    def test_invalid_fragment_is_rejected(self):
        with self.assertRaises(ValueError):
            rc.render(BASE, "not = = toml", "/h")

    def test_relative_home_is_rejected(self):
        with self.assertRaises(ValueError):
            rc.render(BASE, None, "relative")


class CliTests(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rc.main(list(args))
        return code, out.getvalue()

    def test_prints_the_rendered_file_and_treats_a_missing_fragment_as_none(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base.toml"
            base.write_text(BASE)
            code, out = self.run_main("--base", str(base), "--home", "/h",
                                      "--fragment", str(Path(td) / "absent.toml"))
            self.assertEqual(code, 0)
            self.assertEqual(list(tomllib.loads(out)["projects"]), ["/h/Projects"])

    def test_reads_the_fragment_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            base, frag = Path(td) / "base.toml", Path(td) / "frag.toml"
            base.write_text(BASE)
            frag.write_text(FRAGMENT)
            _, out = self.run_main("--base", str(base), "--home", "/h", "--fragment", str(frag))
            self.assertEqual(len(tomllib.loads(out)["projects"]), 2)

    def test_invalid_input_exits_non_zero_with_nothing_on_stdout(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base.toml"
            base.write_text("x = = 1")
            code, out = self.run_main("--base", str(base), "--home", "/h")
            self.assertEqual((code, out), (1, ""))


class EquivalenceTests(unittest.TestCase):
    """AC 7: the rendered config with the overlay fragment parses equal to today's config."""

    def test_base_plus_fragment_equals_the_tracked_config_with_paths_expanded(self):
        tracked = HERE / "config.toml"
        fragment = HERE.parent / "config/codex-projects.toml"
        if not (tracked.is_file() and fragment.is_file()):
            self.skipTest("public tree: no tracked config.toml or overlay fragment")
        expected = tomllib.loads(tracked.read_text())
        # Recover the home the tracked file was written for from its first project path.
        home = next(iter(expected["projects"])).rsplit("/Projects", 1)[0].rsplit("/worktrees", 1)[0]
        got = tomllib.loads(rc.render((HERE / "config.base.toml").read_text(),
                                      fragment.read_text(), home))
        self.assertEqual(got, expected)

    def test_base_alone_holds_only_generic_trusted_paths(self):
        out = tomllib.loads(rc.render((HERE / "config.base.toml").read_text(), None, "/h"))
        self.assertEqual(sorted(out["projects"]), ["/h/Projects", "/h/worktrees"])


if __name__ == "__main__":
    unittest.main()
