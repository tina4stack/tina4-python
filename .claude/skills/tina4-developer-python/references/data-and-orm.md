# Data, ORM & Database (Python)

## Defining Models

Drop a model file in `src/orm/` and it's auto-registered. **Models use field objects, not
bare type annotations.** Each column is a `*Field(...)` descriptor — the framework reads the
field metadata to build tables, cast values, and generate CRUD. A bare annotation like
`name: str = None` is **not** a column and will not persist.

```python
from datetime import datetime
from tina4_python import (
    ORM, IntegerField, StringField, BooleanField,
    TextField, DateTimeField, JSONField,
)

class User(ORM):
    table_name = "users"          # optional — inferred from the class name otherwise

    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
    bio = TextField(default="")
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=lambda: datetime.now())
    preferences = JSONField(default=lambda: {})   # stored as a JSON string / native JSON
```

Available field objects (from `tina4_python`): `IntegerField`, `StringField`, `BooleanField`,
`FloatField`, `NumericField`, `TextField`, `DateTimeField`, `BlobField`, `JSONField`, and
`ForeignKeyField`. The primary key is the field declared with `primary_key=True` — you do not
set a separate `primary_key` attribute. Callable defaults (`default=lambda: ...`) run per-row,
so use them for `datetime.now()` and for mutable defaults like `{}` / `[]`.

## CRUD Operations

> **Query methods are classmethods.** Call them on the class: `User.where(...)`, `User.all()`,
> `User.find(...)`, `User.find_by_id(...)`. They return **plain Python lists** of model
> instances (except `find_by_id` / `find(pk)` / `select_one`, which return a single instance or
> `None`). A list has **no** `.fetch()`, `.to_array()`, or `.to_json()` — there is no v2 query
> chain like `User().select("*").where(...).fetch()`; that raises at request time.

### Create

```python
user = User({"name": "Alice", "email": "alice@example.com"})
saved = user.save()   # returns self (fluent) on success, False on failure
```

### Read — by primary key

```python
user = User.find_by_id(1)   # -> User instance or None
user = User.find(1)         # -> same; an int/str argument is a PK lookup
```

### Read — filtered list

```python
# Dict filter → list[User] (columns AND-ed)
users = User.find({"is_active": True})

# SQL WHERE fragment + bound params → list[User]
users = User.where("is_active = ?", [1])
users = User.where("is_active = ?", [1], limit=20, offset=0)

# All records → list[User]
users = User.all(limit=50)

# A single row — index the list, or use a dict filter
user = User.where("email = ?", ["alice@example.com"])[0]
user = User.find({"email": "alice@example.com"})[0]
```

> **`find("is_active = 1")` is NOT a filter.** A *string* passed to `find()` is treated as a
> primary-key value, so a SQL fragment silently becomes a PK lookup that finds nothing and
> returns `None`. For a SQL condition use `where("is_active = 1")`. Reserve `find(...)` for a PK
> (`find(1)`) or a dict (`find({"is_active": 1})`).
>
> **`select_one` and `select` take FULL SQL**, not a WHERE fragment:
> ```python
> user  = User.select_one("SELECT * FROM users WHERE email = ?", ["alice@example.com"])  # -> User | None
> users = User.select("SELECT * FROM users WHERE is_active = ? ORDER BY name", [1])       # -> list[User]
> ```
> Use `where("email = ?", [...])` when you only have the condition; use `select`/`select_one`
> when you need a complete query.

### Update

```python
user = User.find_by_id(1)
user.name = "Alice Smith"
user.save()
```

### Delete

```python
user = User.find_by_id(1)
user.delete()
```

### Serialisation

```python
# On a single instance:
user.to_dict()    # {"id": 1, "name": "Alice", ...}
user.to_json()    # '{"id": 1, "name": "Alice", ...}'
```

