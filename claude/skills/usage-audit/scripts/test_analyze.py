#!/usr/bin/env python3
"""Tests for analyze.py.

Run: python3 claude/skills/usage-audit/scripts/test_analyze.py

Fixtures are synthetic JSONL written to a temp dir -- the suite never reads the
real ~/.claude/projects corpus, so it stays deterministic and leaks nothing.

The schema these tests encode was verified empirically against real transcripts
(CLI 2.1.x); see references/schema.md. The parser must VALIDATE rather than
assume, so a large share of these tests are drift and malformed-input cases.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if not ok and detail else ""))


def w(path, records):
    """Write records (dicts or raw strings) as JSONL."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in records:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
    return path


def usage(inp=0, out=0, cr=0, cc=0):
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cc,
    }


def asst(mid, ts, model="claude-opus-5", u=None, content=None, **kw):
    rec = {
        "type": "assistant",
        "uuid": f"u-{mid}-{ts}",
        "timestamp": ts,
        "sessionId": "s1",
        "gitBranch": "feat/x",
        "cwd": "/Users/x/Projects/app",
        "version": "2.1.200",
        "isSidechain": False,
        "message": {
            "id": mid,
            "role": "assistant",
            "model": model,
            "usage": u if u is not None else usage(10, 20, 30, 40),
            "content": content if content is not None else [{"type": "text", "text": "hi"}],
        },
    }
    rec.update(kw)
    return rec


