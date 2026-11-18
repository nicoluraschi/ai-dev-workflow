#!/usr/bin/env python3
"""Tests for install.sh, always against a throwaway HOME and a throwaway copy of the repo.

Run: python3 scripts/test_install.py
The real $HOME is never touched: HOME points at a temp dir, and the repo is copied (without .git)
so links point into the copy and the "running from a worktree" warning does not apply.
"""
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The public snapshot has neither config/ nor overlay/ (they are the private layer), so the cases
# that exercise them skip there. In the private repo they always run.
HAS_CONFIG = (REPO / "config").is_dir()
HAS_OVERLAY = (REPO / "overlay").is_dir()


class InstallFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name).resolve()
        self.home = root / "home"
        self.home.mkdir()
        self.repo = root / "repo"
        shutil.copytree(REPO, self.repo, symlinks=True, ignore=shutil.ignore_patterns(".git"))

    def install(self):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(["bash", str(self.repo / "install.sh")], env=env,
                              capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)

    def summary(self, r):
        """The final 'Install missing prerequisites' line, or "" when nothing is missing."""
        return next((l for l in r.stdout.splitlines() if "missing prerequisites" in l), "")

    def codex(self):
        return self.home / ".codex/config.toml"

    def backups(self):
        return sorted(p.name for p in (self.home / ".codex").glob("config.toml.backup.*"))


class CodexRenderTests(InstallFixture):
    @unittest.skipUnless(HAS_CONFIG, "no config/ in this checkout (public snapshot)")
    def test_renders_base_plus_fragment_into_a_regular_file(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.codex().is_file() and not self.codex().is_symlink())
        projects = tomllib.loads(self.codex().read_text())["projects"]
        self.assertEqual(sorted(projects), [f"{self.home}/Projects", f"{self.home}/Projects/platform",
                                            f"{self.home}/worktrees"])

    @unittest.skipUnless(HAS_CONFIG, "no config/ in this checkout (public snapshot)")
    def test_the_fragment_is_linked_outside_the_repo_tree(self):
        self.install()
        link = self.home / ".config/ai-workflow/codex-projects.toml"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.repo / "config/codex-projects.toml").resolve())

    def test_without_the_fragment_only_generic_paths_are_trusted(self):
        shutil.rmtree(self.repo / "config", ignore_errors=True)  # absent in the public snapshot
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        projects = tomllib.loads(self.codex().read_text())["projects"]
        self.assertEqual(sorted(projects), [f"{self.home}/Projects", f"{self.home}/worktrees"])

    def test_a_symlink_at_the_target_is_removed_and_never_written_through(self):
        sentinel = self.home / "sentinel.toml"
        sentinel.write_text('model = "legacy"\n')
        (self.home / ".codex").mkdir()
        self.codex().symlink_to(sentinel)
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sentinel.read_text(), 'model = "legacy"\n')
        self.assertFalse(self.codex().is_symlink())
        self.assertIn("projects", tomllib.loads(self.codex().read_text()))
        self.assertEqual(self.backups(), [])

    def test_unchanged_content_makes_no_backup_and_no_rewrite(self):
        self.install()
        before = self.codex().stat().st_mtime_ns
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.codex().stat().st_mtime_ns, before)

    def test_changed_content_is_backed_up_once_then_replaced(self):
        self.install()
        self.codex().write_text('model = "hand-edited"\n')
        self.install()
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual((self.home / ".codex" / backups[0]).read_text(), 'model = "hand-edited"\n')
        self.assertIn("projects", tomllib.loads(self.codex().read_text()))

    def test_audit_profile_stays_a_symlink(self):
        self.install()
        audit = self.home / ".codex/audit.config.toml"
        self.assertTrue(audit.is_symlink())
        self.assertEqual(audit.resolve(), (self.repo / "codex/audit.config.toml").resolve())

    def test_no_temp_file_is_left_behind(self):
        self.install()
        self.assertEqual([p.name for p in (self.home / ".codex").glob(".config.toml.*")], [])


@unittest.skipUnless(HAS_CONFIG, "no config/ in this checkout (public snapshot)")
class JiraOwnSitesTests(InstallFixture):
    def test_jira_own_sites_is_linked_into_the_personal_config_dir(self):
        self.install()
        link = self.home / ".config/ai-workflow/jira-own-sites"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.repo / "config/jira-own-sites").resolve())


@unittest.skipUnless(HAS_CONFIG, "no config/ in this checkout (public snapshot)")
class TrustedCommentersTests(InstallFixture):
    def test_trusted_commenters_is_linked_into_the_personal_config_dir(self):
        self.install()
        link = self.home / ".config/ai-workflow/trusted-commenters"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.repo / "config/trusted-commenters").resolve())

    def test_it_lists_one_login_per_line_and_starts_with_the_owner(self):
        logins = (REPO / "config/trusted-commenters").read_text().split()
        self.assertEqual(logins[0], "nicolu" "raschi")
        self.assertTrue(all("/" not in l for l in logins))


