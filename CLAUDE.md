# Tina4 Python

Version 3.13.57 — Lightweight Python web framework. See https://tina4.com for full documentation.

## Build & Test

- Package manager: `uv`
- Python: >=3.12
- Install: `uv sync`
- Run all tests: `.venv/bin/python -m pytest tests/`
- Run single test: `.venv/bin/python -m pytest tests/test_file.py::TestClass::test_method`
- Coverage: `.venv/bin/python -m pytest tests/ --cov=tina4_python`
- Start server: `tina4 serve` (development) or `tina4 serve --production` (production)
- CLI: `tina4python` (entry point defined in pyproject.toml)

**IMPORTANT:** Never run `python app.py` directly. Always use `tina4 serve`. The `tina4` Rust CLI handles SCSS compilation, file watching, and server management. To bypass this requirement (e.g. Docker), set `TINA4_OVERRIDE_CLIENT=true` in `.env`.

## Code Principles

- **DRY** — Never duplicate logic. Centralise shared code in `src/app/` helpers, Twig filters, or base classes. If a pattern exists anywhere, use it everywhere
- **Separation of Concerns** — One route resource per file in `src/routes/`, one ORM model per file in `src/orm/`, shared helpers in `src/app/`
- **No inline styles** on any element — use tina4-css classes (e.g. `.form-input`, `.form-control`) or SCSS in `src/scss/`
- **No hardcoded hex colors** — always use CSS variables (`var(--text)`, `var(--border)`, `var(--primary)`, etc.) or SCSS variables
- **Shared CSS only** — Never define UI patterns in local `<style>` blocks. All shared styles go in a project SCSS file (e.g. `src/scss/default.scss`)
- **Use built-in features** — Never reinvent what the framework provides (Queue, Api, Auth, ORM, etc.)
- **Template inheritance** — Every page extends `base.twig`, reusable UI in `partials/`
- **Migrations for all schema changes** — Never execute DDL outside migration files
- **Constants file** — No magic strings or numbers in routes. Put constants in `src/app/constants.py`
- **Service layer pattern** — For complex business logic, create `class FooService` in `src/app/` with a module-level singleton. Routes should be thin wrappers
- **Parity across all frameworks** — Every new feature, fix, or optimization must be implemented with equivalent logic AND tests in all 4 Tina4 frameworks (Python, PHP, Ruby, Node.js). Never ship to one without shipping to all.
- **NO mock testing. Mocks are not acceptable in any circumstances.** A test double (mock, stub, fake, spy, monkeypatch, or any in-test object standing in for a real collaborator) may never substitute for a real dependency, under any justification. There is no "supplement" exception and no "hard to reproduce" exception. Any test that touches a dependency (a DB engine, MongoDB, Redis/Valkey/Memcached, RabbitMQ/Kafka, an HTTP/SMTP service, the filesystem, a socket) must exercise the REAL service; if a failure mode is hard to trigger, reproduce it for real, never simulate it. "Verified"/"green" requires a real run; a passing mock test is not verification. CI provisions the services; use them and add any that is missing. The only tests that need no live dependency are pure functions with no dependency and no double; that is not a mock test. (The Node MongoDB queue re-delivered every completed job for two releases because its queue tests were mock-based and never ran against a real Mongo.)
- **Routes return `response()`** — Always use `response()` not `response.json()`. This is the Tina4 convention
- **Error handling in routes** — Wrap route logic in `try/except`, log with `Debug.error()`, return `response()` with appropriate status
- **All links and references** should point to https://tina4.com
- **Push to staging only** — Never push to production without explicit approval
- Linting: `ruff`
- Async mode: `asyncio_mode = auto` (pytest-asyncio)

### Firebird-Specific Rules

When using Firebird as the database engine:

- **No triggers, no foreign keys** in migrations — use generators for auto-increment IDs
- **ID generation** — Use generators: `generate_next_id(db, "GEN_FOO_ID", "FOO")` pattern
- **Pagination** — Use `ROWS {skip+1} TO {skip+per_page}` syntax (not LIMIT/OFFSET)
- **BLOB handling** — `fetch()` and `fetch_one()` auto-convert memoryview BLOB columns to bytes (PostgreSQL, Firebird). Values are raw bytes, not base64
- **No `TEXT` type** — Use `VARCHAR(n)` or `BLOB SUB_TYPE TEXT`
- **No `REAL`/`FLOAT`** — Use `DOUBLE PRECISION`
- **No `IF NOT EXISTS`** for `ALTER TABLE ADD` — framework handles idempotency automatically

## Development Mode (DevReload)

Set `TINA4_DEBUG=true` in `.env` to enable:

- **Live-reload** — Browser auto-refreshes when `.py`, `.twig`, `.html`, `.js` files change. For `.py` files, the change is also re-imported in-process: new files register and **changed existing files hot-reload their handlers live** (mtime-tracked, `src/` only), so the refreshed page serves fresh code without a server restart
- **CSS hot-reload** — SCSS/CSS changes refresh stylesheets without full page reload
- **SCSS auto-compile** — `.scss` files in `src/scss/` compiled to `src/public/css/` on save
- **Error overlay** — Runtime errors display a rich, syntax-highlighted overlay in the browser

### How DevReload works

The `tina4` Rust CLI is the sole file watcher for the Tina4 stack — there is no framework-side watcher (removed in 3.11.x). The flow is:

1. Rust CLI (`tina4 serve`) watches `src/`, `migrations/`, `.env`. Noise is filtered (Access/Metadata events, `__pycache__`, `.git`, `node_modules`, `logs`, `.log`/`.db*`/`.swp`/`.pyc` files) and a real mtime check defeats overlayfs spurious events.
2. On a real change, the CLI POSTs `/__dev/api/reload` to the running framework.
3. The framework re-runs auto-discover (registers new `src/` files and re-imports changed ones in-process — `src/` modules only, framework modules never), bumps its in-memory reload counter, then (a) broadcasts `{type: 'reload'}` over WebSocket at `/__dev_reload`, and (b) exposes the counter at `GET /__dev/api/mtime` for the polling fallback.
4. The browser's dev toolbar JS listens on the WS (primary) and polls `/__dev/api/mtime` every 3s (fallback). On a change it reloads the page, or swaps the stylesheet if the change was CSS.

No configuration needed. If you're running without the Rust CLI (e.g. Docker), set `TINA4_OVERRIDE_CLIENT=true` — in that mode there is no automatic reload.

## Project Structure

```
tina4_python/          # Core framework package
  HtmlElement.py, Testing.py ...
  core/                # HTTP engine (router, server, request, response, middleware)
    router.py          # Route registration (get, post, put, delete, noauth, secured, cached, template)
    server.py          # Server bootstrap (run, resolve_config)
    request.py         # Request object
    response.py        # Response object
    middleware.py       # CorsMiddleware, RateLimiter
    cache.py           # Core cache utilities
    constants.py       # HTTP constants
    events.py          # Event system (on, emit, once, off)
  auth/               # JWT auth, password hashing (Auth class)
  database/            # Multi-driver database abstraction
    connection.py      # Database class (URL-based connection)
    adapter.py         # DatabaseAdapter, DatabaseResult, SQLTranslator
    sqlite.py, postgres.py, mysql.py, mssql.py, firebird.py, odbc.py
  orm/                 # Active Record ORM (ORM, Field, bind_database)
    model.py           # ORM base class
    fields.py          # IntegerField, StringField, etc.
  frond/               # Template engine (Frond — replaces Template)
    engine.py          # Frond class (render, add_filter, add_global, add_test)
  api/                 # HTTP client (Api class — zero deps)
  queue/               # Database-backed job queue (Queue, Job)
  swagger/             # OpenAPI 3.0.3 generator (Swagger, description, tags, example)
  migration/           # SQL-file migrations (migrate, create_migration, rollback)
    runner.py          # Migration runner
  session/             # Pluggable sessions (Session, FileSessionHandler, DatabaseSessionHandler)
  websocket/           # RFC 6455 WebSocket server (WebSocketServer, WebSocketConnection)
  graphql/             # Zero-dep GraphQL engine (GraphQL, Schema)
  wsdl/                # SOAP 1.1 / WSDL server (WSDL, wsdl_operation)
  crud/                # Auto-CRUD REST endpoint generator (AutoCrud)
  seeder/              # Fake data generation (FakeData, seed_table)
  i18n/                # Internationalization (I18n class)
  ai/                  # AI coding assistant detection & context
  cache/               # In-memory response cache middleware
  container/           # Lightweight dependency injection container
  debug/               # Structured logging (Log) + error overlay
    error_overlay.py   # Rich HTML error overlay for dev mode
  service/             # Service layer utilities
  messenger/           # Messaging integration
  dotenv/              # .env file loader
  cli/                 # CLI commands
  templates/           # Built-in framework templates (Twig)
  public/              # Built-in static assets
  scss/                # Built-in SCSS
src/                   # User application code
  routes/              # Auto-discovered route files (one per resource)
  orm/                 # ORM model definitions (one per model)
  app/                 # Shared helpers and service classes
  templates/           # User Twig templates
  scss/                # User SCSS → auto-compiled to src/public/css/
  public/              # User static assets served at /
  seeds/               # Seeder files (auto-discovered)
tests/                 # pytest test files (27 test modules)
benchmarks/            # Performance benchmarks
migrations/            # Database migration SQL files
```

## Key Method Stubs

### Router — Route registration (decorators)

```python
from tina4_python.core.router import get, post, put, patch, delete, any_method, noauth, secured, cached, middleware, template

@get(path: str | list)           # Public by default
@post(path: str | list)          # Auth required by default
@put(path: str | list)           # Auth required by default
@patch(path: str | list)         # Auth required by default
@delete(path: str | list)        # Auth required by default
@any_method(path: str | list)    # All methods
# Wildcard routes: @get("/api/files/*")  — * matches all remaining path segments
@noauth()                        # Make write route public
@secured()                       # Protect a GET route
@cached(max_age: int = 60)
@middleware(middleware_class, specific_methods: list | None = None)
@template(twig_file: str)        # Auto-render dict return through Frond template
```

**Decorator order** (outermost → innermost): `@noauth`/`@secured` → `@description`/`@tags` → `@get`/`@post`

### Database — Multi-driver abstraction

```python
from tina4_python.database import Database

db = Database(url: str, username="", password="")
# Connection pooling: Database("sqlite:///app.db", pool=4)  # 4 round-robin connections

db.fetch(sql, params=None, limit=10, offset=0) -> DatabaseResult  # records, count, limit, offset
db.fetch_one(sql, params=None) -> dict | None
db.execute(sql, params=None) -> True | DatabaseResult  # True for writes, DatabaseResult for RETURNING/CALL/EXEC; RAISES on SQL error (never returns False — cause on get_error()). Wrap in try/except, don't test the return.
db.execute_many(sql, params=None) -> DatabaseResult
db.insert(table_name, data: dict | list) -> DatabaseResult
db.update(table_name, data: dict) -> DatabaseResult
db.delete(table_name, data: dict) -> DatabaseResult
db.get_last_id() -> int | str | None  # Last insert ID from execute/insert
db.get_error() -> str | None          # Last execute() error message
db.start_transaction()
db.commit()
db.rollback()
db.table_exists(table_name) -> bool
db.get_tables() -> list[str]
db.get_columns(table_name) -> list[dict]
db.get_next_id(table, pk_column="id", generator_name=None) -> int  # Race-safe sequence
db.cache_stats() -> dict
db.cache_clear()
db.pool -> ConnectionPool | None  # Access connection pool (None if pooling disabled)
```