def main():
    with tempfile.TemporaryDirectory() as td:
        # build_report reads the gate log by default. Aim that default at a file that does not
        # exist, so no test depends on (or reads) the developer's real ~/.claude/gate-log.jsonl.
        os.environ["GATE_LOG"] = os.path.join(td, "absent", "gate-log.jsonl")

        # --- 1. Deduplication: the single most important correctness rule ------
        # One API response is written as N lines (one per content block), each
        # carrying the FULL usage object. Verified on real data: 2431 lines ->
        # 1283 messages, with one message repeated 9 times.
        p = w(os.path.join(td, "dedup.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(2, 6184, 418368, 100),
                 content=[{"type": "text", "text": "x"}]),
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(2, 6184, 418368, 100),
                 content=[{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}]),
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(2, 6184, 418368, 100),
                 content=[{"type": "tool_use", "name": "Bash", "id": "t2", "input": {}}]),
        ])
        s = analyze.analyze_session(p)
        check("1a. three lines of one message count as one message",
              s["messages"] == 1, f"got {s['messages']}")
        check("1b. output tokens counted once, not three times",
              s["tokens"]["output"] == 6184, f"got {s['tokens']['output']}")
        check("1c. cache_read counted once",
              s["tokens"]["cache_read"] == 418368, f"got {s['tokens']['cache_read']}")

        # Distinct ids must NOT collapse.
        p = w(os.path.join(td, "distinct.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(out=100)),
            asst("msg_b", "2026-09-01T10:01:00.000Z", u=usage(out=200)),
        ])
        s = analyze.analyze_session(p)
        check("1d. distinct message ids are not collapsed",
              s["messages"] == 2 and s["tokens"]["output"] == 300,
              f"msgs={s['messages']} out={s['tokens']['output']}")

        # Tool calls are counted per block, NOT deduped away with the message.
        p = w(os.path.join(td, "tools.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z",
                 content=[{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}]),
            asst("msg_a", "2026-09-01T10:00:00.000Z",
                 content=[{"type": "tool_use", "name": "Read", "id": "t2", "input": {}}]),
        ])
        s = analyze.analyze_session(p)
        check("1e. tool calls survive message dedup",
              s["tools"]["Bash"]["calls"] == 1 and s["tools"]["Read"]["calls"] == 1,
              json.dumps(s["tools"]))

        # --- 2. Malformed and unknown input -----------------------------------
        p = w(os.path.join(td, "bad.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(out=5)),
            "{not valid json",
            "",
            json.dumps({"type": "totally-new-record-type", "uuid": "z"}),
            json.dumps({"type": "assistant"}),  # no message at all
        ])
        s = analyze.analyze_session(p)
        check("2a. malformed line is counted, not fatal",
              s["drift"]["unparseable_lines"] == 1, json.dumps(s["drift"]))
        check("2b. unknown record type is counted, not silently dropped",
              s["drift"]["unknown_types"].get("totally-new-record-type") == 1,
              json.dumps(s["drift"]))
        check("2c. assistant record without usage is counted as drift",
              s["drift"]["assistant_without_usage"] == 1, json.dumps(s["drift"]))
        check("2d. good record still parsed alongside bad ones",
              s["tokens"]["output"] == 5, f"got {s['tokens']['output']}")

        # Missing individual usage fields must default to 0, not crash.
        p = w(os.path.join(td, "partial.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u={"output_tokens": 7}),
        ])
        s = analyze.analyze_session(p)
        check("2e. missing usage subfields default to zero",
              s["tokens"]["output"] == 7 and s["tokens"]["cache_read"] == 0,
              json.dumps(s["tokens"]))

        # --- 3. Five-hour blocks (reimplemented, no ccusage dependency) --------
        ts = [
            "2026-09-01T10:30:00.000Z",  # block 1 starts, floored to 10:00
            "2026-09-01T12:00:00.000Z",  # same block
            "2026-09-01T14:59:00.000Z",  # same block (< 5h from 10:00)
            "2026-09-01T15:30:00.000Z",  # new block: past the 5h window
        ]
        blocks = analyze.five_hour_blocks(ts)
        check("3a. window boundary opens a new block",
              len(blocks) == 2, f"got {len(blocks)}")
        check("3b. block start is floored to the hour",
              blocks[0]["start"].endswith("10:00:00+00:00"), blocks[0]["start"])
        check("3c. messages are attributed to their block",
              blocks[0]["messages"] == 3 and blocks[1]["messages"] == 1,
              json.dumps([b["messages"] for b in blocks]))

        # A gap longer than the window also starts a new block.
        blocks = analyze.five_hour_blocks([
            "2026-09-01T10:00:00.000Z", "2026-09-02T10:00:00.000Z",
        ])
        check("3d. a long idle gap starts a new block",
              len(blocks) == 2, f"got {len(blocks)}")
        check("3e. no timestamps yields no blocks",
              analyze.five_hour_blocks([]) == [], "expected []")

        # --- 4. Time: turn_duration when present, deltas when not -------------
        p = w(os.path.join(td, "timed.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            {"type": "system", "subtype": "turn_duration", "durationMs": 27903,
             "messageCount": 19, "timestamp": "2026-09-01T10:00:30.000Z"},
            {"type": "system", "subtype": "turn_duration", "durationMs": 51680,
             "messageCount": 32, "timestamp": "2026-09-01T10:02:00.000Z"},
        ])
        s = analyze.analyze_session(p)
        check("4a. turn_duration records are summed as agent time",
              s["time"]["agent_ms"] == 79583, json.dumps(s["time"]))
        check("4b. turn_duration source is reported",
              s["time"]["source"] == "turn_duration", json.dumps(s["time"]))

        p = w(os.path.join(td, "untimed.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            asst("msg_b", "2026-09-01T10:05:00.000Z"),
        ])
        s = analyze.analyze_session(p)
        check("4c. falls back to timestamp deltas when turn_duration is absent",
              s["time"]["source"] == "timestamps", json.dumps(s["time"]))
        check("4d. elapsed span covers first to last record",
              s["time"]["span_ms"] == 300000, json.dumps(s["time"]))

        # --- 5. Tool result sizing across heterogeneous shapes -----------------
        # Real toolUseResult is dict (Bash: stdout/stderr), dict (Read: file),
        # list, or bare string. Sizing must be shape-agnostic.
        base = asst("msg_a", "2026-09-01T10:00:00.000Z",
                    content=[{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}])
        p = w(os.path.join(td, "sizes.jsonl"), [
            base,
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"stdout": "x" * 4000, "stderr": "", "interrupted": False},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1"}]}},
        ])
        s = analyze.analyze_session(p)
        check("5a. bash stdout size is measured",
              s["tools"]["Bash"]["result_bytes"] >= 4000,
              json.dumps(s["tools"]["Bash"]))

        for shape, payload in (("string", "y" * 300),
                               ("list", [{"type": "text", "text": "z" * 300}]),
                               ("file", {"file": {"filePath": "/a", "content": "w" * 300}})):
            p = w(os.path.join(td, f"shape_{shape}.jsonl"), [
                base,
                {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
                 "toolUseResult": payload,
                 "message": {"role": "user", "content": [
                     {"type": "tool_result", "tool_use_id": "t1"}]}},
            ])
            s = analyze.analyze_session(p)
            check(f"5b. tool result shaped as {shape} is sized without crashing",
                  s["tools"]["Bash"]["result_bytes"] >= 300,
                  json.dumps(s["tools"]["Bash"]))

        # --- 6. Redaction: the report must never carry raw content ------------
        secret = "ghp_SUPERSECRETTOKENVALUE123456"
        p = w(os.path.join(td, "secret.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z",
                 content=[{"type": "tool_use", "name": "Bash", "id": "t1",
                           "input": {"command": f"export TOKEN={secret}"}}]),
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"stdout": secret, "stderr": ""},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1"}]}},
        ])
        s = analyze.analyze_session(p)
        check("6a. no raw tool output or prompt text reaches the JSON output",
              secret not in json.dumps(s), "secret leaked into output")

        # The request log stores every prompt and tool result again, content-addressed.
        p = w(os.path.join(td, "secret-blob.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            {"type": "api-request-blob", "sessionId": "s1", "hash": "h1",
             "message": {"role": "user", "content": [{"type": "text", "text": secret}]}},
        ])
        s = analyze.analyze_session(p)
        check("6b. no request-log message content reaches the JSON output",
              secret not in json.dumps(s), "secret leaked into output")

        # --- 7. Attribution: skills, models, PRs, branches --------------------
        p = w(os.path.join(td, "attrib.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", model="claude-opus-5",
                 u=usage(out=100), attributionSkill="test-driven-development"),
            asst("msg_b", "2026-09-01T10:01:00.000Z", model="claude-sonnet-5",
                 u=usage(out=50), attributionSkill="test-driven-development"),
            asst("msg_c", "2026-09-01T10:02:00.000Z", model="claude-sonnet-5",
                 u=usage(out=25)),
            {"type": "pr-link", "sessionId": "s1", "prNumber": 199,
             "prUrl": "https://github.com/o/r/pull/199", "prRepository": "o/r",
             "timestamp": "2026-09-01T10:03:00.000Z"},
        ])
        s = analyze.analyze_session(p)
        check("7a. model mix is keyed by deduped message",
              s["models"]["claude-sonnet-5"]["messages"] == 2,
              json.dumps(s["models"]))
        check("7b. model mix carries output tokens",
              s["models"]["claude-opus-5"]["output"] == 100, json.dumps(s["models"]))
        check("7c. attributionSkill drives phase attribution",
              s["skills"]["test-driven-development"]["output"] == 150,
              json.dumps(s["skills"]))
        check("7d. unattributed messages are not invented into a skill",
              sum(v["messages"] for v in s["skills"].values()) == 2,
              json.dumps(s["skills"]))
        check("7e. pr-link is captured for per-PR rollup",
              s["prs"] == ["o/r#199"], json.dumps(s["prs"]))
        check("7f. pr-link is deduped across repeated records",
              len(s["prs"]) == 1, json.dumps(s["prs"]))
        check("7g. branch is captured",
              s["branches"] == ["feat/x"], json.dumps(s["branches"]))

        # --- 8. Subagents ------------------------------------------------------
        # Real layout: <project>/<session-id>/subagents/<id>.jsonl
        proj = os.path.join(td, "corpus", "-Users-x-Projects-app")
        w(os.path.join(proj, "sess1.jsonl"),
          [asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(out=100))])
        w(os.path.join(proj, "sess1", "subagents", "sub1.jsonl"),
          [asst("msg_s", "2026-09-01T10:00:30.000Z", u=usage(out=70), isSidechain=True)])
        c = analyze.analyze_corpus(os.path.join(td, "corpus"), days=None)
        check("8a. subagent transcripts are discovered under subagents/",
              c["totals"]["subagent_sessions"] == 1, json.dumps(c["totals"]))
        check("8b. subagent tokens are attributed to the parent session",
              c["sessions"][0]["subagents"]["output"] == 70,
              json.dumps(c["sessions"][0]["subagents"]))
        check("8c. main-session tokens stay separate from subagent tokens",
              c["sessions"][0]["tokens"]["output"] == 100,
              json.dumps(c["sessions"][0]["tokens"]))
        check("8d. subagent sessions are not counted as main sessions",
              c["totals"]["sessions"] == 1, json.dumps(c["totals"]))

        # --- 9. Compaction -----------------------------------------------------
        p = w(os.path.join(td, "compact.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            {"type": "system", "subtype": "compact_boundary",
             "timestamp": "2026-09-01T10:01:00.000Z"},
            {"type": "user", "isCompactSummary": True,
             "timestamp": "2026-09-01T10:01:01.000Z",
             "message": {"role": "user", "content": "summary"}},
        ])
        s = analyze.analyze_session(p)
        check("9a. compaction boundaries are counted once, not twice",
              s["compactions"] == 1, f"got {s['compactions']}")

        # --- 10. Window filtering ----------------------------------------------
        proj2 = os.path.join(td, "corpus2", "-Users-x-Projects-app")
        w(os.path.join(proj2, "old.jsonl"),
          [asst("msg_o", "2020-01-01T10:00:00.000Z", u=usage(out=999))])
        w(os.path.join(proj2, "new.jsonl"),
          [asst("msg_n", analyze.now_iso(), u=usage(out=5))])
        c = analyze.analyze_corpus(os.path.join(td, "corpus2"), days=7)
        check("10a. --days excludes sessions outside the window",
              c["totals"]["sessions"] == 1, json.dumps(c["totals"]))
        check("10b. excluded session tokens are not in the totals",
              c["totals"]["tokens"]["output"] == 5,
              json.dumps(c["totals"]["tokens"]))
        c = analyze.analyze_corpus(os.path.join(td, "corpus2"), days=None)
        check("10c. no --days keeps everything",
              c["totals"]["sessions"] == 2, json.dumps(c["totals"]))

        # --- 11. Empty and absent inputs ---------------------------------------
        p = w(os.path.join(td, "empty.jsonl"), [])
        s = analyze.analyze_session(p)
        check("11a. an empty transcript yields zeroes, not an exception",
              s["messages"] == 0 and s["tokens"]["output"] == 0, json.dumps(s["tokens"]))
        c = analyze.analyze_corpus(os.path.join(td, "does-not-exist"), days=None)
        check("11b. a missing corpus root yields an empty result, not an exception",
              c["totals"]["sessions"] == 0, json.dumps(c["totals"]))

        # --- 12. Cache hit ratio ------------------------------------------------
        p = w(os.path.join(td, "cache.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(inp=10, cr=90, cc=0)),
        ])
        s = analyze.analyze_session(p)
        check("12a. cache hit ratio is cache_read over all input",
              abs(s["cache_hit_ratio"] - 0.9) < 1e-9, str(s["cache_hit_ratio"]))
        p = w(os.path.join(td, "nocache.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(inp=0, cr=0, cc=0)),
        ])
        s = analyze.analyze_session(p)
        check("12b. zero input does not divide by zero",
              s["cache_hit_ratio"] == 0.0, str(s["cache_hit_ratio"]))


        # --- 13. Fixed per-session context cost --------------------------------
        # What every session pays before any work happens -- and what each
        # subagent re-pays.
        home = os.path.join(td, "fakehome")
        os.makedirs(os.path.join(home, "skills", "alpha"))
        os.makedirs(os.path.join(home, "skills", "beta"))
        os.makedirs(os.path.join(home, "commands"))
        with open(os.path.join(home, "CLAUDE.md"), "w") as fh:
            fh.write("g" * 400)
        with open(os.path.join(home, "skills", "alpha", "SKILL.md"), "w") as fh:
            fh.write("---\nname: alpha\ndescription: " + "d" * 100
                     + "\n---\n\n# Alpha\n" + "BODY" * 500)
        with open(os.path.join(home, "skills", "beta", "SKILL.md"), "w") as fh:
            fh.write("---\nname: beta\ndescription: " + "e" * 60 + "\n---\n\nbody")
        with open(os.path.join(home, "commands", "c.md"), "w") as fh:
            fh.write("x" * 200)

        fc = analyze.fixed_context_cost(home)
        check("13a. global CLAUDE.md is measured",
              fc["global_claude_md"]["chars"] == 400, json.dumps(fc["global_claude_md"]))
        check("13b. both skill descriptions are counted",
              fc["skill_descriptions"]["count"] == 2,
              json.dumps(fc["skill_descriptions"]))
        check("13c. only the description is counted, not the SKILL.md body",
              fc["skill_descriptions"]["chars"] < 300,
              json.dumps(fc["skill_descriptions"]))
        check("13d. token estimate is derived from characters",
              fc["global_claude_md"]["est_tokens"] == 100,
              json.dumps(fc["global_claude_md"]))
        check("13e. a total estimate is reported",
              fc["total_est_tokens"] > 0, json.dumps(fc))

        proj = os.path.join(td, "fakeproj")
        os.makedirs(proj)
        with open(os.path.join(proj, "CLAUDE.md"), "w") as fh:
            fh.write("p" * 80)
        fc = analyze.fixed_context_cost(home, project_dir=proj)
        check("13f. project CLAUDE.md is added when a project is given",
              fc["project_claude_md"]["chars"] == 80,
              json.dumps(fc["project_claude_md"]))

        fc = analyze.fixed_context_cost(os.path.join(td, "no-such-home"))
        check("13g. a missing config home yields zeroes, not an exception",
              fc["total_est_tokens"] == 0, json.dumps(fc))

        # --- 14. Codex cross-check cost ----------------------------------------
        # Rollout format: {timestamp, ordinal, type, payload}; the last
        # token_count event carries the cumulative total for the session.
        cx = os.path.join(td, "codex", "2026", "09", "20")
        w(os.path.join(cx, "rollout-2026-09-20T12-31-04-abc.jsonl"), [
            {"timestamp": "2026-09-20T15:31:04.605Z", "ordinal": 0,
             "type": "session_meta",
             "payload": {"session_id": "abc", "originator": "codex_exec",
                         "cwd": "/Users/x/Projects/app"}},
            {"timestamp": "2026-09-20T15:33:04.605Z", "ordinal": 5,
             "type": "event_msg",
             "payload": {"type": "token_count",
                         "info": {"total_token_usage": {
                             "input_tokens": 900, "output_tokens": 100,
                             "cached_input_tokens": 800, "total_tokens": 1000}}}},
            {"timestamp": "2026-09-20T15:36:04.605Z", "ordinal": 9,
             "type": "event_msg",
             "payload": {"type": "token_count",
                         "info": {"total_token_usage": {
                             "input_tokens": 1800, "output_tokens": 200,
                             "cached_input_tokens": 1600, "total_tokens": 2000}}}},
        ])
        cs = analyze.codex_summary(os.path.join(td, "codex"), days=None)
        check("14a. codex sessions are discovered in the dated tree",
              cs["sessions"] == 1, json.dumps(cs))
        check("14b. codex wall time spans first to last record",
              cs["wall_ms"] == 300000, json.dumps(cs))
        check("14c. codex tokens come from the LAST cumulative token_count",
              cs["tokens"]["total"] == 2000, json.dumps(cs["tokens"]))
        check("14d. a missing codex root yields zeroes, not an exception",
              analyze.codex_summary(os.path.join(td, "no-codex"), days=None)["sessions"] == 0,
              "expected 0")

        # --- 15. Output hygiene -------------------------------------------------
        # The raw timestamp list is working state, not a metric; emitting it
        # would bloat the report the skill is meant to shrink.
        payload = analyze.build_report(os.path.join(td, "corpus"), days=None,
                                       project=None, claude_home=home,
                                       codex_root=os.path.join(td, "codex"))
        check("15a. per-session timestamp lists are stripped from the report",
              all("timestamps" not in s for s in payload["sessions"]),
              "timestamps present in report")
        check("15b. the report carries the fixed context cost",
              "fixed_context" in payload, json.dumps(list(payload.keys())))
        check("15c. the report carries the codex summary",
              "codex" in payload, json.dumps(list(payload.keys())))
        check("15d. the report is JSON-serialisable",
              isinstance(json.dumps(payload), str), "not serialisable")


        # --- 16. cost-state: the authoritative time split ----------------------
        # Discovered empirically: a `cost-state` record carries measured API and
        # tool duration, so time does NOT have to be inferred from timestamps.
        # It is cumulative and rewritten, so the LAST one wins.
        cost_rec = {
            "type": "cost-state", "sessionId": "s1",
            "totalCostUSD": 13.5, "totalAPIDuration": 1000,
            "totalToolDuration": 3000, "totalDuration": 10000,
            "totalLinesAdded": 462, "totalLinesRemoved": 68,
            "startTime": 1788461853869,
            "modelUsage": {
                "claude-opus-5[1m]": {"inputTokens": 1676, "outputTokens": 76860,
                                      "thinkingTokens": 30065, "costUSD": 13.4},
                "claude-haiku-4-5-20251001": {"inputTokens": 1834, "outputTokens": 30,
                                              "thinkingTokens": 0, "costUSD": 0.1},
            },
        }
        stale = dict(cost_rec, totalCostUSD=1.0, totalAPIDuration=1,
                     totalToolDuration=1, totalDuration=2)
        p = w(os.path.join(td, "cost.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"), stale, cost_rec,
        ])
        s = analyze.analyze_session(p)
        check("16a. measured API time is taken from cost-state",
              s["time"]["api_ms"] == 1000, json.dumps(s["time"]))
        check("16b. measured tool time is taken from cost-state",
              s["time"]["tool_ms"] == 3000, json.dumps(s["time"]))
        check("16c. idle time is the remainder of the session duration",
              s["time"]["idle_ms"] == 6000, json.dumps(s["time"]))
        check("16d. cost-state is the preferred time source",
              s["time"]["source"] == "cost-state", json.dumps(s["time"]))
        check("16e. the last cost-state wins over earlier ones",
              s["cost"]["usd"] == 13.5, json.dumps(s["cost"]))
        check("16f. lines added and removed are captured as a work denominator",
              s["cost"]["lines_added"] == 462 and s["cost"]["lines_removed"] == 68,
              json.dumps(s["cost"]))
        check("16g. per-model usage and cost are captured separately",
              s["model_usage"]["claude-opus-5[1m]"]["costUSD"] == 13.4,
              json.dumps(list(s["model_usage"])))
        check("16h. thinking tokens are surfaced",
              s["model_usage"]["claude-opus-5[1m]"]["thinkingTokens"] == 30065,
              json.dumps(s["model_usage"]))

        # Never let a malformed cost-state produce a negative or bogus split.
        p = w(os.path.join(td, "cost_bad.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            {"type": "cost-state", "sessionId": "s1", "totalAPIDuration": 9000,
             "totalToolDuration": 9000, "totalDuration": 1000},
        ])
        s = analyze.analyze_session(p)
        check("16i. an inconsistent split never yields negative idle time",
              s["time"]["idle_ms"] == 0, json.dumps(s["time"]))

        p = w(os.path.join(td, "nocost.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            asst("msg_b", "2026-09-01T10:01:00.000Z"),
        ])
        s = analyze.analyze_session(p)
        check("16j. a session without cost-state reports no cost, not a guess",
              s["cost"]["usd"] is None, json.dumps(s["cost"]))
        check("16k. api/tool time is None when unmeasured rather than invented",
              s["time"]["api_ms"] is None, json.dumps(s["time"]))

        # --- 17. Span is not active time ---------------------------------------
        # A session left open overnight spans hours it did not consume. Summing
        # spans across sessions produces a meaningless total, so the two are
        # reported separately and never conflated.
        p = w(os.path.join(td, "span.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            asst("msg_b", "2026-09-01T10:01:00.000Z"),   # 1 min: active
            asst("msg_c", "2026-09-01T18:00:00.000Z"),   # ~8h idle: not active
        ])
        s = analyze.analyze_session(p)
        check("17a. span covers the whole session",
              s["time"]["span_ms"] == 28800000, json.dumps(s["time"]))
        check("17b. active time excludes the long idle gap",
              s["time"]["active_ms"] == 60000, json.dumps(s["time"]))

        proj3 = os.path.join(td, "corpus3", "-Users-x-Projects-app")
        w(os.path.join(proj3, "a.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
            dict(cost_rec, sessionId="a"),
        ])
        c = analyze.analyze_corpus(os.path.join(td, "corpus3"), days=None)
        check("17c. totals carry the measured time split",
              c["totals"]["time"]["api_ms"] == 1000
              and c["totals"]["time"]["tool_ms"] == 3000,
              json.dumps(c["totals"]["time"]))
        check("17d. totals report how many sessions were actually measured",
              c["totals"]["time"]["measured_sessions"] == 1,
              json.dumps(c["totals"]["time"]))
        check("17e. totals carry measured cost",
              abs(c["totals"]["cost_usd"] - 13.5) < 1e-9,
              str(c["totals"]["cost_usd"]))

        # --- 18. Drift vocabulary ----------------------------------------------
        # Record types discovered on the real corpus must be known, so that a
        # genuinely new type stands out instead of drowning in familiar noise.
        for known in ("cost-state", "progress", "worktree-state", "relocated",
                      "atis-latch", "file-history-delta", "api-request-shape",
                      "api-request-blob", "api-request", "tools-used"):
            check(f"18. {known} is a recognised record type",
                  known in analyze.KNOWN_TYPES, "missing from KNOWN_TYPES")

        # The request log is known but not measured: assistant usage already counts it.
        plain = [asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(5, 50, 500, 5000))]
        request_log = [
            {"type": "api-request-shape", "sessionId": "s1", "shapeHash": "sh1",
             "timestamp": "2026-09-01T09:59:59.000Z", "version": "2.1.200",
             "shape": {"system": [{"type": "text", "text": "x"}], "tools": []}},
            {"type": "api-request-blob", "sessionId": "s1", "hash": "h1",
             "message": {"role": "user", "content": "x"}},
            {"type": "api-request", "sessionId": "s1", "id": "r1", "base": "b1",
             "shapeHash": "sh1", "tail": ["h1"], "keep": 0,
             "timestamp": "2026-09-01T09:59:59.500Z", "querySource": "repl_main_thread",
             "params": {"model": "claude-opus-5", "max_tokens": 64000}},
            {"type": "tools-used", "sessionId": "s1", "tools": ["Bash", "Read"]},
        ]
        bare = analyze.analyze_session(w(os.path.join(td, "bare.jsonl"), plain))
        logged = analyze.analyze_session(w(os.path.join(td, "logged.jsonl"),
                                           request_log + plain))
        check("18b. request-log records are not drift",
              logged["drift"]["unknown_types"] == {},
              json.dumps(logged["drift"]["unknown_types"]))
        check("18b. request-log records leave token totals unchanged",
              logged["tokens"] == bare["tokens"], json.dumps(logged["tokens"]))


        # --- 19. Pathological input must not crash a run -----------------------
        # A tool result only ever arrives via json.loads, so it is acyclic and
        # already depth-bounded by the decoder -- but deep nesting is still the
        # shape most likely to break the sizer, so it is pinned here.
        deep = cur = {}
        for _ in range(3000):
            cur["n"] = {}
            cur = cur["n"]
        p = w(os.path.join(td, "deep.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z",
                 content=[{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}]),
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": deep,
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1"}]}},
        ])
        s = analyze.analyze_session(p)
        check("19a. a deeply nested tool result does not crash the run",
              s["messages"] == 1, "run aborted")
        check("19b. a deeply nested tool result is still sized",
              s["tools"]["Bash"]["result_bytes"] > 0,
              json.dumps(s["tools"]["Bash"]))

        # A line too deep for the DECODER is the reachable failure, and it must
        # land in drift rather than abort the session.
        p = w(os.path.join(td, "deepline.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(out=11)),
            "[" * 200000 + "]" * 200000,
        ])
        s = analyze.analyze_session(p)
        check("19c. a line too deep to decode is counted as drift, not fatal",
              s["drift"]["unparseable_lines"] == 1 and s["tokens"]["output"] == 11,
              json.dumps(s["drift"]))


        # --- 20. The CLI ---------------------------------------------------------
        # These close coverage on paths whose behaviour was already specified --
        # characterisation tests, not new TDD cycles.
        import contextlib, io as _io

        out = _io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = analyze.main(["--root", os.path.join(td, "corpus"), "--days", "0",
                               "--claude-home", home,
                               "--codex-root", os.path.join(td, "codex")])
        payload = json.loads(out.getvalue())
        check("20a. the CLI exits zero", rc == 0, f"rc={rc}")
        check("20b. the CLI emits a single valid JSON document on stdout",
              payload["totals"]["sessions"] == 1, json.dumps(payload["totals"]))
        check("20c. --days 0 is treated as no window",
              payload["window_days"] is None, str(payload["window_days"]))

        out = _io.StringIO()
        with contextlib.redirect_stdout(out):
            analyze.main(["--root", os.path.join(td, "corpus"), "--days", "0",
                          "--project", "no-such-project", "--claude-home", home,
                          "--codex-root", os.path.join(td, "codex")])
        check("20d. --project filters projects out",
              json.loads(out.getvalue())["totals"]["sessions"] == 0, "filter ignored")

        # --- 21. Read-only guarantee ---------------------------------------------
        # The skill must never touch the corpus it reads.
        def snapshot(root):
            seen = {}
            for folder, _, files in os.walk(root):
                for n in files:
                    fp = os.path.join(folder, n)
                    st = os.stat(fp)
                    seen[fp] = (st.st_size, st.st_mtime_ns)
            return seen

        corpus = os.path.join(td, "corpus")
        before = snapshot(corpus)
        with contextlib.redirect_stdout(_io.StringIO()):
            analyze.main(["--root", corpus, "--days", "0", "--claude-home", home,
                          "--codex-root", os.path.join(td, "codex")])
        check("21a. a run leaves every transcript byte-for-byte untouched",
              snapshot(corpus) == before, "corpus was modified")

        # --- 22. Parsing edge cases ----------------------------------------------
        p = w(os.path.join(td, "badts.jsonl"), [
            asst("msg_a", "not-a-timestamp", u=usage(out=3)),
        ])
        s = analyze.analyze_session(p)
        check("22a. an unparseable timestamp is counted as drift, not fatal",
              s["drift"]["records_without_timestamp"] == 1 and s["tokens"]["output"] == 3,
              json.dumps(s["drift"]))
        check("22b. a session with no usable timestamps reports no span",
              s["time"]["span_ms"] == 0, json.dumps(s["time"]))

        missing = os.path.join(td, "definitely-not-here.jsonl")
        s = analyze.analyze_session(missing)
        check("22c. an unreadable transcript yields an empty session, not an exception",
              s["messages"] == 0, json.dumps(s["tokens"]))

        # A folded, multi-line frontmatter description must be counted whole.
        os.makedirs(os.path.join(home, "skills", "gamma"))
        with open(os.path.join(home, "skills", "gamma", "SKILL.md"), "w") as fh:
            fh.write("---\nname: gamma\ndescription: first part\n"
                     "  continued second part\nallowed-tools: Read\n---\nbody")
        desc = analyze._description_of(os.path.join(home, "skills", "gamma", "SKILL.md"))
        check("22d. a folded description is joined across its continuation lines",
              "continued second part" in desc, repr(desc))
        check("22e. the key after the description is not swallowed into it",
              "allowed-tools" not in desc, repr(desc))

        with open(os.path.join(home, "skills", "gamma", "nofm.md"), "w") as fh:
            fh.write("no frontmatter here")
        check("22f. a file without frontmatter yields an empty description",
              analyze._description_of(
                  os.path.join(home, "skills", "gamma", "nofm.md")) == "", "not empty")

        # --- 23. Codex edge cases -------------------------------------------------
        cx2 = os.path.join(td, "codex2", "2026", "09", "21")
        w(os.path.join(cx2, "rollout-2026-09-21T10-00-00-def.jsonl"), [
            "{broken json",
            {"ordinal": 0, "type": "session_meta", "payload": {"session_id": "def"}},
        ])
        w(os.path.join(cx2, "not-a-rollout.jsonl"), [
            {"timestamp": "2026-09-21T10:00:00.000Z", "type": "event_msg", "payload": {}},
        ])
        cs = analyze.codex_summary(os.path.join(td, "codex2"), days=None)
        check("23a. a rollout with no usable timestamps is skipped",
              cs["sessions"] == 0, json.dumps(cs))
        check("23b. a broken codex line is counted as drift",
              cs["drift"]["unparseable_lines"] == 1, json.dumps(cs["drift"]))
        check("23c. files that are not rollouts are ignored",
              cs["sessions"] == 0, json.dumps(cs))

        cs = analyze.codex_summary(os.path.join(td, "codex"), days=1)
        check("23d. the codex window filter excludes old runs",
              cs["sessions"] == 0, json.dumps(cs))


        # --- 24. Per-PR rollup --------------------------------------------------
        # A session routinely opens several PRs (observed: one session linking
        # 31). Charging the whole session to each PR multiplies the cost, so a
        # multi-PR session is SPLIT evenly and the result is labelled as an
        # allocation rather than a measurement.
        pr_proj = os.path.join(td, "prcorpus", "-Users-x-Projects-app")
        w(os.path.join(pr_proj, "one.jsonl"), [
            asst("msg_1", "2026-09-01T10:00:00.000Z", u=usage(out=100)),
            {"type": "cost-state", "sessionId": "one", "totalCostUSD": 10.0,
             "totalAPIDuration": 1000, "totalToolDuration": 0, "totalDuration": 1000,
             "totalLinesAdded": 50, "totalLinesRemoved": 0},
            {"type": "pr-link", "prRepository": "o/r", "prNumber": 1,
             "timestamp": "2026-09-01T10:01:00.000Z"},
        ])
        w(os.path.join(pr_proj, "two.jsonl"), [
            asst("msg_2", "2026-09-02T10:00:00.000Z", u=usage(out=80)),
            {"type": "cost-state", "sessionId": "two", "totalCostUSD": 8.0,
             "totalAPIDuration": 800, "totalToolDuration": 0, "totalDuration": 800,
             "totalLinesAdded": 20, "totalLinesRemoved": 0},
            {"type": "pr-link", "prRepository": "o/r", "prNumber": 1,
             "timestamp": "2026-09-02T10:01:00.000Z"},
            {"type": "pr-link", "prRepository": "o/r", "prNumber": 2,
             "timestamp": "2026-09-02T10:02:00.000Z"},
        ])
        w(os.path.join(pr_proj, "none.jsonl"), [
            asst("msg_3", "2026-09-03T10:00:00.000Z", u=usage(out=40)),
        ])
        c = analyze.analyze_corpus(os.path.join(td, "prcorpus"), days=None)
        per = c["per_pr"]

        check("24a. a single-PR session is charged in full",
              per["o/r#1"]["output"] == 100 + 40, json.dumps(per["o/r#1"]))
        check("24b. a two-PR session splits its cost evenly",
              per["o/r#2"]["output"] == 40, json.dumps(per["o/r#2"]))
        check("24c. a PR touched by several sessions accumulates",
              per["o/r#1"]["sessions"] == 2, json.dumps(per["o/r#1"]))
        check("24d. a PR fed by a multi-PR session is labelled split",
              per["o/r#2"]["allocation"] == "split", per["o/r#2"]["allocation"])
        check("24e. cost is split the same way as tokens",
              abs(per["o/r#2"]["usd"] - 4.0) < 1e-9, str(per["o/r#2"]["usd"]))
        check("24f. measured time is split the same way",
              per["o/r#2"]["api_ms"] == 400, json.dumps(per["o/r#2"]))
        check("24g. lines are split the same way",
              per["o/r#2"]["lines_added"] == 10, json.dumps(per["o/r#2"]))
        check("24h. a PR fed by any multi-PR session is labelled split",
              per["o/r#1"]["allocation"] == "split", per["o/r#1"]["allocation"])

        # Work that never reached a PR must be visible, not silently dropped.
        check("24i. sessions with no PR land in an unattributed bucket",
              c["unattributed"]["output"] == 40, json.dumps(c["unattributed"]))
        check("24j. the unattributed bucket counts its sessions",
              c["unattributed"]["sessions"] == 1, json.dumps(c["unattributed"]))


        # --- 25. Images are not text -------------------------------------------
        # A screenshot result is base64 bytes, but an image is tokenised by its
        # DIMENSIONS, not its byte length. Counting its bytes as text makes
        # screenshots look like the biggest context cost in the corpus when they
        # are not, so they are measured in a separate bucket.
        img_call = asst("msg_i", "2026-09-01T10:00:00.000Z",
                        content=[{"type": "tool_use", "name": "Snap",
                                  "id": "t9", "input": {}}])
        p = w(os.path.join(td, "img.jsonl"), [
            img_call,
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": [{"type": "image",
                                "source": {"type": "base64", "data": "Q" * 5000}}],
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t9"}]}},
        ])
        s = analyze.analyze_session(p)
        check("25a. image payload bytes stay out of result_bytes",
              s["tools"]["Snap"]["result_bytes"] == 0,
              json.dumps(s["tools"]["Snap"]))
        check("25b. image payloads are counted in their own bucket",
              s["tools"]["Snap"]["image_bytes"] >= 5000,
              json.dumps(s["tools"]["Snap"]))
        check("25c. image results are counted separately from text results",
              s["tools"]["Snap"]["image_results"] == 1
              and s["tools"]["Snap"]["results"] == 0,
              json.dumps(s["tools"]["Snap"]))

        # The isImage flag is the other shape this arrives in.
        p = w(os.path.join(td, "img2.jsonl"), [
            img_call,
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"isImage": True, "stdout": "Q" * 5000},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t9"}]}},
        ])
        s = analyze.analyze_session(p)
        check("25d. an isImage result is also routed to the image bucket",
              s["tools"]["Snap"]["image_results"] == 1,
              json.dumps(s["tools"]["Snap"]))

        p = w(os.path.join(td, "img3.jsonl"), [
            img_call,
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"stdout": "plain text", "isImage": False},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t9"}]}},
        ])
        s = analyze.analyze_session(p)
        check("25e. a text result is unaffected by the image split",
              s["tools"]["Snap"]["result_bytes"] > 0
              and s["tools"]["Snap"]["image_results"] == 0,
              json.dumps(s["tools"]["Snap"]))

        # --- 26. Commands cost their description, not their body ---------------
        # A slash command's body loads when it is invoked, exactly like a skill's.
        # Only the frontmatter description is standing per-session cost.
        fc = analyze.fixed_context_cost(home)
        check("26a. only the command description counts as standing cost",
              fc["commands"]["chars"] < 100, json.dumps(fc["commands"]))
        check("26b. the command body is reported separately, not as fixed cost",
              fc["commands"]["body_chars"] >= 200, json.dumps(fc["commands"]))

        os.makedirs(os.path.join(home, "commands2"), exist_ok=True)
        with open(os.path.join(home, "commands", "d.md"), "w") as fh:
            fh.write("---\ndescription: " + "z" * 40 + "\n---\n" + "B" * 4000)
        fc = analyze.fixed_context_cost(home)
        check("26c. a command with frontmatter contributes only its description",
              fc["commands"]["chars"] < 100, json.dumps(fc["commands"]))
        check("26d. its body lands in body_chars",
              fc["commands"]["body_chars"] >= 4000, json.dumps(fc["commands"]))


        # --- 27. Naive timestamps must not abort the audit ----------------------
        # A timestamp with no Z and no offset parses to a naive datetime, which
        # then cannot be compared with the aware ones. One such record used to
        # take down the whole report.
        check("27a. a naive timestamp is normalised to UTC",
              analyze.parse_ts("2026-09-22T10:00:00").tzinfo is not None,
              "still naive")
        p = w(os.path.join(td, "naive.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=usage(out=5)),
            asst("msg_b", "2026-09-01T11:00:00", u=usage(out=7)),
        ])
        s = analyze.analyze_session(p)
        check("27b. a session mixing naive and aware timestamps still parses",
              s["tokens"]["output"] == 12, json.dumps(s["tokens"]))
        nv = os.path.join(td, "naivecorpus", "-Users-x-Projects-app")
        w(os.path.join(nv, "n.jsonl"), [asst("msg_n", "2026-09-01T11:00:00", u=usage(out=3))])
        c = analyze.analyze_corpus(os.path.join(td, "naivecorpus"), days=None)
        check("27c. a naive timestamp does not abort the corpus walk",
              c["totals"]["tokens"]["output"] == 3, json.dumps(c["totals"]["tokens"]))

        # --- 28. Dedup must survive a missing message.id ------------------------
        # Without an id every content-block line re-adds the full usage object --
        # the exact 2-9x overcount this module exists to prevent.
        p = w(os.path.join(td, "noid.jsonl"), [
            {"type": "assistant", "timestamp": "2026-09-01T10:00:00.000Z",
             "requestId": "req_1", "sessionId": "s1",
             "message": {"role": "assistant", "model": "m", "usage": usage(cr=100),
                         "content": [{"type": "text", "text": "a"}]}},
            {"type": "assistant", "timestamp": "2026-09-01T10:00:00.000Z",
             "requestId": "req_1", "sessionId": "s1",
             "message": {"role": "assistant", "model": "m", "usage": usage(cr=100),
                         "content": [{"type": "text", "text": "b"}]}},
        ])
        s = analyze.analyze_session(p)
        check("28a. requestId stands in for a missing message.id",
              s["tokens"]["cache_read"] == 100, json.dumps(s["tokens"]))
        check("28b. the message count agrees with the token count",
              s["messages"] == 1 and s["models"]["m"]["messages"] == 1,
              f"{s['messages']} vs {s['models']['m']['messages']}")

        p = w(os.path.join(td, "noid2.jsonl"), [
            {"type": "assistant", "timestamp": "2026-09-01T10:00:00.000Z",
             "sessionId": "s1",
             "message": {"role": "assistant", "model": "m", "usage": usage(cr=100),
                         "content": [{"type": "text", "text": "a"}]}},
        ])
        s = analyze.analyze_session(p)
        check("28c. a record with no id at all is counted as drift",
              s["drift"]["messages_without_id"] == 1, json.dumps(s["drift"]))

        # --- 29. Orphaned subagent transcripts ----------------------------------
        # 13% of real subagent files have no surviving parent .jsonl. Dropping
        # them understated subagent tokens by ~18%.
        orph = os.path.join(td, "orphcorpus", "-Users-x-Projects-app")
        w(os.path.join(orph, "live.jsonl"), [asst("msg_l", "2026-09-01T10:00:00.000Z", u=usage(out=10))])
        w(os.path.join(orph, "live", "subagents", "s1.jsonl"),
          [asst("msg_s1", "2026-09-01T10:00:10.000Z", u=usage(out=5))])
        w(os.path.join(orph, "ghost", "subagents", "s2.jsonl"),
          [asst("msg_s2", "2026-09-01T10:00:20.000Z", u=usage(out=70))])
        c = analyze.analyze_corpus(os.path.join(td, "orphcorpus"), days=None)
        check("29a. every subagent transcript on disk is counted",
              c["totals"]["subagent_sessions"] == 2, json.dumps(c["totals"]))
        check("29b. orphaned subagent tokens are not lost",
              c["totals"]["subagent_tokens"]["output"] == 75,
              json.dumps(c["totals"]["subagent_tokens"]))
        check("29c. orphans are reported as such, not hidden in a parent",
              c["totals"]["orphan_subagents"] == 1, json.dumps(c["totals"]))

        # --- 30. --project must narrow the Codex section too --------------------
        cx3 = os.path.join(td, "codex3", "2026", "09", "20")
        for tag, cwd in (("aaa", "/Users/x/Projects/alpha"), ("bbb", "/Users/x/Projects/beta")):
            w(os.path.join(cx3, f"rollout-2026-09-20T12-00-00-{tag}.jsonl"), [
                {"timestamp": "2026-09-20T15:00:00.000Z", "type": "session_meta",
                 "payload": {"session_id": tag, "cwd": cwd}},
                {"timestamp": "2026-09-20T15:05:00.000Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {"total_token_usage": {
                     "total_tokens": 100}}}},
            ])
        cs = analyze.codex_summary(os.path.join(td, "codex3"), days=None, project="alpha")
        check("30a. --project narrows codex runs by their cwd",
              cs["sessions"] == 1, json.dumps(cs["runs"]))
        check("30b. codex tokens follow the same filter",
              cs["tokens"]["total"] == 100, json.dumps(cs["tokens"]))
        payload = analyze.build_report(os.path.join(td, "orphcorpus"), days=None,
                                       project="app", claude_home=home,
                                       codex_root=os.path.join(td, "codex3"))
        check("30c. build_report passes the project filter through to codex",
              payload["codex"]["sessions"] == 0, json.dumps(payload["codex"]["runs"]))

        # --- 31. Blocks must count messages and carry tokens --------------------
        # Saturation is the pivot the whole report turns on, so a block needs
        # deduped messages and their token weight -- not a count of every record.
        p = w(os.path.join(td, "blocktok.jsonl"), [
            asst("msg_b1", "2026-09-01T10:00:00.000Z", u=usage(inp=1, out=10, cr=100)),
            asst("msg_b1", "2026-09-01T10:00:00.000Z", u=usage(inp=1, out=10, cr=100)),
            {"type": "user", "timestamp": "2026-09-01T10:00:05.000Z",
             "message": {"role": "user", "content": "hi"}},
            {"type": "system", "subtype": "turn_duration", "durationMs": 10,
             "timestamp": "2026-09-01T10:00:06.000Z"},
        ])
        s = analyze.analyze_session(p)
        bl = analyze.five_hour_blocks(s["message_events"])
        check("31a. a block counts deduped messages, not every record",
              bl[0]["messages"] == 1, json.dumps(bl[0]))
        check("31b. a block carries the tokens that filled it",
              bl[0]["output"] == 10 and bl[0]["billed_input"] == 101,
              json.dumps(bl[0]))
        check("31c. plain timestamps are still accepted",
              analyze.five_hour_blocks(["2026-09-01T10:00:00.000Z"])[0]["messages"] == 1,
              "string form broke")

        # --- 32. Numeric coercion ------------------------------------------------
        # A CLI release emitting durations as floats must not silently report the
        # entire session as idle while still claiming a measured source.
        p = w(os.path.join(td, "floats.jsonl"), [
            asst("msg_f", "2026-09-01T10:00:00.000Z"),
            {"type": "cost-state", "sessionId": "s1", "totalAPIDuration": 1000.0,
             "totalToolDuration": 2000.0, "totalDuration": 5000.0,
             "totalLinesAdded": 3.0, "totalCostUSD": 1.5},
        ])
        s = analyze.analyze_session(p)
        check("32a. float durations are accepted, not zeroed",
              s["time"]["api_ms"] == 1000 and s["time"]["tool_ms"] == 2000,
              json.dumps(s["time"]))
        check("32b. a float line count is accepted",
              s["cost"]["lines_added"] == 3, json.dumps(s["cost"]))

        # --- 33. An unreadable project directory must not abort the audit -------
        import stat as _stat
        locked_root = os.path.join(td, "lockedcorpus")
        good = os.path.join(locked_root, "-Users-x-good")
        w(os.path.join(good, "g.jsonl"), [asst("msg_g", "2026-09-01T10:00:00.000Z", u=usage(out=9))])
        bad = os.path.join(locked_root, "-Users-x-bad")
        os.makedirs(bad)
        os.chmod(bad, 0)
        try:
            c = analyze.analyze_corpus(locked_root, days=None)
            check("33a. an unreadable project directory is skipped, not fatal",
                  c["totals"]["tokens"]["output"] == 9, json.dumps(c["totals"]["tokens"]))
        finally:
            os.chmod(bad, _stat.S_IRWXU)

        # --- 34. Tool results are deduplicated like tool calls -------------------
        p = w(os.path.join(td, "dupres.jsonl"), [
            asst("msg_t", "2026-09-01T10:00:00.000Z",
                 content=[{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}]),
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"stdout": "x" * 1000},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1"}]}},
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"stdout": "x" * 1000},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1"}]}},
        ])
        s = analyze.analyze_session(p)
        check("34a. a repeated tool_result is counted once",
              s["tools"]["Bash"]["results"] == 1, json.dumps(s["tools"]["Bash"]))
        check("34b. results never exceed calls for the same tool",
              s["tools"]["Bash"]["results"] <= s["tools"]["Bash"]["calls"],
              json.dumps(s["tools"]["Bash"]))

        # --- 35. Cross-folder parent join (AC1-3, AC14) ---------------------------
        # After EnterWorktree, subagents land under the worktree's project slug
        # while the parent .jsonl stays under the original repo's slug.
        def jcorpus(name):
            return os.path.join(td, name)

        cj = jcorpus("join1")
        fa, fb = "-Users-x-Projects-alpha", "-Users-x-worktrees-beta"
        w(os.path.join(cj, fa, "sess1.jsonl"),
          [asst("msg_p", "2026-09-01T10:00:00.000Z", u=usage(out=10))])
        w(os.path.join(cj, fb, "sess1", "subagents", "agent-a1.jsonl"),
          [asst("msg_x", "2026-09-01T10:00:10.000Z", u=usage(out=5))])
        c = analyze.analyze_corpus(cj, days=None)
        check("35a. a subagent in another folder attaches to its parent",
              c["sessions"][0]["subagents"]["sessions"] == 1
              and c["sessions"][0]["subagents"]["output"] == 5,
              json.dumps(c["sessions"][0]["subagents"]))
        check("35b. and is not counted as an orphan",
              c["totals"]["orphan_subagents"] == 0
              and c["totals"]["subagent_sessions"] == 1, json.dumps(c["totals"]))

        cj = jcorpus("join2")
        w(os.path.join(cj, fa, "sess1.jsonl"),
          [asst("msg_p", "2026-09-01T10:00:00.000Z", u=usage(out=10))])
        w(os.path.join(cj, fa, "sess1", "subagents", "agent-a1.jsonl"),
          [asst("msg_x", "2026-09-01T10:00:10.000Z", u=usage(out=5))])
        w(os.path.join(cj, fb, "sess1", "subagents", "agent-a2.jsonl"),
          [asst("msg_y", "2026-09-01T10:00:20.000Z", u=usage(out=7))])
        c = analyze.analyze_corpus(cj, days=None)
        check("35c. subagents from both folders attach, none twice",
              c["sessions"][0]["subagents"]["sessions"] == 2
              and c["totals"]["subagent_sessions"] == 2
              and c["totals"]["orphan_subagents"] == 0,
              json.dumps(c["totals"]))

        c = analyze.analyze_corpus(cj, days=None, project="alpha")
        check("35d. --project keeps the parent with subagents from other folders",
              len(c["sessions"]) == 1
              and c["sessions"][0]["subagents"]["sessions"] == 2,
              json.dumps(c["totals"]))

        c = analyze.analyze_corpus(cj, days=None, project="beta")
        check("35e. --project on the subagent folder neither attaches nor orphans it",
              len(c["sessions"]) == 0 and c["totals"]["orphan_subagents"] == 0
              and c["totals"]["subagent_sessions"] == 0, json.dumps(c["totals"]))

        cj = jcorpus("join3")
        w(os.path.join(cj, fb, "ghost", "subagents", "agent-g.jsonl"),
          [asst("msg_g", "2026-09-01T10:00:20.000Z", u=usage(out=7))])
        c = analyze.analyze_corpus(cj, days=None)
        check("35f. a subagent with no parent anywhere is an orphan",
              c["totals"]["orphan_subagents"] == 1, json.dumps(c["totals"]))

        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        recent = (_dt.now(_tz.utc) - _td(hours=1)).isoformat()
        cj = jcorpus("join4")
        w(os.path.join(cj, fa, "sess1.jsonl"), [asst("msg_p", recent, u=usage(out=10))])
        w(os.path.join(cj, fb, "sess1", "subagents", "agent-old.jsonl"),
          [asst("msg_o", "2026-01-01T10:00:00.000Z", u=usage(out=5))])
        c = analyze.analyze_corpus(cj, days=1)
        check("35g. --days keeps an old subagent of a recent parent, across folders",
              len(c["sessions"]) == 1 and c["sessions"][0]["subagents"]["sessions"] == 1
              and c["totals"]["orphan_subagents"] == 0, json.dumps(c["totals"]))

        # --- 36. Price weights and subagent meta (AC4, AC5) ----------------------
        split = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 1000,
                 "cache_creation_input_tokens": 500,
                 "cache_creation": {"ephemeral_5m_input_tokens": 200,
                                    "ephemeral_1h_input_tokens": 300}}
        expect = 100 + 0.1 * 1000 + 1.25 * 200 + 2 * 300 + 5 * 10
        check("36a. weight uses the 5m/1h cache-write split",
              abs(analyze._weighted(split) - expect) < 1e-9, analyze._weighted(split))
        nosplit = {"input_tokens": 100, "output_tokens": 10,
                   "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 500}
        expect = 100 + 0.1 * 1000 + 1.25 * 500 + 5 * 10
        check("36b. without the split all cache writes count at 1.25",
              abs(analyze._weighted(nosplit) - expect) < 1e-9, analyze._weighted(nosplit))
        p = w(os.path.join(td, "weighted.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=nosplit),
            asst("msg_a", "2026-09-01T10:00:00.000Z", u=nosplit),
        ])
        s = analyze.analyze_session(p)
        check("36c. the model bucket carries weighted tokens, once per message",
              abs(s["models"]["claude-opus-5"]["weighted"] - expect) < 1e-9,
              json.dumps(s["models"]))

        mp = os.path.join(td, "metas", "agent-abc.jsonl")
        w(mp, [asst("msg_a", "2026-09-01T10:00:00.000Z")])
        w(os.path.join(td, "metas", "agent-abc.meta.json"),
          [{"agentType": "implementer", "toolUseId": "toolu_1",
            "description": "SECRET DESCRIPTION", "spawnDepth": 1}])
        m = analyze._subagent_meta(mp)
        check("36d. meta yields agent_type, tool_use_id, agent_id and background",
              m == {"agent_type": "implementer", "tool_use_id": "toolu_1",
                    "agent_id": "abc", "background": False}, json.dumps(m))
        check("36e. the description never reaches the meta result",
              "SECRET" not in json.dumps(m), json.dumps(m))

        # Missing, malformed and agentType-less metas all degrade to "unknown".
        cm = jcorpus("metacorpus")
        w(os.path.join(cm, fa, "s.jsonl"), [asst("msg_p", "2026-09-01T10:00:00.000Z")])
        sd = os.path.join(cm, fa, "s", "subagents")
        for aid in ("nometa", "badmeta", "notype"):
            w(os.path.join(sd, f"agent-{aid}.jsonl"),
              [asst(f"msg_{aid}", "2026-09-01T10:00:10.000Z")])
        with open(os.path.join(sd, "agent-badmeta.meta.json"), "w") as fh:
            fh.write("{not json")
        w(os.path.join(sd, "agent-notype.meta.json"), [{"toolUseId": "t"}])
        check("36f. a missing meta yields unknown",
              analyze._subagent_meta(os.path.join(sd, "agent-nometa.jsonl"))["agent_type"]
              == "unknown", "")
        c = analyze.analyze_corpus(cm, days=None)
        check("36g. missing, malformed and typeless metas are counted as drift",
              c["drift"]["subagents_without_meta"] == 3, json.dumps(c["drift"]))

        # --- 37. Apportioned cost per agent type and model (AC5-8) ---------------
        OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"

        def cost_state(**by_model):
            return {"type": "cost-state", "timestamp": "2026-09-01T10:30:00.000Z",
                    "totalCostUSD": sum(by_model.values()),
                    "modelUsage": {k: {"costUSD": v} for k, v in by_model.items()}}

        def add_sub(corpus, folder, sid, aid, kind, records):
            d = os.path.join(corpus, folder, sid, "subagents")
            w(os.path.join(d, f"agent-{aid}.jsonl"), records)
            w(os.path.join(d, f"agent-{aid}.meta.json"),
              [{"agentType": kind, "toolUseId": f"toolu_{aid}"}])

        def rows_of(c):
            return {(r["agent_type"], r["model"]): r for r in c["subagents_by_type"]}

        # Opus weights: main 150, Explore 50 (W=200); Sonnet implementer 100.
        ca = jcorpus("apport")
        w(os.path.join(ca, fa, "s1.jsonl"), [
            asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=100, out=10)),
            cost_state(**{OPUS + "[1m]": 4.0, SONNET: 0.5}),
        ])
        add_sub(ca, fb, "s1", "imp", "implementer",
                [asst("m_imp", "2026-09-01T10:01:00.000Z", model=SONNET, u=usage(out=20))])
        add_sub(ca, fb, "s1", "exp", "Explore",
                [asst("m_exp", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        c = analyze.analyze_corpus(ca, days=None)
        rows = rows_of(c)
        imp, exp = rows[("implementer", SONNET)], rows[("Explore", OPUS)]
        check("37a. one row per (agent_type, model), main session excluded",
              set(rows) == {("implementer", SONNET), ("Explore", OPUS)}, json.dumps(list(rows)))
        check("37b. row carries spawns, messages, tokens and weighted tokens",
              imp["spawns"] == 1 and imp["messages"] == 1 and imp["output"] == 20
              and imp["input"] == 0 and imp["cache_read"] == 0 and imp["cache_creation"] == 0
              and abs(imp["weighted_tokens"] - 100) < 1e-9, json.dumps(imp))
        check("37c. a [1m]-suffixed cost-state key matches the bare model; costs split by weight",
              abs(exp["cost_usd"] - 1.0) < 1e-6 and abs(imp["cost_usd"] - 0.5) < 1e-6,
              f"{exp['cost_usd']} {imp['cost_usd']}")
        check("37d. priced rows report no unpriced messages",
              exp["unpriced_messages"] == 0 and imp["unpriced_messages"] == 0, "")

        # Two keys normalising to one model are summed: 3.0 + 1.0 = 4.0.
        cb = jcorpus("apport2")
        w(os.path.join(cb, fa, "s1.jsonl"), [
            asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=100, out=10)),
            cost_state(**{OPUS + "[1m]": 3.0, OPUS: 1.0}),
        ])
        add_sub(cb, fa, "s1", "exp", "Explore",
                [asst("m_exp", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        rows = rows_of(analyze.analyze_corpus(cb, days=None))
        check("37e. colliding normalised keys are summed",
              abs(rows[("Explore", OPUS)]["cost_usd"] - 1.0) < 1e-6,
              json.dumps(rows[("Explore", OPUS)]))

        # A subagent that used two models contributes one spawn to each row.
        cc = jcorpus("apport3")
        w(os.path.join(cc, fa, "s1.jsonl"), [
            asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=10)),
            cost_state(**{OPUS: 1.0, SONNET: 1.0}),
        ])
        add_sub(cc, fa, "s1", "two", "general-purpose", [
            asst("m_a", "2026-09-01T10:01:00.000Z", model=OPUS, u=usage(inp=10)),
            asst("m_b", "2026-09-01T10:02:00.000Z", model=SONNET, u=usage(inp=10)),
        ])
        rows = rows_of(analyze.analyze_corpus(cc, days=None))
        check("37f. a two-model subagent is one spawn in each row",
              rows[("general-purpose", OPUS)]["spawns"] == 1
              and rows[("general-purpose", SONNET)]["spawns"] == 1, json.dumps(list(rows)))

        # No cost-state: tokens reported, cost null, messages unpriced.
        cd = jcorpus("apport4")
        w(os.path.join(cd, fa, "s1.jsonl"),
          [asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=10))])
        add_sub(cd, fa, "s1", "exp", "Explore",
                [asst("m_exp", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        r = rows_of(analyze.analyze_corpus(cd, days=None))[("Explore", OPUS)]
        check("37g. without cost-state, cost_usd is null and messages are unpriced",
              r["cost_usd"] is None and r["unpriced_messages"] == 1
              and abs(r["weighted_tokens"] - 50) < 1e-9, json.dumps(r))

        # One (Explore, OPUS) row fed by a priced and an unpriced session.
        ce = jcorpus("apport5")
        w(os.path.join(ce, fa, "s1.jsonl"), [
            asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=50)),
            cost_state(**{OPUS: 2.0}),
        ])
        add_sub(ce, fa, "s1", "exp", "Explore",
                [asst("m_exp", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        w(os.path.join(ce, fa, "s2.jsonl"),
          [asst("m_main2", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=50))])
        add_sub(ce, fa, "s2", "exp2", "Explore",
                [asst("m_exp2", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        r = rows_of(analyze.analyze_corpus(ce, days=None))[("Explore", OPUS)]
        check("37h. a row keeps its priced cost and counts the unpriced messages",
              abs(r["cost_usd"] - 1.0) < 1e-6 and r["unpriced_messages"] == 1
              and r["spawns"] == 2, json.dumps(r))

        # Null cost sorts last, without comparing None to a float.
        cf = jcorpus("apport6")
        w(os.path.join(cf, fa, "s1.jsonl"), [
            asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=50)),
            cost_state(**{OPUS: 2.0}),
        ])
        add_sub(cf, fa, "s1", "exp", "Explore",
                [asst("m_exp", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        w(os.path.join(cf, fa, "s2.jsonl"),
          [asst("m_main2", "2026-09-01T10:00:00.000Z", model=SONNET, u=usage(inp=50))])
        add_sub(cf, fa, "s2", "big", "implementer",
                [asst("m_big", "2026-09-01T10:02:00.000Z", model=SONNET, u=usage(out=900))])
        add_sub(cf, fa, "s1", "small", "Plan",
                [asst("m_small", "2026-09-01T10:03:00.000Z", model=OPUS, u=usage(inp=1))])
        kinds = [r["agent_type"] for r in analyze.analyze_corpus(cf, days=None)["subagents_by_type"]]
        check("37i. priced rows first by cost, null-cost rows last",
              kinds[-1] == "implementer" and kinds[0] == "Explore", json.dumps(kinds))

        # Recorded cost for a model with no messages is reported, not divided.
        cg = jcorpus("apport7")
        w(os.path.join(cg, fa, "s1.jsonl"), [
            asst("m_main", "2026-09-01T10:00:00.000Z", model=OPUS, u=usage(inp=50)),
            cost_state(**{OPUS: 2.0, SONNET: 2.5}),
        ])
        c = analyze.analyze_corpus(cg, days=None)
        check("37j. cost with zero weight lands in unallocated_cost_usd",
              abs(c["totals"]["unallocated_cost_usd"] - 2.5) < 1e-6,
              json.dumps(c["totals"].get("unallocated_cost_usd")))

        # Orphans add tokens to their row, never cost.
        ch = jcorpus("apport8")
        add_sub(ch, fa, "ghost", "o1", "Explore",
                [asst("m_o", "2026-09-01T10:02:00.000Z", model=OPUS, u=usage(inp=50))])
        r = rows_of(analyze.analyze_corpus(ch, days=None))[("Explore", OPUS)]
        check("37k. an orphan contributes tokens but no cost",
              r["cost_usd"] is None and r["input"] == 50 and r["unpriced_messages"] == 1,
              json.dumps(r))

        # --- 38. Implementer handoff windows (AC9-12) ----------------------------
        def tuse(name, tid, **inp):
            return [{"type": "tool_use", "name": name, "id": tid, "input": inp}]

        def tres(tid, ts):
            return {"type": "user", "timestamp": ts,
                    "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}

        def handoff_corpus(name, main_records, subs=(("imp1", "implementer", "toolu_imp"),),
                           shape=None):
            corpus = jcorpus(name)
            w(os.path.join(corpus, fa, "s1.jsonl"), main_records)
            for aid, kind, tid in subs:
                d = os.path.join(corpus, fb, "s1", "subagents")
                w(os.path.join(d, f"agent-{aid}.jsonl"),
                  [asst(f"sub_{aid}", "2026-09-01T10:00:30.000Z", model=SONNET, u=usage(out=40))])
                meta = {"agentType": kind, "toolUseId": tid,
                        "description": "SECRET DESCRIPTION"}
                if shape:
                    meta["requestShape"] = shape
                w(os.path.join(d, f"agent-{aid}.meta.json"), [meta])
            return analyze.analyze_corpus(corpus, days=None)

        def handback(aid, ts):
            """A background subagent's return: a user record whose origin is the peer."""
            return {"type": "user", "timestamp": ts, "isMeta": True,
                    "origin": {"kind": "peer", "from": aid, "handback": True},
                    "message": {"role": "user", "content": "report"}}

        T = lambda n: f"2026-09-01T10:{n:02d}:00.000Z"
        # Pre-window: m1 (spawn), m2, m3. Window: m4, m5, m6 (Opus), m7 (Sonnet).
        # m6 carries a non-audit Skill; m8 carries security-audit and closes.
        main = [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            asst("m2", T(2), model=OPUS, u=usage(inp=10)),
            asst("m3", T(3), model=OPUS, u=usage(inp=10)),
            tres("toolu_imp", T(4)),
            asst("m4", T(5), model=OPUS, u=usage(inp=100)),
            asst("m5", T(6), model=OPUS, u=usage(inp=100)),
            asst("m5", T(6), model=OPUS, u=usage(inp=100),      # same response, next block
                 content=[{"type": "text", "text": "again"}]),
            asst("m6", T(7), model=OPUS, u=usage(inp=100),
                 content=tuse("Skill", "toolu_s1", skill="frontend-iteration")),
            asst("m7", T(8), model=SONNET, u=usage(inp=50)),
            asst("m8", T(9), model=OPUS, u=usage(inp=10),
                 content=tuse("Skill", "toolu_s2", skill="security-audit")),
            cost_state(**{OPUS: 5.0, SONNET: 1.0}),
        ]
        c = analyze.analyze_corpus(jcorpus("noop"), days=None)   # empty corpus baseline
        check("38a. an empty corpus reports an empty handoff",
              c["implementer_handoff"]["returns"] == []
              and c["implementer_handoff"]["totals"]["median_opus_messages"] is None,
              json.dumps(c["implementer_handoff"]))
        c = handoff_corpus("h1", main)
        hrows = c["implementer_handoff"]["returns"]
        row = hrows[0] if hrows else {}
        # Opus weight: 30 + 300 + 10 = 340 -> 5.0/340; Sonnet: main 50 + sub 200 = 250 -> 1.0/250.
        want = 300 * 5.0 / 340 + 50 * 1.0 / 250
        check("38b. one return -> one row with session, agent_id and closed_by",
              len(hrows) == 1 and row.get("session") == "s1"
              and row.get("agent_id") == "imp1" and row.get("closed_by") == "security-audit",
              json.dumps(hrows))
        check("38c. the window holds messages strictly between result and closing message",
              row.get("messages") == {OPUS: 3, SONNET: 1} and row.get("opus_messages") == 3,
              json.dumps(row))
        check("38d. window weight and cost use the session's per-model rate",
              abs(row.get("weighted_tokens", 0) - 350) < 1e-9
              and abs((row.get("cost_usd") or 0) - want) < 1e-6, json.dumps(row))
        check("38e. a non-audit Skill does not close the window; a repeated message counts once",
              row.get("messages") == {OPUS: 3, SONNET: 1}, json.dumps(row))
        tot = c["implementer_handoff"]["totals"]
        check("38f. totals carry returns, opus_messages, weighted_tokens, cost and median",
              tot["returns"] == 1 and tot["opus_messages"] == 3
              and abs(tot["weighted_tokens"] - 350) < 1e-9
              and abs(tot["cost_usd"] - want) < 1e-6 and tot["median_opus_messages"] == 3,
              json.dumps(tot))

        c = handoff_corpus("h2", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            asst("m2", T(2), model=OPUS, u=usage(inp=10)),
        ])
        check("38g. a spawn with no result opens no window",
              c["implementer_handoff"]["returns"] == [], json.dumps(c["implementer_handoff"]))

        c = handoff_corpus("h3", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            tres("toolu_imp", T(2)),
            asst("m2", T(3), model=OPUS, u=usage(inp=10)),
            asst("m3", T(4), model=OPUS, u=usage(inp=10)),
        ])
        hrows = c["implementer_handoff"]["returns"]
        check("38h. no audit skill -> closed by session_end, through the last message",
              len(hrows) == 1 and hrows[0]["closed_by"] == "session_end"
              and hrows[0]["opus_messages"] == 2, json.dumps(hrows))
        check("38i. no cost-state -> cost_usd null in the row and the totals",
              hrows[0]["cost_usd"] is None
              and c["implementer_handoff"]["totals"]["cost_usd"] is None,
              json.dumps(c["implementer_handoff"]))
        check("38u. totals count the returns whose cost is unpriced",
              c["implementer_handoff"]["totals"].get("unpriced_returns") == 1,
              json.dumps(c["implementer_handoff"]["totals"]))

        two = (("imp1", "implementer", "toolu_imp"), ("imp2", "implementer", "toolu_imp2"))
        c = handoff_corpus("h4", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            tres("toolu_imp", T(2)),
            asst("m2", T(3), model=OPUS, u=usage(inp=10)),
            asst("m3", T(4), model=OPUS, u=usage(inp=10),
                 content=tuse("Agent", "toolu_imp2")),
            tres("toolu_imp2", T(5)),
            asst("m4", T(6), model=OPUS, u=usage(inp=10)),
            asst("m5", T(7), model=OPUS, u=usage(inp=10)),
            asst("m6", T(8), model=OPUS, u=usage(inp=10)),
        ], subs=two)
        hrows = c["implementer_handoff"]["returns"]
        check("38j. a second implementer spawn closes the first as next_implementer",
              [r["closed_by"] for r in hrows] == ["next_implementer", "session_end"]
              and [r["agent_id"] for r in hrows] == ["imp1", "imp2"], json.dumps(hrows))
        check("38k. the closing spawn message is excluded from the first window",
              [r["opus_messages"] for r in hrows] == [1, 3], json.dumps(hrows))
        tot = c["implementer_handoff"]["totals"]
        check("38l. totals sum the returns; median is per return",
              tot["returns"] == 2 and tot["opus_messages"] == 4
              and tot["median_opus_messages"] == 2.0, json.dumps(tot))

        c = handoff_corpus("h5", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            tres("toolu_imp", T(2)),
            asst("m2", T(3), model=OPUS, u=usage(inp=10)),
            asst("m3", T(4), model=OPUS, u=usage(inp=10),
                 content=tuse("SendMessage", "toolu_sm", to="imp1")),
            asst("m4", T(5), model=OPUS, u=usage(inp=10)),
        ])
        hrows = c["implementer_handoff"]["returns"]
        check("38m. SendMessage to an implementer closes the window and opens none",
              len(hrows) == 1 and hrows[0]["closed_by"] == "next_implementer"
              and hrows[0]["opus_messages"] == 1, json.dumps(hrows))
        check("38n. and counts an unmeasured resume",
              c["drift"]["unmeasured_resumes"] == 1, json.dumps(c["drift"]))

        c = handoff_corpus("h6", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            tres("toolu_imp", T(2)),
            asst("m2", T(3), model=OPUS, u=usage(inp=10),
                 content=tuse("SendMessage", "toolu_sm", to="someone-else")),
            asst("m3", T(4), model=OPUS, u=usage(inp=10)),
        ])
        hrows = c["implementer_handoff"]["returns"]
        check("38o. SendMessage to another agent neither closes nor counts",
              len(hrows) == 1 and hrows[0]["closed_by"] == "session_end"
              and hrows[0]["opus_messages"] == 2
              and c["drift"]["unmeasured_resumes"] == 0, json.dumps(hrows))

        c = handoff_corpus("h7", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_x")),
            tres("toolu_x", T(2)),
            asst("m2", T(3), model=OPUS, u=usage(inp=10)),
        ], subs=(("ex1", "Explore", "toolu_x"),))
        check("38p. only implementer spawns open a window",
              c["implementer_handoff"]["returns"] == [], "")

        # Background spawn: the tool_result is only the launch acknowledgement; the
        # implementer returns later through a peer handback. m2, m3 run while it works.
        c = handoff_corpus("h8", [
            asst("m1", T(1), model=OPUS, u=usage(inp=10), content=tuse("Agent", "toolu_imp")),
            tres("toolu_imp", T(2)),
            asst("m2", T(3), model=OPUS, u=usage(inp=10)),
            asst("m3", T(4), model=OPUS, u=usage(inp=10)),
            handback("imp1", T(5)),
            asst("m4", T(6), model=OPUS, u=usage(inp=10)),
            asst("m5", T(7), model=OPUS, u=usage(inp=10)),
            asst("m6", T(8), model=OPUS, u=usage(inp=10),
                 content=tuse("Skill", "toolu_s", skill="security-audit")),
            handback("imp1", T(9)),                   # a later hand-back: after a resume
            asst("m7", T(10), model=OPUS, u=usage(inp=10)),
        ], shape="background")
        hrows = c["implementer_handoff"]["returns"]
        check("38s. a background spawn's window opens at its hand-back, not the launch ack",
              len(hrows) == 1 and hrows[0]["opus_messages"] == 2
              and hrows[0]["closed_by"] == "security-audit", json.dumps(hrows))
        check("38t. only an agent's first hand-back opens a window",
              len(hrows) == 1, json.dumps(hrows))
        tot = handoff_corpus("h9", main)["implementer_handoff"]["totals"]
        check("38v. a fully priced handoff has no unpriced returns",
              tot.get("unpriced_returns") == 0, json.dumps(tot))

        rep = analyze.build_report(jcorpus("h1"), days=None, claude_home=home,
                                   codex_root=os.path.join(td, "nocodex"))
        check("38q. working state is not leaked into the report",
              all("events" not in s and "parts" not in s for s in rep["sessions"]), "")
        check("38r. the report never carries meta description or prompt text",
              "SECRET" not in json.dumps(rep, default=str), "")

        # --- 39. Adherence: execution habits, per session ----------------------
        def call(mid, tid, name, **inp):
            return asst(mid, "2026-09-01T10:00:00.000Z",
                        content=[{"type": "tool_use", "name": name, "id": tid, "input": inp}])

        def adherence(name, records):
            return analyze.analyze_session(w(os.path.join(td, name), records))["adherence"]

        # Two parallel calls arrive as two lines sharing one message.id.
        a = adherence("adh-par.jsonl", [
            call("m1", "t1", "Read", file_path="/r/a.rb"),
            call("m1", "t2", "Read", file_path="/r/b.rb"),
            call("m2", "t3", "Bash", command="ls"),
        ])
        check("39a. calls sharing a message.id count as one parallel message",
              a["messages_issuing_several"] == 1 and a["messages_with_tool_calls"] == 2,
              json.dumps(a))
        check("39b. parallel_rate is parallel messages over tool-carrying messages",
              a["parallel_rate"] == 0.5, json.dumps(a))

        a = adherence("adh-read.jsonl", [
            call("m1", "t1", "Read", file_path="/r/app/a.rb"),
            call("m2", "t2", "Read", file_path="/r/app/a.rb"),
        ])
        check("39c. reading a file already read is redundant; the first read is not",
              a["read_file_refs"] == 2 and a["redundant_reads_approx"] == 1, json.dumps(a))

        a = adherence("adh-write.jsonl", [
            call("m1", "t1", "Write", file_path="/r/app/new.rb", content="x"),
            call("m2", "t2", "Read", file_path="/r/app/new.rb"),
        ])
        check("39d. reading a file this session just wrote is redundant",
              a["redundant_reads_approx"] == 1, json.dumps(a))

        a = adherence("adh-shell.jsonl", [
            call("m1", "t1", "Bash", command="cat app/models/book.rb"),
            call("m2", "t2", "Read", file_path="/r/app/models/book.rb"),
        ])
        check("39e. a shell read and a Read of the same file are one file",
              a["redundant_reads_approx"] == 1, json.dumps(a))

        a = adherence("adh-pager.jsonl", [
            call("m1", "t1", "Bash", command="grep -n x app/a.rb | head -5"),
        ])
        check("39f. head after a pipe is a pager, not a read",
              a["read_calls"] == 0, json.dumps(a))

        a = adherence("adh-ext.jsonl", [
            call("m1", "t1", "Bash", command="cat claude/settings.json"),
            call("m2", "t2", "Bash", command="cat claude/settings.js"),
        ])
        check("39g. settings.json is not truncated to settings.js",
              a["read_file_refs"] == 2 and a["redundant_reads_approx"] == 0, json.dumps(a))

        a = adherence("adh-edits.jsonl", [
            call("m1", "t1", "Edit", file_path="/wt/docs/specs/x.md"),
            call("m2", "t2", "Edit", file_path="/main/docs/specs/x.md"),
            call("m3", "t3", "Edit", file_path="/wt/docs/plans/x.md"),
        ])
        check("39h. edits key on the last two segments: worktree and main collapse",
              a["max_edits_one_file"] == 2, json.dumps(a))
        check("39i. a spec and its plan with the same basename stay separate",
              {e["file"]: e["edits"] for e in a["edits_per_file_top"]}
              == {"specs/x.md": 2, "plans/x.md": 1}, json.dumps(a))

        a = adherence("adh-heredoc.jsonl", [
            call("m1", "t1", "Read", file_path="/r/docs/spec.md"),
            call("m2", "t2", "Bash", command="cat > docs/spec.md <<'EOF'\nsee app/a.rb\nEOF"),
        ])
        check("39j. cat writing a file through a heredoc is not a read",
              a["read_calls"] == 1 and a["redundant_reads_approx"] == 0, json.dumps(a))

        a = adherence("adh-segment.jsonl", [
            call("m1", "t1", "Bash",
                 command="git add a.py b.py && git commit -m 'x.md'; cat README.md"),
        ])
        check("39k. only files named in the reading segment count as read",
              a["read_file_refs"] == 1, json.dumps(a))

        r = analyze._shell_read_refs
        check("39n. a heredoc body line starting with cat is not a read",
              r("cat > f.md <<'EOF'\ncat app/a.rb\nEOF") is None,
              str(r("cat > f.md <<'EOF'\ncat app/a.rb\nEOF")))
        check("39o. cat of a heredoc on stdin reads no file",
              r("cat <<'EOF' | gh pr create --body-file -\nbody\nEOF") is None, "")
        check("39p. a > inside quotes is not a write",
              r("sed -n '/=>/p' app/x.rb") == {"x.rb"}, str(r("sed -n '/=>/p' app/x.rb")))
        check("39q. >&2 is not a write",
              r("cat a.md >&2") == {"a.md"}, str(r("cat a.md >&2")))
        check("39r. a ; inside quotes does not split the command",
              r("sed -n '1,5p;9p' app/x.rb") == {"x.rb"}, str(r("sed -n '1,5p;9p' app/x.rb")))
        check("39s. a backslash continuation keeps the second file",
              r("cat app/a.rb \\\napp/b.rb") == {"a.rb", "b.rb"},
              str(r("cat app/a.rb \\\napp/b.rb")))
        check("39t. 2>/dev/null is not a write",
              r("cat a.md 2>/dev/null") == {"a.md"}, str(r("cat a.md 2>/dev/null")))
        check("39v. a quoted string spanning lines does not hide a later read",
              r('echo "x\ny" ; cat app/z.rb') == {"z.rb"}, str(r('echo "x\ny" ; cat app/z.rb')))
        check("39w. a line inside a quoted string is not a command",
              r("git commit -m 'x\ncat app/a.rb\n'") is None,
              str(r("git commit -m 'x\ncat app/a.rb\n'")))
        check("39x. an unquoted newline still separates commands",
              r("cd app\ncat a.rb") == {"a.rb"}, str(r("cd app\ncat a.rb")))
        check("39y. # inside a word is not a comment",
              r("cat notes#1.md") == {"notes#1.md"}, str(r("cat notes#1.md")))
        check("39z. a stderr redirect to a file is not a write of the read",
              r("cat a.md 2> err.log") == {"a.md"}, str(r("cat a.md 2> err.log")))
        check("39aa. >/dev/stderr is not a write",
              r("cat a.md >/dev/stderr") == {"a.md"}, str(r("cat a.md >/dev/stderr")))
        check("39ab. &> writes a file",
              r("cat a.md &> out.md") is None, str(r("cat a.md &> out.md")))
        import time
        big = "ruby -e '" + "\n".join("a << item" for _ in range(2000)) + "'"
        t0 = time.perf_counter()
        r(big)
        check("39ac. an unterminated << does not make parsing quadratic",
              time.perf_counter() - t0 < 0.1, f"{time.perf_counter() - t0:.3f}s")
        check("39u. unbalanced quotes do not crash the parser",
              r("cat 'a.md") is None or isinstance(r("cat 'a.md"), set), "")

        # A subagent's habits count too: work delegated to the implementer must not
        # vanish from the scoreboard and look like an improvement.
        ap = os.path.join(td, "adhcorpus", "-Users-x-Projects-app")
        w(os.path.join(ap, "sess1.jsonl"), [call("m1", "t1", "Bash", command="ls")])
        w(os.path.join(ap, "sess1", "subagents", "agent-i.jsonl"), [
            call("s1", "u1", "Edit", file_path="/wt/app/x.rb"),
            call("s2", "u2", "Edit", file_path="/wt/app/x.rb"),
            call("s3", "u3", "Edit", file_path="/wt/app/x.rb"),
            call("s4", "u4", "Read", file_path="/wt/app/y.rb"),
            call("s4", "u5", "Read", file_path="/wt/app/z.rb"),
        ])
        s = analyze.analyze_corpus(os.path.join(td, "adhcorpus"), days=None)["sessions"][0]
        check("39l. adherence_all folds in subagent edits",
              s["adherence_all"]["max_edits_one_file"] == 3
              and s["adherence"]["max_edits_one_file"] == 0, json.dumps(s["adherence_all"]))
        check("39m. adherence_all sums tool-carrying messages across contexts",
              s["adherence_all"]["messages_with_tool_calls"] == 5
              and s["adherence_all"]["messages_issuing_several"] == 1,
              json.dumps(s["adherence_all"]))

        # --- 40. The gate scorecard ------------------------------------------------
        import subprocess
        from datetime import datetime, timedelta, timezone

        import gate_log

        now = datetime.now(timezone.utc)

        def ago(days):
            return (now - timedelta(days=days)).isoformat(timespec="seconds")

        def tri(b=0, m=0, n=0):
            return {"blocker": b, "major": m, "minor": n}

        def grec(gate="5s", source="claude", lane="workflow", repo="acme", slug="s", ts=None,
                 found=None, accepted=None, rejected=0, deferred=0, human=0, skipped=False,
                 **extra):
            rec = {"ts": ts or ago(1), "repo": repo, "slug": slug, "lane": lane,
                   "tier": "B" if source == "claude" else None, "gate": gate,
                   "found": found or tri(), "accepted": accepted or tri(),
                   "rejected": rejected, "deferred": deferred, "human": human,
                   "skipped": skipped, "source": source}
            rec.update(extra)
            return rec

        def codex(slug, **kw):
            kw.setdefault("accepted", tri(n=None))
            kw.setdefault("source", "codex")
            return grec(gate="1b", slug=slug, **kw)

        glog = os.path.join(td, "gate-log.jsonl")
        w(glog, [
            # Key (acme, s1, 1b), three times: an import, round 1, then the cumulative round 2.
            # Only the last may count.
            # (Threadless records of one ledger share its date, whoever wrote them.)
            codex("s1", source="import", ts=ago(2), found=tri(m=1), wall_s=10),
            codex("s1", ts=ago(2), found=tri(m=2), rounds=1, wall_s=40),
            codex("s1", ts=ago(2), found=tri(m=3, n=1), accepted=tri(m=1, n=None), rejected=1,
                  human=1, rounds=2, wall_s=100),
            codex("s2", found=tri(), wall_s=50),
            # Claude records never supersede: a delta re-audit is its own run.
            grec(found=tri(m=2, n=1), accepted=tri(m=1, n=1), rejected=1),
            grec(),
            grec(skipped=True),
            grec(ts=ago(90), found=tri(m=5)),
            grec(gate="trivial-check", lane="trivial", found=tri(n=1), accepted=tri(n=1)),
            grec(gate="2b", source="codex", repo="webapp", slug="m1", found=tri(m=1),
                 accepted=tri(m=1, n=None)),
            "{not json",
            grec(gate="nope"),
        ])
        rows, bad = analyze.gate_scorecard(glog, days=30)
        by_key = {(r["gate"], r["lane"]): r for r in rows}

        check("40a. rows are one per (gate, lane), in the spec's gate order",
              [(r["gate"], r["lane"]) for r in rows]
              == [("1b", "workflow"), ("2b", "workflow"), ("5s", "workflow"),
                  ("trivial-check", "trivial")], str([(r["gate"], r["lane"]) for r in rows]))
        check("40b. a Codex row keeps only the last record per run key, with full metrics",
              by_key.get(("1b", "workflow")) == {
                  "gate": "1b", "lane": "workflow", "runs": 2, "skipped": 0,
                  "runs_with_findings": 1, "found": tri(m=3, n=1),
                  "accepted": tri(m=1, n=None), "untriaged": tri(n=1), "rejected": 1,
                  "deferred": 0, "human": 1,
                  "accept_rate": {"blocker": None, "major": 1 / 3, "minor": None},
                  "wall_s": 150}, json.dumps(by_key.get(("1b", "workflow"))))
        check("40c. every Claude record counts; skips are counted apart; the old one is out",
              by_key.get(("5s", "workflow")) == {
                  "gate": "5s", "lane": "workflow", "runs": 2, "skipped": 1,
                  "runs_with_findings": 1, "found": tri(m=2, n=1),
                  "accepted": tri(m=1, n=1), "untriaged": tri(), "rejected": 1, "deferred": 0,
                  "human": 0,
                  "accept_rate": {"blocker": None, "major": 0.5, "minor": 1.0},
                  "wall_s": None}, json.dumps(by_key.get(("5s", "workflow"))))
        check("40d. the same gate in the trivial lane is its own row",
              by_key.get(("trivial-check", "trivial"), {}).get("runs") == 1)
        check("40e. an unreadable or invalid line is counted, the rest reported",
              bad == 2, f"bad={bad}")
        rows_all, _ = analyze.gate_scorecard(glog, days=None)
        five = {(r["gate"], r["lane"]): r for r in rows_all}[("5s", "workflow")]
        check("40f. without --days the old record counts too",
              five["runs"] == 3 and five["found"]["major"] == 7, json.dumps(five))
        rows_p, _ = analyze.gate_scorecard(glog, days=30, project="weba")
        check("40g. --project is a substring match on repo",
              [(r["gate"], r["lane"]) for r in rows_p] == [("2b", "workflow")]
              and rows_p[0]["accept_rate"]["major"] == 1.0, json.dumps(rows_p))

        # A row mixing a triaged run with an untriaged one (a one-shot 6b): the rate is over
        # what was triaged, and the untriaged findings are reported, not counted as rejected.
        mlog = os.path.join(td, "mixed-gate-log.jsonl")
        w(mlog, [
            grec(gate="6b", source="codex", slug="t1", found=tri(m=3), accepted=tri(m=2, n=None)),
            grec(gate="6b", source="codex", slug="t2", found=tri(m=4),
                 accepted={"blocker": None, "major": None, "minor": None}),
        ])
        mrow = analyze.gate_scorecard(mlog, days=30)[0][0]
        check("40q. untriaged findings leave the rate's denominator and are reported apart",
              mrow["found"] == tri(m=7) and mrow["accepted"] == tri(m=2, n=None)
              and mrow["untriaged"] == tri(m=4)
              and mrow["accept_rate"] == {"blocker": None, "major": 2 / 3, "minor": None},
              json.dumps(mrow))

        # Report wiring and the missing-log case.
        rows_none, bad_none = analyze.gate_scorecard(os.path.join(td, "no-log.jsonl"), days=30)
        check("40h. a missing log yields no rows and no drift",
              rows_none == [] and bad_none == 0, f"{rows_none} {bad_none}")
        report = analyze.build_report(os.path.join(td, "corpus"), days=30, gate_log_path=glog)
        check("40i. build_report carries .gates and the unparseable count in drift",
              report["gates"] == rows and report["drift"]["gate_log_unparseable"] == 2,
              json.dumps(report["drift"]))
        check("40j. with no log the report still has .gates: []",
              analyze.build_report(os.path.join(td, "corpus"), days=30)["gates"] == [])
        before = open(glog, "rb").read()
        out = _io.StringIO()
        with contextlib.redirect_stdout(out):
            analyze.main(["--root", os.path.join(td, "corpus"), "--days", "30",
                          "--claude-home", home, "--codex-root", os.path.join(td, "codex"),
                          "--gate-log", glog])
        check("40k. the CLI takes --gate-log and reads it without changing it",
              len(json.loads(out.getvalue())["gates"]) == 4 and open(glog, "rb").read() == before)

        # AC9: importing the same ledgers twice reports the same scorecard as once.
        imp = os.path.join(td, "imp")
        os.makedirs(imp)
        for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "i"]):
            subprocess.run(["git", "-c", "user.email=t@e.x", "-c", "user.name=t", *cmd],
                           cwd=imp, check=True, capture_output=True)
        os.makedirs(os.path.join(imp, ".git", "codex-audit"))
        with open(os.path.join(imp, ".git", "codex-audit", "demo-1b.md"), "w") as fh:
            fh.write("# Gate 1b — demo\n\n- **date:** %s\n- **rounds:** 1\n\n"
                     "## Round 1 — Codex, verbatim\n\n## BLOCKER\n\nNone.\n\n## MAJOR\n\n"
                     "### 1b-F01 - x\n- evidence: y\n\n## MINOR\n\nNone.\n"
                     % now.strftime("%Y-%m-%d %H:%M"))
        ilog = os.path.join(td, "import.jsonl")
        os.environ["GATE_LOG"] = ilog
        with contextlib.redirect_stdout(_io.StringIO()):
            gate_log.main(["import-codex", imp])
        once, _ = analyze.gate_scorecard(ilog, days=30)
        with contextlib.redirect_stdout(_io.StringIO()):
            gate_log.main(["import-codex", imp])
        twice, _ = analyze.gate_scorecard(ilog, days=30)
        # A --rerun is a new review of the same artifact: a new thread, so a new run. Round 2
        # resumes round 1's thread, so it is the same run and supersedes it.
        tlog = os.path.join(td, "thread.jsonl")
        w(tlog, [
            codex("r1", found=tri(m=1), thread="t-a", rounds=1),
            codex("r1", found=tri(m=2), thread="t-a", rounds=2),
            codex("r1", found=tri(m=4), thread="t-b", rounds=1),
            codex("sk", skipped=True, ts=ago(2)),
            codex("sk", found=tri(m=1), thread="t-c", rounds=1, ts=ago(1)),
            # A skip recorded AFTER a review (never overwrites it) stays counted.
            codex("late", found=tri(m=1), thread="t-d", rounds=1, ts=ago(2)),
            codex("late", skipped=True, ts=ago(1)),
        ])
        trows, _ = analyze.gate_scorecard(tlog, days=30)
        check("40m. a rerun's new thread is a second run; round 2 on the same thread is not",
              len(trows) == 1 and trows[0]["runs"] == 4 and trows[0]["found"]["major"] == 8,
              json.dumps(trows))
        check("40n. a skip replaced by a later review no longer counts; a skip after one does",
              trows[0]["skipped"] == 1, json.dumps(trows))

        # A legacy ledger has no thread. A skip recorded after it shares its key, and must
        # neither replace the review nor vanish.
        leg = os.path.join(td, "legacy.jsonl")
        w(leg, [
            codex("leg", found=tri(b=1, m=2), ts=ago(5), rounds=1),
            codex("leg", skipped=True, ts=ago(1)),
        ])
        lrows, _ = analyze.gate_scorecard(leg, days=30)
        check("40o. a skip after a threadless review leaves the review intact and counts itself",
              len(lrows) == 1 and lrows[0]["runs"] == 1 and lrows[0]["skipped"] == 1
              and lrows[0]["found"] == tri(b=1, m=2), json.dumps(lrows))

        # Threadless archive and live ledger: told apart by their own dates, not collapsed.
        arc = os.path.join(td, "archive.jsonl")
        w(arc, [
            codex("arc", found=tri(m=1), ts=ago(9), rounds=1),
            codex("arc", found=tri(m=2), ts=ago(3), rounds=1),
        ])
        arows, _ = analyze.gate_scorecard(arc, days=30)
        check("40p. a threadless archive and its live ledger are two runs",
              len(arows) == 1 and arows[0]["runs"] == 2 and arows[0]["found"]["major"] == 3,
              json.dumps(arows))

        check("40l. importing twice yields the same .gates as importing once",
              once == twice and len(once) == 1 and once[0]["runs"] == 1
              and len(open(ilog).read().splitlines()) == 2, json.dumps([once, twice]))

        # Tier audit: one row per unit with the tier it ended on and the clause quoted for it.
        ulog = os.path.join(td, "units.jsonl")
        w(ulog, [
            # Classified B, then restated as A at a later gate: the latest classification wins.
            codex("u1", ts=ago(3), tier="B", trigger="adds a dependency"),
            grec(slug="u1", ts=ago(2), tier="A", trigger="touches personal data (PII)"),
            # A later record with no tier (an old codex-audit call) does not erase it.
            codex("u1", ts=ago(1)),
            # Never classified: only tierless Codex records.
            codex("u2"),
            grec(gate="trivial-check", lane="light", slug="fix-x", tier="routine"),
            grec(gate="trivial-check", lane="trivial", slug="fix-y", tier="routine"),
            grec(slug="old", ts=ago(90)),
            grec(slug="elsewhere", repo="webapp", tier="routine"),
            "{not json",
        ])
        units, mix = analyze.gate_units(ulog, days=30)
        by_unit = {u["slug"]: u for u in units}
        check("41a. a unit keeps its latest tier and the trigger quoted with it",
              by_unit.get("u1") == {"repo": "acme", "slug": "u1", "lane": "workflow",
                                    "tier": "A", "trigger": "touches personal data (PII)",
                                    "records": 3}, json.dumps(by_unit.get("u1")))
        check("41b. a unit never classified has a null tier and no trigger",
              by_unit.get("u2", {}).get("tier") is None
              and by_unit.get("u2", {}).get("trigger") is None, json.dumps(by_unit.get("u2")))
        check("41c. the mix counts units per lane and tier, unclassified ones as unknown",
              mix == {"workflow": {"A": 1, "unknown": 1, "routine": 1},
                      "light": {"routine": 1}, "trivial": {"routine": 1}}, json.dumps(mix))
        check("41d. the window applies: a unit last seen 90 days ago is out",
              "old" not in by_unit, str(sorted(by_unit)))
        p_units, p_mix = analyze.gate_units(ulog, days=30, project="weba")
        check("41e. --project filters units by repo",
              [u["slug"] for u in p_units] == ["elsewhere"]
              and p_mix == {"workflow": {"routine": 1}}, json.dumps([p_units, p_mix]))
        # Review fixes: file order, not ts, is write order (round 2 reuses round 1's ledger
        # date); a tier set before the window still names the unit; a codex line with no tier
        # key is valid and must not crash the report.
        olog = os.path.join(td, "units-order.jsonl")
        notier = codex("u5")
        del notier["tier"]
        w(olog, [
            codex("u3", ts=ago(3), tier="B", trigger="adds a dependency"),
            grec(slug="u3", ts=ago(2), tier="B", trigger="adds a dependency"),
            codex("u3", ts=ago(3), tier="A", trigger="touches money/billing"),
            codex("u4", ts=ago(40), tier="A", trigger="touches authentication"),
            codex("u4", ts=ago(1)),
            notier,
        ])
        o_units = {u["slug"]: u for u in analyze.gate_units(olog, days=30)[0]}
        check("41g. a round-2 restatement wins though it carries round 1's older date",
              o_units.get("u3", {}).get("tier") == "A", json.dumps(o_units.get("u3")))
        check("41h. a tier recorded before the window still classifies a unit seen in it",
              o_units.get("u4", {}).get("tier") == "A"
              and o_units.get("u4", {}).get("records") == 1, json.dumps(o_units.get("u4")))
        check("41i. a codex line with no tier key is an unknown unit, not a crash",
              "u5" in o_units and o_units["u5"]["tier"] is None, str(sorted(o_units)))

        report = analyze.build_report(os.path.join(td, "corpus"), days=30, gate_log_path=ulog)
        check("41f. build_report carries .gate_units and .tier_mix",
              report["gate_units"] == units and report["tier_mix"] == mix,
              json.dumps([report.get("gate_units"), report.get("tier_mix")]))

        # --- 42. Measured fixed context from api-request-shape -----------------
        # The shape holds the real system prompt and tool schemas. Only their sizes
        # may reach the report: every string below is a sentinel that must not leak.
        def tool(n, deferred=False):
            t = {"name": "SECRET_TOOLNAME_%d" % n, "description": "SECRET_DESC_%d" % n,
                 "input_schema": {"type": "object", "properties": {"SECRET_PROP": {}}}}
            if deferred:
                t["defer_loading"] = True
            return t

        def shape(ts, system, eager, deferred, agent=None):
            rec = {"type": "api-request-shape", "sessionId": "s42", "shapeHash": ts,
                   "timestamp": ts, "version": "2.1.200",
                   "shape": {"system": [{"type": "text", "text": s} for s in system],
                             "tools": eager + deferred}}
            if agent:
                rec["agentId"] = agent
            return rec

        def chars(tools):
            return sum(len(json.dumps(t)) for t in tools)

        e1, e2, d1 = [tool(1), tool(2)], [tool(3)], [tool(4, deferred=True)]
        mproj = os.path.join(td, "corpus42", "-Users-x-Projects-app")
        w(os.path.join(mproj, "m1.jsonl"), [
            # A resumed session: this shape predates the window, the session does not.
            shape(ago(60), ["SECRET_SYS_H" * 999], e1, d1),
            shape(ago(3), ["SECRET_SYS_A" * 10], e1, d1),
            shape(ago(1), ["SECRET_SYS_B" * 2, "SECRET_SYS_C"], e2, []),
        ])
        w(os.path.join(mproj, "m2.jsonl"), [shape(ago(2), ["SECRET_SYS_D" * 5], e1 + e2, d1)])
        w(os.path.join(mproj, "m1", "subagents", "agent-x.jsonl"),
          [shape(ago(1), ["SECRET_SYS_E"], e2, d1, agent="agent-x")])
        # No agentId: the subagent file, not the record, decides the kind.
        w(os.path.join(mproj, "m2", "subagents", "agent-y.jsonl"),
          [shape(ago(2), ["SECRET_SYS_I"], e1, [])])
        w(os.path.join(mproj, "old.jsonl"), [shape(ago(90), ["SECRET_SYS_F" * 99], e1, d1)])
        w(os.path.join(td, "corpus42", "-Users-x-Projects-other", "o1.jsonl"),
          [shape(ago(1), ["SECRET_SYS_G" * 99], e1, d1)])

        fcm = analyze.build_report(os.path.join(td, "corpus42"), days=30, project="app",
                                   claude_home=os.path.join(td, "no-home"),
                                   gate_log_path=os.path.join(td, "no-log.jsonl")
                                   )["fixed_context_measured"]
        main_m, sub_m = fcm["main"], fcm["subagent"]
        check("42a. main and subagent shapes are counted apart, by the file they sit in",
              main_m["shapes"] == 3 and sub_m["shapes"] == 2, json.dumps(fcm))
        latest = {"system_chars": 36, "eager_tool_chars": chars(e2), "deferred_tool_chars": 0,
                  "eager_tools": 1, "deferred_tools": 0,
                  "est_tokens": (36 + chars(e2)) // 4}
        check("42b. latest is the newest main shape, every size reported",
              main_m["latest"] == latest, json.dumps(main_m["latest"]))
        check("42c. the median is taken per field across the window's shapes",
              main_m["median"]["system_chars"] == 60
              and main_m["median"]["eager_tool_chars"] == chars(e1)
              and main_m["median"]["eager_tools"] == 2, json.dumps(main_m["median"]))
        check("42d. a defer_loading tool is deferred, sized apart and out of est_tokens",
              sub_m["latest"]["deferred_tools"] == 1
              and sub_m["latest"]["deferred_tool_chars"] == chars(d1)
              and sub_m["latest"]["eager_tools"] == 1
              and sub_m["latest"]["est_tokens"] == (12 + chars(e2)) // 4,
              json.dumps(sub_m["latest"]))
        check("42e. --days and --project leave out-of-window shapes uncounted",
              main_m["shapes"] == 3 and main_m["median"]["system_chars"] < 1000,
              json.dumps(main_m))
        check("42h. a string system prompt is sized like a block list",
              analyze._shape_size({"shape": {"system": "abcd", "tools": []}})
              ["system_chars"] == 4, "string system not sized")
        full = json.dumps(analyze.build_report(
            os.path.join(td, "corpus42"), days=None,
            claude_home=os.path.join(td, "no-home"),
            gate_log_path=os.path.join(td, "no-log.jsonl")), default=str)
        check("42f. no system prompt or tool schema text reaches the report",
              "SECRET_" not in full, "sentinel leaked")
        empty = analyze.build_report(os.path.join(td, "no-corpus"), days=30,
                                     claude_home=os.path.join(td, "no-home"),
                                     gate_log_path=os.path.join(td, "no-log.jsonl"))
        check("42g. no shapes in the window yields zero counts and null sizes",
              all(empty["fixed_context_measured"][k] == {"shapes": 0, "latest": None,
                                                        "median": None}
                  for k in ("main", "subagent")), json.dumps(empty["fixed_context_measured"]))

        # --- 43. Edit/Write results cost what the model is sent ----------------
        # Verified on real transcripts: an Edit/Write toolUseResult carries
        # originalFile, oldString/newString, structuredPatch (Write: content) --
        # ~4 KB mean -- while the model only receives the tool_result block's
        # content string (~150-220 B). Size the latter for these tools.
        sent = "The file /a.py has been updated successfully." + "s" * 100
        for tool, local in (("Edit", {"filePath": "/a.py", "oldString": "o" * 500,
                                      "newString": "n" * 500, "originalFile": "f" * 4000,
                                      "structuredPatch": [{"lines": ["l" * 500]}]}),
                            ("Write", {"type": "update", "filePath": "/a.py",
                                       "content": "c" * 4000, "originalFile": "f" * 4000,
                                       "structuredPatch": []})):
            p = w(os.path.join(td, f"sent_{tool}.jsonl"), [
                asst("msg_a", "2026-09-01T10:00:00.000Z",
                     content=[{"type": "tool_use", "name": tool, "id": "t1", "input": {}}]),
                {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
                 "toolUseResult": local,
                 "message": {"role": "user", "content": [
                     {"type": "tool_result", "tool_use_id": "t1", "content": sent}]}},
            ])
            s = analyze.analyze_session(p)
            check(f"43a. {tool} result_bytes is the content sent to the model",
                  s["tools"][tool]["result_bytes"] == len(sent)
                  and s["tools"][tool]["results"] == 1,
                  json.dumps(s["tools"][tool]))
        p = w(os.path.join(td, "sent_bash.jsonl"), [
            asst("msg_a", "2026-09-01T10:00:00.000Z",
                 content=[{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}]),
            {"type": "user", "timestamp": "2026-09-01T10:00:01.000Z",
             "toolUseResult": {"stdout": "x" * 4000, "stderr": ""},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "short"}]}},
        ])
        s = analyze.analyze_session(p)
        check("43b. other tools still size toolUseResult",
              s["tools"]["Bash"]["result_bytes"] >= 4000, json.dumps(s["tools"]["Bash"]))

        # --- 44. session-owner is a known record type --------------------------
        # Seen in main transcripts: {type, sessionId, accountUuid, organizationUuid}.
        p = w(os.path.join(td, "owner.jsonl"), [
            {"type": "session-owner", "sessionId": "s1",
             "accountUuid": "ACCOUNT_SENTINEL", "organizationUuid": "ORG_SENTINEL"},
            asst("msg_a", "2026-09-01T10:00:00.000Z"),
        ])
        s = analyze.analyze_session(p)
        check("44a. session-owner records are not drift",
              s["drift"]["unknown_types"] == {}, json.dumps(s["drift"]["unknown_types"]))
        check("44b. session-owner account ids never reach the output",
              "SENTINEL" not in json.dumps(s), "account id leaked")

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
