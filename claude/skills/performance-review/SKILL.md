---
name: performance-review
description: Performance analysis across design and implementation phases. Trigger automatically when designing data models, queries, APIs, or system flows (detect performance problems before they are built), and when reviewing or generating code that touches database queries, loops over collections, background jobs, caching, or external calls. Also invoke explicitly with "is this fast enough?", "will this scale?", "review for performance", "check for N+1", or "optimize this". Do not skip for features that seem small — performance issues compound and are expensive to fix after the fact.
---

# /performance-review

Performance analysis at design time and implementation time. Catching a bad query plan in a design costs nothing; fixing it in production costs data, time, and users.

## Phase Selection

| You have | Phase to run |
|---|---|
| A feature description, data model, API design, or system flow | **DESIGN** |
| Code, a query, a migration, or a background job | **IMPL** |

When working end-to-end, run DESIGN first, then IMPL on the generated code.

---

## PHASE 1: DESIGN — Performance Architecture Review

**Goal:** Identify structural performance risks before implementation begins.

### Steps

1. **Map data flows** — What data is read, written, and how often? What are the expected volumes?
2. **Identify hot paths** — Which operations will be called most frequently? Which are on the critical path for user-facing response time?
3. **Apply the design checklist below.**
4. **Produce performance requirements** — Concrete constraints the implementation must satisfy.

### Design Checklist

**Query & Data Access Patterns**
- [ ] Are collection relationships traversed in a way that will generate N+1 queries?
- [ ] Is pagination defined for every endpoint or query that returns a list? (No unbounded result sets)
- [ ] Are filter and sort fields covered by indexes, or will queries do full table scans?
- [ ] Are aggregate queries (COUNT, SUM, GROUP BY) on large tables feasible without materialized views or counters?
- [ ] Are there joins across tables that will be large? Is the join order and index coverage considered?

**Caching Strategy**
- [ ] Are expensive or frequently-read computations identified as cache candidates?
- [ ] Is the cache invalidation strategy defined? (What triggers invalidation? TTL vs event-based?)
- [ ] Are there cache stampede risks on high-traffic keys?

**Background Jobs & Async Processing**
- [ ] Are heavy operations (email, file processing, external API calls, large data mutations) moved to background jobs?
- [ ] Are job queues sized and prioritized appropriately? (Latency-sensitive vs bulk jobs separated)
- [ ] Are there fan-out risks? (One event triggering thousands of jobs)

**External Dependencies**
- [ ] Are external API calls on the critical path? Should they be async or cached?
- [ ] Is there a timeout and circuit breaker strategy for external dependencies?
- [ ] Are bulk operations used where available instead of per-item API calls?

**Concurrency**
- [ ] Are there race conditions on shared resources (counters, limited inventory, account balances)?
- [ ] Is the locking strategy defined (optimistic vs pessimistic) and appropriate for the expected contention?

**Output budget** (CLAUDE.md): no findings → `Performance review — <phase>: 🟢 <verdict>`; otherwise failures only, ≤40 words each.

### Output — DESIGN phase

```
## Performance Design Review: [Feature / Component]

### Hot Paths Identified
- [Path]: [expected call frequency and data volume]

### Risks Found

| # | Area | Risk | Severity | Recommendation |
|---|------|------|----------|----------------|
| 1 | Queries | N+1 on user → posts relationship | 🟠 High | Eager load or use a join |
| 2 | Caching | No invalidation strategy for dashboard counters | 🟡 Medium | Define TTL or event hook |

### Performance Requirements (must satisfy in implementation)
- [ ] [Requirement]

### Verdict
🟢 Clear to implement / 🟠 Implement with constraints noted / 🔴 Redesign needed
```

---

## PHASE 2: IMPL — Code Performance Audit

**Goal:** Verify the implementation is free of common performance anti-patterns.

### Steps

1. Read the code — all files relevant to the feature.
2. Detect the language, framework, and data store automatically.
3. Apply the **universal checklist** below.
4. Apply **stack-specific checks** for the detected stack (see `references/stacks.md`).
5. Rate each finding and report.

### Universal Performance Checklist

**Query Efficiency**
- [ ] No queries inside loops — batch or eager-load instead
- [ ] No `SELECT *` on tables with many columns or large text/binary fields when only a subset is needed
- [ ] Collection sizes are bounded — pagination or limit applied before returning results
- [ ] Filters applied at the database level, not in application memory after fetching all rows
- [ ] Aggregations done in the database, not by loading all rows and summing in code

**Data Structures & Algorithms**
- [ ] No O(n²) or worse complexity in hot paths (nested loops over large collections)
- [ ] Lookups in tight loops use hash maps / sets, not linear search
- [ ] Large in-memory collections are not built unnecessarily when streaming is possible

**I/O & External Calls**
- [ ] No external HTTP calls (APIs, services) in a synchronous request/response cycle unless strictly necessary and bounded by timeout
- [ ] No per-item external calls inside a loop — use bulk endpoints where available
- [ ] File I/O is streamed for large files, not read entirely into memory

**Caching**
- [ ] Expensive or repeated computations within a request are memoized
- [ ] Cross-request caching is used for data that changes infrequently
- [ ] Cache keys are deterministic and include all relevant dimensions (user, locale, etc.)

**Background Jobs**
- [ ] Heavy operations are enqueued, not executed inline in the request
- [ ] Jobs are idempotent — safe to retry on failure
- [ ] Jobs process in batches where the work is parallelizable and the dataset is large

**Memory**
- [ ] Large collections are not accumulated in memory across iterations (use streaming / cursors)
- [ ] No unbounded growth of in-memory state (caches, queues, accumulators) without eviction

For stack-specific checks (Rails, PostgreSQL, Node.js, Python, etc.):
→ See `references/stacks.md`

### Severity scale

| Level | Meaning |
|---|---|
| 🟠 High | Will cause degradation under normal load or on realistic data volumes |
| 🟡 Medium | Will cause problems as data grows or under moderate load |
| 🔵 Low | Inefficiency that matters at scale or in high-frequency paths |
| ℹ️ Info | Optimization opportunity — no immediate risk |

### Output — IMPL phase

```
## Performance Audit: [File / Feature]

### Findings

| # | Severity | Location | Issue | Fix |
|---|----------|----------|-------|-----|
| 1 | 🟠 High | `jobs/report_job.rb:34` | Loads all records into memory before processing | Use `find_each` / cursor-based iteration |
| 2 | 🟡 Medium | `api/search.js:12` | No pagination on search results | Add `limit` + `offset` or cursor params |

### Verdict
🟢 No significant issues / 🟠 Issues to address before merge / 🔴 Redesign needed for [area]
```
