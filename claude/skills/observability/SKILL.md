---
name: observability
description: Observability instrumentation for new and existing code. Trigger automatically when implementing a new feature, endpoint, background job, or integration — generate the logging, error tracking, and metrics instrumentation alongside the implementation code. Also trigger when reviewing existing code that lacks observability ("add logging to this", "instrument this", "we're flying blind on this feature", "set up error tracking", "what should we monitor here"). Do not treat observability as optional or a follow-up task — it is part of the definition of done for any production feature.
---

# Observability

Observability is what lets you understand what your system is doing in production without attaching a debugger. It is not an afterthought — it is generated alongside the feature.

## Two Modes

| Situation | Mode |
|---|---|
| Implementing a new feature, endpoint, or job | **GENERATE** — produce instrumentation code alongside the implementation |
| Reviewing existing code | **AUDIT** — identify what's missing and produce the missing instrumentation |

---

## What Good Observability Covers

Three pillars, applied proportionally to the feature's complexity and risk:

| Pillar | Purpose | Always? |
|---|---|---|
| **Structured Logging** | Human-readable + machine-parseable record of what happened | Yes |
| **Error Tracking** | Capture exceptions with full context; alert on new errors | Yes |
| **Metrics / Health** | Quantitative signals for dashboards and alerting | For jobs, critical paths, and external integrations |

Distributed tracing (OpenTelemetry spans) is covered in `references/tracing.md` — apply when the feature crosses service boundaries.

---

## MODE 1: GENERATE — Instrument as You Build

When implementing a feature, generate instrumentation for each of the following touchpoints:

### 1. Structured Logging

Every significant operation should emit a structured log entry. Key principles:

- **Use structured fields, not string interpolation.** Log entries must be machine-parseable.
- **Log at boundaries**: request in, response out, external call made, external call returned, job started, job completed.
- **Include context**: user ID, request ID / trace ID, resource ID, operation name.
- **Log outcomes, not just starts**: success path AND error path.
- **Never log secrets, tokens, passwords, or PII** in plaintext.

```
# What a good log entry contains:
{
  "level": "info",
  "event": "payment.processed",
  "user_id": 42,
  "order_id": 9981,
  "amount_cents": 4999,
  "duration_ms": 143,
  "provider": "stripe",
  "trace_id": "abc123"
}
```

**Log levels:**
- `DEBUG` — detailed internals, disabled in production by default
- `INFO` — normal operations, business events worth keeping
- `WARN` — something unexpected but handled; operation succeeded
- `ERROR` — operation failed; requires attention
- `FATAL` — system cannot continue

### 2. Error Tracking

For every error path in the feature:

- Capture the exception with full stack trace, context, and user/request identifiers.
- Add breadcrumbs / context tags that help reproduce the problem: what was the user doing, what data was involved.
- Group errors by fingerprint — not by raw message — so you know if it's a new error or a recurrence.
- Distinguish expected errors (validation, not-found, 4xx) from unexpected errors (5xx, crashes) — only the latter should alert.

**Sentry integration pattern:**
```
# On exception:
- Capture with Sentry.capture_exception / Sentry.captureException
- Set user context: Sentry.set_user({ id, email })
- Set tags for routing: environment, component, job name
- Add extra context: the params or payload that triggered the error
```

See `references/sentry.md` for implementation patterns per stack.

### 3. Metrics (for jobs, critical paths, and integrations)

Instrument these with counters, gauges, or timers:

- **Job execution**: started count, success count, failure count, duration
- **External API calls**: call count, success/failure rate, latency
- **Business-critical operations**: payment attempts, user signups, data imports
- **Queue depth**: jobs waiting, jobs processing (if the job system exposes it)

Metric naming convention: `<service>.<component>.<operation>.<unit>`
Example: `app.payments.charge.duration_ms`, `app.jobs.import.failure_count`

---

## MODE 2: AUDIT — Review Existing Code

When reviewing existing code for observability gaps:

### Checklist

**Logging**
- [ ] Significant operations emit structured log entries (not `puts`, `console.log` raw strings, or `print`)
- [ ] Error paths are logged at `ERROR` or `WARN` level with context
- [ ] External calls are logged with outcome and duration
- [ ] Log entries include request/trace ID for correlation across services
- [ ] No sensitive data (passwords, tokens, full card numbers, SSNs) in logs

**Error Tracking**
- [ ] Unhandled exceptions are captured and sent to an error tracker
- [ ] Handled exceptions that represent real problems are also captured (not silently swallowed)
- [ ] User context is set before errors are captured
- [ ] Background jobs capture errors with job-specific context (job class, arguments)
- [ ] Errors are distinguishable: validation errors vs application bugs vs infrastructure failures

**Metrics & Alerting**
- [ ] Background jobs emit timing and success/failure metrics
- [ ] External integrations have error rate visibility
- [ ] There is at least one alert configured for the feature's most critical failure mode

**Output budget** (CLAUDE.md): no findings → `Observability — <phase>: 🟢 <verdict>`; otherwise failures only, ≤40 words each.

### Output — AUDIT mode

```
## Observability Audit: [File / Feature]

### Gaps

| # | Pillar | Location | Gap | Fix |
|---|--------|----------|-----|-----|
| 1 | Error Tracking | `jobs/sync_job.rb:45` | Exception swallowed silently | Capture with Sentry + log at ERROR |
| 2 | Logging | `services/payment.rb:12` | No log on payment failure path | Add structured log with user_id, amount, error |
| 3 | Metrics | `jobs/import_job.rb` | No duration or failure tracking | Add timing around job body |

### Instrumentation to Add
[Code snippets for each gap]
```

---

## What Not to Log

Always verify generated instrumentation does not include:

- Passwords or password hashes
- Authentication tokens, API keys, session tokens
- Credit card numbers, CVVs, bank account numbers
- Full request bodies that may contain any of the above
- PII beyond what is strictly necessary for debugging (email and user ID are usually acceptable; full address, phone, SSN are not)

---

## Reference Files

- `references/sentry.md` — Sentry setup and patterns per stack (Rails, Node, Python)
- `references/tracing.md` — Distributed tracing with OpenTelemetry for multi-service features
