#!/usr/bin/env python3
"""Tests for session-hygiene.py.

Run: python3 claude/hooks/test_session_hygiene.py
The hook never blocks; it injects context at most once per session.

Assertions on the notice pin a DISTINCTIVE phrase ("500 messages", "9.0h open"), never a bare
number: a bare number can appear elsewhere in the notice, so the check would pass no matter
what the hook computed.

The transcript is the hook's only real input, so most of the setup here is building one.
`transcript()` writes the JSONL shape the hook counts: assistant records carrying
`message.usage`, which is the same unit the 2026-09 usage audit measured.
"""
import json, os, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session-hygiene.py")
results = []


def transcript(path, n_assistant, first_age_h=0.5, extra_lines=(), append=False):
    """Write (or append) a transcript with n_assistant countable assistant records.

    first_age_h controls the age of the FIRST record, which is what the span trigger reads.
    """
    start = datetime.now(timezone.utc) - timedelta(hours=first_age_h)
    with open(path, "a" if append else "w") as f:
        for i in range(n_assistant):
            f.write(json.dumps({
                "type": "assistant",
                "timestamp": (start + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"),
                "message": {"id": f"msg_{i}", "model": "claude-opus-5",
                            "usage": {"input_tokens": 3, "output_tokens": 7,
                                      "cache_read_input_tokens": 100}},
            }) + "\n")
        for line in extra_lines:
            f.write(line + "\n")


def pr_create(tool_id, result, is_error=False, command="gh pr create --title t --body-file b"):
    """The two lines a `gh pr create` leaves: the assistant's Bash tool_use (which carries
    usage, so it also counts as a message) and the user record holding its tool_result."""
    return (
        json.dumps({"type": "assistant", "timestamp": "2026-11-01T12:00:00Z",
                    "message": {"id": f"msg_{tool_id}", "usage": {"output_tokens": 5},
                                "content": [{"type": "tool_use", "id": tool_id, "name": "Bash",
                                             "input": {"command": command}}]}}),
        json.dumps({"type": "user", "timestamp": "2026-11-01T12:00:05Z",
                    "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": tool_id, "content": result,
                         "is_error": is_error}]}}),
    )


def run(state_dir, transcript_path, session="s1", event="UserPromptSubmit", env_extra=None):
    e = dict(os.environ)
    e["CLAUDE_AUDIT_STATE_DIR"] = state_dir
    e.pop("CLAUDE_SESSION_HYGIENE_SKIP", None)
    if env_extra:
        e.update(env_extra)
    payload = {"hook_event_name": event, "session_id": session,
               "transcript_path": transcript_path, "cwd": os.getcwd(),
               "prompt": "siguiente tarea"}
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=e)


def fired(p):
    """True when the hook injected a notice."""
    if p.returncode != 0 or not p.stdout.strip():
        return False
    try:
        out = json.loads(p.stdout)
    except Exception:
        return False
    return bool((out.get("hookSpecificOutput") or {}).get("additionalContext"))


def notice(p):
    return (json.loads(p.stdout).get("hookSpecificOutput") or {}).get("additionalContext", "")


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  -- " + detail) if detail and not cond else ""))


