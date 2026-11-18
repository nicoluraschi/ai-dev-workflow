#!/usr/bin/env python3
"""Tests for the two Jira subagents the jira-backlog skill delegates to.

Run: python3 claude/skills/jira-backlog/test_agents.py

Ticket text is untrusted and is read by a Haiku model, so the split is structural: the agent
that reads tickets holds no write tool, and the one that writes never reads ticket text. These
tests pin each agent's frontmatter to exactly that tool list.
"""
import re
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "agents"

READ_TOOLS = {
    "mcp__atlassian__getAccessibleAtlassianResources",
    "mcp__atlassian__searchJiraIssuesUsingJql",
    "mcp__atlassian__getJiraIssue",
    "mcp__atlassian__listJiraIssueComments",
    "mcp__atlassian__executeRead",
}
WRITE_TOOLS = {
    "mcp__atlassian__transitionJiraIssue",
    "mcp__atlassian__addOrEditJiraIssueComment",
    "mcp__atlassian__createJiraIssue",
}
# Generic Atlassian runners that neither agent holds: the write and destructive ones run any
# operation of their tier on any product, and discover opens the whole catalogue.
DENIED_RUNNERS = {
    "mcp__atlassian__discover",
    "mcp__atlassian__executeWrite",
    "mcp__atlassian__executeDestructive",
}
# Operations the reader may run through executeRead, and nothing else.
EXECUTE_READ_OPS = {"listJiraIssueTransitions"}
# A backticked Atlassian tool or operation name in an agent body, e.g. `getJiraIssue`,
# `executeRead`, `discover`.
BODY_TOOL = re.compile(r"`([a-z]+[A-Za-z]*(?:Jira|Atlassian)[A-Za-z]*|execute[A-Z][a-z]+|discover)`")


def frontmatter(name):
    text = (AGENTS / f"{name}.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{name}.md has no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


def tools(fm):
    return {t.strip() for t in fm["tools"].split(",")}


class JiraAgentTests(unittest.TestCase):
    def test_reader_runs_on_haiku_with_only_the_read_tools(self):
        fm = frontmatter("jira-reader")
        self.assertEqual(fm["name"], "jira-reader")
        self.assertEqual(fm["model"], "haiku")
        self.assertEqual(tools(fm), READ_TOOLS)

    def test_writer_runs_on_haiku_with_only_the_write_tools(self):
        fm = frontmatter("jira-writer")
        self.assertEqual(fm["name"], "jira-writer")
        self.assertEqual(fm["model"], "haiku")
        self.assertEqual(tools(fm), WRITE_TOOLS)

    def test_both_cap_their_turns_and_skip_claude_md(self):
        for name in ("jira-reader", "jira-writer"):
            fm = frontmatter(name)
            self.assertTrue(fm.get("maxTurns", "").isdigit(), name)
            self.assertEqual(fm.get("omitClaudeMd"), "true", name)

    def test_tool_sets_do_not_overlap(self):
        self.assertFalse(READ_TOOLS & WRITE_TOOLS)

    def test_neither_holds_a_denied_runner(self):
        for name in ("jira-reader", "jira-writer"):
            self.assertFalse(tools(frontmatter(name)) & DENIED_RUNNERS, name)

    def test_every_operation_a_body_names_is_one_the_agent_holds(self):
        for name in ("jira-reader", "jira-writer"):
            held = {t.removeprefix("mcp__atlassian__") for t in tools(frontmatter(name))}
            if "executeRead" in held:
                held |= EXECUTE_READ_OPS
            body = (AGENTS / f"{name}.md").read_text().split("\n---\n", 1)[1]
            named = set(BODY_TOOL.findall(body))
            self.assertTrue(named, name)
            self.assertEqual(named - held, set(), name)


if __name__ == "__main__":
    unittest.main()
