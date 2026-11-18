#!/usr/bin/env python3
"""Tests for scripts/test-all.

Run: python3 scripts/test_test_all.py
Each test copies the script into a throwaway tree laid out like the repo and runs it there.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "test-all"
PASS_PY = "import os\nprint('cwd=' + os.getcwd())\n"
FAIL_PY = "import sys\nprint('the failure detail')\nsys.exit(1)\n"


class TestAllTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts/test-all")

    def add(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def run_all(self):
        return subprocess.run([sys.executable, str(self.root / "scripts/test-all")], cwd="/",
                              text=True, capture_output=True, timeout=120)

    def test_discovers_every_documented_location_and_runs_each_from_the_repo_root(self):
        self.add("claude/hooks/test_a.py", PASS_PY)
        self.add("claude/skills/s/scripts/test_b.py", PASS_PY)
        self.add("scripts/test_c.py", PASS_PY)
        self.add("codex/test_d.py", PASS_PY)
        self.add("codex/lib/test_e.sh", "#!/bin/bash\npwd\n")
        self.add("git/bin/test_f.py", PASS_PY)
        self.add("git/bin/test_g.sh", "#!/bin/bash\nexit 0\n")
        self.add("zed/bin/test_h.sh", "#!/bin/bash\nexit 0\n")
        r = self.run_all()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in ("claude/hooks/test_a.py", "claude/skills/s/scripts/test_b.py",
                    "scripts/test_c.py", "codex/test_d.py", "codex/lib/test_e.sh",
                    "git/bin/test_f.py", "git/bin/test_g.sh", "zed/bin/test_h.sh"):
            self.assertIn(f"PASS  {rel}", r.stdout)
        self.assertIn("8 suites, 0 failed", r.stdout)

    def test_zsh_suites_run_when_zsh_is_there(self):
        if not shutil.which("zsh"):
            self.skipTest("zsh not installed")
        self.add("shell/test_zed.zsh", "print ok\n")
        r = self.run_all()
        self.assertIn("PASS  shell/test_zed.zsh", r.stdout)

    def test_a_failing_suite_fails_the_run_and_shows_its_output(self):
        self.add("claude/hooks/test_ok.py", PASS_PY)
        self.add("scripts/test_bad.py", FAIL_PY)
        r = self.run_all()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL  scripts/test_bad.py", r.stdout)
        self.assertIn("PASS  claude/hooks/test_ok.py", r.stdout)
        self.assertIn("the failure detail", r.stdout)
        self.assertIn("2 suites, 1 failed", r.stdout)

    def test_the_overlay_is_excluded(self):
        self.add("claude/hooks/test_ok.py", PASS_PY)
        self.add("overlay/claude/skills/x/scripts/test_x.py", FAIL_PY)
        self.add("overlay/scripts/test_y.py", FAIL_PY)
        r = self.run_all()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("overlay", r.stdout)

    def test_fixtures_and_unknown_extensions_are_not_suites(self):
        self.add("claude/hooks/test_ok.py", PASS_PY)
        self.add("codex/bin/test_6b_prompt.golden", "golden\n")
        self.add("claude/hooks/test_notes.txt", "notes\n")
        self.add("claude/hooks/helper.py", FAIL_PY)
        r = self.run_all()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1 suites, 0 failed", r.stdout)

    def test_no_suites_at_all_is_a_failure(self):
        r = self.run_all()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no test suites", r.stdout + r.stderr)

    def test_the_real_repo_layout_is_discovered(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--list"], cwd="/", text=True,
                             capture_output=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        listed = out.stdout.splitlines()
        self.assertIn("scripts/test_privacy_check.py", listed)
        self.assertIn("claude/hooks/test_public_text_guard.py", listed)
        self.assertTrue(all(not l.startswith("overlay/") for l in listed))


if __name__ == "__main__":
    unittest.main()