> **Query results are plain lists — serialize with a comprehension.** `where()`, `all()`,
> `find(dict)`, and `select()` return a `list`, and a list has no `.to_dict()` / `.to_array()`.
> Build the payload per-instance:
> ```python
> return response([u.to_dict() for u in User.all()])
> ```
> `to_array()` / `to_json()` / `to_csv()` on the *result object* belong to the `DatabaseResult`
> returned by `db.fetch()` (see below), not to ORM list results.

## Relationships

Declare relationships as **descriptor attributes** on the model class:

```python
from tina4_python import ORM, IntegerField, StringField, has_many, belongs_to

class User(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    posts = has_many("Post", "user_id")      # user.posts -> [Post, ...]

class Post(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    user_id = IntegerField()
    title = StringField()
    author = belongs_to("User", "user_id")   # post.author -> User

# Access (lazy-loaded on first touch, then cached on the instance):
user = User.find_by_id(1)
posts = user.posts          # all posts by this user
post  = Post.find_by_id(1)
author = post.author        # the post's author
```

`has_one(name, foreign_key)` also exists. Alternatively, declare a `ForeignKeyField` and both
sides are wired automatically:

```python
class Post(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    user_id = ForeignKeyField(to=User)   # auto-creates post.user (belongs_to) + User.posts (has_many)
    title = StringField()
```

Use `related_name=` on `ForeignKeyField` to rename the reverse accessor
(`ForeignKeyField(to=Post, related_name="comments")` → `post.comments`).

## Soft Delete

```python
class Article(ORM):
    soft_delete = True                      # excludes is_deleted=1 rows from default queries
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    is_deleted = IntegerField(default=0)    # REQUIRED — you must declare it yourself

article = Article.find_by_id(1)
article.delete()          # sets is_deleted = 1 (soft)
article.restore()         # sets is_deleted = 0
article.force_delete()    # actually removes the row

# Default queries exclude soft-deleted records:
articles = Article.all()
# Include deleted:
articles = Article.with_trashed()
```

> **You MUST declare `is_deleted` yourself.** `create_table()` builds the table from
> your declared fields only — it does **not** inject an `is_deleted` column when
> `soft_delete = True`. Omit the field and the table has no such column, so `delete()`
> (writes `is_deleted = 1`) and `all()` / `find()` / `where()` (append
> `WHERE is_deleted = 0 OR is_deleted IS NULL`) all fail with
> `no such column: is_deleted`. Declare `is_deleted = IntegerField(default=0)`.

## Pagination

`find()`, `all()`, `where()`, and `select()` accept `limit` and `offset`:

```python
users = User.all(limit=20, offset=40)   # page 3 at 20/page
```

For a paginated UI that also needs the total, use `where(..., with_count=True)` — it returns a
`(list, total)` tuple and runs the count in the same call:

```python
page, total = User.where("is_active = ?", [1], limit=20, offset=40, with_count=True)
return response({
    "data": [u.to_dict() for u in page],
    "total": total,
    "page": 3,
    "per_page": 20,
})
```

Models with `auto_crud = True` return this paginated envelope from their generated list route
automatically.

## DatabaseResult Methods

`db.fetch()` returns a `DatabaseResult` (not a list), which carries convenience methods:

| Method | Description |
|--------|-------------|
| `size()` | Record count |
| `to_array()` | Convert to a list of dicts |
| `to_json()` | Convert to a JSON string |
| `to_csv()` | Convert to a CSV string |

```python
results = db.fetch("SELECT * FROM users")
results.size()       # 42
results.to_array()   # [{"id": 1, "name": "Alice"}, ...]
results.to_json()    # '[{"id": 1, "name": "Alice"}, ...]'
results.to_csv()     # 'id,name\n1,Alice\n...'
```

