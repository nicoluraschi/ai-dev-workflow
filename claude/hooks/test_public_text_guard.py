#!/usr/bin/env python3
"""Tests for public-text-guard.py.

Run: python3 claude/hooks/test_public_text_guard.py

The hook runs in a subprocess with a fake HOME (public-repo config, a denylist holding the
planted term, a STUB extra scanner), a PATH holding only git and a stub gitleaks, a throwaway
"public" repo with a worktree, and a plain repo. The real $HOME, scanner and denylist are never
read. Each covered gh form is tested with the planted term (deny) and a clean variant (allow).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE / "public-text-guard.py"
PRIVACY_CHECK = HERE.parent.parent / "scripts/privacy-check"
OWNER = "nicolu" "raschi"
PUBLIC = f"{OWNER}/ai-dev-workflow"
TERM = "planted-term"
STUB_SCANNER = '''\
import sys
print("0 unexpected hits")
sys.exit(0)
'''


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "n", "GIT_COMMITTER_NAME": "n",
                        "GIT_AUTHOR_EMAIL": "n@example.com", "GIT_COMMITTER_EMAIL": "n@example.com"})


class Fixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "home"
        self.cfg = self.home / ".config/ai-workflow"
        self.tools = self.root / "tools"
        self.scanner = self.home / "private-scan/scan.py"
        for d in (self.cfg, self.tools, self.scanner.parent):
            d.mkdir(parents=True)
        self.scanner.write_text(STUB_SCANNER)
        (self.cfg / "extra-scanner").write_text(f"{self.scanner}\n")
        (self.cfg / "privacy-denylist").write_text(f"{TERM}\n")
        os.symlink(shutil.which("git"), self.tools / "git")
        gl = self.tools / "gitleaks"
        gl.write_text("#!/bin/sh\nexit 0\n")
        gl.chmod(0o755)
        self.pub = self.repo("pub")
        (self.pub / "scripts").mkdir()
        shutil.copy(PRIVACY_CHECK, self.pub / "scripts/privacy-check")
        git(self.pub, "add", "-A")
        git(self.pub, "commit", "-qm", "scripts")
        self.wt = self.root / "wt"
        git(self.pub, "worktree", "add", "-q", "-b", "feat", str(self.wt))
        self.plain = self.repo("plain")
        (self.cfg / "public-repo").write_text(f"{self.pub}\n")

    def repo(self, name):
        d = self.root / name
        d.mkdir()
        git(d, "init", "-q", "-b", "main")
        (d / "f").write_text("x\n")
        git(d, "add", "-A")
        git(d, "commit", "-qm", "init")
        return d

    def payload(self, tool, tool_input, cwd):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(cwd),
                "tool_input": tool_input}

    def run_hook(self, payload, raw=None):
        env = {"HOME": str(self.home), "PATH": str(self.tools), "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run([sys.executable, str(HOOK)],
                              input=raw if raw is not None else json.dumps(payload),
                              text=True, capture_output=True, env=env, timeout=60)

    def bash(self, command, cwd=None):
        return self.run_hook(self.payload("Bash", {"command": command}, cwd or self.pub))

    def edit(self, path, tool="Write", cwd=None):
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        return self.run_hook(self.payload(tool, {key: str(path)}, cwd or self.plain))

    def decision(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)["hookSpecificOutput"]

    def assertDenied(self, proc, mentions=None):
        d = self.decision(proc)
        self.assertIsNotNone(d, f"expected a deny; stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertEqual(d["permissionDecision"], "deny")
        if mentions:
            self.assertIn(mentions, d["permissionDecisionReason"])

    def assertAllowed(self, proc):
        self.assertIsNone(self.decision(proc), proc.stdout)

    def covered(self, template, **kw):
        """template has {x}: the planted term must deny, a clean variant must allow."""
        cwd = kw.get("cwd")
        self.assertDenied(self.bash(template.format(x=TERM), cwd), "privacy-check")
        self.assertAllowed(self.bash(template.format(x="harmless words"), cwd))

    def write(self, name, text):
        p = self.pub / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p


class CoveredFormTests(Fixture):
    def test_pr_create_title_and_body(self):
        self.covered("gh pr create --title 'fix {x}' --body 'text'")
        self.covered("gh pr create --title t --body 'about {x}'")
        self.covered("gh pr create -t t -b 'about {x}'")
        self.covered("gh pr create --title=t --body='about {x}'")

    def test_pr_create_body_file(self):
        self.write("body-bad.md", f"has {TERM}\n")
        self.write("body-ok.md", "fine\n")
        self.assertDenied(self.bash("gh pr create --title t --body-file body-bad.md"), "privacy-check")
        self.assertAllowed(self.bash("gh pr create --title t --body-file body-ok.md"))
        self.assertDenied(self.bash("gh pr create --title t -F body-bad.md"))
        self.assertAllowed(self.bash("gh pr create --title t -F body-ok.md"))

    def test_a_missing_or_unreadable_body_file_is_denied(self):
        self.assertDenied(self.bash("gh pr create --title t --body-file nope.md"))

    def test_the_head_branch_and_base_are_scanned_too(self):
        self.covered("gh pr create --title t --body b --head feat-{x}")

    def test_issue_create_edit_comment_close(self):
        self.covered("gh issue create --title '{x}' --body b")
        self.covered("gh issue comment 3 --body '{x}'")
        self.covered("gh issue edit 3 --title '{x}'")
        self.covered("gh issue close 3 --comment '{x}'")
        self.covered("gh issue close 3 -c '{x}'")

    def test_pr_comment_review_merge_edit(self):
        self.covered("gh pr comment 4 --body '{x}'")
        self.covered("gh pr review 4 --comment --body '{x}'")
        self.covered("gh pr merge 4 --squash --subject '{x}'")
        self.covered("gh pr merge 4 --squash --body '{x}'")
        self.covered("gh pr edit 4 --add-label '{x}'")
        self.covered("gh pr edit 4 --body '{x}'")

    def test_release_notes_and_notes_file(self):
        self.covered("gh release create v1 --title t --notes '{x}'")
        self.write("n-bad.md", f"{TERM}\n")
        self.write("n-ok.md", "ok\n")
        self.assertDenied(self.bash("gh release create v1 --notes-file n-bad.md"))
        self.assertAllowed(self.bash("gh release create v1 --notes-file n-ok.md"))

    def test_release_asset_files_are_scanned(self):
        self.write("asset-bad.txt", f"{TERM}\n")
        self.write("asset-ok.txt", "ok\n")
        self.assertDenied(self.bash("gh release create v1 asset-bad.txt"))
        self.assertAllowed(self.bash("gh release create v1 asset-ok.txt"))

    def test_repo_description_and_label_names(self):
        self.covered("gh repo edit --description '{x}'")
        self.covered("gh label create '{x}' --color ff0000")
        self.covered("gh label create fine --description '{x}'")

    def test_gist_description_and_files(self):
        self.covered("gh gist create --desc '{x}'")
        self.write("g-bad.txt", f"{TERM}\n")
        self.write("g-ok.txt", "ok\n")
        self.assertDenied(self.bash("gh gist create g-bad.txt"))
        self.assertAllowed(self.bash("gh gist create g-ok.txt"))

    def test_gh_api_writes_inline_and_from_files(self):
        self.covered("gh api -X POST repos/o/r/issues -f title='{x}'")
        self.covered("gh api repos/o/r/issues -f body='{x}'")
        self.covered("gh api repos/o/r/issues --raw-field body='{x}'")
        self.covered("gh api repos/o/r/issues -F body='{x}'")
        self.covered("gh api repos/o/r/issues --field body='{x}'")
        self.write("in-bad.json", f'{{"body": "{TERM}"}}')
        self.write("in-ok.json", '{"body": "ok"}')
        self.assertDenied(self.bash("gh api repos/o/r/issues --input in-bad.json"))
        self.assertAllowed(self.bash("gh api repos/o/r/issues --input in-ok.json"))
        self.write("f-bad.txt", f"{TERM}\n")
        self.write("f-ok.txt", "ok\n")
        self.assertDenied(self.bash("gh api repos/o/r/issues -F body=@f-bad.txt"))
        self.assertAllowed(self.bash("gh api repos/o/r/issues -F body=@f-ok.txt"))

    def test_gh_api_graphql_query_field(self):
        self.covered("gh api graphql -f query='mutation {{ addComment(body: \"{x}\") }}'")

    def test_generic_hits_deny_too(self):
        self.assertDenied(self.bash("gh issue comment 3 --body 'mail bob@" "gmail.com'"), "email")

    def test_an_extra_scanner_hit_denies(self):
        self.scanner.write_text("import sys\nprint(\"BANNED   0.txt: 'x'\")\nsys.exit(1)\n")
        self.assertDenied(self.bash("gh issue comment 3 --body 'whatever text'"))

    def test_a_missing_extra_scanner_pointer_denies(self):
        (self.cfg / "extra-scanner").unlink()
        self.assertDenied(self.bash("gh issue comment 3 --body 'whatever text'"))


class ReadOnlyTests(Fixture):
    def test_read_only_gh_calls_are_allowed_in_a_public_checkout(self):
        for cmd in ("gh pr view 3", "gh pr view 3 --json title,body", "gh issue list",
                    "gh issue view 3 --comments", "gh pr status", "gh pr diff 3", "gh pr checks 3",
                    "gh repo view", "gh release list", "gh api repos/o/r/pulls",
                    "gh api repos/o/r/pulls --jq '.[].title'", "gh api -X GET repos/o/r/pulls",
                    "gh pr list -R " + PUBLIC, "gh auth status"):
            self.assertAllowed(self.bash(cmd))

    def test_gh_api_with_body_fields_is_a_write(self):
        self.assertDenied(self.bash(f"gh api repos/o/r/pulls -f title={TERM}"))

    def test_gh_api_with_a_non_get_method_is_a_write(self):
        self.assertDenied(self.bash(f"gh api -X POST repos/o/r/issues/1/comments -f body={TERM}"))
        self.assertDenied(self.bash("gh api --method=POST repos/o/r/issues -f body=$HOME"))

    def test_non_gh_commands_in_a_public_checkout_are_allowed(self):
        for cmd in ("ls -la", "git status", "python3 -c 'print(1)'", "echo hello", "which gh",
                    "bash -c 'echo hi'", "git commit -m 'update the docs'"):
            self.assertAllowed(self.bash(cmd))


class UnresolvableFormTests(Fixture):
    def test_command_substitution_backticks_and_variables(self):
        for body in ("$(cat body.txt)", "`cat body.txt`", "$BODY", "${BODY}", "pre-$(date)"):
            self.assertDenied(self.bash(f'gh issue comment 3 --body "{body}"'), "resolve")

    def test_a_substitution_outside_the_gh_segment_still_denies(self):
        self.assertDenied(self.bash("gh issue comment 3 --body ok $(echo hi)"))

    def test_heredocs_and_here_strings(self):
        self.assertDenied(self.bash("gh issue comment 3 --body-file - <<EOF\ntext\nEOF"), "resolve")
        self.assertDenied(self.bash("gh issue comment 3 --body-file - <<< text"))
        self.assertDenied(self.bash("gh issue comment 3 --body-file - < body.txt"))

    def test_dash_as_a_file(self):
        for cmd in ("gh issue comment 3 --body-file -", "gh pr create --title t -F -",
                    "gh api repos/o/r/issues --input -", "gh gist create -",
                    "gh release create v1 --notes-file -", "gh api repos/o/r/issues -F body=@-"):
            self.assertDenied(self.bash(cmd), "resolve")

    def test_shell_dash_c(self):
        for sh in ("bash", "sh", "zsh"):
            self.assertDenied(self.bash(f"{sh} -c 'gh issue create --title t --body b'"), "resolve")
            self.assertDenied(self.bash(f"{sh} -c 'gh issue view 3'"), "resolve")
        self.assertDenied(self.bash("bash -lc 'gh issue view 3'"))

    def test_gh_behind_a_pipe_or_a_separator(self):
        for cmd in ("echo hi | gh issue comment 3 -F -", "echo hi | gh issue view 3",
                    "git push; gh pr create --title t", "git push && gh pr create --title t",
                    "false || gh pr create --title t", "(gh pr create --title t)",
                    "xargs gh issue close < list", "sudo gh issue close 3", "watch gh pr status"):
            self.assertDenied(self.bash(cmd), "resolve")

    def test_a_gh_before_a_separator_is_still_checked_on_its_own(self):
        self.assertDenied(self.bash(f"gh issue comment 3 --body {TERM} | cat"), "privacy-check")
        self.assertAllowed(self.bash("gh pr view 3 | head -5"))
        self.assertAllowed(self.bash("gh pr view 3 > out.txt"))

    def test_leading_cd_exports_and_assignments_are_fine(self):
        self.assertAllowed(self.bash(f"cd {self.pub} && gh pr view 3", cwd=self.plain))
        self.assertAllowed(self.bash("export FOO=1; gh pr view 3"))
        self.assertAllowed(self.bash("FOO=1 gh pr view 3"))

    def test_a_script_run_from_the_public_checkout_that_contains_gh(self):
        self.write("tools/post.sh", "#!/bin/sh\ngh issue create --title t --body b\n")
        self.write("tools/ok.sh", "#!/bin/sh\necho hello\n")
        self.write("tools/post.py", "import subprocess\nsubprocess.run(['gh', 'pr', 'list'])\n")
        os.chmod(self.pub / "tools/post.sh", 0o755)
        os.chmod(self.pub / "tools/ok.sh", 0o755)
        for cmd in ("bash tools/post.sh", "sh tools/post.sh", "./tools/post.sh", "tools/post.sh",
                    f"{self.pub}/tools/post.sh", "python3 tools/post.py"):
            self.assertDenied(self.bash(cmd), "resolve")
        for cmd in ("bash tools/ok.sh", "./tools/ok.sh", "bash -x tools/ok.sh"):
            self.assertAllowed(self.bash(cmd))

    def test_a_script_that_cannot_be_read_is_denied_in_a_public_checkout(self):
        self.assertDenied(self.bash("./tools/missing.sh"))

    def test_a_write_with_no_extractor_is_denied(self):
        for cmd in ("gh secret set TOKEN", "gh workflow run ci.yml", "gh variable set X",
                    "gh repo delete o/r", "gh alias set a b", "gh extension install o/r",
                    "gh ssh-key add key.pub"):
            self.assertDenied(self.bash(cmd), "extract")


class WhereItAppliesTests(Fixture):
    def test_a_non_public_cwd_is_not_guarded(self):
        self.assertAllowed(self.bash(f"gh issue comment 3 --body '{TERM}'", cwd=self.plain))
        self.assertAllowed(self.bash("bash -c 'gh issue view 3'", cwd=self.plain))
        self.assertAllowed(self.bash("echo hi | gh issue comment 3 -F -", cwd=self.plain))

    def test_a_worktree_of_the_public_repo_is_guarded(self):
        self.assertDenied(self.bash(f"gh issue comment 3 --body '{TERM}'", cwd=self.wt))
        self.assertAllowed(self.bash("gh issue comment 3 --body 'fine'", cwd=self.wt))

    def test_a_subdirectory_of_the_public_checkout_is_guarded(self):
        (self.pub / "sub").mkdir()
        self.assertDenied(self.bash(f"gh issue comment 3 --body '{TERM}'", cwd=self.pub / "sub"))

    def test_dash_R_or_repo_naming_the_public_repo_guards_a_plain_cwd(self):
        for flag in (f"-R {PUBLIC}", f"--repo {PUBLIC}", f"--repo={PUBLIC}", f"-R{PUBLIC}"):
            self.assertDenied(self.bash(f"gh issue comment 3 {flag} --body '{TERM}'", cwd=self.plain))
            self.assertAllowed(self.bash(f"gh issue comment 3 {flag} --body 'fine'", cwd=self.plain))
        self.assertAllowed(self.bash(f"gh issue comment 3 -R {OWNER}/other --body '{TERM}'",
                                     cwd=self.plain))

    def test_a_url_or_api_path_naming_the_public_repo_guards_a_plain_cwd(self):
        self.assertDenied(self.bash(
            f"gh issue comment https://github.com/{PUBLIC}/issues/3 --body '{TERM}'", cwd=self.plain))
        self.assertDenied(self.bash(
            f"gh api repos/{PUBLIC}/issues -f body='{TERM}'", cwd=self.plain))

    def test_GH_REPO_inline_or_exported_guards_a_plain_cwd(self):
        self.assertDenied(self.bash(f"GH_REPO={PUBLIC} gh issue comment 3 --body '{TERM}'",
                                    cwd=self.plain))
        self.assertDenied(self.bash(f"export GH_REPO={PUBLIC}; gh issue comment 3 --body '{TERM}'",
                                    cwd=self.plain))
        self.assertAllowed(self.bash(f"GH_REPO={OWNER}/other gh issue comment 3 --body '{TERM}'",
                                     cwd=self.plain))

    def test_a_cd_into_the_public_checkout_guards_the_command(self):
        self.assertDenied(self.bash(f"cd {self.pub} && gh issue comment 3 --body '{TERM}'",
                                    cwd=self.plain))
        self.assertAllowed(self.bash(f"cd {self.plain} && gh issue comment 3 --body '{TERM}'",
                                     cwd=self.pub))

    def test_no_public_repo_config_and_no_origin_means_nothing_is_guarded(self):
        (self.cfg / "public-repo").unlink()
        self.assertAllowed(self.bash(f"gh issue comment 3 --body '{TERM}'", cwd=self.pub))

    def test_a_matching_origin_alone_guards_the_checkout(self):
        (self.cfg / "public-repo").unlink()
        git(self.pub, "remote", "add", "origin", f"git@github.com:{PUBLIC}.git")
        self.assertDenied(self.bash(f"gh issue comment 3 --body '{TERM}'", cwd=self.pub))


class FailClosedTests(Fixture):
    def test_a_missing_privacy_check_denies(self):
        os.remove(self.pub / "scripts/privacy-check")
        self.assertDenied(self.bash("gh issue comment 3 --body fine"), "privacy-check")

    def test_a_missing_denylist_denies_through_the_scripts_own_fail_closed(self):
        (self.cfg / "privacy-denylist").unlink()
        self.assertDenied(self.bash("gh issue comment 3 --body fine"))

    def test_a_missing_gitleaks_denies(self):
        (self.tools / "gitleaks").unlink()
        self.assertDenied(self.bash("gh issue comment 3 --body fine"))

    def test_the_script_comes_from_the_configured_clone_not_the_worktree(self):
        (self.wt / "scripts/privacy-check").write_text("#!/bin/sh\nexit 0\n")
        self.assertDenied(self.bash(f"gh issue comment 3 --body '{TERM}'", cwd=self.wt))

    def test_a_bad_payload_is_allowed_silently(self):
        self.assertAllowed(self.run_hook(None, raw="not json"))
        self.assertAllowed(self.run_hook(self.payload("Bash", {}, self.pub)))

    def test_an_unparseable_shell_line_with_gh_in_a_public_checkout_is_denied(self):
        self.assertDenied(self.bash("gh issue comment 3 --body 'unterminated"))
        self.assertAllowed(self.bash("echo 'unterminated"))


class ExternalScriptTests(Fixture):
    """6b-F01: in a public cwd every invoked script is inspected, wherever it lives."""

    def setUp(self):
        super().setUp()
        self.ext = self.root / "ext"
        self.ext.mkdir()
        (self.ext / "post.sh").write_text("#!/bin/sh\ngh issue create --title t\n")
        (self.ext / "post.py").write_text("import subprocess\nsubprocess.run(['gh', 'pr', 'list'])\n")
        (self.ext / "ok.sh").write_text("#!/bin/sh\necho hello\n")
        for n in ("post.sh", "ok.sh"):
            os.chmod(self.ext / n, 0o755)

    def test_a_script_outside_the_public_checkout_that_contains_gh_is_denied(self):
        for cmd in (f"bash {self.ext}/post.sh", f"sh {self.ext}/post.sh", f"{self.ext}/post.sh",
                    f"python3 {self.ext}/post.py", f"env FOO=1 {self.ext}/post.sh"):
            self.assertDenied(self.bash(cmd), "resolve")

    def test_a_script_outside_without_gh_is_allowed(self):
        for cmd in (f"bash {self.ext}/ok.sh", f"{self.ext}/ok.sh"):
            self.assertAllowed(self.bash(cmd))

    def test_compiled_binaries_and_missing_outside_paths_are_not_scripts(self):
        self.assertAllowed(self.bash("/bin/ls"))
        self.assertAllowed(self.bash(f"{self.ext}/missing.sh"))

    def test_a_non_public_cwd_does_not_inspect_scripts(self):
        self.assertAllowed(self.bash(f"bash {self.ext}/post.sh", cwd=self.plain))

    def test_a_fifo_script_is_denied_without_blocking(self):
        fifo = self.ext / "fifo.sh"
        os.mkfifo(fifo)
        self.assertDenied(self.bash(f"bash {fifo}"))


class CwdResolutionTests(Fixture):
    """5s #3: pushd, unresolvable cd targets, GIT_DIR / GIT_WORK_TREE."""

    def test_pushd_is_treated_like_cd(self):
        self.assertDenied(self.bash(f"pushd {self.pub} && gh issue comment 3 --body '{TERM}'",
                                    cwd=self.plain), "privacy-check")
        self.assertAllowed(self.bash(f"pushd {self.pub} && gh issue comment 3 --body fine",
                                     cwd=self.plain))
        self.assertAllowed(self.bash(f"pushd {self.plain} && gh issue comment 3 --body '{TERM}'",
                                     cwd=self.pub))

    def test_cd_and_pushd_options_are_skipped(self):
        self.assertDenied(self.bash(f"cd -P {self.pub} && gh issue comment 3 --body '{TERM}'",
                                    cwd=self.plain))

    def test_an_unresolvable_cd_or_pushd_target_before_a_gh_call_is_denied(self):
        for pre in ("cd $DIR", "cd ${DIR}/x", 'cd "$(pwd)"', "cd `pwd`", "cd ~root", "cd -",
                    "pushd $DIR", "pushd -", "pushd ~root", "popd"):
            self.assertDenied(self.bash(f"{pre} && gh issue view 3", cwd=self.plain), "resolve")

    def test_an_unresolvable_cd_without_a_gh_call_is_fine(self):
        self.assertAllowed(self.bash("cd $DIR && ls", cwd=self.plain))
        self.assertAllowed(self.bash(f"cd ~ && gh issue view 3", cwd=self.plain))

    def test_git_dir_and_git_work_tree_name_the_repo_gh_will_use(self):
        git_dir = self.pub / ".git"
        for prefix in (f"GIT_DIR={git_dir} ", f"GIT_WORK_TREE={self.pub} ",
                       f"export GIT_DIR={git_dir}; ", f"export GIT_WORK_TREE={self.pub}; "):
            self.assertDenied(self.bash(f"{prefix}gh issue comment 3 --body '{TERM}'", cwd=self.plain),
                              "privacy-check")
            self.assertAllowed(self.bash(f"{prefix}gh issue comment 3 --body fine", cwd=self.plain))
        self.assertAllowed(self.bash(
            f"GIT_DIR={self.plain}/.git gh issue comment 3 --body '{TERM}'", cwd=self.plain))


