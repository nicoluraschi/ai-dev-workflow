---
name: data-integrity
description: Database integrity review for schema design and the constraints migrations introduce. Trigger automatically when designing a data model or database schema, writing or reviewing migrations, adding or modifying relationships between models, handling deletions or state transitions, or working with financial data, counters, or any field where correctness is critical. Also invoke explicitly with "design this schema", "review this data model", or "will this cause data loss?". Do not skip this for small schema changes — constraint gaps are among the most expensive bugs to fix in production.
---

# Data integrity

Data integrity problems are silent: no exception is raised when a foreign key is missing and an orphaned record silently breaks a query three months later. This skill enforces integrity at the database level — not only in application code.

## Phase Selection

| You have | Phase to run |
|---|---|
| A data model description, ER diagram, or schema design | **DESIGN** |
| A migration file, schema change, or existing schema to review | **DESIGN** on the schema it produces; the migration's own safety (locking, backfill, reversibility) belongs to `migration-safety` |
| Built schema at feature-workflow phase 5, with a recorded 2d DESIGN verdict | **CONFORMANCE** first; DESIGN only on what drifted |

## CONFORMANCE — phase 5 after a 2d review

The 2d DESIGN run already reviewed this data model in the plan; re-running the whole checklist on
the same schema found no major gap in 42 measured phase-5 runs. So compare first.

**Applies only when** the spec's §4 holds the `2d-data:` verdict line with 0 rejected and 0
deferred (every 2d finding, gap or recommendation, fixed in the plan), and the plan's data model
has not changed since that verdict (a 2b fold-in or a checkpoint edit counts). Otherwise (light or
trivial lane, 2d did not run, no `2d-data:` line, a finding rejected or deferred, or a data-model
edit after 2d) → no CONFORMANCE: run DESIGN in full.

1. Read the approved plan's data model (`<artifacts>/plans/<slug>.md`), the spec's §4, and
   `git diff <base>` (the base branch against the working tree, with its default context so each
   changed line shows its table) under migrations, schema files and models.
2. **Drift** is any table, column, column type or size, null / default / unique / FK / CHECK
   constraint, FK `ON DELETE` behaviour, index, association, validation, enum or callback in the
   diff that the plan does not state — or one the plan states that the diff omits or changes.
3. No drift → print `Data integrity — phase 5: 🟢 matches 2d` and stop.
4. Drift → name each drift item, then run the DESIGN checklist below on the drifted tables plus
   every table with an FK to or from them (a soft-delete or cascade change alters their unique
   indexes and FKs too).

---

## PHASE 1: DESIGN — Schema Integrity Review

**Goal:** Ensure the data model is correct by construction — constraints enforced at the DB level, not trusted to application logic alone.

### Checklist

**Referential Integrity**
- [ ] Every foreign key column has a `FOREIGN KEY` constraint defined in the database — not just at the ORM/model level
- [ ] Cascading behavior is explicitly defined: `ON DELETE CASCADE`, `ON DELETE RESTRICT`, or `ON DELETE SET NULL` — never left to default or handled only in application code
- [ ] Orphan prevention: are there paths where a referenced record can be deleted while children exist?

**Column Constraints**
- [ ] Required fields have `NOT NULL` at the database level — not just `validates :presence` in the model
- [ ] Fields with a fixed set of valid values use a `CHECK` constraint or a DB enum — not just application-level validation
- [ ] Numeric fields that cannot be negative (prices, quantities, counts) have `CHECK (column >= 0)`
- [ ] String fields with known max length have appropriate type sizing

**Uniqueness**
- [ ] Unique fields have a `UNIQUE` index at the database level — not just `validates :uniqueness` (which has race conditions)
- [ ] Composite uniqueness constraints (e.g., one entry per user per day) use a composite unique index

**Defaults**
- [ ] Columns with sensible defaults have `DEFAULT` defined at the DB level for consistency across all write paths
- [ ] Timestamps (`created_at`, `updated_at`) have DB-level defaults

**Counters and Balances**
- [ ] Fields that represent totals, balances, or counts are protected against concurrent writes (optimistic locking, advisory locks, or DB-level transactions)
- [ ] Financial amounts stored as integers (cents) — never floats

**Soft Deletes (if used)**
- [ ] Soft delete column (`deleted_at`, `discarded_at`) has a partial index on the non-deleted rows for query performance
- [ ] Unique constraints account for soft deletes (a "deleted" email should not block re-registration)
- [ ] Foreign key semantics are defined for soft-deleted records: are children still accessible?

**State Machines**
- [ ] Valid state transitions are enumerated and enforced — not an open string field
- [ ] Invalid states cannot be written directly to the DB (CHECK constraint on state column, or DB enum)

**Output budget** (CLAUDE.md): no findings → `Data integrity — <phase>: 🟢 <verdict>`; otherwise failures only, ≤40 words each.

### Output — DESIGN phase

```
## Data Integrity Review: [Model / Schema]

### Constraint Gaps

| # | Table | Column / Relationship | Gap | Fix |
|---|-------|-----------------------|-----|-----|
| 1 | orders | user_id FK | No DB-level foreign key | Add FK constraint with ON DELETE RESTRICT |
| 2 | products | price_cents | Can be negative | Add CHECK (price_cents >= 0) |
| 3 | memberships | (user_id, plan_id) | Uniqueness only in model | Add composite UNIQUE index |

### Recommendations
- [Non-blocking suggestions]

### Verdict
🟢 Schema is sound / 🟠 Add constraints before implementing / 🔴 Redesign needed for [area]
```

