# QA guide: <project name>

Project-specific context for the `qa` agent. Keep it short and current — a stale QA
guide sends an independent reviewer down a path that no longer exists.

**No secrets.** Name the env var or the password-manager entry that holds a
credential; never the credential itself.

## Running the app
- Start: `<command>`
- URLs: `<frontend>`, `<api>`
- Reset to a known state: `<command>` (development only)

## Test users
| Role | Login | Password source |
|---|---|---|
| admin | `<login>` | `<ENV_VAR>` |
| user | `<login>` | `<ENV_VAR>` |

## Data
- What the seeds create.
- How to create edge-case data (console/runner snippets, factories).

## Where specs live
- e.g. `docs/specs/YYYY-MM-<slug>.md`, acceptance criteria in §6.

## Environments
- Local development: everything, including destructive tests.
- Staging: `<URL>` — read-only smoke checks only.
- Production: never.

## Critical flows
1. ...

## Domain notes
- Time zone, locale, currency, and the business rules that look fine when violated.

## Out of scope for QA
- e.g. load testing, third-party sandboxes, anything CI already covers
  deterministically (lint, types, SAST, secret scanning).
