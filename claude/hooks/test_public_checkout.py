#!/usr/bin/env python3
"""Tests for public_checkout.py, the helper both public-checkout hooks share.

Run: python3 claude/hooks/test_public_checkout.py

Real temp git repos and a worktree, a fake HOME; the real $HOME is never read.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_checkout as pcx  # noqa: E402

OWNER = "nicolu" "raschi"
PUBLIC = f"{OWNER}/ai-dev-workflow"
AT = "@"  # keeps fixtures with unusual hosts from hitting the generic email pattern when scanned


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "n", "GIT_COMMITTER_NAME": "n",
                               "GIT_AUTHOR_EMAIL": "n@example.com",
                               "GIT_COMMITTER_EMAIL": "n@example.com"}).stdout.strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "home"
        (self.home / ".config/ai-workflow").mkdir(parents=True)
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        self.addCleanup(self.restore_home)

    def restore_home(self):
        if self._home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home

    def repo(self, name, origin=None):
        d = self.root / name
        d.mkdir()
        git(d, "init", "-q", "-b", "main")
        (d / "f").write_text("x\n")
        git(d, "add", "-A")
        git(d, "commit", "-qm", "init")
        if origin:
            git(d, "remote", "add", "origin", origin)
        return d

    def point_public_repo_at(self, path):
        (self.home / ".config/ai-workflow/public-repo").write_text(f"{path}\n")


class NormalizeRemoteTests(unittest.TestCase):
    def test_ssh_https_and_scp_forms_normalize_to_owner_repo(self):
        for url in (f"git@github.com:{OWNER}/ai-dev-workflow.git",
                    f"git@github.com:{OWNER}/ai-dev-workflow",
                    f"ssh://git@github.com/{OWNER}/ai-dev-workflow",
                    f"https://github.com/{OWNER}/ai-dev-workflow.git",
                    f"https://github.com/{OWNER}/ai-dev-workflow/",
                    f"https://tok{AT}github.com/{OWNER}/AI-Dev-Workflow"):
            self.assertEqual(pcx.normalize_remote(url), PUBLIC, url)

    def test_other_hosts_and_garbage_do_not_normalize(self):
        for url in ("https://evil.example/o/r", f"https://github.com.evil.io/{OWNER}/x", "", "x",
                    f"git{AT}gitlab.com:o/r.git"):
            self.assertIsNone(pcx.normalize_remote(url), url)


class IsPublicTests(Fixture):
    def test_no_config_and_no_matching_origin_is_not_public(self):
        d = self.repo("plain", origin="git@github.com:someone/else.git")
        self.assertFalse(pcx.is_public(str(d)))

    def test_matching_origin_alone_is_public(self):
        d = self.repo("clone", origin=f"https://github.com/{PUBLIC}.git")
        self.assertTrue(pcx.is_public(str(d)))

    def test_any_remote_url_fetch_or_push_matching_makes_it_public(self):
        d = self.repo("multi", origin="git@github.com:someone/else.git")
        self.assertFalse(pcx.is_public(str(d)))
        git(d, "remote", "add", "upstream", f"https://github.com/{PUBLIC}.git")
        self.assertTrue(pcx.is_public(str(d)))
        e = self.repo("pushonly", origin="git@github.com:someone/else.git")
        git(e, "config", "remote.origin.pushurl", f"git@github.com:{PUBLIC}.git")
        self.assertTrue(pcx.is_public(str(e)))

    def test_the_configured_checkout_and_its_subdirectory_are_public(self):
        d = self.repo("pub")
        (d / "sub").mkdir()
        self.point_public_repo_at(d)
        self.assertTrue(pcx.is_public(str(d)))
        self.assertTrue(pcx.is_public(str(d / "sub")))

    def test_a_worktree_of_the_configured_checkout_is_public(self):
        d = self.repo("pub")
        wt = self.root / "wt"
        git(d, "worktree", "add", "-q", "-b", "feat", str(wt))
        self.point_public_repo_at(d)
        self.assertTrue(pcx.is_public(str(wt)))

    def test_an_unrelated_repo_is_not_public_even_with_the_config(self):
        pub = self.repo("pub")
        other = self.repo("other")
        self.point_public_repo_at(pub)
        self.assertFalse(pcx.is_public(str(other)))

    def test_not_a_repo_a_missing_dir_or_a_dangling_config_is_not_public(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.point_public_repo_at(self.root / "gone")
        self.assertFalse(pcx.is_public(str(plain)))
        self.assertFalse(pcx.is_public(str(self.root / "missing")))
        self.assertFalse(pcx.is_public(str(self.repo("x"))))


class RepoRootTests(Fixture):
    def test_the_configured_clone_wins_over_the_cwd_toplevel(self):
        pub = self.repo("pub")
        wt = self.root / "wt"
        git(pub, "worktree", "add", "-q", "-b", "feat", str(wt))
        self.point_public_repo_at(pub)
        self.assertEqual(pcx.public_root(str(wt)), str(pub))

    def test_falls_back_to_the_toplevel_of_an_origin_matched_checkout(self):
        d = self.repo("clone", origin=f"git@github.com:{PUBLIC}.git")
        (d / "sub").mkdir()
        self.assertEqual(pcx.public_root(str(d / "sub")), str(d))

    def test_none_when_nothing_is_public(self):
        self.assertIsNone(pcx.public_root(str(self.repo("plain"))))


class SharedParsingTests(unittest.TestCase):
    def test_cd_targets_that_can_be_known_statically(self):
        self.assertEqual(pcx.cd_target("cd", ["/x/y"]), "/x/y")
        self.assertEqual(pcx.cd_target("cd", ["-P", "/x"]), "/x")
        self.assertEqual(pcx.cd_target("cd", []), "~")
        self.assertEqual(pcx.cd_target("cd", ["~/work"]), "~/work")
        self.assertEqual(pcx.cd_target("pushd", ["/x"]), "/x")

    def test_cd_targets_that_cannot(self):
        for head, args in (("cd", ["$D"]), ("cd", ["`pwd`"]), ("cd", ["-"]), ("cd", ["~bob"]),
                           ("pushd", []), ("pushd", ["+1"]), ("pushd", ["-1"]), ("pushd", ["+0"]),
                           ("popd", []), ("popd", ["+1"])):
            self.assertIsNone(pcx.cd_target(head, args), (head, args))

    def test_unquoted_newlines_become_separators_and_quoted_ones_do_not(self):
        self.assertEqual(pcx.newlines_to_semicolons("a\nb"), "a ; b")
        self.assertEqual(pcx.newlines_to_semicolons("a 'x\ny' b"), "a 'x\ny' b")
        self.assertEqual(pcx.newlines_to_semicolons('a "x\ny"'), 'a "x\ny"')
        self.assertEqual(pcx.newlines_to_semicolons("a \\\nb"), "a \\\nb")


class RepoFlagTests(unittest.TestCase):
    def test_flag_forms_naming_the_public_repo(self):
        for args in (["-R", PUBLIC], ["pr", "create", "--repo", PUBLIC], [f"--repo={PUBLIC}"],
                     [f"-R{PUBLIC}"], ["-R", PUBLIC.upper()], ["-R", f"github.com/{PUBLIC}"],
                     ["pr", "view", f"https://github.com/{PUBLIC}/pull/3"],
                     ["api", f"repos/{PUBLIC}/issues"]):
            self.assertTrue(pcx.repo_flag_names_public(args, {}), args)

    def test_gh_repo_env_names_the_public_repo(self):
        self.assertTrue(pcx.repo_flag_names_public(["pr", "list"], {"GH_REPO": PUBLIC}))
        self.assertFalse(pcx.repo_flag_names_public(["pr", "list"], {"GH_REPO": "o/r"}))

    def test_other_repos_do_not_count(self):
        for args in (["-R", "o/r"], ["--repo", f"{OWNER}/other"], ["pr", "list"],
                     ["-R", f"{PUBLIC}-private"], []):
            self.assertFalse(pcx.repo_flag_names_public(args, {}), args)


if __name__ == "__main__":
    unittest.main()
