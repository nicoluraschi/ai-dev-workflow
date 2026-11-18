# Hooks — design rationale

The [README](../README.md#️-hooks--the-guarantees) lists what each hook does. This page explains
why they are built the way they are.

## The edit guard

The protected roots are a tuple, so a new root is data, not code, and they are deliberately not
env-overridable: this is the guard that must not be self-bypassable.

**It's wider than it first looks.** The guard resolves symlinks, and most of the live config
(`~/.claude`, `~/.codex`, `~/.config/zed`, `~/.config/git/ignore`, `~/.config/zsh`, the CLIs in
`~/.local/bin`) symlinks into this repo. All of it is blocked on `main`. That's the point: config
changes get a branch like any other change. `~/.claude/projects/` (memory, transcripts) is real,
not symlinked, and stays writable.

Any `ai-profile.md` under `docs/` stays blocked whatever its casing or nesting: it authorizes
sending a repo's artifacts to a second AI provider — an authorization record, not a spec.

Bash writes are detected, not blocked, by `uncommitted-on-main.py` (Stop hook).

## Per-hook design

- **`no-commit-on-red.py`** reads the *summary line* of the most recent test run, not the exit
  code, because a pipe (`rspec 2>&1 | tail -12`) makes the exit status `tail`'s. Silence isn't
  red: if no suite ran, the commit goes through. A red *full* run holds until a green full run of
  the same suite (rspec, jest, pytest); a green related-tests run doesn't clear it.
- **`suite-form-guard.py`** acts only where the repo's lefthook pre-push runs that runner (RSpec,
  or Jest/Vitest via `npm test`/`pnpm test`) through `suite-queue`. A full run in another form
  never matches the push's argv, so the push would rerun it; the deny names the form that does
  match. Related-test forms (files, patterns, `--findRelatedTests`, `vitest related`) stay
  allowed. It also denies a push that disables the pre-push hook, in such a repo and in any
  checkout of the public repo, where that hook is the privacy guard. There it is deny by default:
  only a plain `git push` with standard options passes.
- **`public-text-guard.py`** keeps private text out of the public repo's GitHub text. A checkout
  is *public* when it, or a worktree of it, is the clone named in
  `~/.config/ai-workflow/public-repo`, or its `origin` is the public repo; a `gh` call also counts
  when its flags, a URL, an API path or `GH_REPO` name the public repo. There, every `gh` call
  that is not read-only has its arguments and the files it uploads piped through
  `scripts/privacy-check --private --stdin`, taken from the configured clone rather than from a
  worktree that may hold an outsider's branch. It denies on a hit, on a non-zero exit, on a write
  it cannot extract text from, and on any shell form it cannot resolve statically. Everywhere,
  public or not, it denies edit-tool writes and common shell writes to `~/.config/ai-workflow/`
  (the trusted paths and lists there are edited by hand), and in a public checkout the same writes
  to `lefthook-local.yml`. A backstop, not a sandbox. Inside a guarded case any internal error
  denies.
- **`gate-state-guard.py`** stops the agent from switching its own gates off. It denies Edit,
  Write and NotebookEdit on the resolved path of the audit state dir (`CLAUDE_AUDIT_STATE_DIR`,
  and always `~/.claude/.audit-state`), the scanner pointer and the extra scanner it names (plus
  that scanner's directory, since it reads files beside itself), and any Bash command whose text
  names one of them or `.audit-state`, reads included (the Read and Grep tools stay open). A speed
  bump against drift, not a boundary: a script that touches the state dir without naming it
  passes. Gate refusals name the gate and ask the agent to get the human to silence it; they print
  no path. **The human silences a gate** from the prompt with `!`, e.g.
  `! touch "$STATE/<session_id>.skip.<gate>"` (`audit-guard` also takes `<session_id>.skip` for
  all gates), where `$STATE` is the audit state dir; or `CLAUDE_*_SKIP=1` at launch.
- **`uncommitted-on-main.py`** exists because, measured over 30 days, ~49% of file mutations go
  through Bash. It detects rather than prevents, and releases after two refusals so it can't trap
  a turn.
- **`session-hygiene.py`** never blocks — the right response is to finish the PR in flight
  *first*. It speaks once per trigger kind: session size (500 msgs or 8h), more than 4 sessions
  at once, and a PR opened from this session (so the next piece of work starts with a fresh
  context).
- **`audit-guard.py`** counts an audit only if the skill ran *after* the last triggering edit, so
  editing an audited file re-arms it. It releases after two refusals, and each gate is silenced on
  its own, never all at once, with a silencer that expires after 4h. A repo whose domain collides
  with a keyword (a `ReadingSession` model vs `session`) lists per-skill terms to ignore in a
  tracked `.claude/audit-guard.json`: `{"ignore": {"security-audit": ["reading_session"]}}`.
  Editing that file owes a security audit itself.
- **`qa-agent-readonly.py`** fires only when `agent_type == "qa"`; everywhere else it's
  invisible, which is the only way a guard like this survives. It blocks git writes, file
  mutations outside scratch paths, redirection into a real file in every form, in-place editors
  and interpreter one-liners that write. **Writes to the development database are allowed on
  purpose** — the rule is "QA doesn't change the thing it is judging", and edge-case data is part
  of the job. The threat model is a *helpful* agent "just fixing" the bug it found.

## The auto-mode classifier environment

`settings.json` carries an `autoMode` block: the environment description and extra `soft_deny`
rules the auto-mode classifier reads when deciding what may run without a prompt.
`claude auto-mode config` prints the effective result.

It follows the two-layer split. **The global block names no trusted repository** — only what's
true on any repo on this machine: the secret-file patterns (`.env*`,
`config/credentials.yml.enc`, `config/master.key`, `.kamal/secrets`, `*.pem`, `*.key`), the
`prod`/`production` whole-word heuristic for remote targets, the protected IaC scopes, the
`main`/`master` protection, and the worktree convention. Naming a trusted repo globally would
widen what the agent may do unprompted in *every* repo.

**`autoMode` has no project layer — verified, not assumed.** It is read from user scope and the
`--settings` flag only; a `.claude/settings.json` or `.claude/settings.local.json` declaring it is
silently ignored. Across the tiers that *are* read, arrays merge rather than replace, and
`$defaults` interpolates the shipped built-ins, not the user-scope entries. Reproduce it:

```bash
claude auto-mode config | jq '.environment | length'                              # user scope only
claude --settings '{"autoMode":{"environment":["MARKER"]}}' auto-mode config \
  | jq '.environment | map(select(contains("MARKER"))) | length'                  # 1 — merged in
```

So **per-repo trust context can't be expressed today.** That fails safe — auto mode prompts
*more*, never less — and it stays that way on purpose until the key gains a project scope.