def main():
    with tempfile.TemporaryDirectory() as td:
        # 1. a small, young session is silent
        sd = os.path.join(td, "s1"); os.makedirs(sd)
        t = os.path.join(td, "t1.jsonl"); transcript(t, 50, first_age_h=1)
        p = run(sd, t, "s1")
        check("1. 50 msgs / 1h span stays silent", p.returncode == 0 and not fired(p),
              f"rc={p.returncode} out={p.stdout[:160]}")

        # 2. the message threshold fires and names the count
        sd = os.path.join(td, "s2"); os.makedirs(sd)
        t = os.path.join(td, "t2.jsonl"); transcript(t, 500, first_age_h=1)
        p = run(sd, t, "s2")
        check("2. 500 msgs fires and names the count",
              fired(p) and "500 messages" in notice(p), f"out={p.stdout[:200]}")
        check("2b. the notice says to start a fresh session",
              fired(p) and "fresh session" in notice(p).lower(), notice(p)[:200] if fired(p) else "")
        check("2c. the notice is at most 40 words",
              fired(p) and len(notice(p).split()) <= 40,
              f"{len(notice(p).split())} words" if fired(p) else "")

        # 3. the span threshold fires on its own, with few messages
        sd = os.path.join(td, "s3"); os.makedirs(sd)
        t = os.path.join(td, "t3.jsonl"); transcript(t, 20, first_age_h=9)
        p = run(sd, t, "s3")
        check("3. a 9h span fires on 20 msgs and names the span",
              fired(p) and "9.0h open" in notice(p), f"out={p.stdout[:200]}")

        # 4. once per session, not once per prompt
        p2 = run(sd, t, "s3")
        check("4. the same trigger is silent the second time", not fired(p2), p2.stdout[:160])

        # 4b. one notice per session: the other trigger crossing later stays silent
        transcript(t, 500, first_age_h=0.1, append=True)   # 520 total
        p2 = run(sd, t, "s3")
        check("4b. after the span notice, crossing 500 msgs is silent", not fired(p2),
              p2.stdout[:160])

        # 5. both at once -> one notice, both markers recorded
        sd = os.path.join(td, "s5"); os.makedirs(sd)
        t = os.path.join(td, "t5.jsonl"); transcript(t, 550, first_age_h=10)
        p = run(sd, t, "s5")
        both = fired(p) and "550 messages" in notice(p) and "10.0h open" in notice(p)
        check("5. both thresholds produce one notice covering both", both,
              f"out={p.stdout[:240]}")
        p2 = run(sd, t, "s5")
        check("5b. and both are then silent", not fired(p2), p2.stdout[:160])

        # 6. incremental scan: appended lines are counted, earlier ones are not re-counted
        sd = os.path.join(td, "s6"); os.makedirs(sd)
        t = os.path.join(td, "t6.jsonl"); transcript(t, 450, first_age_h=1)
        p = run(sd, t, "s6")
        check("6. 450 msgs is still under the threshold", not fired(p), p.stdout[:160])
        transcript(t, 60, first_age_h=0.1, append=True)   # 510 total
        p = run(sd, t, "s6")
        check("6b. appended msgs push it over, counted incrementally",
              fired(p) and "510 messages" in notice(p), f"out={p.stdout[:200]}")

        # 7. fails open when the transcript is missing
        sd = os.path.join(td, "s7"); os.makedirs(sd)
        p = run(sd, os.path.join(td, "does-not-exist.jsonl"), "s7")
        check("7. missing transcript fails open, silently",
              p.returncode == 0 and not fired(p) and "Traceback" not in p.stderr,
              f"rc={p.returncode} err={p.stderr[:160]}")

        # 8. malformed lines are skipped, valid ones still counted
        sd = os.path.join(td, "s8"); os.makedirs(sd)
        t = os.path.join(td, "t8.jsonl")
        transcript(t, 500, first_age_h=1, extra_lines=("not json at all", "{broken", ""))
        p = run(sd, t, "s8")
        check("8. malformed lines skipped, valid ones counted",
              fired(p) and "500 messages" in notice(p) and "Traceback" not in p.stderr,
              f"out={p.stdout[:200]} err={p.stderr[:120]}")

        # 9. the skip file silences it, and expires
        sd = os.path.join(td, "s9"); os.makedirs(sd)
        t = os.path.join(td, "t9.jsonl"); transcript(t, 600, first_age_h=1)
        skip = os.path.join(sd, "s9.skip.session-hygiene")
        open(skip, "w").close()
        p = run(sd, t, "s9")
        check("9. a fresh skip file silences the notice", not fired(p), p.stdout[:160])
        old = time.time() - (5 * 3600)
        os.utime(skip, (old, old))
        p = run(sd, t, "s9")
        check("9b. a skip file older than the TTL no longer silences it", fired(p),
              f"out={p.stdout[:200]}")
        check("9c. the expired skip file is deleted", not os.path.exists(skip))

        # 9d. the env escape hatch disables it entirely
        sd = os.path.join(td, "s9d"); os.makedirs(sd)
        t = os.path.join(td, "t9d.jsonl"); transcript(t, 600, first_age_h=1)
        p = run(sd, t, "s9d", env_extra={"CLAUDE_SESSION_HYGIENE_SKIP": "1"})
        check("9d. CLAUDE_SESSION_HYGIENE_SKIP=1 disables the gate", not fired(p), p.stdout[:160])

        # 10. concurrency: fresh sibling sessions are mentioned, stale ones are not
        sd = os.path.join(td, "s10"); os.makedirs(sd)
        t = os.path.join(td, "t10.jsonl"); transcript(t, 600, first_age_h=1)
        for i in range(4):
            open(os.path.join(sd, f"other{i}.json"), "w").close()
        p = run(sd, t, "s10")
        # NB: assert on the addendum, not on "4". The fixed notice body contains "45% more per
        # message", so `"4" in notice(p)` was true with zero siblings -- the original form of this
        # check passed whatever concurrent_sessions() returned.
        check("10. 4 fresh sibling sessions are mentioned",
              fired(p) and "4 other sessions" in notice(p), f"out={p.stdout[:300]}")

        # 10c. 3 siblings is 4 sessions in all -- within the cap, so not mentioned
        sd = os.path.join(td, "s10c"); os.makedirs(sd)
        t = os.path.join(td, "t10c.jsonl"); transcript(t, 600, first_age_h=1)
        for i in range(3):
            open(os.path.join(sd, f"other{i}.json"), "w").close()
        p = run(sd, t, "s10c")
        check("10c. 3 fresh sibling sessions are within the cap and not mentioned",
              fired(p) and "other sessions" not in notice(p), f"out={p.stdout[:300]}")

        sd = os.path.join(td, "s10b"); os.makedirs(sd)
        t = os.path.join(td, "t10b.jsonl"); transcript(t, 600, first_age_h=1)
        stale = time.time() - (3 * 3600)
        for i in range(4):
            f = os.path.join(sd, f"other{i}.json"); open(f, "w").close()
            os.utime(f, (stale, stale))
        p = run(sd, t, "s10b")
        check("10b. stale sibling markers are ignored",
              fired(p) and "in parallel" not in notice(p).lower(),
              f"out={p.stdout[:260]}")

        # 11. wrong event / garbage payload
        sd = os.path.join(td, "s11"); os.makedirs(sd)
        t = os.path.join(td, "t11.jsonl"); transcript(t, 600, first_age_h=1)
        p = run(sd, t, "s11", event="PreToolUse")
        check("11. a non-UserPromptSubmit event is ignored", not fired(p), p.stdout[:160])

        e = dict(os.environ); e["CLAUDE_AUDIT_STATE_DIR"] = sd
        p = subprocess.run([sys.executable, HOOK], input="not json",
                           capture_output=True, text=True, timeout=30, env=e)
        check("11b. garbage stdin fails open", p.returncode == 0, f"rc={p.returncode}")

        p = subprocess.run([sys.executable, HOOK], input=json.dumps(
            {"hook_event_name": "UserPromptSubmit"}),
            capture_output=True, text=True, timeout=30, env=e)
        check("11c. a payload with no transcript_path fails open",
              p.returncode == 0 and not fired(p), f"rc={p.returncode} out={p.stdout[:120]}")

        # --- what counts as a message -------------------------------------------------
        # These four close the gap the coverage run exposed: case 8's malformed lines never
        # reach json.loads, because the `"usage"` fast path filters them out first. A line has
        # to LOOK countable to exercise the decode guard and the record discrimination.

        # 12. a malformed line that does contain "usage" reaches the decoder and is skipped
        sd = os.path.join(td, "s12"); os.makedirs(sd)
        t = os.path.join(td, "t12.jsonl")
        transcript(t, 499, first_age_h=1, extra_lines=(
            '{"type":"assistant","message":{"usage":{"output_tokens":1}',   # truncated JSON
            '{"type":"assistant","message":{"usage": BROKEN}}',
        ))
        p = run(sd, t, "s12")
        check("12. a malformed line containing 'usage' is skipped, not counted",
              not fired(p) and "Traceback" not in p.stderr,
              f"out={p.stdout[:200]} err={p.stderr[:120]}")

        # 13. a non-assistant record carrying usage is not a message
        sd = os.path.join(td, "s13"); os.makedirs(sd)
        t = os.path.join(td, "t13.jsonl")
        transcript(t, 499, first_age_h=1, extra_lines=(
            json.dumps({"type": "user", "timestamp": "2026-09-25T12:00:00Z",
                        "message": {"usage": {"output_tokens": 5}}}),
        ))
        p = run(sd, t, "s13")
        check("13. a non-assistant record with usage is not counted", not fired(p),
              f"out={p.stdout[:200]}")

        # 14. an assistant record with no usage is not a message either
        sd = os.path.join(td, "s14"); os.makedirs(sd)
        t = os.path.join(td, "t14.jsonl")
        transcript(t, 499, first_age_h=1, extra_lines=(
            json.dumps({"type": "assistant", "timestamp": "2026-09-25T12:00:00Z",
                        "message": {"id": "x", "usage": {}}}),
        ))
        p = run(sd, t, "s14")
        check("14. an assistant record with empty usage is not counted", not fired(p),
              f"out={p.stdout[:200]}")

        # 15. a replaced (shorter) transcript resets the count instead of seeking past its end
        sd = os.path.join(td, "s15"); os.makedirs(sd)
        t = os.path.join(td, "t15.jsonl"); transcript(t, 450, first_age_h=1)
        p = run(sd, t, "s15")
        check("15. 450 msgs is under the threshold", not fired(p), p.stdout[:160])
        transcript(t, 10, first_age_h=1)              # replaced, now much shorter
        run(sd, t, "s15")
        transcript(t, 495, first_age_h=0.1, append=True)   # 505 in the new transcript
        p = run(sd, t, "s15")
        check("15b. a replaced transcript is re-counted from zero, not skipped",
              fired(p) and "505 messages" in notice(p), f"out={p.stdout[:220]}")

        # 16. a traversing session_id must not write outside the state dir.
        # session_id arrives in the payload and is interpolated into every state filename, so
        # an id like `../../x` must never let save() write outside the state dir.
        sd = os.path.join(td, "s16"); os.makedirs(sd)
        outside = os.path.join(td, "escaped.json")
        t = os.path.join(td, "t16.jsonl"); transcript(t, 600, first_age_h=1)
        p = run(sd, t, "../escaped")
        check("16. a traversing session_id writes nothing outside the state dir",
              not os.path.exists(outside)
              and not os.path.exists(os.path.join(td, "escaped.hygiene.json")),
              f"leaked; dir={sorted(os.listdir(td))[:8]}")
        check("16b. and it does not crash", p.returncode == 0 and "Traceback" not in p.stderr,
              f"rc={p.returncode} err={p.stderr[:160]}")

        # --- concurrency is a trigger of its own --------------------------------------
        # Many sessions can run at once while none reaches 500 msgs or 8h, so concurrency fires
        # on its own rather than riding on the size notice.

        # 17. a small, young session with 4 fresh siblings fires on concurrency alone
        sd = os.path.join(td, "s17"); os.makedirs(sd)
        t = os.path.join(td, "t17.jsonl"); transcript(t, 50, first_age_h=1)
        for i in range(4):
            open(os.path.join(sd, f"other{i}.json"), "w").close()
        p = run(sd, t, "s17")
        check("17. 4 fresh siblings fire on a 50-msg session",
              fired(p) and "4 other sessions" in notice(p), f"out={p.stdout[:300]}")
        check("17b. the concurrency notice does not quote the size",
              fired(p) and "50 messages" not in notice(p), notice(p)[:200] if fired(p) else "")
        check("17c. the concurrency notice is shown to the developer too",
              fired(p) and "4 other sessions" in (json.loads(p.stdout).get("systemMessage") or ""),
              f"out={p.stdout[:300]}")

        # 17d. once per session
        p2 = run(sd, t, "s17")
        check("17d. the concurrency notice is silent the second time", not fired(p2),
              p2.stdout[:160])

        # 17e. it does not use up the size notice, which no longer repeats the addendum
        transcript(t, 460, first_age_h=0.1, append=True)   # 510 total
        p2 = run(sd, t, "s17")
        check("17e. crossing 500 msgs after a concurrency notice still fires",
              fired(p2) and "510 messages" in notice(p2), f"out={p2.stdout[:240]}")
        check("17f. and does not repeat the concurrency addendum",
              fired(p2) and "other sessions" not in notice(p2), notice(p2)[:240] if fired(p2) else "")

        # 18. 3 fresh siblings on a small session stay silent
        sd = os.path.join(td, "s18"); os.makedirs(sd)
        t = os.path.join(td, "t18.jsonl"); transcript(t, 50, first_age_h=1)
        for i in range(3):
            open(os.path.join(sd, f"other{i}.json"), "w").close()
        p = run(sd, t, "s18")
        check("18. 3 fresh siblings on a small session stay silent", not fired(p), p.stdout[:160])

        # 19. a state dir that cannot be created fails open
        blocker = os.path.join(td, "not-a-dir"); open(blocker, "w").close()
        t = os.path.join(td, "t19.jsonl"); transcript(t, 50, first_age_h=1)
        p = run(blocker, t, "s19")
        check("19. an unusable state dir fails open, silently",
              p.returncode == 0 and not fired(p) and "Traceback" not in p.stderr,
              f"rc={p.returncode} err={p.stderr[:160]}")

        # --- a PR opened in this session is a trigger of its own -----------------------
        # The 2026-11-01 usage audit: the costliest sessions ran 200-344 msgs at 270-366k
        # context per message, spanning several PRs, and never crossed 500 msgs. The moment a
        # PR opens is when the next piece of work should start fresh.
        url = "https://github.com/acme/app/pull/42"

        # 20. a successful gh pr create fires on the next prompt, naming the PR, to both
        sd = os.path.join(td, "s20"); os.makedirs(sd)
        t = os.path.join(td, "t20.jsonl")
        transcript(t, 30, first_age_h=1, extra_lines=pr_create("toolu_a", url))
        p = run(sd, t, "s20")
        check("20. an opened PR fires and names its URL", fired(p) and url in notice(p),
              f"out={p.stdout[:240]}")
        check("20b. the PR notice says to /clear or open a new session",
              fired(p) and "/clear" in notice(p), notice(p)[:240] if fired(p) else "")
        check("20c. the PR notice is shown to the developer too",
              fired(p) and url in (json.loads(p.stdout).get("systemMessage") or ""),
              f"out={p.stdout[:300]}")

        # 20d. once per session: a second PR stays silent
        transcript(t, 0, extra_lines=pr_create("toolu_b", "https://github.com/acme/app/pull/43"),
                   append=True)
        p2 = run(sd, t, "s20")
        check("20d. a second PR in the same session is silent", not fired(p2), p2.stdout[:200])

        # 21. a failed gh pr create (no URL, is_error) does not fire
        sd = os.path.join(td, "s21"); os.makedirs(sd)
        t = os.path.join(td, "t21.jsonl")
        transcript(t, 30, first_age_h=1, extra_lines=pr_create(
            "toolu_c", "a pull request for branch \"x\" already exists", is_error=True))
        p = run(sd, t, "s21")
        check("21. a failed gh pr create stays silent", not fired(p), p.stdout[:200])

        # 21b. a /pull/ URL in some other command's result does not fire
        sd = os.path.join(td, "s21b"); os.makedirs(sd)
        t = os.path.join(td, "t21b.jsonl")
        transcript(t, 30, first_age_h=1, extra_lines=pr_create("toolu_d", url, command="gh pr view 42"))
        p = run(sd, t, "s21b")
        check("21b. a PR URL from another command stays silent", not fired(p), p.stdout[:200])

        # 22. the tool_use and its result land in different scans: still detected
        sd = os.path.join(td, "s22"); os.makedirs(sd)
        t = os.path.join(td, "t22.jsonl")
        use, res = pr_create("toolu_e", url)
        transcript(t, 30, first_age_h=1, extra_lines=(use,))
        p = run(sd, t, "s22")
        check("22. a pending gh pr create with no result yet is silent", not fired(p), p.stdout[:200])
        transcript(t, 0, extra_lines=(res,), append=True)
        p = run(sd, t, "s22")
        check("22b. its result in a later scan fires", fired(p) and url in notice(p),
              f"out={p.stdout[:240]}")

        # 23. the silencer and the env hatch cover the PR notice too
        sd = os.path.join(td, "s23"); os.makedirs(sd)
        t = os.path.join(td, "t23.jsonl")
        transcript(t, 30, first_age_h=1, extra_lines=pr_create("toolu_f", url))
        open(os.path.join(sd, "s23.skip.session-hygiene"), "w").close()
        p = run(sd, t, "s23")
        check("23. a fresh skip file silences the PR notice", not fired(p), p.stdout[:200])
        sd = os.path.join(td, "s23b"); os.makedirs(sd)
        p = run(sd, t, "s23b", env_extra={"CLAUDE_SESSION_HYGIENE_SKIP": "1"})
        check("23b. CLAUDE_SESSION_HYGIENE_SKIP=1 silences the PR notice", not fired(p),
              p.stdout[:200])

        # 24. size and PR due on the same prompt: one notice covering both
        sd = os.path.join(td, "s24"); os.makedirs(sd)
        t = os.path.join(td, "t24.jsonl")
        transcript(t, 520, first_age_h=1, extra_lines=pr_create("toolu_g", url))
        p = run(sd, t, "s24")
        check("24. size and PR due together give one notice naming both",
              fired(p) and "521 messages" in notice(p) and url in notice(p),
              f"out={p.stdout[:300]}")

        # 25. a malformed tool_result line is skipped, never fatal
        sd = os.path.join(td, "s25"); os.makedirs(sd)
        t = os.path.join(td, "t25.jsonl")
        transcript(t, 30, first_age_h=1, extra_lines=(
            '{"type":"user","message":{"content":[{"type":"tool_result", BROKEN',))
        p = run(sd, t, "s25")
        check("25. a malformed tool_result line fails open, silently",
              p.returncode == 0 and not fired(p) and "Traceback" not in p.stderr,
              f"rc={p.returncode} err={p.stderr[:160]}")

    print()
    failed = [n for n, ok in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