> **`to_array()` / `to_json()` / `to_csv()` are on the `DatabaseResult` from `db.fetch()` only.**
> The ORM methods `Model.all()` / `Model.where()` / `Model.select()` return a plain list of
> model instances — a list has no `.to_array()`. To serialize ORM results, use a comprehension:
> `[m.to_dict() for m in Note.all()]`. (Chaining `Note.all().to_array()` raises
> `'list' object has no attribute 'to_array'` — a common, boot-time failure.)

## QueryBuilder — Fluent Queries with JOINs

Use `QueryBuilder` for complex queries (JOINs, aggregates, GROUP BY) instead of raw SQL.
Prefer QueryBuilder over `db.fetch()` for maintainability.

```python
from tina4_python.query_builder import QueryBuilder

# Simple query
users = QueryBuilder.from_table("users") \
    .select("id", "name", "email") \
    .where("is_active = ?", [1]) \
    .order_by("name ASC") \
    .limit(10) \
    .get()                     # -> DatabaseResult

# JOINs
orders = QueryBuilder.from_table("orders o") \
    .select("o.*", "c.name as customer_name") \
    .join("customers c", "o.customer_id = c.id") \
    .where("o.status = ?", ["pending"]) \
    .order_by("o.created_at DESC") \
    .limit(20) \
    .get()

# LEFT JOIN
products = QueryBuilder.from_table("products p") \
    .select("p.*", "c.name as category_name") \
    .left_join("categories c", "p.category_id = c.id") \
    .where("p.is_active = ?", [1]) \
    .get()

# Aggregates
total = QueryBuilder.from_table("orders") \
    .select("coalesce(sum(total), 0) as total") \
    .where("status != ?", ["cancelled"]) \
    .first()["total"]          # -> single row dict

# COUNT
count = QueryBuilder.from_table("users") \
    .where("is_active = ?", [1]) \
    .count()                   # -> int

# GROUP BY + HAVING
stats = QueryBuilder.from_table("orders o") \
    .select("c.name", "count(*) as order_count") \
    .join("customers c", "o.customer_id = c.id") \
    .group_by("c.name") \
    .having("count(*) > ?", [5]) \
    .get()

# From an ORM model (inherits the model's DB connection)
results = User.query() \
    .where("age > ?", [18]) \
    .order_by("name") \
    .get()

# Check existence
exists = QueryBuilder.from_table("users") \
    .where("email = ?", ["alice@example.com"]) \
    .exists()                  # -> bool
```

> QueryBuilder's start method is `from_table()` in Python (the bare `from()` would clash with the
> `from` keyword).

### QueryBuilder Methods

| Method | Description |
|--------|-------------|
| `from_table(table)` | Start a query |
| `select(*cols)` | Set columns to select |
| `where(cond, params)` | AND condition |
| `or_where(cond, params)` | OR condition |
| `join(table, on)` | INNER JOIN |
| `left_join(table, on)` | LEFT JOIN |
| `group_by(col)` | GROUP BY |
| `having(expr, params)` | HAVING clause |
| `order_by(expr)` | ORDER BY |
| `limit(n, offset)` | LIMIT + optional OFFSET |
| `get()` | Execute → DatabaseResult |
| `first()` | Execute → single row dict or None |
| `count()` | Execute → int |
| `exists()` | Execute → bool |
| `to_sql()` | Build SQL string without executing |
| `to_mongo()` | Convert to a MongoDB query document |

## Raw SQL

For queries that can't be expressed with the ORM or QueryBuilder, use `db.fetch()` directly:

```python
from tina4_python.database import Database

db = Database("sqlite:data/app.db")
results = db.fetch("SELECT * FROM users WHERE id = ?", [1])
```

## Database Connection Strings

Set in `.env` as `TINA4_DATABASE_URL`:

```
sqlite:data/app.db
postgresql://user:password@localhost:5432/mydb
mysql://user:password@localhost:3306/mydb
mssql://user:password@localhost:1433/mydb
firebird://user:password@localhost:3050/mydb
mongodb://user:password@localhost:27017/mydb
```

