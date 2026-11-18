#!/usr/bin/env python3
"""Line-scan tests for export/root/.github/workflows/ci.yml (no YAML dependency).

Run: python3 scripts/test_ci_workflow.py
AC 26: pull_request and push to main only, never pull_request_target, `permissions: contents:
read`, no secrets, every action pinned by full commit SHA, no persisted credentials. AC 6: the
steps the spec lists.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# In the private repo the file lives under export/root/; in the public repo it is at the root.
CI = next(p for p in (REPO / "export/root/.github/workflows/ci.yml", REPO / ".github/workflows/ci.yml")
          if p.is_file())


def code_lines():
    return [l.rstrip("\n") for l in CI.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = CI.read_text()
        self.lines = code_lines()
        self.body = "\n".join(self.lines)

    def test_never_pull_request_target(self):
        self.assertNotIn("pull_request_target", self.body)
        self.assertNotIn("workflow_run", self.body)

    def test_triggers_are_pull_request_and_push_to_main_only(self):
        i = self.lines.index("on:")
        block = []
        for l in self.lines[i + 1:]:
            if not l.startswith(" "):
                break
            block.append(l)
        keys = [l.strip().rstrip(":") for l in block if re.match(r"^  \w", l)]
        self.assertEqual(keys, ["pull_request", "push"])
        self.assertIn("branches: [main]", "\n".join(block))

    def test_top_level_permissions_are_contents_read_only(self):
        i = self.lines.index("permissions:")
        self.assertEqual(self.lines[i + 1], "  contents: read")
        self.assertFalse(self.lines[i + 2].startswith(" "), "permissions must hold contents only")
        self.assertEqual(len([l for l in self.lines if l.startswith("permissions:")]), 1)
        self.assertNotRegex(self.body, r"(?m)^\s+(?!contents)\w[\w-]*: (write|read)$")

    def test_no_secrets(self):
        self.assertNotIn("secrets.", self.body)
        self.assertNotIn("secrets:", self.body)

    def test_every_uses_is_pinned_to_a_full_commit_sha(self):
        uses = [l for l in self.lines if re.match(r"^\s*-?\s*uses:", l)]
        self.assertTrue(uses)
        for l in uses:
            self.assertRegex(l, r"uses: [\w.-]+/[\w./-]+@[0-9a-f]{40}( +#.*)?$", l)
        self.assertEqual([re.search(r"uses: ([\w.-]+/[\w-]+)@", l).group(1) for l in uses],
                         ["actions/checkout"])

    def test_checkout_does_not_persist_credentials_and_fetches_full_history(self):
        self.assertIn("persist-credentials: false", self.body)
        self.assertIn("fetch-depth: 0", self.body)

    def test_runs_on_macos_latest(self):
        self.assertEqual([l.strip() for l in self.lines if "runs-on:" in l], ["runs-on: macos-latest"])

    def test_github_context_reaches_shell_only_through_env(self):
        for l in self.lines:
            if "${{" in l:
                self.assertRegex(l, r"^\s+[A-Z][A-Z0-9_]*: \$\{\{ [\w.]+ \}\}$",
                                 f"interpolation outside an env mapping: {l}")

    def test_the_spec_steps_are_present(self):
        for needle in ("scripts/test-all", "scripts/install-smoke", "scripts/privacy-check .",
                       "scripts/privacy-check --range", "scripts/check-links", "gitleaks git",
                       "gitleaks dir"):
            self.assertIn(needle, self.body)
        self.assertNotIn("--private", self.body)  # CI holds no denylist, scanner or secrets

    def test_range_covers_pr_and_push_and_the_zero_before(self):
        self.assertIn("github.event.pull_request.base.sha", self.body)
        self.assertIn("github.event.pull_request.head.sha", self.body)
        self.assertIn("github.event.before", self.body)
        self.assertRegex(self.body, r"0{40}")

    def test_gitleaks_is_version_pinned_and_checksum_verified(self):
        self.assertRegex(self.body, r"GITLEAKS_VERSION: \d+\.\d+\.\d+")
        self.assertRegex(self.body, r"GITLEAKS_SHA256: [0-9a-f]{64}")
        self.assertIn("darwin_arm64", self.body)
        self.assertRegex(self.body, r"shasum -a 256 -c")
        # verification must come before the archive is unpacked
        self.assertLess(self.body.index("shasum -a 256 -c"), self.body.index("tar -xzf"))


def step_lines(name):
    """The lines of the step called `name`, up to the next step."""
    lines = CI.read_text().splitlines()
    start = lines.index(f"      - name: {name}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("      - name:")),
               len(lines))
    return lines[start + 1:end]


def step_script(name):
    return run_body(step_lines(name))


def run_body(step):
    """The `run: |` body of a step's lines, dedented: it ends at the first non-blank line
    indented less than the body, so a later step key is never run as shell."""
    out, indent = [], None
    for l in step:
        if indent is None:
            if l.strip() == "run: |":
                indent = len(l) - len(l.lstrip()) + 2
            continue
        if l.strip() and len(l) - len(l.lstrip()) < indent:
            break
        out.append(l[indent:])
    return "\n".join(out) + "\n"


class CommitRangeStepTests(unittest.TestCase):
    """Runs the "Privacy check, commits" script with a stub privacy-check that prints its args."""

    def run_step(self, **env):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d, "scripts/privacy-check")
            stub.parent.mkdir()
            stub.write_text('#!/usr/bin/env bash\necho "$@"\n')
            stub.chmod(0o755)
            base = {"EVENT_NAME": "push", "PR_BASE": "", "PR_HEAD": "", "PUSH_BEFORE": "a" * 40,
                    "PUSH_AFTER": "b" * 40, "PUSH_FORCED": "false", "PATH": os.environ["PATH"]}
            r = subprocess.run(["bash", "-c", step_script("Privacy check, commits")], cwd=d,
                               env={**base, **env}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_env_maps_each_variable_to_its_github_context(self):
        # the tests below inject these values, so the mapping itself is checked here
        env = {l.strip() for l in step_lines("Privacy check, commits")}
        for line in ("EVENT_NAME: ${{ github.event_name }}",
                     "PR_BASE: ${{ github.event.pull_request.base.sha }}",
                     "PR_HEAD: ${{ github.event.pull_request.head.sha }}",
                     "PUSH_BEFORE: ${{ github.event.before }}",
                     "PUSH_AFTER: ${{ github.sha }}",
                     "PUSH_FORCED: ${{ github.event.forced }}"):
            self.assertIn(line, env)

    def test_run_body_stops_before_a_later_step_key(self):
        step = ["        run: |", "          echo one", "", "          echo two",
                "        continue-on-error: true", "      # a comment"]
        self.assertEqual(run_body(step), "echo one\n\necho two\n")

    def test_pull_request_scans_base_to_head(self):
        out = self.run_step(EVENT_NAME="pull_request", PR_BASE="c" * 40, PR_HEAD="d" * 40)
        self.assertEqual(out, f"--range {'c' * 40}..{'d' * 40}")

    def test_push_scans_before_to_after(self):
        self.assertEqual(self.run_step(), f"--range {'a' * 40}..{'b' * 40}")

    def test_first_push_scans_whole_history(self):
        self.assertEqual(self.run_step(PUSH_BEFORE="0" * 40), f"--range {'b' * 40}")

    def test_forced_push_scans_whole_history(self):
        # the replaced head is gone from the remote, so `before..after` cannot resolve
        self.assertEqual(self.run_step(PUSH_FORCED="true"), f"--range {'b' * 40}")


if __name__ == "__main__":
    unittest.main()
