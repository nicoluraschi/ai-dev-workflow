#!/usr/bin/env python3
"""Tests for scripts/pre-push and export/root/lefthook.yml.

Run: python3 scripts/test_pre_push.py

Throwaway git repos in temp dirs, a fake HOME, a stub `gitleaks` and a stub extra scanner. The
hook is only ever run on local refs; nothing is pushed anywhere and the real $HOME is untouched.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/pre-push"
# In the private repo the file lives under export/root/; in the public repo it is at the root.
LEFTHOOK = next(p for p in (REPO / "export/root/lefthook.yml", REPO / "lefthook.yml") if p.is_file())
OWNER = "nicolu" "raschi"
URL = f"git@github.com:{OWNER}/ai-dev-workflow.git"
ZERO = "0" * 40
NOREPLY = "1234+someone@users.noreply.github.com"
STUB_SCANNER = '''\
import os, re, sys
hits = 0
for dp, dirs, files in os.walk(sys.argv[1]):
    for f in files:
        text = open(os.path.join(dp, f), errors="replace").read()
        for m in re.finditer("bannedone", text, re.I):
            print(f"BANNED   {f}: '{m.group(0)}'"); hits += 1
print(f"{hits} unexpected hits")
sys.exit(1 if hits else 0)
'''
STUB_GITLEAKS = '''#!/bin/sh
echo "$@" >> "$GITLEAKS_LOG"
[ -e "$GITLEAKS_FAIL" ] && exit 1
exit 0
'''


class PrePushTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "home"
        self.tools = self.root / "tools"
        self.repo = self.root / "repo"
        for d in (self.home, self.tools, self.repo):
            d.mkdir()
        os.symlink(shutil.which("git"), self.tools / "git")
        self.gitleaks = self.tools / "gitleaks"
        self.gitleaks.write_text(STUB_GITLEAKS)
        self.gitleaks.chmod(0o755)
        self.log = self.root / "gitleaks.log"
        self.fail_flag = self.root / "gitleaks.fail"
        self.cfg = self.home / ".config/ai-workflow"
        self.scanner = self.write(self.home / "private-scan/scan.py", STUB_SCANNER)
        self.write(self.cfg / "extra-scanner", f"{self.scanner}\n")
        self.write(self.cfg / "privacy-denylist", "planted-term\n")
        self.git("init", "-q", "-b", "main")
        self.root_sha = self.commit("a.txt", "one\n", "init")
        self.write(self.cfg / "public-root", self.root_sha + "\n")

    def write(self, path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def git(self, *args, env=None):
        e = {**os.environ, "GIT_AUTHOR_NAME": "N", "GIT_COMMITTER_NAME": "N",
             "GIT_AUTHOR_EMAIL": NOREPLY, "GIT_COMMITTER_EMAIL": NOREPLY, **(env or {})}
        return subprocess.run(["git", *args], cwd=self.repo, env=e, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, name, text, message="msg", env=None):
        self.write(self.repo / name, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, env=env)
        return self.git("rev-parse", "HEAD")

    def push(self, lines, url=URL, stdin=None, path=None, extra_args=None):
        """Run the hook as lefthook would: `pre-push origin <url>` with ref lines on stdin."""
        text = stdin if stdin is not None else "".join(l + "\n" for l in lines)
        env = {"HOME": str(self.home), "PATH": path if path is not None else str(self.tools),
               "GITLEAKS_LOG": str(self.log), "GITLEAKS_FAIL": str(self.fail_flag),
               "GIT_CONFIG_NOSYSTEM": "1"}
        args = extra_args if extra_args is not None else ["origin", url]
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=text, text=True,
                              capture_output=True, cwd=self.repo, env=env, timeout=60)

    def ref(self, sha, remote_sha=ZERO, remote_ref="refs/heads/main"):
        return f"refs/heads/main {sha} {remote_ref} {remote_sha}"

    def gitleaks_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    # --- the clean path and what it runs -------------------------------------------------

    def test_a_clean_first_push_passes_and_scans_the_whole_ref(self):
        c = self.commit("a.txt", "two\n", "second")
        r = self.push([self.ref(c)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.gitleaks_calls(), [f"git --log-opts={c} --redact"])

    def test_a_later_push_scans_only_remote_to_local(self):
        c = self.commit("a.txt", "two\n", "second")
        self.assertEqual(self.push([self.ref(c, self.root_sha)]).returncode, 0)
        self.assertEqual(self.gitleaks_calls(), [f"git --log-opts={self.root_sha}..{c} --redact"])

    def test_every_ref_line_is_scanned(self):
        c = self.commit("a.txt", "two\n", "second")
        d = self.commit("a.txt", "three\n", "third")
        r = self.push([self.ref(c, self.root_sha), f"refs/heads/other {d} refs/heads/other {ZERO}"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.gitleaks_calls()), 2)

    def test_a_deletion_is_skipped(self):
        r = self.push([f"(delete) {ZERO} refs/heads/old {self.root_sha}"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.gitleaks_calls(), [])

    def test_no_ref_lines_on_stdin_fails(self):
        for text in ("", "\n\n"):
            r = self.push([], stdin=text)
            self.assertEqual(r.returncode, 1, text)
            self.assertIn("no ref", r.stderr)

    # --- AC 9: what blocks ------------------------------------------------------------------

    def test_a_planted_secret_blocks_through_gitleaks(self):
        c = self.commit("a.txt", "two\n", "second")
        self.fail_flag.write_text("")
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("gitleaks", r.stderr + r.stdout)

    def test_a_planted_banned_term_blocks(self):
        c = self.commit("a.txt", "see BannedOne here\n", "second")
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.txt:1", r.stdout)

    def test_a_planted_denylist_term_in_a_file_blocks(self):
        c = self.commit("a.txt", "has planted-term\n", "second")
        self.assertEqual(self.push([self.ref(c, self.root_sha)]).returncode, 1)

    def test_a_planted_denylist_term_in_a_commit_message_blocks(self):
        c = self.commit("a.txt", "two\n", "second\n\nmentions planted-term")
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("message", r.stdout)

    def test_a_term_added_then_removed_inside_the_range_still_blocks(self):
        self.commit("a.txt", "has planted-term\n", "second")
        c = self.commit("a.txt", "clean again\n", "third")
        self.assertEqual(self.push([self.ref(c, self.root_sha)]).returncode, 1)

    def test_a_term_before_the_pushed_range_does_not_block(self):
        a = self.commit("a.txt", "has planted-term\n", "second")
        c = self.commit("a.txt", "clean\n", "third")
        self.assertEqual(self.push([self.ref(c, a)]).returncode, 0)

    def test_a_non_allowlisted_author_email_blocks(self):
        c = self.commit("a.txt", "two\n", "second", env={"GIT_AUTHOR_EMAIL": "bob@" "gmail.com"})
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("author-email", r.stdout)

    def test_a_denylist_term_in_the_remote_ref_name_blocks(self):
        c = self.commit("a.txt", "two\n", "second")
        r = self.push([self.ref(c, self.root_sha, "refs/heads/feat-planted-term")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("remote ref", r.stdout + r.stderr)

    def test_a_denylist_term_in_a_pushed_tag_name_or_message_blocks(self):
        self.commit("a.txt", "two\n", "second")
        self.git("tag", "-a", "v1", "-m", "has planted-term")
        tag = self.git("rev-parse", "v1")
        r = self.push([f"refs/tags/v1 {tag} refs/tags/v1 {ZERO}"])
        self.assertEqual(r.returncode, 1)

    # --- AC 23: fail closed -----------------------------------------------------------------

    def test_missing_gitleaks_fails_closed(self):
        c = self.commit("a.txt", "two\n", "second")
        self.gitleaks.unlink()
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("gitleaks", r.stderr)

    def test_missing_scanner_or_denylist_or_an_empty_denylist_fails_closed(self):
        c = self.commit("a.txt", "two\n", "second")
        line = self.ref(c, self.root_sha)
        self.scanner.unlink()
        self.assertEqual(self.push([line]).returncode, 1)
        self.write(self.scanner, STUB_SCANNER)
        (self.cfg / "extra-scanner").unlink()
        r = self.push([line])
        self.assertEqual(r.returncode, 1)
        self.assertIn("extra-scanner", r.stderr)
        self.write(self.cfg / "extra-scanner", f"{self.scanner}\n")
        self.write(self.cfg / "privacy-denylist", "# nothing\n")
        self.assertEqual(self.push([line]).returncode, 1)
        (self.cfg / "privacy-denylist").unlink()
        self.assertEqual(self.push([line]).returncode, 1)

    # --- AC 11: the root and the URL ---------------------------------------------------------

    def test_a_missing_public_root_file_fails_closed(self):
        c = self.commit("a.txt", "two\n", "second")
        (self.cfg / "public-root").unlink()
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("public-root", r.stderr)

    def test_a_history_with_another_root_is_refused(self):
        self.write(self.cfg / "public-root", "f" * 40 + "\n")
        c = self.commit("a.txt", "two\n", "second")
        r = self.push([self.ref(c, self.root_sha)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("root", r.stderr)

    def test_a_second_root_in_the_pushed_history_is_refused(self):
        self.git("checkout", "-q", "--orphan", "other")
        self.git("rm", "-rqf", ".")
        o = self.commit("o.txt", "orphan\n", "orphan")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--allow-unrelated-histories", "-m", "merge", o)
        c = self.git("rev-parse", "HEAD")
        self.assertEqual(self.push([self.ref(c, self.root_sha)]).returncode, 1)

    def test_only_the_public_url_in_any_normalized_form_passes(self):
        c = self.commit("a.txt", "two\n", "second")
        line = self.ref(c, self.root_sha)
        for url in (URL, f"git@github.com:{OWNER}/ai-dev-workflow",
                    f"ssh://git@github.com/{OWNER}/ai-dev-workflow",
                    f"https://github.com/{OWNER}/ai-dev-workflow.git",
                    f"https://github.com/{OWNER}/ai-dev-workflow"):
            self.assertEqual(self.push([line], url=url).returncode, 0, url)
        for url in (f"git@github.com:{OWNER}/other.git", "https://example.com/o/r.git",
                    f"git@github.com:{OWNER}/ai-dev-workflow-fork.git", ""):
            r = self.push([line], url=url)
            self.assertEqual(r.returncode, 1, url)

    def test_wrong_arguments_fail(self):
        c = self.commit("a.txt", "two\n", "second")
        self.assertEqual(self.push([self.ref(c)], extra_args=[]).returncode, 1)

    def test_an_unreachable_remote_sha_is_refused_before_gitleaks(self):
        c = self.commit("a.txt", "two\n", "second")
        r = self.push([self.ref(c, "a" * 40)], extra_args=["public", URL])
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"remote sha {'a' * 40} is not a local commit", r.stderr)
        self.assertIn("git fetch public", r.stderr)
        self.assertEqual(self.gitleaks_calls(), [])

    def test_an_unreachable_remote_sha_keeps_the_other_refusals(self):
        self.write(self.cfg / "public-root", "f" * 40 + "\n")
        c = self.commit("a.txt", "two\n", "second")
        r = self.push([self.ref(c, "a" * 40)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("not the approved public-root", r.stderr)
        self.assertIn("not a local commit", r.stderr)

    def test_replacing_an_unrelated_remote_root_that_is_fetched_passes(self):
        self.git("checkout", "-q", "--orphan", "old")
        self.git("rm", "-rqf", ".")
        old = self.commit("o.txt", "old root\n", "old root")
        self.git("checkout", "-q", "main")
        c = self.commit("a.txt", "two\n", "second")
        r = self.push([self.ref(c, old)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.gitleaks_calls(), [f"git --log-opts={old}..{c} --redact"])

    def test_a_malformed_ref_line_fails(self):
        self.assertEqual(self.push(["only three fields here"]).returncode, 1)


def wrapper():
    """The lefthook script that runs scripts/pre-push (export/root/ here, root in the public repo)."""
    rel = ".lefthook/pre-push/public-guard.sh"
    return next((p for p in (REPO / "export/root" / rel, REPO / rel) if p.is_file()), None)


class LefthookWiringTests(unittest.TestCase):
    def test_pre_push_is_a_script_job_with_stdin(self):
        # A `commands:` job is skipped by lefthook 2 when the checked-out branch has no file
        # changes ("no matching push files") — the guard would fail open. A `scripts:` job is not.
        text = LEFTHOOK.read_text()
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(lines[0], "pre-push:")
        self.assertIn("scripts:", lines)
        self.assertNotIn("commands:", lines)
        self.assertIn('"public-guard.sh":', lines)
        self.assertIn("use_stdin: true", lines)
        w = wrapper()
        self.assertIsNotNone(w, "missing .lefthook/pre-push/public-guard.sh")
        self.assertIn('exec scripts/pre-push "$@"', w.read_text())

    def lefthook_push(self, stdin, change_files):
        lefthook = shutil.which("lefthook")
        if not lefthook:
            self.skipTest("lefthook is not installed")
        self.assertIsNotNone(wrapper(), "missing .lefthook/pre-push/public-guard.sh")
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        d = Path(td.name)
        (d / "scripts").mkdir()
        probe = d / "scripts/pre-push"
        probe.write_text('#!/bin/sh\necho "args=$1 $2" > "$(git rev-parse --show-toplevel)/../probe.out"\n'
                         'cat >> "$(git rev-parse --show-toplevel)/../probe.out"\nexit 1\n')
        probe.chmod(0o755)
        shutil.copy(LEFTHOOK, d / "lefthook.yml")
        (d / ".lefthook/pre-push").mkdir(parents=True)
        shutil.copy(wrapper(), d / ".lefthook/pre-push/public-guard.sh")
        env = {**os.environ, "GIT_AUTHOR_NAME": "n", "GIT_COMMITTER_NAME": "n",
               "GIT_AUTHOR_EMAIL": "n@example.com", "GIT_COMMITTER_EMAIL": "n@example.com"}
        env.pop("LEFTHOOK", None)
        def git(*args):
            subprocess.run(["git", *args], cwd=d, env=env, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-qm", "x")
        if change_files:
            git("checkout", "-qb", "topic")
            (d / "f.txt").write_text("f\n")
            git("add", "f.txt")
            git("commit", "-qm", "z")
        r = subprocess.run([lefthook, "run", "pre-push", "origin", URL, "--no-auto-install",
                            "--no-tty", "--colors", "off"], cwd=d, env=env, input=stdin,
                           text=True, capture_output=True, timeout=60)
        out = d.parent / "probe.out"
        seen = out.read_text() if out.exists() else None
        if out.exists():
            out.unlink()
        return r, seen

    def test_lefthook_really_passes_the_args_and_the_stdin(self):
        r, seen = self.lefthook_push("a b c d\n", change_files=True)
        self.assertEqual(seen, f"args=origin {URL}\na b c d\n", r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0, "the guard's refusal must fail the push")

    def test_lefthook_runs_the_guard_with_no_changed_files_and_empty_stdin(self):
        # HEAD == main: no push files. The guard must still run (and refuse the empty stdin).
        r, seen = self.lefthook_push("", change_files=False)
        self.assertEqual(seen, f"args=origin {URL}\n", r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
