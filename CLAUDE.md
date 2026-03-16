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
- CLI: `tina4` (entry point defined in pyproject.toml)

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
  DevReload.py, Debug.py, HtmlElement.py, Api.py ...
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
- Version: 0.2.200

## Links

- Website: https://tina4.com
- GitHub: https://github.com/tina4stack/tina4-python
