#!/usr/bin/env python3
"""Tests for scripts/privacy-check.

Run: python3 scripts/test_privacy_check.py

Every test uses a fake HOME in a temp dir, a STUB scanner that mimics the real one's interface
(`python3 -I <scan.py> <dir>`; BANNED/WATCH lines; exit 1 on a hit) and throwaway git repos.
The real $HOME, the real scanner and the real denylist are never read. Fixtures that would hit
the generic patterns are built from pieces so this file scans clean itself.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "privacy-check"
_loader = SourceFileLoader("privacy_check", str(SCRIPT))
_spec = importlib.util.spec_from_loader("privacy_check", _loader)
pc = importlib.util.module_from_spec(_spec)
_loader.exec_module(pc)

OWNER = "nicolu" "raschi"
HOME_MAC = "/Us" "ers/"
HOME_LINUX = "/ho" "me/"
NOREPLY = "1234+someone@users.noreply.github.com"


def fx(text):
    """Fixture text is written with [at] and [dot] so this file scans clean itself."""
    return text.replace("[at]", "@").replace("[dot]", ".")


STUB_SCANNER = '''\
import os, re, sys
BANNED = ["bannedone", "styleword", "clientco"]
WATCH = ["watchlang"]
root = sys.argv[1]
hits = 0
for dp, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d != ".git"]
    for f in sorted(files):
        rel = os.path.relpath(os.path.join(dp, f), root)
        text = open(os.path.join(dp, f), errors="replace").read()
        for kind, words in (("BANNED", BANNED), ("WATCH", WATCH)):
            for w in words:
                for m in re.finditer(re.escape(w), text, re.I):
                    print(f"{kind:<8} {rel}: '{m.group(0)}'")
                    hits += 1
print(f"{hits} unexpected hits")
sys.exit(1 if hits else 0)
'''


class GenericPatternTests(unittest.TestCase):
    def hits(self, text):
        return [kind for kind, _ in pc.generic_hits(fx(text))]

    def test_home_paths_hit_for_any_real_name(self):
        self.assertEqual(self.hits(f"see {HOME_MAC}bob/code"), ["home path"])
        self.assertEqual(self.hits(f"cd {HOME_LINUX}alice"), ["home path"])
        self.assertEqual(self.hits(f"{HOME_MAC}Shared/x"), ["home path"])

    def test_placeholder_names_and_prefixed_forms_pass(self):
        for text in (f"{HOME_MAC}x/a", f"{HOME_MAC}user/a", f"{HOME_MAC}me/a", f"{HOME_LINUX}you/a",
                     f"{HOME_LINUX}example/a", f"{HOME_MAC}<name>/a",
                     f"${{X}}{HOME_LINUX}worktrees", f"$HOME{HOME_MAC}x", f"a/{HOME_LINUX}bob",
                     f"./{HOME_LINUX}bob", "~/worktrees/repo"):
            self.assertEqual(self.hits(text), [], text)

    def test_emails_only_noreply_and_reserved_domains_pass(self):
        for ok in (NOREPLY, "41898282+github-actions[bot]@users.noreply.github.com",
                   "noreply@github.com", "noreply@anthropic.com", "git@github.com:o/r.git",
                   "t@example.com", "a@example.org", "a@example.net", "a@mail.example.com",
                   "a@host.example", "a@x.test", "a@x.invalid", "a@box.localhost",
                   "A@EXAMPLE.COM"):
            self.assertEqual(self.hits(f"mail {ok} now"), [], ok)
        for bad in ("bob[at]gmail.com", "bob[at]corp.io", "12+x[at]users.noreply.github.org",
                    "x[at]users.noreply.github.com", "bob[at]example.com.evil.io",
                    "x[bot][at]evil.com", "noreply[at]evil.com"):
            self.assertEqual(self.hits(f"mail {bad} now"), ["email"], bad)

    def test_file_localhost_urls_and_a_gt_before_a_home_path_hit(self):
        for text in (f"file://localhost{HOME_MAC}bob/x", f"file://localhost{HOME_LINUX}alice",
                     f"a>{HOME_LINUX}bob", f"x >{HOME_MAC}bob", f"1 > {HOME_MAC}bob",
                     f"</td>{HOME_MAC}bob", f"<td>{HOME_LINUX}worktrees",
                     f"<code>{HOME_MAC}realperson/x</code>", f"<td>{HOME_MAC}realperson</td>",
                     f"{HOME_MAC}<b>realname/x"):
            self.assertEqual(self.hits(text), ["home path"], text)
        for text in (f"file://localhost{HOME_MAC}x/a", f'<code class="path">{HOME_MAC}x/y'):
            self.assertEqual(self.hits(text), [], text)

    def test_file_urls_to_home_paths_hit(self):
        for text in (f"file://{HOME_MAC}bob/x", f"open file://{HOME_LINUX}alice/y"):
            self.assertEqual(self.hits(text), ["home path"], text)
        for text in (f"file://{HOME_MAC}x/a", f"file://{HOME_LINUX}user/a", "file:///tmp/x",
                     f"file://host{HOME_MAC}bob"):
            self.assertEqual(self.hits(text), [], text)

    def test_version_pins_are_not_emails(self):
        self.assertEqual(self.hits("npm i pkg@1.2.3 and @types/node"), [])

    def test_atlassian_hosts_other_than_example_hit(self):
        self.assertEqual(self.hits("https://acme.atlassian[dot]net/browse/X-1"), ["atlassian host"])
        self.assertEqual(self.hits("ACME.Atlassian[dot]Net."), ["atlassian host"])
        self.assertEqual(self.hits("a.example.atlassian[dot]net"), ["atlassian host"])
        self.assertEqual(self.hits("notexample.atlassian[dot]net"), ["atlassian host"])
        for ok in ("example.atlassian[dot]net", "https://EXAMPLE.atlassian[dot]net./x", ".atlassian[dot]net",
                   "atlassian[dot]net", "an atlassian net thing"):
            self.assertEqual(self.hits(ok), [], ok)

    def test_links_to_other_owner_repos_hit_in_every_form(self):
        for text in (f"https://github.com/{OWNER}/other", f"git@github.com:{OWNER}/other.git",
                     f"ssh://git@github.com/{OWNER}/other", f"see {OWNER}/other here",
                     f"GitHub.com/{OWNER.upper()}/Other", f"{OWNER}/ai-dev-workflow-private"):
            self.assertEqual(self.hits(text), ["repo link"], text)
        for text in (f"https://github.com/{OWNER}/ai-dev-workflow", f"{OWNER}/AI-Dev-Workflow.git",
                     f"git@github.com:{OWNER}/ai-dev-workflow.git", f"by {OWNER}", f"x{OWNER}/y"):
            self.assertEqual(self.hits(text), [], text)

    def test_public_repo_constant(self):
        self.assertEqual(pc.PUBLIC_REPO, f"{OWNER}/ai-dev-workflow")


class Fixture(unittest.TestCase):
    """A fake HOME, a PATH holding only git and a stub gitleaks, and a stub scanner."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "home"
        self.tools = self.root / "tools"
        self.work = self.root / "work"
        for d in (self.home, self.tools, self.work):
            d.mkdir()
        os.symlink(shutil.which("git"), self.tools / "git")
        self.gitleaks = self.tools / "gitleaks"
        self.gitleaks.write_text("#!/bin/sh\nexit 0\n")
        self.gitleaks.chmod(0o755)
        self.scanner = self.home / "private-scan/scan.py"
        self.pointer = self.home / ".config/ai-workflow/extra-scanner"

    def private_setup(self, denylist="planted-term\n", scanner=STUB_SCANNER):
        if scanner is not None:
            self.write(self.scanner, scanner)
            self.write(self.pointer, f"{self.scanner}\n")
        if denylist is not None:
            self.write(self.home / ".config/ai-workflow/privacy-denylist", denylist)

    def write(self, path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fx(text).encode() if isinstance(text, str) else text)
        return path

    def run_pc(self, *args, stdin="", cwd=None):
        env = {"HOME": str(self.home), "PATH": str(self.tools), "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=fx(stdin), text=True,
                              capture_output=True, cwd=str(cwd or self.work), env=env, timeout=60)