**`tina4_sequences` table** — Auto-created by `get_next_id()` on first use for SQLite, MySQL, and MSSQL. Stores the current sequence value per table. Do not modify this table manually.

### ORM — Active Record base class

```python
from tina4_python.orm import ORM, bind_database, Field, IntegerField, StringField, ForeignKeyField

class MyModel(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    # _db = "analytics"   # optional: bind this model to a named connection
    # ForeignKeyField(to=Other) auto-wires belongs_to on this class
    # AND has_many on the referenced class (default key: ClassName.lower() + "s")
    # author_id = ForeignKeyField(to=Author, related_name="posts")

# Instance methods
model = MyModel(data: dict | str = None, **kwargs)  # dict, JSON object string, or kwargs
# MyModel('{"id": 1, "name": "Alice"}')  -> parsed JSON object into one record
# Passing a list/array raises a clear TypeError (map over the list for many records)
model.save() -> self | False          # Returns self on success (fluent), False on failure
model.delete() -> None                # Soft-delete if enabled, else hard delete
model.force_delete() -> None          # Hard delete (bypasses soft-delete)
model.restore() -> None               # Restore soft-deleted record
model.load(sql, params=None, include=None) -> bool  # selectOne into self; True if found
model.validate() -> list[str]         # Validate fields; empty list = valid
model.to_dict(include=None) -> dict   # Convert to dict (optionally with relationships)
model.to_assoc(include=None) -> dict  # Alias for to_dict()
model.to_json(include=None) -> str    # Convert to JSON string
model.to_array() -> list              # Convert to flat list of values
model.to_list() -> list               # Alias for to_array()
model.to_object() -> dict             # Alias for to_dict()
model.has_one(related_class, foreign_key=None)    # Imperative relationship query
model.has_many(related_class, foreign_key=None)   # Imperative relationship query
model.belongs_to(related_class, foreign_key=None) # Imperative relationship query

# Class methods — also callable on instances: MyModel().all()
MyModel.find(pk_value, include=None) -> MyModel | None
MyModel.find_by_id(pk_value, include=None) -> MyModel | None
MyModel.find_or_fail(pk_value) -> MyModel          # Raises ValueError if not found
MyModel.exists(pk_value) -> bool                   # True if record with that PK exists
MyModel.create(data=None, **kwargs) -> MyModel     # Create + save in one call
MyModel.all(limit=100, offset=0, include=None) -> list[MyModel]
MyModel.select(sql, params=None, limit=20, offset=0, include=None) -> list[MyModel]
MyModel.select_one(sql, params=None, include=None) -> MyModel | None
MyModel.where(filter_sql, params=None, limit=20, offset=0, include=None) -> list[MyModel]
MyModel.with_trashed(filter_sql="1=1", params=None, limit=20, offset=0) -> list[MyModel]
MyModel.count(conditions=None, params=None) -> int
MyModel.create_table() -> bool
MyModel.query() -> QueryBuilder
MyModel.scope(name, filter_sql, params=None)  # Registers a reusable named method on the class
MyModel.cached(sql, params=None, ttl=60, limit=20, offset=0) -> list[MyModel]

bind_database(db: Database, name: str = None) -> None
```

**Database binding:**

