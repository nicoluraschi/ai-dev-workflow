# Stack-Specific Performance Checks

Loaded during IMPL phase once the stack is detected.

---

## Ruby on Rails

### N+1 Queries
```ruby
# ❌ Classic N+1 — 1 query for posts + N queries for authors
Post.all.each { |p| puts p.author.name }

# ✅ Eager load
Post.includes(:author).each { |p| puts p.author.name }

# ✅ When you need a join for filtering
Post.joins(:author).where(authors: { active: true })
```

**What to scan for:**
- `.each` or `.map` on an ActiveRecord relation that calls associations inside the block
- `belongs_to` or `has_many` accessed inside a view loop without includes
- Counter columns accessed without `counter_cache: true`

### Unbounded Queries
```ruby
# ❌ Loads everything
User.all.map(&:email)

# ✅ Batched
User.find_each(batch_size: 500) { |u| process(u) }

# ✅ Or use pluck when only the value is needed
User.pluck(:email)
```

### Unnecessary Data Loading
```ruby
# ❌ Loads full objects when only IDs are needed
Post.where(published: true).map(&:id)

# ✅
Post.where(published: true).ids

# ❌ Loads full records for a count
User.where(active: true).to_a.count

# ✅
User.where(active: true).count
```

### Caching
- `Rails.cache.fetch` with a block — verify key includes all cache-busting dimensions
- Fragment caching in views: check `cache` calls have appropriate keys
- `counter_cache` for frequently-read counts on associations

### Background Jobs (Solid Queue / Sidekiq / GoodJob)
- Jobs calling ActiveRecord inside a loop: use `find_each` or batch inserts
- Jobs that enqueue other jobs in a loop: check for fan-out risk
- `perform_now` in a controller: should almost always be `perform_later`

### Database-Level
- Missing indexes: check `add_index` in migrations for every foreign key and every column used in `WHERE`, `ORDER BY`, or `GROUP BY`
- `explain` / `ANALYZE` output for complex queries — look for Seq Scan on large tables

---

## PostgreSQL

### Index Coverage
```sql
-- Flag these query patterns without an index:
WHERE column = $1          -- needs index on column
ORDER BY column            -- needs index on column
WHERE a = $1 AND b = $2   -- consider composite index (a, b)
LIKE 'prefix%'             -- can use btree index
LIKE '%suffix'             -- needs pg_trgm or full-text
```

### Query Planning
- `EXPLAIN ANALYZE` output: look for Seq Scan on tables > ~10k rows
- Nested Loop with high rows estimate: may need a Hash Join hint or index
- High cost estimates on ORDER BY without index: add index or limit early

### Expensive Patterns
```sql
-- ❌ Count on large table without index
SELECT COUNT(*) FROM events WHERE user_id = $1;
-- ✅ Use a counter cache or partial index

-- ❌ Correlated subquery in SELECT list (runs once per row)
SELECT *, (SELECT COUNT(*) FROM orders WHERE orders.user_id = users.id) FROM users;
-- ✅ Use a lateral join or window function
```

### Bulk Operations
```sql
-- ❌ Row-by-row inserts in a loop
INSERT INTO tags (name) VALUES ($1);  -- repeated N times

-- ✅ Single multi-row insert
INSERT INTO tags (name) VALUES ($1), ($2), ($3), ...;
```

### Locking
- `SELECT ... FOR UPDATE` without a `LIMIT`: locks the whole result set
- Long-running transactions holding row locks: check for unnecessary work inside transactions
- Advisory locks for distributed mutex patterns: verify they are always released

---

## Node.js (Express / Fastify / general)

### Async Patterns
```javascript
// ❌ Sequential awaits when operations are independent
const user = await getUser(id);
const posts = await getPosts(id);  // doesn't need user to start

// ✅ Parallel
const [user, posts] = await Promise.all([getUser(id), getPosts(id)]);
```

### Database (generic ORM / query builder)
- `findAll()` / `find()` without `limit`: unbounded result set
- N+1 with `include` / `populate` missing for nested relations
- Selecting all columns when only a subset is needed

### Memory
- `Buffer.concat` in a loop on large streams: accumulates in memory
- Unbounded arrays built by pushing in a loop without draining
- Large JSON payloads parsed and held in memory across async operations

### CPU-Intensive Work
- Synchronous `JSON.parse` / `JSON.stringify` on very large objects on the hot path
- Crypto operations (hashing, signing) on the main thread at high frequency: move to worker threads

---

## Python (Django / FastAPI / SQLAlchemy)

### Django ORM
```python
# ❌ N+1
for post in Post.objects.all():
    print(post.author.name)  # hits DB every iteration

# ✅
for post in Post.objects.select_related('author'):
    print(post.author.name)

# ❌ Loading all for a count
Post.objects.filter(published=True).__len__()

# ✅
Post.objects.filter(published=True).count()
```

### SQLAlchemy
- Lazy loading relationships inside a loop: use `joinedload` or `selectinload`
- `session.query(Model).all()` on large tables: use `yield_per` for streaming

### Async (FastAPI / asyncio)
```python
# ❌ Sequential I/O
user = await get_user(id)
posts = await get_posts(id)

# ✅ Concurrent
user, posts = await asyncio.gather(get_user(id), get_posts(id))
```

### Memory
- Loading large files into memory with `file.read()`: use chunked reading
- Building large lists in memory when a generator would do
