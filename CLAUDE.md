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

Set `TINA4_DEBUG_LEVEL=ALL` or `TINA4_DEBUG_LEVEL=DEBUG` in `.env` to enable:

- **Live-reload** — Browser auto-refreshes when `.py`, `.twig`, `.html`, `.js` files change
- **CSS hot-reload** — SCSS/CSS changes refresh stylesheets without full page reload
- **SCSS auto-compile** — `.scss` files in `src/scss/` compiled to `src/public/css/` on save
- **Error overlay** — Runtime errors display a rich, syntax-highlighted overlay in the browser
- **Hot-patching** — Python code changes are live-patched via jurigged (no server restart)

DevReload connects via WebSocket at `/__dev_reload`. No configuration needed.

## Project Structure

```
tina4_python/          # Core framework package
  Auth.py, Router.py, ORM.py, Database.py, Seeder.py,
  Migration.py, Template.py, Swagger.py, Webserver.py,
  Queue.py, Session.py, GraphQL.py, WSDL.py, CRUD.py,
  Websocket.py, Localization.py, MiddleWare.py, cli.py,
  DevReload.py, Debug.py, HtmlElement.py, Api.py,
  Testing.py ...
  core/                # Core subsystems
    events.py          # Event system (on, emit, once, off)
  ai/                  # AI coding assistant detection & context
  cache/               # In-memory response cache middleware
  container/           # Lightweight dependency injection container
  debug/               # Debug utilities
    error_overlay.py   # Rich HTML error overlay for dev mode
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
@get(path: str | list)           # Public by default
@post(path: str | list)          # Auth required by default
@put(path: str | list)           # Auth required by default
@patch(path: str | list)         # Auth required by default
@delete(path: str | list)        # Auth required by default
@any(path: str | list)           # All methods
@noauth()                        # Make write route public
@secured()                       # Protect a GET route
@cached(is_cached: bool, max_age: int = 60)
@middleware(middleware_class, specific_methods: list | None = None)
@template(twig_file: str)        # Auto-render dict return through template
```

**Decorator order** (outermost → innermost): `@noauth`/`@secured` → `@description`/`@tags` → `@get`/`@post`

### Database — Multi-driver abstraction

```python
db = Database(connection_string: str, username="", password="", charset="")

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
db.get_database_tables() -> list[str]
db.get_table_info(table_name) -> list[dict]
```

### ORM — Active Record base class

```python
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

orm(dba: Database) -> None  # Bind database to all ORM subclasses
```

### Template — Jinja2/Twig engine

```python
Template.render(template_or_file_name: str, data: dict = None) -> str
Template.add_filter(name: str, func: callable)
Template.add_global(name: str, value: any)
Template.add_test(name: str, func: callable)
Template.add_extension(extension: type)
```

### Seeder — Fake data generation

```python
fake = FakeData(seed: int | None = None)
fake.name() -> str
fake.email() -> str
fake.phone() -> str
fake.sentence(words=6) -> str
fake.integer(min_val=0, max_val=10000) -> int
fake.numeric(min_val=0.0, max_val=1000.0, decimals=2) -> float
fake.datetime() -> datetime
fake.for_field(field: BaseField, column_name=None) -> any

seed_orm(orm_class, count=10, overrides=None) -> int
seed_table(db, table_name, count=10, field_map=None, overrides=None) -> int
seed(seeders: list[Seeder]) -> None
```

### Api — External HTTP client

```python
api = Api(base_url="", auth_header="", ignore_ssl_validation=False)
api.send_request(rest_service="", request_type="GET", body=None, content_type="application/json") -> dict
api.add_custom_headers(headers: dict)
api.set_username_password(username, password)
# Returns: {"http_code": 200, "body": {...}, "headers": {...}, "error": None}
```

### Queue — Background processing

```python
queue = Queue(topic="tasks", callback=handler_func, batch_size=1)
producer = Producer(queue)
producer.produce(data: dict)
consumer = Consumer(queue)
consumer.run_forever()
```

### Migration

```python
migrate(dba: Database, delimiter=";", migration_folder="migrations")
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
container.singleton("db", lambda: Database("sqlite3:app.db"))

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

- Activated when `TINA4_DEBUG_LEVEL` is `ALL` or `DEBUG`
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
- All public API classes registered as builtins (Router, ORM, Database, Seeder, etc.)
- SCSS compilation via `libsass`
- JWT auth via `pyjwt` + `cryptography`
- Queue support via `litequeue` (+ RabbitMQ, Kafka, MongoDB backends)
- WebSocket support via `simple-websocket`
- Hot reload via `jurigged` + `watchdog`
- Event system via `tina4_python.core.events` (observer pattern, async support)
- AI context scaffolding via `tina4_python.ai` (Claude, Cursor, Copilot, etc.)
- Response caching via `tina4_python.cache` (LRU, TTL, middleware)
- DI container via `tina4_python.container` (transient + singleton)
- Debug error overlay via `tina4_python.debug.error_overlay`
- Inline testing via `tina4_python.Testing` (decorator-based assertions)
- HTML builder via `tina4_python.HtmlElement` (programmatic HTML generation)
- Version: 3.0.0

## Links

- Website: https://tina4.com
- GitHub: https://github.com/tina4stack/tina4-python

## Tina4 Maintainer Skill
Always read and follow the instructions in .claude/skills/tina4-maintainer/SKILL.md when working on this codebase. Read its referenced files in .claude/skills/tina4-maintainer/references/ as needed for specific subsystems.

## Tina4 Developer Skill
Always read and follow the instructions in .claude/skills/tina4-developer/SKILL.md when building applications with this framework. Read its referenced files in .claude/skills/tina4-developer/references/ as needed.

## Tina4-js Frontend Skill
Always read and follow the instructions in .claude/skills/tina4-js-skill/SKILL.md when working with tina4-js frontend code. Read its referenced files in .claude/skills/tina4-js-skill/references/ as needed.
