# Tina4 Python

Lightweight Python web framework. See https://tina4.com for full documentation.

## Build & Test

- Package manager: `uv`
- Python: >=3.12
- Install: `uv sync`
- Run all tests: `.venv/bin/python -m pytest tests/`
- Run single test: `.venv/bin/python -m pytest tests/test_file.py::TestClass::test_method`
- Coverage: `.venv/bin/python -m pytest tests/ --cov=tina4_python`
- Start server: `python app.py`
- CLI: `tina4python` (entry point defined in pyproject.toml)

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
- **BLOB handling** — `fetch_one()` auto-base64-encodes BLOB fields; use `decode_blob()` to reverse
- **No `TEXT` type** — Use `VARCHAR(n)` or `BLOB SUB_TYPE TEXT`
- **No `REAL`/`FLOAT`** — Use `DOUBLE PRECISION`
- **No `IF NOT EXISTS`** for `ALTER TABLE ADD` — framework handles idempotency automatically

## Development Mode (DevReload)

Set `TINA4_DEBUG=true` in `.env` to enable:

- **Live-reload** — Browser auto-refreshes when `.py`, `.twig`, `.html`, `.js` files change
- **CSS hot-reload** — SCSS/CSS changes refresh stylesheets without full page reload
- **SCSS auto-compile** — `.scss` files in `src/scss/` compiled to `src/public/css/` on save
- **Error overlay** — Runtime errors display a rich, syntax-highlighted overlay in the browser
- **Hot-patching** — Python code changes are live-patched via jurigged (no server restart)

DevReload connects via WebSocket at `/__dev_reload`. No configuration needed.

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
  orm/                 # Active Record ORM (ORM, Field, orm_bind)
    model.py           # ORM base class
    fields.py          # IntegerField, StringField, etc.
  frond/               # Template engine (Frond — replaces Template)
    engine.py          # Frond class (render, add_filter, add_global, add_test)
  api/                 # HTTP client (Api class — zero deps)
  queue/               # Database-backed job queue (Queue, Producer, Consumer)
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
@noauth()                        # Make write route public
@secured()                       # Protect a GET route
@cached(is_cached: bool, max_age: int = 60)
@middleware(middleware_class, specific_methods: list | None = None)
@template(twig_file: str)        # Auto-render dict return through Frond template
```

**Decorator order** (outermost → innermost): `@noauth`/`@secured` → `@description`/`@tags` → `@get`/`@post`

### Database — Multi-driver abstraction

```python
from tina4_python.database import Database

db = Database(url: str, username="", password="")

db.fetch(sql, params=None, limit=10, skip=0) -> DatabaseResult
db.fetch_one(sql, params=None) -> dict | None
db.execute(sql, params=None) -> DatabaseResult
db.execute_many(sql, params=None) -> DatabaseResult
db.insert(table_name, data: dict | list) -> DatabaseResult
db.update(table_name, data: dict) -> DatabaseResult
db.delete(table_name, data: dict) -> DatabaseResult
db.start_transaction()
db.commit()
db.rollback()
db.table_exists(table_name) -> bool
db.get_tables() -> list[str]
db.get_columns(table_name) -> list[dict]
```

### ORM — Active Record base class

```python
from tina4_python.orm import ORM, orm_bind, Field, IntegerField, StringField