> **SQLite URLs: use `sqlite:data/app.db` (scheme-only) or the URL form `sqlite:///data/app.db`
> (three slashes).** Do **not** write `sqlite://data/app.db` (two slashes) — `urlparse` reads
> `data` as the host and drops it, so you end up pointing at `app.db` in the wrong place.

```python
from tina4_python.database import Database

db = Database.from_env()          # reads TINA4_DATABASE_URL
db = Database("sqlite:data/app.db")  # or an explicit URL
```

## Migrations

```bash
tina4 migrate:create "create users table"   # creates an SQL file in migrations/ (project root)
tina4 migrate                                # runs pending migrations
```

> Migrations live in **`migrations/`** at the project root — **not** `src/migrations/`.
> That is the folder the CLI scaffolds and both `tina4 migrate` and the server's
> startup auto-migrate read from.

Migration files are versioned SQL. Write standard SQL:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Seeding

```bash
tina4 seed:create "initial users"   # creates a seed file
tina4 seed                           # runs all seeds
```

Quick seeding with fake data:

```python
from tina4_python.seeder import FakeData, seed_orm

fake = FakeData()
fake.name()     # "Alice Johnson"
fake.email()    # "alice.johnson@example.com"

seed_orm(User, count=50)   # bulk-seed rows from the model's field types
```

## Auto-CRUD

Set `auto_crud = True` on an ORM model — Tina4 auto-registers a full
list/create/read/update/delete route set for it, no handler to write:

```python
from tina4_python import ORM, IntegerField, StringField

class User(ORM):
    auto_crud = True          # registers CRUD routes for this model on startup
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
```

## ORM Lifecycle & Footguns

The write path has a deliberate but **inconsistent** failure contract: some calls
fail *soft* (return `False`), some fail *loud* (raise). Getting this wrong is the
single biggest source of wasted debugging on Tina4. Each item below is **what bites
→ the safe idiom → what breaks.** All verified against the framework source
(`tina4_python/orm/model.py`, `database/connection.py`); the boot-gate
`tests/test_orm_footguns_doc.py` pins every one.

### The write path fails *soft* — `save()` / `create()` never raise

`save()` returns `self` on success and **`False`** on *any* failure (validation OR a
driver error). It **never raises** and never returns `None`. The real cause is
recorded on `model.last_error` / `model.get_error()` (mirroring `db.get_error()`), so
a swallowed failure is always recoverable. `create()` = construct + `save()`; when the
save fails it returns `False` (not a half-saved instance).

```python
# SAFE — check the return, surface the cause
user = User({"name": "Alice", "email": "a@x.com"})
if not user.save():                       # False on failure — NOT an exception
    return response({"error": user.get_error()}, 422)   # e.g. "Field 'name' is required"
```

