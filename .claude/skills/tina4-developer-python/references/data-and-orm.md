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
    soft_delete = True   # uses the is_deleted column (INTEGER, 0/1)
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()

article = Article.find_by_id(1)
article.delete()          # sets is_deleted = 1 (soft)
article.restore()         # sets is_deleted = 0
article.force_delete()    # actually removes the row

# Default queries exclude soft-deleted records:
articles = Article.all()
# Include deleted:
articles = Article.with_trashed()
```

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
tina4 migrate:create "create users table"   # creates an SQL file in src/migrations/
tina4 migrate                                # runs pending migrations
```

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