class MyModel(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()

model = MyModel(init_object: dict | None = None)
model.save() -> bool
model.load(query="", params=None) -> bool
model.delete(query="", params=None) -> bool
model.select(column_names="*", filter="", params=None, join="", group_by="", having="", order_by="", limit=10, skip=0) -> DatabaseResult
model.fetch_one(column_names="*", filter="", params=None) -> dict | None
model.to_dict() -> dict
model.to_json() -> str
model.create_table() -> bool

orm_bind(dba: Database) -> None  # Bind database to all ORM subclasses
```

### Frond — Template engine (replaces Template)

```python
from tina4_python.frond import Frond

Frond.render(template_or_file_name: str, data: dict = None) -> str
Frond.render_string(source: str, data: dict = None) -> str
Frond.add_filter(name: str, func: callable)
Frond.add_global(name: str, value: any)
Frond.add_test(name: str, func: callable)
```

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
from tina4_python.queue import Queue, Producer, Consumer

queue = Queue(db, topic="tasks", max_retries=3)
queue.push(data: dict, priority=0, delay_seconds=0) -> int
queue.pop() -> Job | None
queue.size(status="pending") -> int
queue.purge(status="completed")
queue.retry_failed() -> int
queue.dead_letters() -> list[dict]

producer = Producer(queue)
producer.push(data: dict, priority=0, delay_seconds=0) -> int

consumer = Consumer(queue, callback=handler_func, poll_interval=1.0)
consumer.run()                  # Process until queue empty
consumer.run_forever()          # Poll continuously
consumer.poll() -> list[Job]    # Poll once
consumer.stop()                 # Stop run_forever loop

# Job methods
job.complete()                  # Mark as completed
job.fail(error="")              # Mark as failed
job.retry(delay_seconds=0)      # Re-queue with optional delay
```

### Migration

```python
from tina4_python.migration import migrate, create_migration, rollback

migrate(db)                              # Run all pending migrations
create_migration("add users table")      # Create new .sql file
rollback(db)                             # Rollback last batch
```

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

### AI Integration — AI assistant context scaffolding

Detect AI coding tools in a project and install framework-aware context files.

```python
from tina4_python.ai import detect_ai, install_context, status_report

# Detect which AI tools are present
tools = detect_ai()
# [{"name": "claude-code", "description": "Claude Code (Anthropic CLI)", "installed": True}, ...]

# Install context files for all detected tools
created_files = install_context()       # auto-detect
created_files = install_context(tools=["claude-code", "cursor"])  # specific tools
created_files = install_context(force=True)  # overwrite existing

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
@cached(True, max_age=120)
@get("/api/slow")
async def slow(request, response):
    return response(very_slow_query())

# Check cache stats
stats = cache_stats()  # {"hits": 42, "misses": 7, "size": 15}

# Flush all cached entries
clear_cache()
```

Environment variables:
- `TINA4_CACHE_TTL` — default TTL in seconds (default: 60)
- `TINA4_CACHE_MAX_ENTRIES` — max cached entries (default: 1000)

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
from tina4_python.Testing import run_all_tests
results = run_all_tests(quiet=False, failfast=False)
# {"passed": 3, "failed": 0, "errors": 0, "details": [...]}
```

Available assertions: `assert_equal(args, expected)`, `assert_raises(exception_class, args)`, `assert_true(args)`, `assert_false(args)`.

Run from CLI:
```bash
uv run tina4python test   # Discovers @tests in src/**/*.py
```

## Key Architecture

- Routes auto-discovered from `src/routes/`
- ORM uses class-level field definitions with `FieldTypes`
- Templates use Jinja2/Twig syntax
- Zero external dependencies — stdlib only for all core features
- Routes via `tina4_python.core.router` (get, post, put, delete, noauth, secured, cached, template)
- Server via `tina4_python.core.server` (run, resolve_config)
- Database via `tina4_python.database` (URL-based: sqlite:///, postgresql://, mysql://, etc.)
- ORM via `tina4_python.orm` (ORM, Field, orm_bind)
- Template engine via `tina4_python.frond` (Frond — Jinja2/Twig-compatible, replaces Template)
- JWT auth via `tina4_python.auth` (zero-dep HMAC-SHA256, password hashing via PBKDF2)
- Queue via `tina4_python.queue` (database-backed, zero deps)
- WebSocket via `tina4_python.websocket` (RFC 6455, asyncio-based)
- API client via `tina4_python.api` (urllib-based, zero deps)
- Swagger via `tina4_python.swagger` (OpenAPI 3.0.3 generator)
- GraphQL via `tina4_python.graphql` (recursive-descent parser, ORM auto-generation)
- WSDL/SOAP via `tina4_python.wsdl` (SOAP 1.1 with auto WSDL generation)
- Migrations via `tina4_python.migration` (SQL-file-based with tracking)
- Sessions via `tina4_python.session` (File, Database backends)
- Auto-CRUD via `tina4_python.crud` (AutoCrud — REST from ORM models)
- Seeder via `tina4_python.seeder` (FakeData, seed_table)
- i18n via `tina4_python.i18n` (I18n — JSON-based translations)
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
- DB query caching: `TINA4_DB_CACHE=true` env var, `cache_stats()`, `cache_clear()`
- ORM relationships: `has_many`, `has_one`, `belongs_to` with eager loading (`include=`)
- Queue backends: SQLite (default), RabbitMQ, Kafka — configured via env vars
- Cache backends: memory (default), Redis, file — configured via env vars
- Session backends: file, Redis, Valkey, MongoDB, database
- Gallery: 7 interactive examples with Try It deploy at `/__dev/`
- Tests: 1,633 passing (38 modules)
- Version: 3.0.0

## Links

- Website: https://tina4.com
- GitHub: https://github.com/tina4stack/tina4-python

## Tina4 Maintainer Skill
Always read and follow the instructions in .claude/skills/tina4-maintainer/SKILL.md when working on this codebase. Read its referenced files in .claude/skills/tina4-maintainer/references/ as needed for specific subsystems.

## Tina4 Developer Skill
Always read and follow the instructions in .claude/skills/tina4-developer/SKILL.md when building applications with this framework. Read its referenced files in .claude/skills/tina4-developer/references/ as needed.

## Tina4-js Frontend Skill
Always read and follow the instructions in .claude/skills/tina4-js/SKILL.md when working with tina4-js frontend code. Read its referenced files in .claude/skills/tina4-js/references/ as needed.