* **Breaks:** `try: user.save() except: ...` — the `except` never fires, so a failed
  write looks like success. Testing `if user.save() is None` is also wrong (it's `False`).
  `model.py:327` (`save`), `model.py:521` (`create`).

### No auto table-create — `save()` into a missing table returns `False`

Defining a model does **not** create its table. The first `save()` into a table that
doesn't exist hits `no such table` in the driver, which `save()` catches → returns
`False` with the cause on `last_error`. Nothing tells you to create the table.

```python
# SAFE — create the table (dev) or run a migration (prod) before the first write
User.create_table()          # idempotent: CREATE TABLE IF NOT EXISTS from the fields
User({"name": "Alice"}).save()
```

* **Breaks:** relying on `save()` to bootstrap the schema — it returns `False`
  silently and no row lands. Note `create_table()` builds DDL from **declared fields
  only** (it injects nothing — see soft-delete's `is_deleted`). `model.py:786`.

### `delete()` / `restore()` DO raise — the asymmetry

Unlike `save()`, the delete family fails **loud**: `delete()` / `force_delete()` raise
`ValueError` when there's no primary-key value (and re-raise any driver error);
`restore()` raises `RuntimeError` on a model without `soft_delete`. Same framework,
opposite contract.

```python
# SAFE — guard the preconditions; wrap in try/except if the row may be gone
user = User.find_by_id(uid)
if user:
    user.delete()            # raises if user.id is None or the DB write fails
```

* **Breaks:** `Model(...).delete()` on an unsaved instance (`id is None`) → `ValueError`,
  not `False`. `model.py:453` (`delete`), `:497` (`restore`), `:477` (`force_delete`).

### Hydration coerces types but never re-enforces business constraints

Every read path — `find`/`all`/`where`/`select`/`load()`, and building a model
directly from a dict/JSON string (`__init__` → `_populate`, `model.py:286`) — calls
`field.coerce()` (`fields.py`), NOT `field.validate()`. `coerce()` runs the SAME type
coercion as the write path (a string → `datetime`, `int` 0/1 → `bool`, a JSON
string/bytes → a native `dict`/`list`) but never re-enforces `required`/`length`/
`range`/`regex`/`choices`/a custom validator — those are write-path-only rules
(feature 19, `ORM.validate()` → `field.validate_value()`, called by `save()`). A row
already in the table always hydrates, even if it violates a constraint, or one was
TIGHTENED after the row was written — a single non-conforming row (or cell) no longer
aborts the whole `select()`.

```python
# A stored row that no longer satisfies `role`'s choices still hydrates — it does
# NOT raise and does NOT abort the surrounding select().
user = User.find(42)          # role="superadmin", but choices=["admin","user"] now
user.role                     # "superadmin" — read back as-is, no raise

# Building straight from untrusted input is likewise safe — it no longer turns a
# bad request body into an unhandled 500 (the old constructor-vs-save() asymmetry
# this section used to document is gone: both paths are now non-raising for a
# constraint violation).
user = User(request.body)     # a missing required field / bad choice does NOT raise
if not user.save():           # the WRITE-path gate (ORM.validate()) still rejects it
    return response({"error": user.get_error()}, 422)
```

* **What still raises:** a genuinely un-coercible type — `IntegerField` handed
  `"not_a_number"`, a `JSONField` handed unparsable JSON text — still raises
  `ValueError` (that's type coercion failing, not a business rule). A non-dict,
  non-JSON-string positional arg to the constructor still raises `TypeError`
  (`model.py:256`).
* **What changed:** `save()` remains the ONLY place `required`/`length`/`range`/
  `regex`/`choices` are enforced — hydration and plain construction never enforce
  them. `Model(None)` / `Model()` were always safe (defaults only); now a dict/JSON
  carrying a *bad value* is safe too — only a value that cannot be TYPE-coerced still
  raises.

### Bind a database before any ORM or QueryBuilder call

Every ORM query and `QueryBuilder` needs a bound connection. Resolution order
(`model.py:281`): `cls._db` → the global set by `bind_database(db)` → auto-discovery
from `TINA4_DATABASE_URL`. If none resolves, the call raises `RuntimeError:
"No database bound..."`.

```python
# SAFE — set TINA4_DATABASE_URL in .env (auto-discovered) …
#   sqlite:data/app.db            (scheme-only)  or  sqlite:///data/app.db  (URL form)
# … or bind explicitly at boot:
from tina4_python.orm import bind_database
from tina4_python.database import Database
bind_database(Database("sqlite:data/app.db"))
```

* **Breaks:** running an ORM query in a script/worker that never set
  `TINA4_DATABASE_URL` or called `bind_database()` → `RuntimeError`. (Also: write
  `sqlite:data/app.db` or `sqlite:///data/app.db`, never `sqlite://data/app.db` — two
  slashes makes `urlparse` read `data` as the host and drop it.)

### `db.execute()` raises — it does not return `False`

Raw writes via `db.execute()` fail **loud**: on a driver error they **raise** (and set
`db.get_error()`); they do **not** return `False`. (The ORM's `save()` wraps this and
converts it to `False` — but a *direct* `db.execute()` propagates.)

```python
# SAFE — wrap writes you expect might fail; don't test the return value
try:
    db.execute("INSERT INTO audit (msg) VALUES (?)", ["ok"])
    db.commit()
except Exception:
    return response({"error": db.get_error()}, 500)
```

* **Breaks:** `if not db.execute(sql): ...` — a successful simple write returns `True`,
  and a *failed* one raises rather than returning a falsy value, so the branch never
  runs. `connection.py:511`.

### Auto-migrate is fail-soft and server-only

On `tina4 serve`, the server applies pending SQL migrations from `migrations/` at boot
(`server.py:2320`). It is **fail-soft**: a bad migration is logged loud and **the
service still starts** (a broken migration must not take the backend down). The
explicit **`tina4 migrate` CLI stays fail-fast** (non-zero exit for CI). Disable boot
migration with `TINA4_AUTO_MIGRATE=false` (recommended for multi-instance prod, where
concurrent first-apply can race).

* **Breaks:** assuming a green server boot means migrations applied — check the logs, or
  gate deploys on `tina4 migrate` (which does exit non-zero).

### No default ordering — paginate with a unique tiebreaker

`all()` / `where()` / `find()` apply **no `ORDER BY` unless you pass `order_by`**
(`model.py:636`). Without one, row order is engine-defined (SQLite rowid, unspecified on
Postgres), and `limit`/`offset` pages can repeat or skip rows. Ordering by a non-unique
column (e.g. `created_at`) has the same problem on ties.

```python
# SAFE — always order by a UNIQUE tiebreaker for stable pagination
page = User.where("is_active = ?", [1], limit=20, offset=40,
                  order_by="created_at DESC, id DESC")
```

* **Breaks:** `User.all(limit=20, offset=20)` with no `order_by`, or `order_by="created_at DESC"`
  alone — two rows with the same timestamp can land on two different pages (or neither).

### Framework gotchas (auth, routing, templates, background work)

These bite outside the ORM but hit the same agent-build loop. Verified against source.

* **N1 — Auth / unexpected 401 (security).** An unexpected 401 means **the caller needs
  a token**, not that the route should be opened. `@noauth()` is a **last resort** for
  genuinely public endpoints only. See **`auth-and-services.md` → "Auth footguns"** for
  the full treatment (import path, the swagger `@security()` docs-only trap, and why you
  must never blanket `@noauth()` to silence 401s).

* **N2 — Decorator order.** The route decorator (`@get`/`@post`/…) must be **innermost**
  (closest to `def`); meta decorators (`@noauth`/`@secured`/`@description`/`@tags`) go
  **above** it. Wrong order crashes at registration.

  ```python
  @noauth()                 # meta on top
  @description("Create a user")
  @post("/users")           # route decorator innermost — closest to def
  async def create_user(request, response):
      ...
  ```

* **N3 — Postgres needs an explicit commit for writes.** The psycopg2 connection runs
  with `autocommit = False` (`database/postgres.py:266`), so a raw write is only durable
  once committed. The framework's adapter auto-commits a **standalone** `db.execute()`
  write when `TINA4_AUTOCOMMIT=true` (the default), but a write made **inside
  `db.start_transaction()`** — or with `TINA4_AUTOCOMMIT=false` — needs an explicit
  `db.commit()` or it rolls back and the row never lands. (The ORM's `save()` already
  wraps start_transaction + commit.)

* **N4 — Frond templates (`src/templates/`, engine is Frond, not real Jinja2).**
  Unescape with `{{ x|raw }}` **or** `{{ x|safe }}` (both work). Concatenate with `~`,
  **not `+`**: `{{ "hi " ~ name }}` — `+` coerces to numbers, and on strings that fails
  and Frond **silently renders nothing** (empty, no error). Live regions raise at render
  if malformed: `{% live "x" poll 5 %}` (poll needs seconds), `{% live "x" ws "/ws/x" %}`
  (ws needs a path), and a `src "..."` must be a **same-origin path** (an absolute
  `http(s)://` URL raises). Note Frond accepts **both** `{% elif %}` and `{% elseif %}`,
  and `{{ x|e }}` / `{{ x|escape }}` HTML-escape and ignore any extra args (they do
  **not** raise) — so pure-Jinja2 advice ("`elif` not `elseif`", "`|e` takes no args")
  does **not** apply here. (`frond/engine.py`; full syntax in `templates-and-frontend.md`.)

* **N5 — `DatabaseResult` is not a list.** `db.fetch()` returns a `DatabaseResult`; the
  rows live on **`.records`** (a `list[dict]`), accessed by key: `result.records[0]["name"]`,
  never `.name`. The result object is iterable/indexable/`len()`-able for convenience,
  but a *list* (from ORM `all()`/`where()`) has **no** `.to_array()`/`.to_json()` — those
  are `DatabaseResult` methods. (`database/adapter.py:11`.)

* **N6 — Periodic work uses `background`, not threads.** Register recurring work with
  `background(fn, interval)` from `tina4_python.core.server` (runs cooperatively in the
  server event loop with clean shutdown) — never spin a raw `threading.Thread`.
  (`core/server.py:39`.)

  ```python
  from tina4_python.core.server import background
  background(sync_inbox, interval=60)   # every 60s
  ```

* **N7 — Route param types are a fixed set.** A typed path param (`/users/{id:int}`)
  must use a known type name, or route registration **raises `ValueError`**. Valid
  types: **`string`, `int`, `integer`, `float`, `number`, `alpha`, `alnum`, `slug`,
  `uuid`, `path`** (`int`/`integer` cast to `int`, `float`/`number` to `float`; the rest
  stay `str`). `{id:inetger}` (typo) crashes at boot. (`core/router.py:470`.)

## When to reach for `tina4_context`

`tina4_context(instruction, language="python")` (server `tina4-coder`) retrieves the
authoritative, version-current Tina4 API + real examples from the live corpus. It is a
**grounding** tool, not a code generator — write the code yourself from what it returns.
Use it as a ladder, not a reflex:

1. **Skill covers it → write from the skill.** These reference files are the source of
   truth for the common surface (models, routes, CRUD, templates, auth, queues). Don't
   call `tina4_context` for something documented here — you'll just spend tokens.
2. **Uncovered / current-tree API / a surprise → then call `tina4_context`.** Reach for
   it when the skill doesn't cover the case, you need an API the installed version added
   recently, or the framework did something the doc didn't predict (a footgun you hit).
   Pass `language="python"` explicitly — auto-detection mis-fires on ambiguous text.
3. **Write it yourself, then verify against the live API.** Confirm any method/field/
   route shape against the running project's MCP index — `api_method("Database", "fetch")`,
   `api_class("ORM")`, `api_search("...")` at `/__dev/mcp` (needs `tina4 serve` +
   `TINA4_DEBUG=true`). **The framework code is the final authority.** Do **not** use
   `tina4_code` (the self-hosted generator) — the value is the retrieval, not a small model. It failed a boot-and-verify gate that Claude grounded with `tina4_context` passed.

## Batteries included — zero dependencies

`pyproject.toml` declares **`dependencies = []`** — Tina4-Python's core has *zero*
runtime dependencies (only optional DB drivers are extras: `[postgres]`, `[mysql]`,
`[mssql]`, `[firebird]`). Before you `pip install` anything, check whether it's already
in the box. **Need → Tina4 built-in (verified import/idiom) — don't add the dep:**

| Need | Tina4 built-in — don't `pip install …` |
|------|----------------------------------------|
| Auth / JWT / password hashing | `from tina4_python.auth import Auth, get_token` — `Auth.hash_password/check_password/valid_token/get_payload`, `get_token(payload)` *(don't add `pyjwt`, `passlib`)* |
| ORM / models | `from tina4_python import ORM, IntegerField, StringField, …, bind_database` *(don't add `sqlalchemy`, `peewee`)* |
| Fluent queries / JOINs | `from tina4_python.query_builder import QueryBuilder` — `QueryBuilder.from_table(...)` |
| DB drivers (multi-engine) | `from tina4_python.database import Database` — sqlite built in; postgres/mysql/mssql/firebird/mongodb via extras |
| Migrations | `tina4 migrate:create` / `tina4 migrate` CLI (or `from tina4_python.migration.runner import Migration, create_migration`) *(don't add `alembic`)* |
| Templating | `from tina4_python import Frond` (Frond engine) + `response.render("page.twig", {...})`; templates in `src/templates/` *(don't add `jinja2`, `markupsafe`)* |
| SCSS → CSS | drop `.scss` in `src/scss/` — auto-compiled to `src/public/css/` on `tina4 serve` *(don't add `libsass`, `dart-sass`)* |
| Input validation | `from tina4_python.validator import Validator` |
| Response / JSON serialization | `response(data)` — dicts/lists → JSON; an ORM model is serialized via its `to_dict()`; also `response.json(...)`, `response.render(...)`, `response.redirect(...)` |
| Background queue | `from tina4_python import Queue` — `Queue(topic=...).push({...})` / `.consume()` *(don't add `celery`, `rq`)* |
| Email | `from tina4_python import Messenger` — `Messenger().send(to=…, subject=…, body=…, html=True)` |
| Sessions | `request.session.set/get/clear` (backends: file/redis/valkey/mongodb/database via `TINA4_SESSION_BACKEND`) |
| Caching | `from tina4_python.cache import ResponseCache, cache_stats, clear_cache` + `{% cache "k" 60 %}` template blocks (backends: memory/redis/file/valkey/memcached/mongo/database) *(don't add `flask-caching`)* |
| OpenAPI / Swagger docs | `from tina4_python.swagger import description, tags, example, response_schema, security` — docs metadata only (see N1) |
| WebSockets | `from tina4_python.core.router import websocket` — `@websocket("/ws/…")`; live regions via Frond `{% live %}` |
| Real-time (WebRTC signalling, presence) | `from tina4_python import realtime, MeshBackend` (+ `LocalStorage`/`S3Storage` from `tina4_python.realtime.storage`) |
| GraphQL API from models | `from tina4_python import GraphQL` — `GraphQL().auto_register(User, Post)` + `GraphQL.set_default(gql)` → `/graphql` *(don't add `graphene`, `strawberry`)* |
| SOAP / WSDL | `from tina4_python import WSDL, wsdl_operation` |
| i18n / localization | `from tina4_python.i18n import I18n` — `.translate(key, params)` / `.t(key, **kwargs)`; JSON in `src/locales/` |
| .env loading + typed env | `from tina4_python.dotenv import load_env`; `from tina4_python import Env` (typed getters) *(don't add `python-dotenv`)* |
| Document store (Mongo-style on SQLite) | `from tina4_python.docstore import ObjectId, …` — Mongo-compatible collections (`SqliteDatabase`/`SqliteCollection`) |
| Dependency injection | `from tina4_python import Container` |
| Fake data / seeding | `from tina4_python.seeder import FakeData, seed_orm` — `seed_orm(User, count=50)` *(don't add `faker`)* |
| In-process HTTP test client | `from tina4_python.test_client import TestClient` — drives routes without a live server *(don't add `httpx`/`requests` for tests)* |
| Events | `from tina4_python import on, emit, once, off` |
| **Outbound HTTP calls** | `from tina4_python import Api` — `Api(base_url).get(...)/.post(...)`, built on stdlib `urllib` *(don't add `requests`, `httpx`)* |
