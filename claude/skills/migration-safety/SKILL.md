---
name: migration-safety
description: Review a database migration for production safety before it ships — locking, backfill strategy, reversibility, and whether schema and application code can deploy independently. Fires on any diff touching db/migrate/, on "add a migration", "change the schema", "add a column", "add an index", "rename a column", "is this migration safe", "safe to deploy", and before deploying any change that alters the schema of a live database. Targets Rails and Postgres. A migration is the one change that reverting the code will not undo.
---

# Migration safety

## Why this exists

Every other kind of mistake is recoverable by reverting a commit. A migration is not. It runs
against a live database, it can hold a lock that stalls every request behind it, and its
damage survives a rollback of the code that introduced it.

The failure mode is not usually a wrong schema. It is a *correct* schema applied in a way
that takes the site down for ninety seconds, or a column removed while the previous release
is still serving traffic and still selecting it.

## Verify the version first

Lock behaviour is version-dependent and the folklore is mostly out of date. Before applying
any rule below, establish the actual Postgres major version — much advice that was true
before PG 11 is now wrong, and repeating it produces pointless churn.

## The five checks

### 1. Lock profile — what lock, on what, for how long

Ask what the statement locks and whether that lock blocks reads, writes, or both, and for how
long it is held. A statement that is instant on an empty local database can hold a table for
a long time in production.

Usually fine:
- `add_column` with no default, or with a **constant** default on PG 11+ (no table rewrite)
- dropping a constraint
- `add_index` **with `algorithm: :concurrently`**

Needs care — check size and lock class first:
- `add_index` **without** `concurrently` — blocks writes for the duration of the build
- `add_foreign_key` — locks both tables while validating; prefer `validate: false` then a
  separate `validate_foreign_key` (Postgres: `NOT VALID`, then `VALIDATE CONSTRAINT` in its own
  step, which takes a weaker lock)
- `change_column_null(..., false)` — scans the whole table to verify
- `change_column` that changes a type — often rewrites the table. A narrowing change
  (`VARCHAR(500)` → `VARCHAR(100)`) also fails on existing rows over the new limit; query for
  them first
- `add_column` with a **volatile** default (e.g. a function call) — rewrites the table

Practically always a problem in one step:
- `rename_column` / `rename_table` — the old name disappears while old code is still running
- `remove_column` — see check 4

Also set a `lock_timeout` for anything that takes a strong lock. A blocked DDL statement does
not just wait; it queues behind itself every query that needs the table, which is how a
migration that "only takes a second" becomes an outage.

### 2. Indexes concurrently

```ruby
class AddIndexToThings < ActiveRecord::Migration[8.1]
  disable_ddl_transaction!
  def change
    add_index :things, :slug, algorithm: :concurrently
  end
end
```

`concurrently` cannot run inside a transaction, hence `disable_ddl_transaction!`. Note the
trade-off: a concurrent build that fails leaves an **invalid** index behind that must be
dropped before retrying. Say so in the migration if you use it.

### 3. Backfill is not a schema change

Do not backfill data in the same migration that alters the schema. The migration holds its
transaction for the whole backfill, and a long transaction on a live table is the thing you
are trying to avoid.

Split it: schema change → deploy → backfill in batches (a rake task or a job, with a sleep
between batches) → only then add the constraint that assumes the data is there.

If a migration's backfill has nothing to migrate because the table is new, say that
explicitly in the migration body rather than writing a no-op loop.

### 4. Two deploys, not one — can code and schema ship independently?

At every moment during a deploy, **the old code runs against the new schema** and briefly the
reverse. A migration is only safe if both combinations work.

Removing a column is the classic case and needs two deploys:
1. Deploy code that no longer references the column, with `ignored_columns` set so
   ActiveRecord stops selecting it.
2. Then deploy the migration that drops it.

Do it in one and the still-running old release selects a column that no longer exists.

Renames are the same problem with no safe single-step form: add the new column, write to both,
backfill, switch reads, drop the old one.

Enum values follow the same rule: adding one is safe, removing or renaming one is not — the old
release still reads and writes the old value.

Step-by-step patterns for each of these: `references/zero-downtime.md`.

### 5. Reversibility — can you get back?

`change` must be genuinely reversible, or the migration must define `up` and `down`
explicitly. `remove_column` without the column type is irreversible, and Rails will only tell
you at rollback time, which is the worst possible moment.

Then answer the question the `down` method does not: **what is the actual rollback plan?** If
the migration is irreversible in practice — data was dropped — say so plainly, and say what
the recovery path is (restore, or forward-fix only). Before a destructive transformation — a
drop, or a rewrite of existing values — back up or copy the affected data first, so restore is
actually possible.

## What not to report

Do not flag style, naming, or anything the linter and CI already cover. This is about what
happens when the statement meets a live table with real rows in it.

## Output

One verdict per migration file. A safe file is **one line**:

```
Migration safety — 20260910170658_add_report_to_extraction_runs.rb: 🟢 safe in one step — additive, constant default, reversible
```

A file with a problem lists only the failing checks, each ≤40 words, with the fix:

```
Migration safety — 20260912090000_add_index_on_runs_status.rb
  Lock         ❌ add_index without CONCURRENTLY locks writes on runs — use algorithm: :concurrently + disable_ddl_transaction!
  → blocked until fixed
```

Say what to change, not just that it is wrong.
