# Zero-Downtime Migration Patterns

Linked from check 4 of `migration-safety` when a risky operation is detected. Patterns are written for PostgreSQL — adapt for other databases where noted.

---

## Pattern 1: Adding a NOT NULL Column to a Large Table

### Problem
`ALTER TABLE ADD COLUMN col NOT NULL DEFAULT 'x'` on PostgreSQL < 11 rewrites the entire table. On PG 11+ it's instant for constant defaults, but a computed default still rewrites.

### Safe approach (3 migrations)

**Migration 1 — Add nullable column**
```sql
ALTER TABLE orders ADD COLUMN status VARCHAR(50);
-- No lock issue: nullable column, no default rewrite
```

**Deploy code** that writes to the new column (while still writing the old way too).

**Migration 2 — Backfill existing rows** (in batches, not a single UPDATE)
```ruby
# Rails
Order.in_batches(of: 1000) do |batch|
  batch.update_all(status: 'pending')
  sleep(0.05)  # give the DB breathing room
end
```

**Migration 3 — Add NOT NULL constraint**
```sql
-- First, validate no NULLs remain
ALTER TABLE orders ALTER COLUMN status SET NOT NULL;
-- Fast if no NULLs exist; or use NOT VALID + VALIDATE for large tables
```

---

## Pattern 2: Renaming a Column Safely

### Problem
Renaming a column breaks any running code that references the old name. You cannot do this in one step without downtime.

### Safe approach (3 steps)

1. **Add the new column** (nullable, no data yet)
2. **Dual-write**: deploy code that writes to both old and new columns; reads from old
3. **Backfill**: copy old → new for all existing rows (in batches)
4. **Migrate reads**: deploy code that reads from new column, still writes both
5. **Stop writing to old**: deploy code that only writes new column
6. **Drop old column** in a separate migration after verifying

**PostgreSQL shortcut for small tables (< ~1M rows, low traffic):**
```sql
-- This acquires an ACCESS EXCLUSIVE lock but completes fast on small tables
ALTER TABLE users RENAME COLUMN username TO handle;
```
For large tables: always use the dual-write approach.

---

## Pattern 3: Adding an Index on a Large Table

### Problem
`CREATE INDEX` without `CONCURRENTLY` acquires a `SHARE` lock, blocking all writes for the duration (minutes on large tables).

### Safe approach

```sql
-- PostgreSQL: always use CONCURRENTLY for production
CREATE INDEX CONCURRENTLY idx_orders_user_id ON orders(user_id);

-- Rails migration equivalent
add_index :orders, :user_id, algorithm: :concurrently
```

**Caveats with CONCURRENTLY:**
- Cannot run inside a transaction (`disable_ddl_transaction!` in Rails)
- Takes longer (does two full table scans)
- Can fail if a deadlock occurs — leaves an invalid index that must be cleaned up manually

```ruby
# Rails migration with CONCURRENTLY
class AddIndexOnOrdersUserId < ActiveRecord::Migration[7.1]
  disable_ddl_transaction!

  def change
    add_index :orders, :user_id, algorithm: :concurrently
  end
end
```

---

## Pattern 4: Adding a Foreign Key Safely

### Problem
`ALTER TABLE ADD CONSTRAINT ... FOREIGN KEY` validates the entire table, holding a lock during validation.

### Safe approach

```sql
-- Step 1: Add constraint without validating existing data (fast, minimal lock)
ALTER TABLE orders
  ADD CONSTRAINT fk_orders_user_id
  FOREIGN KEY (user_id) REFERENCES users(id)
  NOT VALID;

-- Step 2: Validate in a separate transaction (no write lock, just ShareUpdateExclusive)
ALTER TABLE orders VALIDATE CONSTRAINT fk_orders_user_id;
```

```ruby
# Rails equivalent
add_foreign_key :orders, :users, validate: false
validate_foreign_key :orders, :users  # in a separate migration or step
```

---

## Pattern 5: Changing a Column Type

### Problem
`ALTER COLUMN TYPE` rewrites the table and acquires an exclusive lock.

### Safe approach

Use the rename pattern (Pattern 2) with the new column having the new type:
1. Add new column with new type
2. Dual-write to both (with type coercion in application)
3. Backfill old → new (with cast)
4. Migrate reads to new column
5. Drop old column

**For safe casts** (e.g., `int` → `bigint` on PG, `varchar(100)` → `varchar(500)`):
```sql
-- bigint extension is safe and fast in PostgreSQL (no rewrite needed)
ALTER TABLE users ALTER COLUMN id TYPE BIGINT;
```

**For unsafe casts** (narrowing, changing semantics): always use the dual-write pattern.

---

## Pattern 6: Backfilling a Large Table

### Problem
`UPDATE large_table SET col = value WHERE col IS NULL` locks all matching rows and can take minutes.

### Safe approach

```ruby
# Rails: process in small batches with a sleep to avoid replication lag
class BackfillOrderStatus < ActiveRecord::Migration[7.1]
  disable_ddl_transaction!

  def up
    Order.unscoped.in_batches(of: 500) do |batch|
      batch.update_all(status: 'pending')
      sleep(0.1)
    end
  end
end
```

**For very large tables** (tens of millions of rows): consider a background job instead of a migration, and track completion separately.

---

## Pattern 7: Dropping a Column Safely

### Problem
Dropping a column that is still referenced in code causes `ActiveRecord::StatementInvalid` (Rails caches column lists).

### Safe approach (2 deploys)

**Deploy 1:** Ignore the column in application code before dropping
```ruby
# Rails: tell ActiveRecord to ignore the column
class Order < ApplicationRecord
  self.ignored_columns += ["legacy_status"]
end
```

**Deploy 2 (migration):** Now safe to drop
```sql
ALTER TABLE orders DROP COLUMN legacy_status;
```
Remove `ignored_columns` line in the same deploy or a follow-up.

---

## Pattern 8: Removing an Enum Value (PostgreSQL)

### Problem
PostgreSQL does not support removing values from an enum type — only adding them.

### Safe approach

Treat the enum as a string column with a `CHECK` constraint instead:
```sql
-- Instead of: CREATE TYPE order_status AS ENUM (...)
-- Use:
ALTER TABLE orders ADD COLUMN status VARCHAR(50);
ALTER TABLE orders ADD CONSTRAINT chk_orders_status
  CHECK (status IN ('pending', 'processing', 'completed', 'cancelled'));
```

`CHECK` constraints can be dropped and re-added with a different value set (with `NOT VALID` + `VALIDATE` for large tables).

---

## Checklist Before Running Any Migration in Production

- [ ] Tested on a production-sized dataset (or a clone with representative data volume)
- [ ] Estimated execution time is known and acceptable
- [ ] No full table locks on tables > ~100k rows — or a maintenance window is scheduled
- [ ] Indexes created with `CONCURRENTLY` where applicable
- [ ] Foreign keys added with `NOT VALID` on large tables
- [ ] Large backfills done in batches with sleep
- [ ] Old code + new schema is compatible (safe during deploy window)
- [ ] New code + old schema is compatible (safe if rollback is needed)
- [ ] Rollback procedure is documented
