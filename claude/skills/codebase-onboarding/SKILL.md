---
name: codebase-onboarding
description: Build a working mental model of a codebase you did not write, fast, and write it down. Fires on "what is this codebase", "onboard me to this repo", "explain this project", "I just inherited this", "help me understand this code", "where do I start", and at the start of work in an unfamiliar repo. Produces a durable note under docs/ — entry points, data model, request lifecycle, test strategy, deploy path, and the things most likely to surprise you — with every claim citing a real path.
---

# Codebase onboarding

## Why this exists

The first hour in an unfamiliar repo is usually spent building a model that then evaporates,
because it lived in a chat log. Do it once, in a fixed order, and write it to a file that
survives the session.

The order matters. Reading files alphabetically teaches you nothing. Following a request from
the edge to the database and back teaches you almost everything.

## The pass

Work through these in order. Cite a real path for every claim — a model of the codebase that
cannot be checked against the codebase is a guess.

### 1. Edges — how does anything get in?
Routes, CLI entry points, scheduled jobs, webhooks, queue consumers. Answer: what can trigger
work in this system? This bounds everything else.

### 2. Data model — what does it actually store?
Schema first, not the ORM classes. Tables, the relationships that carry meaning, and which
columns are doing real work. Note anything unusual: jsonb columns, soft deletes, state
machines, denormalized counters.

Then name the **core domain nouns** in the project's own vocabulary. Using the codebase's
words is most of the battle; if the repo has a glossary, read it.

### 3. Lifecycle — follow one request end to end
Pick the most representative operation and trace it: entry → auth → validation →
business logic → persistence → serialization → response. Note where the layers are and where
the conventions break.

### 4. Tests — what does the repo believe about testing?
Framework, where tests live, what they cover, and — more informative — what they *don't*.
Run the suite. A suite you have not run is a suite you do not understand.

### 5. Deploy — how does code reach production?
CI, environments, migrations, secrets, rollback. Answer: if you merged right now, what
happens?

### 6. Surprises — the five things that will bite you
This is the part that justifies the whole exercise. Non-obvious coupling, a convention that
contradicts itself, a "temporary" workaround load-bearing for two years, a test that passes
for the wrong reason, generated code that looks hand-written.

Be specific and cite paths. "The code is complex" helps nobody.

## Write it down

Output a file — `docs/onboarding.md`, or wherever the repo keeps notes — not a wall of
terminal text. Chat output is lost at the end of the session; that is the problem this skill
exists to solve.

Keep it to roughly a page and a half. This is a map, not a rewrite of the source.

```markdown
# Onboarding notes — <repo>

_Written <date> from commit <sha>. A map, not a spec — verify before relying on any of it._

## What this is
## Edges          — what can trigger work
## Data model     — core nouns and what they store
## Lifecycle      — one request, end to end
## Tests          — framework, coverage, gaps (suite run: <result>)
## Deploy         — what happens when you merge
## Surprises      — five things that will bite you
## Open questions — what I could not determine
```

## Hard rules

- **Cite paths.** Every structural claim points at a file.
- **Run the suite.** Report the real result, including failures.
- **Keep the open questions section.** An honest "I could not work out how X is wired" is
  worth more than a confident wrong answer, and it tells the next reader where to dig.
- **Do not change code.** This is a reading exercise. If you spot a bug, note it under
  Surprises and move on.