class PathAndStdinTests(Fixture):
    def test_clean_file_exits_0(self):
        f = self.write(self.work / "a.txt", "nothing here\n")
        r = self.run_pc(str(f))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_hit_reports_file_and_line_and_exits_1(self):
        f = self.write(self.work / "a.txt", f"fine\nmail bob[at]gmail.com\n")
        r = self.run_pc(str(f))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{f}:2", r.stdout)
        self.assertIn("email", r.stdout)

    def test_directories_are_walked_and_git_is_skipped(self):
        self.write(self.work / "sub/deep/a.txt", "x\nbob[at]gmail.com\n")
        self.write(self.work / ".git/config", "bob[at]gmail.com\n")
        r = self.run_pc(str(self.work))
        self.assertEqual(r.returncode, 1)
        self.assertIn("sub/deep/a.txt:2", r.stdout)
        self.assertNotIn(".git/config", r.stdout)

    def test_a_git_checkout_is_scanned_as_tracked_plus_untracked_unignored(self):
        subprocess.run(["git", "init", "-q", str(self.work)], check=True, env=os.environ)
        self.write(self.work / ".gitignore", "ignored.txt\n")
        self.write(self.work / "ignored.txt", "bob[at]gmail.com\n")
        self.write(self.work / "kept.txt", "clean\n")
        self.assertEqual(self.run_pc(str(self.work)).returncode, 0)
        self.write(self.work / "untracked.txt", "bob[at]gmail.com\n")
        r = self.run_pc(str(self.work))
        self.assertEqual(r.returncode, 1)
        self.assertIn("untracked.txt:1", r.stdout)
        self.assertNotIn("ignored.txt", r.stdout)

    def test_binary_files_and_symlinks_are_skipped(self):
        (self.work / "b.bin").write_bytes(b"\x00bob[at]gmail.com\n")
        os.symlink(self.work / "b.bin", self.work / "link.txt")
        self.assertEqual(self.run_pc(str(self.work)).returncode, 0)

    def test_private_mode_fails_closed_on_a_binary_or_non_utf8_path_input(self):
        self.private_setup()
        nul = self.work / "nul.dat"
        nul.write_bytes(b"abc\x00def\n")
        bad = self.work / "latin.txt"
        bad.write_bytes(b"caf\xe9\n")
        for f in (nul, bad):
            r = self.run_pc("--private", str(f))
            self.assertEqual(r.returncode, 2, f)
            self.assertIn(str(f), r.stderr)
        r = self.run_pc("--private", str(self.work))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.run_pc(str(nul)).returncode, 0)  # generic mode still skips it

    def test_missing_path_is_an_internal_error(self):
        r = self.run_pc(str(self.work / "nope"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope", r.stderr)

    def test_stdin_hits_are_located_as_stdin_lines(self):
        r = self.run_pc("--stdin", stdin="ok\nsee https://acme.atlassian[dot]net/x\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("<stdin>:2", r.stdout)
        self.assertEqual(self.run_pc("--stdin", stdin="all clean\n").returncode, 0)

    def test_no_input_is_a_usage_error(self):
        self.assertEqual(self.run_pc().returncode, 2)

    def test_the_script_does_not_hit_itself(self):
        r = self.run_pc(str(SCRIPT), str(Path(__file__).resolve()))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)


class PrivateModeTests(Fixture):
    def test_missing_prerequisites_fail_closed_with_exit_2(self):
        f = self.write(self.work / "a.txt", "clean\n")
        cases = {
            "gitleaks": lambda: self.gitleaks.unlink(),
            "scanner": lambda: self.scanner.unlink(),
            "denylist missing": lambda: (self.home / ".config/ai-workflow/privacy-denylist").unlink(),
            "denylist empty": lambda: self.write(
                self.home / ".config/ai-workflow/privacy-denylist", "\n# only a comment\n\n"),
            "denylist unreadable": lambda: os.chmod(
                self.home / ".config/ai-workflow/privacy-denylist", 0),
        }
        for name, break_it in cases.items():
            with self.subTest(name):
                self.private_setup()
                self.gitleaks.write_text("#!/bin/sh\nexit 0\n")
                self.gitleaks.chmod(0o755)
                break_it()
                r = self.run_pc("--private", str(f))
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertTrue(r.stderr.strip())
                self.assertNotIn("planted-term", r.stdout + r.stderr)
                os.chmod(self.home / ".config/ai-workflow/privacy-denylist", 0o644) \
                    if (self.home / ".config/ai-workflow/privacy-denylist").exists() else None

    def test_a_bad_extra_scanner_pointer_fails_closed_without_printing_it(self):
        f = self.write(self.work / "a.txt", "clean\n")
        cases = {
            "pointer missing": lambda: self.pointer.unlink(),
            "pointer empty": lambda: self.write(self.pointer, "\n"),
            "two lines": lambda: self.write(self.pointer, f"{self.scanner}\n{self.scanner}\n"),
            "relative path": lambda: self.write(self.pointer, "private-scan/scan.py\n"),
            "tilde path": lambda: self.write(self.pointer, "~/private-scan/scan.py\n"),
            "target is a directory": lambda: self.write(self.pointer, f"{self.scanner.parent}\n"),
            "pointer is a symlink": lambda: (
                self.write(self.home / "elsewhere", f"{self.scanner}\n"),
                self.pointer.unlink(), self.pointer.symlink_to(self.home / "elsewhere")),
            "pointer unreadable": lambda: os.chmod(self.pointer, 0),
        }
        for name, break_it in cases.items():
            with self.subTest(name):
                if self.pointer.is_symlink() or self.pointer.exists():
                    self.pointer.unlink()
                self.private_setup()
                break_it()
                r = self.run_pc("--private", str(f))
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("extra-scanner", r.stderr)
                self.assertNotIn("private-scan", r.stdout + r.stderr)

    def test_the_extra_scanner_named_by_the_pointer_runs(self):
        self.private_setup()
        f = self.write(self.work / "a.txt", "ok\na bannedone here\n")
        r = self.run_pc("--private", str(f))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(f"{f}:2: BANNED term", r.stdout)


    def test_denylist_term_hits_case_insensitively_and_is_never_printed(self):
        self.private_setup(denylist="# friends\n\nPlanted-Term\n")
        f = self.write(self.work / "a.txt", "ok\nthis has a PLANTED-term inside\n")
        r = self.run_pc("--private", str(f))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{f}:2", r.stdout)
        self.assertIn("denylist", r.stdout)
        self.assertNotIn("planted", r.stdout.lower().replace("denylist", ""))

    def test_banned_hit_is_located_by_line_and_the_match_is_not_printed(self):
        self.private_setup()
        f = self.write(self.work / "a.txt", "ok\nok\nsome ClientCo thing\n")
        r = self.run_pc("--private", str(f))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{f}:3", r.stdout)
        self.assertIn("BANNED", r.stdout)
        self.assertNotIn("clientco", r.stdout.lower())

    def test_allowlisted_word_passes_but_a_mixed_line_does_not(self):
        self.private_setup()
        allow = self.write(self.work / "allow.txt", "styleword\tstyle word, not private\n")
        f = self.write(self.work / "a.txt", "plan styleword and Styleword\nstyleword with clientco\n")
        r = self.run_pc("--private", "--allow", str(allow), str(f))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn(f"{f}:1", r.stdout)
        self.assertIn(f"{f}:2", r.stdout)

    def test_allowlist_never_suppresses_denylist_or_generic_hits(self):
        self.private_setup(denylist="styleword\n")
        allow = self.write(self.work / "allow.txt", "styleword\treason\n")
        f = self.write(self.work / "a.txt", "plan styleword\nbob[at]gmail.com styleword\n")
        r = self.run_pc("--private", "--allow", str(allow), str(f))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{f}:1", r.stdout)
        self.assertIn(f"{f}:2", r.stdout)

    def test_watch_hits_are_info_and_never_fail(self):
        self.private_setup()
        f = self.write(self.work / "a.txt", "we like WatchLang\n")
        r = self.run_pc("--private", str(f))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WATCH", r.stdout)
        self.assertIn(f"{f}:1", r.stdout)

    def test_clean_input_exits_0_in_private_mode(self):
        self.private_setup()
        f = self.write(self.work / "a.txt", "clean\n\n   \nclean\n")
        r = self.run_pc("--private", str(f))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_scanner_crash_or_unparsable_output_fails_closed(self):
        f = self.write(self.work / "a.txt", "clean\n")
        for body in ("import sys\nsys.exit(3)\n", "raise SystemExit('boom')\n",
                     "import sys\nprint('garbage')\nsys.exit(1)\n"):
            self.private_setup(scanner=body)
            r = self.run_pc("--private", str(f))
            self.assertEqual(r.returncode, 2, body)

    def test_stdin_is_scanned_privately_too(self):
        self.private_setup()
        r = self.run_pc("--private", "--stdin", stdin="branch-planted-term\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("<stdin>:1", r.stdout)

    def test_default_allowlist_is_found_at_the_repo_root_then_export_root(self):
        self.private_setup()
        subprocess.run(["git", "init", "-q", str(self.work)], check=True, env=os.environ)
        f = self.write(self.work / "a.txt", "plan styleword\n")
        self.assertEqual(self.run_pc("--private", str(f)).returncode, 1)
        self.write(self.work / "export/root/.privacy-allow", "styleword\treason\n")
        self.assertEqual(self.run_pc("--private", str(f)).returncode, 0)
        self.write(self.work / ".privacy-allow", "other\treason\n")  # root file wins
        self.assertEqual(self.run_pc("--private", str(f)).returncode, 1)

    def test_malformed_allowlist_lines_exit_2(self):
        self.private_setup()
        f = self.write(self.work / "a.txt", "clean\n")
        for bad in ("noreason\n", "two words\treason\n", "re.gex\treason\n", "word\t   \n",
                    "\treason\n", "a*\treason\n"):
            allow = self.write(self.work / "allow.txt", bad)
            r = self.run_pc("--private", "--allow", str(allow), str(f))
            self.assertEqual(r.returncode, 2, repr(bad))
            self.assertIn("allow.txt:1", r.stderr)

    def test_allowlist_comments_and_blank_lines_are_fine(self):
        self.private_setup()
        allow = self.write(self.work / "allow.txt", "# why\n\nstyleword\tstyle\n")
        f = self.write(self.work / "a.txt", "styleword\n")
        self.assertEqual(self.run_pc("--private", "--allow", str(allow), str(f)).returncode, 0)


class CheckAllowTests(Fixture):
    def test_clean_allowlist_exits_0(self):
        self.private_setup(denylist="friendname\n")
        allow = self.write(self.work / "allow.txt", "styleword\treason\n")
        r = self.run_pc("--check-allow", "--allow", str(allow))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_overlap_in_either_direction_fails_and_prints_only_line_numbers(self):
        self.private_setup(denylist="acme-corp-secret\nshort\n")
        allow = self.write(self.work / "allow.txt",
                           "styleword\treason\nacme\treason\nxshortx\treason\n")
        r = self.run_pc("--check-allow", "--allow", str(allow))
        self.assertEqual(r.returncode, 1)
        self.assertIn("2", r.stdout)
        self.assertIn("3", r.stdout)
        for secret in ("acme", "short", "secret"):
            self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertNotIn("styleword", r.stdout)

    def test_the_denylist_is_required_and_fails_closed(self):
        self.private_setup(denylist=None)
        allow = self.write(self.work / "allow.txt", "styleword\treason\n")
        self.assertEqual(self.run_pc("--check-allow", "--allow", str(allow)).returncode, 2)
        self.private_setup(denylist="# nothing\n")
        self.assertEqual(self.run_pc("--check-allow", "--allow", str(allow)).returncode, 2)



class RangeTests(Fixture):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")

    def git(self, *args, env=None):
        e = {**os.environ, "GIT_AUTHOR_NAME": "N", "GIT_COMMITTER_NAME": "N",
             "GIT_AUTHOR_EMAIL": NOREPLY, "GIT_COMMITTER_EMAIL": NOREPLY,
             **{k: fx(v) for k, v in (env or {}).items()}}
        return subprocess.run(["git", *map(fx, args)], cwd=self.repo, env=e, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, name, text, message="msg", env=None):
        self.write(self.repo / name, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, env=env)
        return self.git("rev-parse", "HEAD")

    def check(self, rng, *extra):
        return self.run_pc(*extra, "--range", rng, cwd=self.repo)

    def test_clean_range_exits_0(self):
        base = self.commit("a.txt", "one\n")
        self.commit("a.txt", "one\ntwo\n", message="add two")
        r = self.check(f"{base}..HEAD")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_added_line_hit_is_located_by_sha_file_and_line(self):
        base = self.commit("a.txt", "one\n")
        bad = self.commit("a.txt", "one\ntwo\nmail bob[at]gmail.com\n")
        r = self.check(f"{base}..HEAD")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{bad[:12]} a.txt:3", r.stdout)

    def test_a_term_added_then_removed_inside_the_range_still_hits(self):
        base = self.commit("a.txt", "one\n")
        bad = self.commit("a.txt", "one\nbob[at]gmail.com\n")
        self.commit("a.txt", "one\n")
        r = self.check(f"{base}..HEAD")
        self.assertEqual(r.returncode, 1)
        self.assertIn(bad[:12], r.stdout)

    def test_removed_lines_and_commits_before_the_range_do_not_hit(self):
        self.commit("a.txt", "one\nbob[at]gmail.com\n")
        base = self.commit("a.txt", "one\nbob[at]gmail.com\nmore\n")
        self.commit("a.txt", "one\nmore\n")
        self.assertEqual(self.check(f"{base}..HEAD").returncode, 0)

    def test_a_bare_revision_scans_the_whole_history(self):
        self.commit("a.txt", "bob[at]gmail.com\n")
        self.commit("a.txt", "clean\n")
        self.assertEqual(self.check("HEAD").returncode, 1)

    def test_commit_message_hit_in_private_mode_only_with_the_denylist(self):
        self.private_setup()
        base = self.commit("a.txt", "one\n")
        bad = self.commit("a.txt", "two\n", message="subject\n\nbody has planted-term here")
        r = self.check(f"{base}..HEAD", "--private")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{bad[:12]} message:3", r.stdout)
        self.assertEqual(self.check(f"{base}..HEAD").returncode, 0)

    def test_denylist_term_in_added_lines_in_private_mode(self):
        self.private_setup()
        base = self.commit("a.txt", "one\n")
        self.commit("a.txt", "one\nplanted-term\n")
        r = self.check(f"{base}..HEAD", "--private")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.txt:2", r.stdout)

    def test_non_noreply_author_and_committer_emails_hit(self):
        base = self.commit("a.txt", "one\n")
        a = self.commit("a.txt", "two\n", env={"GIT_AUTHOR_EMAIL": "bob[at]gmail.com"})
        r = self.check(f"{base}..HEAD")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{a[:12]} author-email", r.stdout)
        c = self.commit("a.txt", "three\n", env={"GIT_COMMITTER_EMAIL": "bob[at]gmail.com"})
        r = self.check(f"{a}..HEAD")
        self.assertIn(f"{c[:12]} committer-email", r.stdout)

    def test_annotated_tag_message_and_tagger_email_are_scanned(self):
        base = self.commit("a.txt", "one\n")
        self.commit("a.txt", "two\n")
        self.git("tag", "-a", "v1", "-m", "release by bob[at]gmail.com")
        r = self.check(f"{base}..HEAD")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tag refs/tags/v1 message:1", r.stdout)
        self.git("tag", "-d", "v1")
        self.git("tag", "-a", "v2", "-m", "fine", env={"GIT_COMMITTER_EMAIL": "bob[at]gmail.com"})
        r = self.check(f"{base}..HEAD")
        self.assertIn("tag refs/tags/v2 tagger-email", r.stdout)

    def test_ref_names_pointing_into_the_range_are_scanned(self):
        self.private_setup()
        base = self.commit("a.txt", "one\n")
        self.commit("a.txt", "two\n")
        self.git("branch", "feat-planted-term")
        r = self.check(f"{base}..HEAD", "--private")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ref refs/heads/feat-planted-term", r.stdout)

    def test_refs_outside_the_range_are_ignored(self):
        self.private_setup()
        first = self.commit("a.txt", "zero\n")
        self.git("branch", "old-planted-term")
        base = self.commit("a.txt", "one\n")
        self.commit("a.txt", "two\n")
        self.assertEqual(self.check(f"{base}..HEAD", "--private").returncode, 0)

    def test_a_bad_range_or_a_non_repo_is_an_internal_error(self):
        self.commit("a.txt", "one\n")
        self.assertEqual(self.check("nope..HEAD").returncode, 2)
        self.assertEqual(self.run_pc("--range", "a..b").returncode, 2)

    def test_a_diff_off_text_file_is_still_scanned(self):
        self.private_setup()
        base = self.commit(".gitattributes", "*.dat -diff\n")
        self.commit("notes.dat", "plain text with planted-term inside\n")
        r = self.check(f"{base}..HEAD", "--private")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("notes.dat:1", r.stdout)
        self.commit("more.dat", "mail bob[at]gmail.com\n")
        self.assertIn("more.dat:1", self.check(f"{base}..HEAD").stdout)

    def test_private_mode_fails_closed_on_a_really_binary_file_added_in_the_range(self):
        self.private_setup()
        base = self.commit("a.txt", "one\n")
        (self.repo / "img.bin").write_bytes(b"\x89PNG\x00\x01binary")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "binary")
        r = self.check(f"{base}..HEAD", "--private")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("img.bin", r.stderr)
        (self.repo / "latin.txt").write_bytes(b"caf\xe9\n")
        self.git("rm", "-q", "--cached", "img.bin")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "latin")
        self.assertEqual(self.check(f"{self.git('rev-parse', 'HEAD~1')}..HEAD", "--private").returncode, 2)

    def test_a_binary_file_that_was_only_deleted_in_the_range_is_fine(self):
        self.private_setup()
        (self.repo / "img.bin").write_bytes(b"\x00\x01")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "binary")
        base = self.git("rev-parse", "HEAD")
        self.git("rm", "-q", "img.bin")
        self.git("commit", "-q", "-m", "rm")
        self.assertEqual(self.check(f"{base}..HEAD", "--private").returncode, 0)

    def test_changed_file_names_are_scanned_even_for_an_empty_file(self):
        self.private_setup()
        base = self.commit("a.txt", "one\n")
        self.commit("dir/planted-term-notes.txt", "")
        r = self.check(f"{base}..HEAD", "--private")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("path-name", r.stdout)
        self.assertNotIn("planted-term", r.stdout)
        self.assertEqual(self.check(f"{base}..HEAD").returncode, 0)

    def test_a_tag_of_a_tag_is_peeled_and_every_message_is_scanned(self):
        base = self.commit("a.txt", "one\n")
        self.commit("a.txt", "two\n")
        self.git("tag", "-a", "inner", "-m", "inner by bob[at]gmail.com")
        self.git("tag", "-a", "outer", "-m", "outer is fine", "inner")
        self.git("tag", "-d", "inner")
        r = self.check(f"{base}..HEAD")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("tag refs/tags/outer", r.stdout)

    def test_merge_commit_added_lines_are_scanned(self):
        base = self.commit("a.txt", "one\n")
        self.git("checkout", "-q", "-b", "side")
        self.commit("b.txt", "bob[at]gmail.com\n")
        self.git("checkout", "-q", "main")
        self.commit("c.txt", "ok\n")
        self.git("merge", "-q", "--no-ff", "side", "-m", "merge")
        r = self.check(f"{base}..HEAD")
        self.assertEqual(r.returncode, 1)
        self.assertIn("b.txt:1", r.stdout)


if __name__ == "__main__":
    unittest.main()