class LefthookCheckTests(InstallFixture):
    """With a root lefthook.yml (the public checkout), the installer checks lefthook is there
    and is the repo's pre-push hook, and says so in its final summary when it is not."""

    def setUp(self):
        super().setUp()
        self.tools = Path(self._td.name).resolve() / "tools"
        self.tools.mkdir()
        os.symlink(shutil.which("python3"), self.tools / "python3")
        self.path = f"{self.tools}:/usr/bin:/bin:/usr/sbin:/sbin"
        (self.repo / "lefthook.yml").write_text("pre-push:\n  commands: {}\n")

    def stub_lefthook(self):
        stub = self.tools / "lefthook"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    def install_hook(self, text="#!/bin/sh\n# lefthook hook\n"):
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True)
        hook = self.repo / ".git/hooks/pre-push"
        hook.write_text(text)
        hook.chmod(0o755)

    def run_install(self):
        env = dict(os.environ, HOME=str(self.home), PATH=self.path)
        return subprocess.run(["bash", str(self.repo / "install.sh")], env=env, capture_output=True,
                              text=True, timeout=300, stdin=subprocess.DEVNULL)

    def test_no_lefthook_yml_means_no_lefthook_check(self):
        (self.repo / "lefthook.yml").unlink()
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("lefthook", r.stdout)

    def test_lefthook_missing_from_path_is_warned_and_reaches_the_summary(self):
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("lefthook not found", r.stdout)
        self.assertIn("lefthook", self.summary(r))

    def test_lefthook_present_but_not_the_pre_push_hook_is_warned(self):
        self.stub_lefthook()
        self.install_hook("#!/bin/sh\necho some other hook\n")
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("lefthook install", self.summary(r))

    def test_no_pre_push_hook_at_all_is_warned(self):
        self.stub_lefthook()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True)
        r = self.run_install()
        self.assertIn("lefthook install", self.summary(r))

    def test_lefthook_installed_as_the_pre_push_hook_is_clean(self):
        self.stub_lefthook()
        self.install_hook()
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("lefthook", self.summary(r))
        self.assertNotIn("lefthook install", r.stdout)






class ExtraScannerPointerTests(InstallFixture):
    """The public pre-push guard and public-text-guard.py fail closed without the extra-scanner
    pointer, so the installer says when it is missing instead of letting the first push find out."""

    def test_a_missing_pointer_is_warned_and_reaches_the_summary(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("extra-scanner not found", r.stdout)
        self.assertIn("extra-scanner", self.summary(r))

    def test_a_symlinked_pointer_is_warned_like_a_missing_one(self):
        cfg = self.home / ".config/ai-workflow"
        cfg.mkdir(parents=True)
        (self.home / "elsewhere").write_text("/bin/true\n")
        (cfg / "extra-scanner").symlink_to(self.home / "elsewhere")
        r = self.install()
        self.assertIn("extra-scanner", self.summary(r))

    def pointer_to(self, text):
        (self.home / "scanner").write_text("#!/bin/sh\n")
        cfg = self.home / ".config/ai-workflow"
        cfg.mkdir(parents=True)
        (cfg / "extra-scanner").write_text(text)
        return self.install()

    def test_a_pointer_privacy_check_would_reject_is_warned(self):
        ok = f"{self.home}/scanner"
        for text in ("", "relative/scanner\n", f"{self.home}/no-such-scanner\n", f"{ok}\n{ok}\n",
                     f"{ok}\n\n"):
            with self.subTest(text=text):
                r = self.pointer_to(text)
                self.assertIn("extra-scanner", self.summary(r))
                shutil.rmtree(self.home / ".config/ai-workflow")

    def test_a_regular_pointer_file_naming_a_scanner_is_clean(self):
        r = self.pointer_to(f"{self.home}/scanner\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("extra-scanner not found", r.stdout)
        self.assertNotIn("extra-scanner", self.summary(r))


class PythonPrerequisiteTests(InstallFixture):
    """The hooks run under plain python3 (stdlib only): uv is not checked, and python3 must be
    3.11+ because the Codex config render imports tomllib."""

    def test_uv_is_not_checked(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("check uv", (REPO / "install.sh").read_text())
        self.assertNotRegex(r.stdout, r"uv (not found|\()")

    def test_a_python3_older_than_3_11_is_warned(self):
        tools = Path(self._td.name).resolve() / "tools"
        tools.mkdir()
        old = tools / "python3"
        # Only the version probe is answered as 3.9; every other python3 call runs the real one.
        old.write_text("#!/bin/sh\ncase \"$2\" in *version_info*) exit 1;; esac\n"
                       f"exec {shutil.which('python3')} \"$@\"\n")
        old.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home), PATH=f"{tools}:{os.environ['PATH']}")
        r = subprocess.run(["bash", str(self.repo / "install.sh")], env=env, capture_output=True,
                           text=True, timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("older than 3.11", r.stdout)
        self.assertIn("python3>=3.11", self.summary(r))

    def test_a_current_python3_is_not_warned(self):
        self.assertNotIn("older than 3.11", self.install().stdout)


class McpMergeTests(InstallFixture):
    """install.sh merges mcp/mcpServers.json into ~/.claude.json: the tracked entry wins, other
    servers and unrelated keys stay. HOME is a temp dir, so the live file is never touched."""

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_an_unpinned_entry_is_replaced_and_the_rest_is_kept(self):
        other = {"type": "stdio", "command": "other-cmd", "args": []}
        (self.home / ".claude.json").write_text(json.dumps({
            "theme": "dark",
            "mcpServers": {
                "chrome-devtools": {"type": "stdio", "command": "npx",
                                    "args": ["-y", "chrome-devtools-mcp@latest"], "env": {}},
                "other": other,
            },
        }))
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        merged = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(merged["mcpServers"]["chrome-devtools"]["args"],
                         ["-y", "chrome-devtools-mcp@1.12.0"])
        self.assertEqual(merged["mcpServers"]["other"], other)
        self.assertEqual(merged["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
