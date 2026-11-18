---
description: Run independent QA on a feature. /qa verify <spec> [focused|full] or /qa design <spec>
argument-hint: verify|design <spec path or reference> [focused|full]
---

Arguments: $ARGUMENTS

You are orchestrating QA; you are not doing it. Your job is to assemble a clean,
independent brief and hand it over — everything you know about *how* the feature was
built is contamination, and keeping it out is the whole value of this command.

1. Parse the mode (`verify` or `design`) and, for verify, the depth (`focused` or
   `full`). If the depth is missing, take it from the plan's QA recommendation only when
   that records `focused` or `full`. If it records `skip` — which is the default, and
   which the human is free to overturn — or there is no plan, use `focused`. `skip` is a
   recommendation, never a depth: the agent's contract accepts only the other two.
2. Locate the spec and its acceptance criteria (`docs/specs/YYYY-MM-<slug>.md`, §6).
   If there are no clear acceptance criteria, stop and say so — do not write them
   yourself for this purpose. Criteria invented now would be written to match what
   was built, which is the opposite of an independent check.
3. Read the project's `docs/qa.md`. If it does not exist, stop and say so; offer to
   create it from `qa-methodology/references/docs-qa-template.md`.
4. For focused verify, take the risk areas from the plan's QA recommendation. Rewrite them
   as observable behaviours if needed: no class, method, table, component or file
   names, nothing about how it was built.
5. For verify, make sure the app is running the way `docs/qa.md` describes, from the
   worktree holding the feature, and that the change under test is actually the code
   that is running.
6. Delegate to the `qa` subagent. The prompt must contain ONLY: mode, depth, the spec
   and acceptance criteria (verbatim or as file paths), the risk areas (focused), the
   path to `docs/qa.md`, and environment details (URLs, branch). Do NOT include the
   plan, the diff, a summary of what was built or how, the files touched, or your own
   opinion on whether it works.
7. Show me the report exactly as it came back, unedited. Do not soften a finding, do
   not answer it with what you know about the implementation, and do not drop one you
   think is wrong — a finding you disagree with is for me to arbitrate.
8. For verify, propose next steps without starting them:
   - each bug I accept goes through `test-driven-development` — the failing
     regression test first, then the fix;
   - each question is a spec question: it either changes the spec or is answered in it.