class RoundTwoBypassTests(Fixture):
    """Audit round 2: eval, source, a shell fed from stdin, pushd +N, CDPATH."""

    def setUp(self):
        super().setUp()
        self.ext = self.root / "ext2"
        self.ext.mkdir()
        (self.ext / "s.sh").write_text("gh pr comment 1 -b secret\n")
        (self.ext / "ok.sh").write_text("echo hello\n")
        self.write("s.sh", "gh pr comment 1 -b secret\n")

    def test_eval_of_a_string_containing_gh_is_unresolvable(self):
        for cmd in ("eval 'gh pr comment 1 -b secret'", "eval gh pr comment 1 -b secret",
                    'eval "gh issue view 3"', "eval 'echo hi; gh pr list'"):
            self.assertDenied(self.bash(cmd), "resolve")
        self.assertAllowed(self.bash("eval 'echo hi'"))
        self.assertAllowed(self.bash("eval 'gh issue comment 3 --body x'", cwd=self.plain))

    def test_source_and_dot_inspect_the_file_like_a_script(self):
        for cmd in (f"source {self.ext}/s.sh", f". {self.ext}/s.sh", "source s.sh", ". s.sh",
                    "source ./s.sh"):
            self.assertDenied(self.bash(cmd), "resolve")
        self.assertAllowed(self.bash(f"source {self.ext}/ok.sh"))
        self.assertAllowed(self.bash(f". {self.ext}/ok.sh"))
        self.assertAllowed(self.bash(f"source {self.ext}/s.sh", cwd=self.plain))

    def test_a_shell_fed_from_stdin_is_unresolvable_in_a_guarded_context(self):
        for cmd in (f"bash < {self.ext}/s.sh", f"sh < {self.ext}/s.sh", f"zsh < {self.ext}/s.sh",
                    f"cat {self.ext}/s.sh | sh", f"cat {self.ext}/s.sh | bash",
                    f"cat {self.ext}/s.sh | zsh", f"cat {self.ext}/s.sh | bash -s",
                    f"echo hi | sh -e"):
            self.assertDenied(self.bash(cmd), "resolve")
            self.assertAllowed(self.bash(cmd, cwd=self.plain))

    def test_a_shell_running_a_named_file_is_not_a_stdin_shell(self):
        self.assertAllowed(self.bash(f"bash {self.ext}/ok.sh"))

    def test_pushd_by_index_and_cdpath_make_the_cwd_unresolvable(self):
        for pre in (f"pushd {self.pub}; pushd {self.plain}; pushd +1", "pushd -1", "pushd +0",
                    f"export CDPATH={self.root}; cd pub", f"CDPATH={self.root} cd pub",
                    f"export CDPATH=:; cd pub"):
            self.assertDenied(self.bash(f"{pre}; gh pr comment 1 -b secret", cwd=self.plain), "resolve")
        self.assertAllowed(self.bash("export CDPATH=:; cd ~; ls", cwd=self.plain))

    def test_a_cd_that_may_not_take_effect_or_is_wrapped_is_unresolvable(self):
        # Re-audits #4-#6: from the public checkout, a cd out of it the guard cannot trust.
        for pre in (f"(cd {self.plain}); ", f"cd {self.plain} | true; ", f"true || cd {self.plain}; ",
                    f"{{ cd {self.plain}; }} && "):
            with self.subTest(pre=pre):
                self.assertDenied(self.bash(f"{pre}gh pr comment 1 -b fine"), "resolve")
        # Followed: this guard unwraps builtin/time and knows zsh's chdir.
        for pre in ("cd", "builtin cd", "time cd", "chdir"):
            with self.subTest(pre=pre):
                self.assertAllowed(self.bash(f"{pre} {self.plain} && gh pr comment 1 -b fine"))
        self.assertDenied(self.bash(f"chdir {self.pub} && gh pr comment 1 -b {TERM}",
                                    cwd=self.plain), "privacy-check")

    def test_a_computed_command_name_makes_the_cwd_unresolvable(self):
        # Re-audit #7: `$'cd'`, a backtick or a variable may be a cd into the public checkout.
        for pre in (f"$'cd' {self.pub} && ", f"`echo cd` {self.pub} && ",
                    f'C=cd; "$C" {self.pub} && '):
            with self.subTest(pre=pre):
                self.assertDenied(self.bash(f"{pre}gh pr comment 1 -b fine", cwd=self.plain))


