#!/usr/bin/env python3
"""Tests for scripts/install-smoke.

Run: python3 scripts/test_install_smoke.py
The script is exercised against tiny stub installers in throwaway git repos, plus one real run
against this repo. Its temp HOME is always fresh; the real $HOME is never touched.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "install-smoke"
REPO = SCRIPT.parent.parent

GOOD = '''#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.claude"
ln -sfn "$REPO/payload.txt" "$HOME/.claude/payload.txt"
if [ -d "$REPO/overlay" ]; then echo present >> "$HOME/overlay.log"; else echo absent >> "$HOME/overlay.log"; fi
'''


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name).resolve() / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / "scripts/install-smoke")
        (self.repo / "payload.txt").write_text("payload\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True)
        self.installer(GOOD)

    def installer(self, text):
        (self.repo / "install.sh").write_text(text)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)

    def smoke(self):
        env = {**os.environ, "TMPDIR": str(self.repo.parent)}
        return subprocess.run([sys.executable, str(self.repo / "scripts/install-smoke")],
                              cwd="/", text=True, capture_output=True, env=env, timeout=300)

    def test_a_clean_installer_passes_both_runs_and_the_overlay_is_present_then_absent(self):
        r = self.smoke()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok", r.stdout)

    def test_runs_are_no_overlay_on_a_fresh_home_then_overlay_present_then_overlay_removed(self):
        self.installer(GOOD.replace('echo present >> "$HOME/overlay.log"',
                                    'echo present >> "$HOME/overlay.log"; echo "run:present"')
                       .replace('echo absent >> "$HOME/overlay.log"',
                                'echo absent >> "$HOME/overlay.log"; echo "run:absent"'))
        r = self.smoke()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        marks = [l for l in r.stdout.splitlines() if l.startswith("run:")]
        self.assertEqual(marks, ["run:absent", "run:present", "run:absent"])

    def test_the_no_overlay_run_uses_its_own_fresh_home(self):
        # Fails only when the overlay is absent AND the HOME already holds the payload link.
        self.installer(GOOD + '[ -d "$REPO/overlay" ] || [ ! -e "$HOME/seen" ] || exit 6\n'
                       'touch "$HOME/seen"\n')
        r = self.smoke()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("exited 6", r.stdout)
        self.assertEqual(r.stdout.count("exited 6"), 1)  # only the overlay-removed re-run

    def test_a_failure_with_no_overlay_on_a_fresh_home_is_reported(self):
        self.installer(GOOD + '[ -d "$REPO/overlay" ] || [ -e "$HOME/.claude/seen" ] || exit 5\n'
                       'touch "$HOME/.claude/seen"\n')
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("exited 5 with no overlay on a fresh HOME", r.stdout)

    def test_a_dangling_link_left_with_no_overlay_is_reported(self):
        self.installer(GOOD + '[ -d "$REPO/overlay" ] || ln -sfn "$HOME/nowhere" "$HOME/.claude/d"\n')
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("dangling", r.stdout)

    def test_a_failing_installer_fails(self):
        self.installer("#!/bin/sh\necho boom >&2\nexit 3\n")
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("exited 3", r.stdout + r.stderr)

    def test_a_dangling_link_fails(self):
        self.installer(GOOD + 'ln -sfn "$HOME/nowhere" "$HOME/.claude/dangling"\n')
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("dangling", r.stdout)
        self.assertIn(".claude/dangling", r.stdout)

    def test_a_link_into_the_overlay_after_it_is_removed_fails(self):
        self.installer(GOOD + 'mkdir -p "$REPO/overlay/x" && ln -sfn "$REPO/overlay/x" "$HOME/.claude/ov"\n')
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("overlay", r.stdout)

    def test_it_does_not_touch_the_working_repo(self):
        before = sorted(p.name for p in self.repo.iterdir())
        self.smoke()
        self.assertEqual(sorted(p.name for p in self.repo.iterdir()), before)

    def test_a_real_run_against_this_repo_passes(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], cwd="/", text=True, capture_output=True,
                           timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