- **`.env` default (no call needed)** — models auto-bind to `TINA4_DATABASE_URL` when set, so most apps need no binding call at all.
- **`bind_database(db)`** — override the default explicitly with a `Database` instance (assigns it to all ORM subclasses that don't pick a named connection).
- **`bind_database(db, name="analytics")` + `_db = "analytics"`** — register a named/secondary connection, then point a model at it by setting `_db = "analytics"` on the class. A missing named connection raises a clear error.

```python
bind_database(Database("sqlite:///app.db"))                          # override default
bind_database(Database("postgres://…/analytics", "u", "p"), name="analytics")  # named

class Visit(ORM):
    _db = "analytics"   # this model uses the analytics connection
```

Soft-delete: Set `soft_delete = True` on the model class. Uses the `is_deleted` column (INTEGER, 0/1). `delete()` sets `is_deleted = 1`, `force_delete()` removes the row, `restore()` sets `is_deleted = 0`. (There is no `deleted_at` column — the flag is `is_deleted`.)

### File Uploads

Multipart file uploads are available via `request.files` (dict keyed by field name). Each file is a dict:

```python
# request.files["avatar"] =>
{
    "filename": "photo.png",
    "type": "image/png",
    "content": b"...",       # raw bytes — NOT base64
    "size": 102400
}
```

```python
@post("/api/upload")
async def upload(request, response):
    file = request.files.get("avatar")
    if not file:
        return response.json({"error": "No file"}, 400)
    with open(f"src/public/uploads/{file['filename']}", "wb") as f:
        f.write(file["content"])  # raw bytes, write directly
    return response.json({"ok": True})
```

Max upload size: `TINA4_MAX_UPLOAD_SIZE` env var (default 10MB).

### Auth — JWT tokens and password hashing

```python
from tina4_python.auth import Auth, get_token, valid_token, get_payload

# expires_in is in MINUTES (default 60). Reads SECRET from env.
token = get_token({"user_id": 1}, expires_in=60)       # 60 minutes
payload = valid_token(token)                            # dict | None
payload = get_payload(token)                            # decode without verifying
Auth.hash_password("secret") -> str                     # PBKDF2-SHA256, 260000 iterations, $ delimiter
Auth.check_password("secret", hashed) -> bool           # timing-safe comparison
Auth.validate_api_key(provided, expected=None) -> bool  # reads TINA4_API_KEY from env
Auth.authenticate_request(headers) -> dict | None       # Bearer JWT, falls back to API key
```

### Session — Multi-backend session management

```python
from tina4_python.session import Session

session.start(session_id=None) -> str       # Returns session ID
session.get(key, default=None)              # Get value
session.set(key, value)                     # Set value
session.delete(key)                         # Remove key
session.has(key) -> bool                    # Check existence
session.all() -> dict                       # All data (excludes internals)
session.clear()                             # Wipe data
session.destroy()                           # Destroy session entirely
session.regenerate() -> str                 # New ID, returns it
session.flash(key, value=None)              # Dual-mode: set with value, get+remove without
session.get_flash(key, default=None)        # Explicit getter alias for flash()
session.save()                              # Persist to backend (lazy — called if dirty)
session.cookie_header(name="tina4_session") -> str  # Set-Cookie header value
session.gc()                                # Garbage collection
```

Backends: file (default), redis, valkey, mongodb, database. Set via `TINA4_SESSION_BACKEND` env var.

**Backend-failure policy (all 4 frameworks): log-loud + degrade.** If a backend (Redis/Valkey/Mongo/DB) becomes unreachable mid-request, the session layer logs an error and degrades rather than crashing the whole app or losing data silently: a read failure yields an empty session (the request still serves), and `save()` returns `False` (best-effort, dirty flag retained for retry) — both are logged via `Log.error`. A genuinely empty session (no data yet) is NOT an error and is never logged. Set `TINA4_SESSION_STRICT=true` to re-raise instead (the same escape hatch as the `strict` flag on events/seeding) when a failed persist should surface loudly. Call `session.regenerate()` right after a successful login or privilege change to defeat session fixation.

### DocStore — pymongo-style document store (zero-config SQLite fallback)

`get_collection(name)` returns a Mongo-style collection. When a Mongo URI is configured (and `pymongo` is installed) it is a real `pymongo` collection; otherwise it is a `SqliteCollection` backed by a local SQLite file using JSON1. The call sites are identical either way — only the backend differs — so you develop against a zero-dependency local store and switch to MongoDB in production by setting one env var.

```python
from tina4_python.docstore import get_collection, ObjectId, is_serverless

orders = get_collection("orders")
res = orders.insert_one({"customer_id": 1, "total": 9.99, "status": "new"})
orders.find_one({"_id": res.inserted_id})
orders.update_one({"_id": res.inserted_id}, {"$set": {"status": "shipped"}})
for doc in orders.find({"total": {"$gt": 5}}).sort("total", -1).limit(10):
    ...
orders.count_documents({"status": "shipped"})
is_serverless()   # True when running on the SQLite fallback
```

Filter operators: equality, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$ne`, `$exists`, `$regex`, implicit AND, `$or`, `$and`, and dotted nested keys (`addr.city`). Updates: `$set`, `$unset`, `$inc`, replace, upsert. Cursors: `sort`, `limit`, `skip`, projection. Values round-trip (datetime to/from ISO-8601, `ObjectId` to/from 24-hex) and stay queryable via `json_extract`. Non-goals: aggregation pipelines, `$elemMatch`, geo queries.

Selection and configuration:
- `TINA4_MONGO_URI` — app-wide Mongo URI. Falls back to `TINA4_SESSION_MONGO_URI`, then the legacy `TINA4_SESSION_MONGO_URL`. When one is set and the driver is present, `get_collection` returns a real Mongo collection.
- `TINA4_DOC_STORE_PATH` — SQLite file for the fallback store (default `data/tina4_docstore.db`).

### Request extras

```python
request.query -> dict      # Query string params only (separate from route params)
request.cookies -> dict    # Parsed from Cookie header
request.content_type -> str
response.stream(generator, content_type="text/event-stream")  # SSE/streaming response
```

**`response()` auto-serializes domain objects.** Return an ORM model, a list of models, or a `DatabaseResult` straight from a route — no manual `to_dict()` / `to_json()` needed. A single model becomes a JSON object; a list of models or a `DatabaseResult` becomes a JSON array. Plain dicts, lists and strings behave exactly as before (purely additive).

```python
return response(User.find(1))     # single model -> JSON object
return response(User.all())       # list of models -> JSON array
return response(db.fetch("SELECT * FROM users"))  # DatabaseResult -> JSON array
```

### QueryBuilder — Fluent query construction

Use `QueryBuilder` for complex queries with JOINs, aggregates, GROUP BY. Always prefer over raw `db.fetch()`.

```python
from tina4_python.query_builder import QueryBuilder

# JOINs
orders = QueryBuilder.from_table("orders o") \
    .select("o.*", "c.name as customer_name") \
    .join("customers c", "o.customer_id = c.id") \
    .where("o.status = ?", ["pending"]) \
    .order_by("o.created_at DESC") \
    .limit(20) \
    .get()                     # -> DatabaseResult

# LEFT JOIN
products = QueryBuilder.from_table("products p") \
    .select("p.*", "c.name as category_name") \
    .left_join("categories c", "p.category_id = c.id") \
    .get()

# Aggregates
total = QueryBuilder.from_table("orders") \
    .select("coalesce(sum(total), 0) as total") \
    .where("status != ?", ["cancelled"]) \
    .first()["total"]          # -> single row dict

# From ORM model
results = User.query().where("age > ?", [18]).order_by("name").get()

# Methods: from_table(), select(), where(), or_where(), join(), left_join(),
#          group_by(), having(), order_by(), limit(), get(), first(), count(),
#          exists(), to_sql(), to_mongo()
```

NoSQL support: `to_mongo()` generates MongoDB query documents from the same fluent API.

### Frond — Template engine (replaces Template)

```python
from tina4_python.frond import Frond

engine = Frond()
engine.render(template_or_file_name: str, data: dict = None) -> str
engine.render_string(source: str, data: dict = None) -> str
Frond.add_filter(name: str, func: callable)
Frond.add_global(name: str, value: any)
Frond.add_test(name: str, func: callable)
engine.sandbox(allowed_filters=["upper"], allowed_tags=["if"], allowed_vars=["x"])
```

- **SafeString**: Custom filters can return `SafeString(value)` to bypass auto-HTML-escaping.
- **Fragment caching**: `{% cache "key" 300 %}...{% endcache %}` -- caches rendered block content for TTL seconds.
- **Raw blocks**: `{% raw %}...{% endraw %}` -- output literal template syntax without parsing.
- **Sandbox mode**: Restrict template capabilities via `engine.sandbox(allowed_filters=, allowed_tags=, allowed_vars=)`.

### Seeder — Fake data generation

```python
from tina4_python.seeder import FakeData, seed_table

fake = FakeData(seed: int | None = None)
fake.name() -> str
fake.email() -> str
fake.phone() -> str
fake.sentence(words=8) -> str
fake.integer(min_val=0, max_val=10000) -> int
fake.decimal(min_val=0.0, max_val=1000.0, decimals=2) -> float
fake.date() -> str
fake.datetime_iso() -> str
fake.uuid() -> str
fake.url() -> str
fake.address() -> str
fake.paragraph() -> str
fake.text() -> str
fake.boolean() -> bool
fake.word() -> str

seed_table(db, table_name, count=10, field_map=None, overrides=None) -> int
```

### Api — External HTTP client

```python
from tina4_python.api import Api

api = Api(base_url="", auth_header="", ignore_ssl=False, timeout=30)
api.get(path="", params=None) -> dict
api.post(path="", body=None, content_type="application/json") -> dict
api.put(path="", body=None, content_type="application/json") -> dict
api.patch(path="", body=None, content_type="application/json") -> dict
api.delete(path="", body=None) -> dict
api.send(method="", path="", body=None, content_type="application/json") -> dict
api.add_headers(headers: dict)
api.set_basic_auth(username, password)
api.set_bearer_token(token)
# Returns: {"http_code": 200, "body": {...}, "headers": {...}, "error": None}
```

### Queue — Database-backed job queue

```python
from tina4_python.queue import Queue

queue = Queue(topic="tasks", max_retries=3)
# visibility_timeout (seconds): a popped job is reserved this long; if the
# consumer dies before complete()/fail() the next pop() reclaims it
# (at-least-once delivery). Default 300; env TINA4_QUEUE_VISIBILITY_TIMEOUT; <= 0 disables.
queue = Queue(topic="tasks", visibility_timeout=300)
queue.push(data: dict, priority=0, delay_seconds=0) -> int
queue.pop() -> Job | None
queue.size(status="pending") -> int
queue.purge(status="completed")
queue.retry_failed() -> int
queue.dead_letters() -> list[dict]
queue.produce(topic, data, priority=0, delay_seconds=0)  # Push to a specific topic
queue.consume(topic=None, job_id=None, poll_interval=1.0)   # Long-running generator; sleeps when empty. poll_interval=0 for single-pass drain.

# Job methods
job.complete()                  # Mark as completed
job.fail(error="")              # Mark as failed
job.reject(reason="")           # Alias for fail()
job.retry(delay_seconds=0)      # Re-queue with optional delay
```

### Migration

```python
from tina4_python.migration import migrate, create_migration, rollback

migrate(db)                              # Run all pending migrations
create_migration("add users table")      # Create new .sql file
rollback(db)                             # Rollback last batch
```

**Auto-run on startup (`TINA4_AUTO_MIGRATE`, default on).** When a `migrations/`
folder exists, `tina4 serve` applies pending migrations during boot — no manual
`tina4 migrate` step. It is **non-breaking**: a failed migration is logged
(`Log.error`) and the service still starts (a bad migration must never take the
backend down). Set `TINA4_AUTO_MIGRATE=false` to disable (e.g. multi-instance
production that migrates as a separate deploy step — concurrent first-apply can
race). The explicit `tina4 migrate` CLI is unaffected and stays **fail-fast**
(non-zero exit on failure) for CI.

### Events — Decoupled communication

```python
from tina4_python.core.events import on, emit, once, off, emit_async

# Register a listener (decorator)
@on("user.created")
def send_welcome_email(user):
    print(f"Welcome {user['name']}!")

# Register with priority (higher = runs first)
@on("user.created", priority=10)
def audit_signup(user):
    log_event("signup", user)

# Fire an event synchronously
results = emit("user.created", {"name": "Alice", "email": "alice@example.com"})

# One-shot listener (auto-removes after first fire)
@once("app.ready")
def on_ready():
    print("App started!")

# Async listeners
@on("order.placed")
async def process_order(order):
    await send_notification(order)

results = await emit_async("order.placed", order_data)

# Remove listeners
off("user.created", send_welcome_email)  # remove specific
off("user.created")                       # remove all for event
```

### Background Tasks — Periodic background work in the server event loop

Register callbacks that run periodically in the asyncio event loop. No threads, no separate processes — tasks run cooperatively alongside HTTP request handling.

```python
from tina4_python.core.server import background

# Process queue jobs every 2 seconds
queue = container.get("queue")
background(lambda: process_orders(queue), interval=2.0)

# Health check every 30 seconds
async def check_health():
    api = Api("https://api.example.com")
    result = api.get("/health")
    if result["error"]:
        Log.warning("Health check failed")

background(check_health, interval=30.0)
```

**Never use `threading.Thread` for periodic work.** Use `background()` instead — it integrates with the server lifecycle, handles errors gracefully, supports both sync and async callbacks, and cancels cleanly on shutdown.

```python
background(callback: callable, interval: float = 1.0) -> None
```

### AI Integration — AI assistant context scaffolding

Detect AI coding tools in a project and install framework-aware context files.

```python
from tina4_python.ai import detect_ai, install_context, status_report

# Detect which AI tools are present
tools = detect_ai()
# [{"name": "claude-code", "description": "Claude Code (Anthropic CLI)", "installed": True}, ...]

# Install context files for all detected tools
created_files = install_context()       # all known tools (default)
created_files = install_context(tools=["claude-code", "cursor"])  # specific tools

# Human-readable detection report
print(status_report())
```

Supports: Claude Code, Cursor, GitHub Copilot, Windsurf, Aider, Cline, OpenAI Codex CLI.

### Response Cache — In-memory GET response caching

LRU cache middleware for GET responses with configurable TTL.

```python
from tina4_python.cache import ResponseCache, cache_stats, clear_cache

# As middleware on a route
@middleware(ResponseCache)
@get("/api/products")
async def products(request, response):
    return response(expensive_query())

# Per-route TTL override via @cached decorator
@cached(max_age=120)
@get("/api/slow")
async def slow(request, response):
    return response(very_slow_query())

# Check cache stats
stats = cache_stats()  # {"hits": 42, "misses": 7, "size": 15}

# Flush all cached entries
clear_cache()
```

Environment variables:
- `TINA4_CACHE_BACKEND` — backend for the response/KV cache. One of `memory` (default), `file`, `redis`, `valkey`, `memcached`, `mongodb`, `database`.
- `TINA4_CACHE_URL` — connection string for `redis`/`valkey`/`memcached`/`mongodb`, OR a SQL URL for `database` (falls back to `TINA4_DATABASE_URL`).
- `TINA4_CACHE_USERNAME` / `TINA4_CACHE_PASSWORD` — credentials (mirrors `TINA4_DATABASE_USERNAME`/`_PASSWORD`); may also be embedded in `TINA4_CACHE_URL` (`redis://user:pass@host`, `redis://:pass@host`, `mongodb://user:pass@host`). memcached is unauthenticated.
- `TINA4_CACHE_TTL` — default TTL in seconds (default: 60)
- `TINA4_CACHE_MAX_ENTRIES` — max cached entries (default: 1000)
- `TINA4_CACHE_DIR` — directory for the `file` backend (default: `data/cache`)

**Graceful fallback**: if a configured backend's driver is missing or the service/credentials are unreachable or wrong, the cache logs a warning and falls back to the **file** backend — a real persistent cache, never a silent no-op.

### DI Container — Lightweight dependency injection

Thread-safe container with transient and singleton registrations.

```python
from tina4_python.container import Container

container = Container()

# Transient — new instance on every get()
container.register("mailer", lambda: MailService())

# Singleton — created once, memoised
container.singleton("db", lambda: Database("sqlite:///app.db"))

# Resolve
mailer = container.get("mailer")   # new instance each call
db     = container.get("db")       # same instance every call

# Check registration
container.has("db")       # True
container.has("missing")  # False

# Clear all registrations
container.reset()
```

### Error Overlay — Rich debug error pages

Renders a syntax-highlighted HTML error page with stack trace, source context, request details, and environment info when an unhandled exception occurs.

```python
from tina4_python.debug.error_overlay import render_error_overlay, render_production_error, is_debug_mode

try:
    handler(request, response)
except Exception as exc:
    if is_debug_mode():
        html = render_error_overlay(exc, request)
    else:
        html = render_production_error(500, "Internal Server Error")
```

- Activated when `TINA4_DEBUG` is `true`
- In production, `render_production_error()` returns a safe, generic error page
- Shows: exception type/message, full stack trace with source code, request details, environment info

### HtmlElement — Programmatic HTML builder

Build HTML without string concatenation. Supports all HTML tags, void tags, builder pattern, and auto-escaping.

```python
from tina4_python.HtmlElement import HTMLElement, add_html_helpers

# Direct construction
el = HTMLElement("div", {"class": "card"}, ["Hello"])
str(el)  # <div class="card">Hello</div>

# Builder pattern via __call__
page = HTMLElement("div")(
    HTMLElement("h1")("Title"),
    HTMLElement("p")("Content"),
)

# Dict arguments merge as attributes
el = HTMLElement("a")({"href": "/home", "class": "link"}, "Home")

# Void tags render correctly (no closing tag)
HTMLElement("br")       # <br>
HTMLElement("img", {"src": "logo.png"})  # <img src="logo.png">

# Helper functions — injects _div(), _p(), _a(), _span(), etc. into namespace
add_html_helpers(globals())
html = _div({"class": "card"},
    _h1("Title"),
    _p({"class": "text-muted"}, "Description"),
    _a({"href": "/more"}, "Read more"),
)
```

### Inline Testing — Decorator-based test assertions

Attach test assertions directly to functions. Tests run via CLI or programmatically.

```python
from tina4_python.Testing import tests, assert_equal, assert_raises, assert_true, assert_false

@tests(
    assert_equal((5, 3), 8),
    assert_equal((0, 0), 0),
    assert_raises(ValueError, (None,)),
    assert_true((1, 1)),
)
def add(a, b=None):
    if b is None:
        raise ValueError("b required")
    return a + b

# Run all decorated tests
from tina4_python.Testing import run_all
results = run_all(quiet=False, failfast=False)
# {"passed": 3, "failed": 0, "errors": 0, "details": [...]}
```

Available assertions: `assert_equal(args, expected)`, `assert_raises(exception_class, args)`, `assert_true(args)`, `assert_false(args)`.

Run from CLI:
```bash
uv run tina4python test   # Discovers @tests in src/**/*.py
```

## Key Architecture

- Routes auto-discovered from `src/routes/`
- ORM: subclass `ORM`; columns are field objects from `tina4_python.orm` (`StringField`, `IntegerField`, `FloatField`, `BooleanField`, `DateTimeField`, `ForeignKeyField(to=...)`) — NOT `FieldTypes`
- Templates use Jinja2/Twig syntax
- Zero external dependencies — stdlib only for all core features
- Routes via `tina4_python.core.router` (get, post, put, delete, noauth, secured, cached, template)
- Server via `tina4_python.core.server` (run, resolve_config)
- Database via `tina4_python.database` (URL-based: sqlite:///, postgresql://, mysql://, etc.)
- ORM via `tina4_python.orm` (ORM, Field, bind_database)
- Template engine via `tina4_python.frond` (Frond — Jinja2/Twig-compatible, replaces Template)
- JWT auth via `tina4_python.auth` (zero-dep HMAC-SHA256, password hashing via PBKDF2)
- Queue via `tina4_python.queue` (database-backed, zero deps)
- WebSocket via `tina4_python.websocket` (RFC 6455, asyncio-based). WebSocket backplane for scaling broadcast across instances via Redis or NATS pub/sub — **wired for real**: each `broadcast`/`broadcast_all`/`broadcast_to_room` delivers to LOCAL connections first (resilient — a dead/slow client is logged + pruned, never aborting the rest), then publishes an envelope `{src,kind,exclude,room,path,+text|b64}` to the shared channel `tina4:ws`; a sibling instance's backplane listener relays it to its own LOCAL connections only (origin guard drops the instance's own echo by `src`; the relay never re-publishes — no cluster loop). Lazily started on first broadcast (best-effort — a backplane failure logs + degrades to local-only, never crashes a broadcast). Configured via `TINA4_WS_BACKPLANE` (`redis` or `nats`) and `TINA4_WS_BACKPLANE_URL`. **Security**: origin allow-list via `TINA4_WS_ALLOWED_ORIGINS` (comma-separated; empty/unset = allow all — non-breaking; set = reject mismatched/missing Origin 403 on every upgrade path). **Idle reaper**: `TINA4_WS_IDLE_TIMEOUT` (seconds; 0/unset = disabled) closes connections idle past the timeout. (Per-route WS auth is a deliberate follow-up — the origin allow-list is the shipped control.) Rooms API: `ws.join_room(name)`, `ws.leave_room(name)`, `ws.rooms`, `ws.broadcast_to_room(name, msg)`, `mgr.room_count(name)`, `mgr.get_room_connections(name)`, `mgr.broadcast_to_room(name, msg, exclude=None)`. SSE/`response.stream()` hardened: a client disconnect cancels the generator cleanly and a generator error mid-stream is logged + ends cleanly (worker never crashes).
- API client via `tina4_python.api` (urllib-based, zero deps)
- Swagger via `tina4_python.swagger` (OpenAPI 3.0.3 generator)
- GraphQL via `tina4_python.graphql` (recursive-descent parser, ORM auto-generation)
- WSDL/SOAP via `tina4_python.wsdl` (SOAP 1.1 with auto WSDL generation)
- Migrations via `tina4_python.migration` (SQL-file-based with tracking)
- Sessions via `tina4_python.session` (File, Database backends). `TINA4_SESSION_SAMESITE` env var controls SameSite attribute (default: Lax)
- Auto-CRUD via `tina4_python.crud` (AutoCrud — REST from ORM models)
- Seeder via `tina4_python.seeder` (FakeData, seed_table)
- i18n via `tina4_python.i18n` (I18n — JSON-based translations)
- Background tasks via `background()` — cooperative periodic callbacks in the asyncio event loop (no threads)
- Event system via `tina4_python.core.events` (observer pattern, async support)
- AI context scaffolding via `tina4_python.ai` (Claude, Cursor, Copilot, etc.)
- Response caching via `tina4_python.cache` (LRU, TTL, middleware)
- DI container via `tina4_python.container` (transient + singleton)
- Structured logging via `tina4_python.debug` (Log — rotation, JSON/human output)
- Debug error overlay via `tina4_python.debug.error_overlay`
- Inline testing via `tina4_python.Testing` (decorator-based assertions)
- HTML builder via `tina4_python.HtmlElement` (programmatic HTML generation)
- Messenger via `tina4_python.messenger` (.env driven, SMTP/IMAP)
- SQL Translation via `tina4_python.database.adapter` (cross-engine SQL portability + query cache)
- CLI scaffolding: `tina4python generate model/route/migration/middleware`
- Production server auto-detection: `tina4python serve --production` (auto-installs uvicorn)
- Frond pre-compilation for 2.8x template render improvement (clear_cache method)
- DB query caching: request-scoped auto cache **off by default — opt-in via `TINA4_AUTO_CACHING=true`** (TTL `TINA4_AUTO_CACHING_TTL=5`) dedupes identical reads within a request and flushes on any write. It ships OFF because a request-scoped cache can hand back pre-write state in a read-after-write (e.g. `SELECT MAX(id)` right before an `INSERT` in the same request → duplicate keys / stale grids); turn it on per-app for read-heavy endpoints. Persistent cross-request cache is also opt-in via `TINA4_DB_CACHE=true` (TTL `TINA4_DB_CACHE_TTL=30`). The persistent DB cache routes through the same unified backend set via `TINA4_DB_CACHE_BACKEND` (memory/file/redis/valkey/memcached/mongodb/database) + `TINA4_DB_CACHE_URL`, so multiple instances share one cache with global write-invalidation. `cache_stats()` reports `mode` (request/persistent/off) and `backend`, `cache_clear()`
- ORM relationships: `has_many`, `has_one`, `belongs_to` with eager loading (`include=`)
- Queue backends: file (default), RabbitMQ, Kafka, MongoDB — configured via env vars. **Reservation/visibility timeout** (file + MongoDB): a popped job is reserved for `TINA4_QUEUE_VISIBILITY_TIMEOUT` seconds (default 300; `Queue(visibility_timeout=)`; `<= 0` disables) — if the consumer dies before `complete()`/`fail()`, the next `pop()` reclaims it (incrementing `attempts`, dead-lettering past `max_retries`), so a crashed/evicted consumer never strands a job. RabbitMQ/Kafka delegate redelivery to the broker.
- Cache backends: unified set across response/KV and persistent DB cache — `memory` (default), `file`, `redis`, `valkey`, `memcached`, `mongodb`, `database` — selected via `TINA4_CACHE_BACKEND` (+ `TINA4_CACHE_URL`/credentials); falls back to the file backend if a backend is unreachable
- Session backends: file, Redis, Valkey, MongoDB, database
- QueryBuilder with NoSQL/MongoDB support (`to_mongo()`)
- WebSocket backplane (Redis/NATS pub/sub) for horizontal scaling — wired into the live broadcast path with origin-guard + local-first delivery (see the WebSocket bullet); WS origin allow-list + idle reaper
- SameSite=Lax default on session cookies (`TINA4_SESSION_SAMESITE`)
- `tina4 deploy docker` generates Dockerfile and .dockerignore
- Gallery: 7 interactive examples with Try It deploy at `/__dev/`
- Race-safe `get_next_id()` with atomic sequence table (`tina4_sequences`) for SQLite/MySQL/MSSQL; PostgreSQL auto-creates sequences
- Frond template engine optimizations: pre-compiled regexes, lazy loop context (copy-on-write), filter chain caching, path split caching, inline common filters (11-15% speedup)
- SSE/Streaming via `response.stream()` — Server-Sent Events support for real-time data push. Pass an async generator; framework handles chunked transfer encoding, `text/event-stream` content type, and connection keep-alive
- MCP server (`tina4_python.mcp`): built-in dev tools auto-start when MCP is a capability of the deployment. Developer API: `McpServer`, `@mcp_tool`, `@mcp_resource`. JSON-RPC 2.0 over SSE. **Security is a two-layer gate (v3.13.40):** `is_enabled()` is a pure capability gate (explicit `TINA4_MCP` wins, else `TINA4_DEBUG`; host-independent), and `is_request_allowed(remote_ip, has_valid_token)` authorises each request on the RAW socket peer (`request.remote_ip`, never X-Forwarded-For): loopback always; a remote caller needs `TINA4_MCP_REMOTE=true` AND a token matching `TINA4_MCP_TOKEN` (fallback `TINA4_API_KEY`; sent as Authorization Bearer / X-MCP-Token / X-Api-Key; no configured token means remote is always denied). All MCP surfaces (REST shim, JSON-RPC, SSE) 404 a disallowed caller. `database_query` is SELECT/WITH-only and rejects stacked statements; the file tools are sandboxed to the project root. `is_localhost()` is informational only, not the gate
- Tests: 2,901 passing (122 modules)
- Version: 3.13.57

## Links

- Website: https://tina4.com
- GitHub: https://github.com/tina4stack/tina4-python

## Tina4 Maintainer Skill
Always read and follow the instructions in .claude/skills/tina4-maintainer/SKILL.md when working on this codebase. Read its referenced files in .claude/skills/tina4-maintainer/references/ as needed for specific subsystems.

## Tina4 Developer Skill
Always read and follow the instructions in .claude/skills/tina4-developer/SKILL.md when building applications with this framework. Read its referenced files in .claude/skills/tina4-developer/references/ as needed.

## Tina4-js Frontend Skill
Always read and follow the instructions in .claude/skills/tina4-js/SKILL.md when working with tina4-js frontend code. Read its referenced files in .claude/skills/tina4-js/references/ as needed.

## First Principle: Documentation Matches Code Reality

**This rule overrides everything else in this file.**

Every command, env var, method, class, or feature mentioned in any
documentation file (`*.md` in this repo, or any tina4-book chapter,
or `tina4-documentation/docs/`) MUST exist in code. No exceptions.
No "we'll build it later" entries. No Laravel/Rails-style commands
that look right but don't exist. No env vars that the framework
doesn't actually read.

When you add a doc reference, add the implementation in the same PR.
When you remove a feature, remove every doc reference in the same PR.
When you find drift, fix it both ways: build the real thing OR delete
the doc.

The `tina4-documentation/scripts/audit-truth.py` script is the source
of truth. It runs as a CI gate (`audit-truth.yml`) on every PR — the
build fails on CLI drift. Run it locally before pushing if you've
touched docs:

```bash
cd /path/to/tina4-documentation
python3 scripts/audit-truth.py --strict
```

If you're unsure whether something exists, run `tina4 <command> --help`
or grep the framework source. Don't guess.