class StrictReadOnlyTests(Fixture):
    """5s #4: read-only means a known group with a read verb, nothing else."""

    def test_unknown_or_single_word_groups_are_denied_as_having_no_extractor(self):
        for cmd in ("gh co 123", "gh myalias", "gh co view", "gh status", "gh pr", "gh frob list"):
            self.assertDenied(self.bash(cmd), "extract")

    def test_alias_set_and_import_are_denied_while_listing_is_a_read(self):
        self.assertDenied(self.bash("gh alias set co 'pr checkout'"), "extract")
        self.assertDenied(self.bash("gh alias import aliases.yml"), "extract")
        self.assertAllowed(self.bash("gh alias list"))

    def test_known_groups_with_read_verbs_stay_allowed(self):
        for cmd in ("gh pr view 1", "gh issue list", "gh run view 5", "gh workflow list",
                    "gh release list", "gh repo view", "gh gist view abc", "gh label list",
                    "gh pr status", "gh pr diff 1", "gh pr checks 1", "gh --version"):
            self.assertAllowed(self.bash(cmd))

    def test_non_guarded_contexts_are_unaffected(self):
        self.assertAllowed(self.bash("gh co 123", cwd=self.plain))


class FileOperandTests(Fixture):
    """5s #7 and #9: globs, non-text uploads, non-regular files."""

    def test_glob_characters_in_upload_operands_or_file_flags_are_unresolvable(self):
        self.write("a.txt", "x\n")
        for cmd in ("gh release create v1 'dist/*.zip'", "gh release upload v1 'a?.txt'",
                    "gh gist create 'a[12].txt'", "gh issue comment 3 --body-file 'b*.md'",
                    "gh release create v1 --notes-file 'n?.md'", "gh pr create --title t -F 'x[1].md'"):
            self.assertDenied(self.bash(cmd), "glob")

    def test_glob_characters_in_ordinary_text_are_fine(self):
        for cmd in ("gh issue comment 3 --body 'is this ok? *bold* [x] done'",
                    "gh pr create --title 'what?' --body '[ ] todo'",
                    "gh release create v1 --notes 'a*b' --title 'v[1]'",
                    "gh gist create --desc 'how? *really*'"):
            self.assertAllowed(self.bash(cmd))

    def test_a_non_utf8_upload_or_body_file_is_denied(self):
        (self.pub / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")
        (self.pub / "latin.txt").write_bytes(b"caf\xe9\n")
        for cmd in ("gh release create v1 pic.png", "gh release upload v1 pic.png",
                    "gh gist create pic.png", "gh gist create latin.txt",
                    "gh issue comment 3 --body-file pic.png", "gh issue comment 3 --body-file latin.txt"):
            self.assertDenied(self.bash(cmd), "UTF-8")

    def test_only_regular_files_are_read_and_a_fifo_does_not_block(self):
        fifo = self.pub / "pipe.md"
        os.mkfifo(fifo)
        for cmd in ("gh issue comment 3 --body-file pipe.md", "gh gist create pipe.md",
                    "gh release create v1 pipe.md", "gh api repos/o/r/issues --input pipe.md",
                    "gh api repos/o/r/issues -F body=@pipe.md", "gh pr create --title t -F pipe.md"):
            self.assertDenied(self.bash(cmd), "regular")

    def test_an_upload_directory_operand_is_denied(self):
        (self.pub / "dist").mkdir()
        self.assertDenied(self.bash("gh release create v1 dist"), "regular")


class ResolvedConfigTargetTests(Fixture):
    """5s #8: the real files behind the links in the config dir are protected too."""

    def setUp(self):
        super().setUp()
        self.elsewhere = self.root / "elsewhere"
        self.elsewhere.mkdir()
        self.real = self.elsewhere / "trusted.txt"
        self.real.write_text("owner\n")
        os.symlink(self.real, self.cfg / "trusted-commenters")
        self.realdir = self.elsewhere / "projects"
        self.realdir.mkdir()
        (self.realdir / "p.md").write_text("x\n")
        os.symlink(self.realdir, self.cfg / "projects")

    def test_write_edit_and_notebookedit_to_a_resolved_target_are_denied(self):
        for tool in ("Write", "Edit", "NotebookEdit"):
            self.assertDenied(self.edit(self.real, tool, cwd=self.plain), "ai-workflow")
            self.assertDenied(self.edit(self.realdir / "p.md", tool, cwd=self.plain))
            self.assertDenied(self.edit(self.realdir / "new.md", tool, cwd=self.plain))

    def test_bash_write_forms_on_a_resolved_target_are_denied(self):
        for cmd in (f"echo x > {self.real}", f"echo x >> {self.real}", f"rm {self.real}",
                    f"mv {self.real} /tmp/x", f"cp /tmp/x {self.real}", f"tee {self.real}",
                    f"rm {self.realdir}/p.md", f"echo x > {self.realdir}/new.md"):
            self.assertDenied(self.bash(cmd, cwd=self.plain), "ai-workflow")

    def test_neighbours_of_a_resolved_target_are_not_protected(self):
        self.assertAllowed(self.edit(self.elsewhere / "other.txt", cwd=self.plain))
        self.assertAllowed(self.bash(f"echo x > {self.elsewhere}/other.txt", cwd=self.plain))
        self.assertAllowed(self.bash(f"cat {self.real}", cwd=self.plain))


class RegistrationTests(unittest.TestCase):
    def test_settings_registers_the_hook_for_bash_and_the_edit_tools(self):
        settings = json.loads((HERE.parent / "settings.json").read_text())
        command = 'python3 "$HOME/.claude/hooks/public-text-guard.py"'
        matchers = {entry["matcher"] for entry in settings["hooks"]["PreToolUse"]
                    for h in entry["hooks"] if h["command"] == command and h["timeout"] == 10}
        self.assertEqual(matchers, {"Bash", "Edit|Write|NotebookEdit"})

    def test_the_outside_text_rule_is_in_the_skill_and_the_global_instructions(self):
        for rel in ("skills/gh-pr-comments-fixer/SKILL.md", "CLAUDE.md"):
            text = (HERE.parent / rel).read_text()
            for needle in ("trusted-commenters", "public-repo", "data"):
                self.assertIn(needle, text, f"{needle} missing from {rel}")

    def test_the_shared_helper_ships_next_to_the_hooks(self):
        self.assertTrue((HERE / "public_checkout.py").is_file())


class InternalErrorTests(Fixture):
    """Run main() in-process with a classifier that blows up."""

    def run_main(self, command, cwd, breaks="classify"):
        import contextlib
        import importlib.util
        import io
        from importlib.machinery import SourceFileLoader
        loader = SourceFileLoader("public_text_guard_inproc", str(HOOK))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        def boom(*a, **k):
            raise RuntimeError("boom")
        setattr(mod, breaks, boom)
        payload = json.dumps(self.payload("Bash", {"command": command}, cwd))
        out, saved = io.StringIO(), (sys.stdin, os.environ.get("HOME"))
        sys.stdin = io.StringIO(payload)
        os.environ["HOME"] = str(self.home)
        try:
            with contextlib.redirect_stdout(out):
                try:
                    mod.main()
                except SystemExit:
                    pass
        finally:
            sys.stdin = saved[0]
            os.environ["HOME"] = saved[1]
        return out.getvalue()

    def test_an_internal_error_in_a_guarded_case_denies(self):
        out = self.run_main("gh issue comment 3 --body fine", self.pub)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_an_internal_error_where_nothing_is_guarded_allows(self):
        self.assertEqual(self.run_main("gh issue comment 3 --body fine", self.plain), "")
        self.assertEqual(self.run_main("ls", self.pub, breaks="build_segments"), "")


class ConfigDirTests(Fixture):
    def test_write_edit_and_notebookedit_under_the_config_dir_are_denied_everywhere(self):
        for tool in ("Write", "Edit", "NotebookEdit"):
            for name in ("public-repo", "privacy-denylist", "new-file", "projects/x/y"):
                self.assertDenied(self.edit(self.cfg / name, tool, cwd=self.plain), "ai-workflow")
            self.assertDenied(self.edit(self.cfg / "public-repo", tool, cwd=self.pub))

    def test_dotdot_and_symlink_paths_into_the_config_dir_are_denied(self):
        self.assertDenied(self.edit(self.cfg / "projects/../public-repo"))
        real = self.root / "real.txt"
        real.write_text("x")
        os.symlink(real, self.cfg / "linked")
        self.assertDenied(self.edit(self.cfg / "linked"))
        os.symlink(self.cfg, self.root / "alias")
        self.assertDenied(self.edit(self.root / "alias/public-repo"))

    def test_other_paths_are_allowed(self):
        self.assertAllowed(self.edit(self.plain / "f"))
        self.assertAllowed(self.edit(self.home / ".config/zed/settings.json"))
        self.assertAllowed(self.edit(self.home / ".config/ai-workflow-notes"))

    def test_bash_redirections_rm_and_mv_on_the_config_dir_are_denied_everywhere(self):
        targets = ("~/.config/ai-workflow/public-repo", "$HOME/.config/ai-workflow/public-repo",
                   "${HOME}/.config/ai-workflow/public-repo", f"{self.cfg}/public-repo")
        for t in targets:
            for cmd in (f"echo x > {t}", f"echo x >> {t}", f"echo x >{t}", f"rm {t}", f"rm -f {t}",
                        f"mv {t} /tmp/x", f"mv /tmp/x {t}", f"cp /tmp/x {t}", f"tee {t}",
                        f"ln -sf /tmp/x {t}", f"echo x 2> {t}"):
                self.assertDenied(self.bash(cmd, cwd=self.plain), "ai-workflow")

    def test_relative_paths_resolve_against_the_cwd(self):
        self.assertDenied(self.bash("echo x > public-repo", cwd=self.cfg))
        self.assertDenied(self.bash(f"cd {self.cfg} && rm public-repo", cwd=self.plain))

    def test_reading_the_config_dir_is_allowed(self):
        for cmd in (f"cat {self.cfg}/public-repo", "ls ~/.config/ai-workflow", "grep x ~/.config/ai-workflow/*",
                    "echo x > ~/.config/ai-workflow-notes", f"echo x > {self.plain}/out.txt"):
            self.assertAllowed(self.bash(cmd, cwd=self.plain))

    def test_lefthook_local_is_denied_in_a_public_checkout_only(self):
        for name in ("lefthook-local.yml", ".lefthook-local.yml", "lefthook-local.yaml"):
            self.assertDenied(self.edit(self.pub / name, cwd=self.pub), "lefthook-local")
            self.assertDenied(self.edit(self.wt / name, "Edit", cwd=self.wt), "lefthook-local")
            self.assertAllowed(self.edit(self.plain / name, cwd=self.plain))
        self.assertDenied(self.edit(self.pub / "new-dir/lefthook-local.yml", cwd=self.pub))
        self.assertAllowed(self.edit(self.pub / "lefthook.yml", cwd=self.pub))

    def test_lefthook_local_bash_writes_in_a_public_checkout_are_denied(self):
        self.assertDenied(self.bash("echo 'pre-push: {}' > lefthook-local.yml"), "lefthook-local")
        self.assertDenied(self.bash("rm lefthook-local.yml"))
        self.assertDenied(self.bash("mv x lefthook-local.yml"))
        self.assertAllowed(self.bash("echo 'pre-push: {}' > lefthook-local.yml", cwd=self.plain))
        self.assertAllowed(self.bash("cat lefthook-local.yml"))


if __name__ == "__main__":
    unittest.main()
