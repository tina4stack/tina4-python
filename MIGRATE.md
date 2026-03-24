# Migrating from Tina4 Python v2 to v3

## Why Migrate

v3 is a ground-up rewrite. You get:

- **38 built-in features** with zero third-party dependencies (no PyJWT, no bcrypt, no Jinja2, no python-dotenv)
- **5 database drivers** — SQLite, PostgreSQL, MySQL, MSSQL, Firebird (plus MongoDB and ODBC)
- **ORM relationships** — `has_many`, `has_one`, `belongs_to` with eager loading
- **Built-in template engine** — Frond replaces Jinja2 (still uses Twig/Jinja2 syntax)
- **Queue backends** — SQLite, RabbitMQ, Kafka, MongoDB — switched via env vars, not code
- **Event system**, response caching, DI container, GraphQL, WSDL/SOAP, error overlay
- **1,633 tests** passing across all modules
- **Production server** auto-detection with uvicorn

v2 required `jwt`, `bcrypt`, `jinja2`, and `python-dotenv` as runtime dependencies. v3 uses only the Python stdlib.

---

## Import Changes

v2 used flat module files in `tina4_python/`. v3 uses subpackages.

| v2 Import | v3 Import |
|-----------|-----------|
| `from tina4_python.Router import get, post, put, delete` | `from tina4_python.core.router import get, post, put, delete` |
| `from tina4_python.Router import Router` | `from tina4_python.core.router import Router` |
| `from tina4_python.Router import noauth, secured, cached, middleware` | `from tina4_python.core.router import noauth, secured, cached, middleware` |
| `from tina4_python.Database import Database` | `from tina4_python.database import Database` |
| `from tina4_python.DatabaseResult import DatabaseResult` | `from tina4_python.database.adapter import DatabaseResult` |
| `from tina4_python.ORM import ORM` | `from tina4_python.orm import ORM` |
| `from tina4_python.ORM import orm` | `from tina4_python.orm import orm_bind` |
| `from tina4_python.FieldTypes import IntegerField, StringField, ...` | `from tina4_python.orm import IntegerField, StringField, ...` |
| `from tina4_python.Template import Template` | `from tina4_python.frond import Frond` |
| `from tina4_python.Auth import Auth` | `from tina4_python.auth import Auth` |
| `from tina4_python.Queue import Queue, Producer, Consumer` | `from tina4_python.queue import Queue, Producer, Consumer` |
| `from tina4_python.Queue import Config` | Removed. Use env vars instead. |
| `from tina4_python.Response import Response` | `from tina4_python.core.response import Response` |
| `from tina4_python.Request import Request` | `from tina4_python.core.request import Request` |
| `from tina4_python.Debug import Debug` | `from tina4_python.debug import Log` |
| `from tina4_python.Session import Session` | `from tina4_python.session import Session` |
| `from tina4_python.Migration import migrate` | `from tina4_python.migration import migrate` |
| `from tina4_python.Swagger import description, tags` | `from tina4_python.swagger import description, tags` |
| `from tina4_python.Env import load_env` | `from tina4_python.dotenv import load_env` |
| `from tina4_python import Constant` | `from tina4_python.core.constants import HTTP_OK, ...` |
| `from tina4_python.MiddleWare import MiddleWare` | `from tina4_python.core.middleware import CorsMiddleware, RateLimiter` |

Many v3 symbols are also re-exported from `tina4_python` directly:

```python
from tina4_python import ORM, IntegerField, StringField, has_many, has_one, belongs_to
```

---

## Entry Point

### v2

```python
from tina4_python import run_web_server

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
```

### v3

```python
from tina4_python.core import run

if __name__ == "__main__":
    run()
```

`run()` reads host and port from env vars or CLI args. No need to pass them explicitly.

---

## Database

### Connection String Format

v2 used a colon-separated format: `driver:host/port:schema`.

v3 uses standard URL format: `driver://host:port/database`.

| v2 | v3 |
|----|-----|
| `Database("sqlite3:app.db")` | `Database("sqlite:///app.db")` |
| `Database("postgres:localhost/5432:mydb", "user", "pw")` | `Database("postgresql://localhost:5432/mydb", "user", "pw")` |
| `Database("mysql:localhost/3306:mydb", "user", "pw")` | `Database("mysql://localhost:3306/mydb", "user", "pw")` |
| `Database("firebird:localhost/3050:/path/to/db", "SYSDBA", "masterkey")` | `Database("firebird://localhost:3050//path/to/db", "SYSDBA", "masterkey")` |
| `Database("mssql:localhost/1433:mydb", "sa", "pw")` | `Database("mssql://localhost:1433/mydb", "sa", "pw")` |
| `Database("pymongo:localhost/27017:mydb")` | `Database("pymongo:localhost/27017:mydb")` |

### Environment Variable

| v2 | v3 |
|----|-----|
| `DATABASE_PATH` | `DATABASE_URL` |
| `DATABASE_USERNAME` | `DATABASE_USERNAME` (unchanged) |
| `DATABASE_PASSWORD` | `DATABASE_PASSWORD` (unchanged) |

### No-argument Constructor

```python
# v2 — reads DATABASE_PATH
db = Database(os.environ.get("DATABASE_PATH"))

# v3 — reads DATABASE_URL automatically
db = Database()
```

---

## ORM

### Binding

```python
# v2
from tina4_python.ORM import orm
orm(Database("sqlite3:app.db"))

# v3
from tina4_python.orm import orm_bind
from tina4_python.database import Database
orm_bind(Database("sqlite:///app.db"))
```

### Field Definitions

Field classes moved from `tina4_python.FieldTypes` to `tina4_python.orm`.

```python
# v2
from tina4_python.FieldTypes import IntegerField, StringField

# v3
from tina4_python.orm import IntegerField, StringField
# or
from tina4_python import IntegerField, StringField
```

v3 adds short aliases: `IntField`, `StrField`, `BoolField`.

### Relationships (New in v3)

v2 had no relationship support. v3 adds descriptors:

```python
from tina4_python.orm import ORM, IntegerField, StringField, has_many, belongs_to

class Author(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    books = has_many("Book", foreign_key="author_id")

class Book(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    author_id = IntegerField()
    author = belongs_to("Author", foreign_key="author_id")
```

### to_dict with Includes

```python
# v3 only — eager-load relationships
author.to_dict(include=["books"])
```

### create_table (New in v3)

```python
# v3 — auto-generate DDL from field definitions
MyModel().create_table()
```

### Query Method Rename

| v2 | v3 |
|----|-----|
| `model.fetch(filter=..., limit=..., skip=...)` | `model.select(filter=..., limit=..., offset=...)` |

---

## Template Engine

v2 used `Template` which wrapped Jinja2 (an external dependency).
v3 uses `Frond` — a built-in engine with the same Twig/Jinja2 syntax.

### Rendering

```python
# v2
from tina4_python.Template import Template
html = Template.render("page.twig", {"title": "Hello"})

# v3
from tina4_python.frond import Frond
html = Frond.render("page.twig", {"title": "Hello"})
```

### Custom Filters

```python
# v2
Template.add_filter("money", lambda v: f"{float(v):,.2f}")

# v3
Frond.add_filter("money", lambda v: f"{float(v):,.2f}")
```

### Custom Globals and Tests

```python
# v2
Template.add_global("APP_NAME", "My App")

# v3
Frond.add_global("APP_NAME", "My App")
Frond.add_test("positive", lambda x: x > 0)
```

### @template Decorator

```python
# v2 — not available
# v3
from tina4_python.core.router import get, template

@template("pages/dashboard.twig")
@get("/dashboard")
async def dashboard(request, response):
    return {"title": "Dashboard"}
```

---

## Auth

v2 depended on `PyJWT` and `bcrypt`. v3 uses stdlib only (HMAC-SHA256 for JWT, PBKDF2 for passwords).

### Method Name Changes

| v2 | v3 |
|----|-----|
| `auth.get_token(payload)` | `auth.get_token(payload)` (unchanged) |
| `auth.valid(token)` → `bool` | `auth.valid_token(token)` → `dict \| None` |
| `auth.hash_password(text)` | `Auth.hash_password(text)` (now a static method) |
| `auth.check_password(hash, text)` | `Auth.check_password(hash, text)` (now a static method) |
| `auth.get_payload(token)` | `auth.get_payload(token)` (unchanged) |

### Construction

```python
# v2 — global instance at tina4_python.tina4_auth
from tina4_python import tina4_auth
token = tina4_auth.get_token({"user_id": 1})

# v3 — create your own instance
from tina4_python.auth import Auth
auth = Auth(secret="my-secret")
token = auth.get_token({"user_id": 1})
```

### Password Hashing Change

v2 used bcrypt. v3 uses PBKDF2-HMAC-SHA256. Existing bcrypt hashes are **not** compatible. You must re-hash passwords on first login after migration.

---

## Queue

### v2 — Config Object Required

```python
from tina4_python.Queue import Queue, Producer, Consumer, Config

config = Config()
config.queue_type = "rabbitmq"
config.rabbitmq_config = {"host": "localhost", "port": 5672}

queue = Queue(config=config, topic="emails")
Producer(queue).produce({"to": "alice@test.com"})
```

### v3 — Env-Driven Backend Selection

```python
from tina4_python.queue import Queue, Producer, Consumer

# Backend is selected by TINA4_QUEUE_BACKEND env var
queue = Queue(topic="emails")
Producer(queue).push({"to": "alice@test.com"})
```

Set these in `.env`:

```bash
TINA4_QUEUE_BACKEND=rabbitmq          # sqlite (default), rabbitmq, kafka
TINA4_RABBITMQ_HOST=localhost
# or
TINA4_QUEUE_URL=amqp://localhost:5672
```

### Method Renames

| v2 | v3 |
|----|-----|
| `producer.produce(data)` | `producer.push(data)` |
| `consumer.messages()` (generator) | `consumer.poll()` (returns list) |
| `consumer.consume()` | `consumer.run()` or `consumer.run_forever()` |
| `Queue(config=..., topic=...)` | `Queue(topic=...)` |

### Database-Backed Queue

v2 required a `Config` object with `queue_type="litequeue"`. v3 auto-detects the backend from environment variables:

```python
# v3
queue = Queue(topic="tasks", max_retries=3)
queue.push({"action": "process"})
```

---

## Environment Variables

| v2 | v3 | Notes |
|----|-----|-------|
| `TINA4_DEBUG_LEVEL` | `TINA4_DEBUG` + `TINA4_LOG_LEVEL` | Split into two vars |
| `TINA4_AUTO_COMMIT` | `TINA4_AUTOCOMMIT` | No underscore between AUTO and COMMIT |
| `DATABASE_PATH` | `DATABASE_URL` | URL format, not colon-separated |
| `SECRET` | `SECRET` | Unchanged |
| `API_KEY` | `API_KEY` | Unchanged |
| `TINA4_TOKEN_LIMIT` | `TINA4_TOKEN_EXPIRES_IN` | Renamed, value in minutes |

### Debug Settings

```bash
# v2
TINA4_DEBUG_LEVEL=ALL

# v3 — two separate controls
TINA4_DEBUG=true           # enables dev mode (live reload, error overlay)
TINA4_LOG_LEVEL=ALL        # log verbosity: ALL, DEBUG, INFO, WARNING, ERROR
```

---

## Response Pattern

The response callable works the same way in both versions. One change:

```python
# v2 — Response.add_header was coroutine-scoped via contextvars
from tina4_python.Response import Response
Response.add_header("X-Custom", "value")

# v3 — same pattern, different import
from tina4_python.core.response import Response
Response.add_header("X-Custom", "value")
```

Template rendering in responses:

```python
# v2
return response(Template.render("page.twig", data))

# v3 — use response.render directly
return response.render("page.twig", data)
```

---

## CLI

| v2 Command | v3 Command | Notes |
|------------|------------|-------|
| `tina4 init PROJECT` | `tina4python init PROJECT` | CLI binary renamed |
| `tina4 start [PORT]` | `tina4python serve` or `tina4python start` | Both work |
| `tina4 migrate` | `tina4python migrate` | |
| `tina4 migrate:create DESC` | `tina4python migrate:create DESC` | |
| `tina4 seed` | `tina4python seed` | |
| `tina4 test` | `tina4python test` | |
| — | `tina4python migrate:rollback` | New in v3 |
| — | `tina4python routes` | New in v3 |
| — | `tina4python build` | New in v3 |
| — | `tina4python ai` | New in v3 |
| — | `tina4python generate model/route/migration/middleware` | New in v3 |
| — | `tina4python serve --production` | Auto-installs uvicorn |

The CLI entry point changed in `pyproject.toml`:

```toml
# v2 (setup.py)
[console_scripts]
tina4 = tina4_python.cli:main

# v3 (pyproject.toml)
[project.scripts]
tina4python = "tina4_python.cli:main"
```

---

## Removed Dependencies

| v2 Dependency | v3 Replacement |
|---------------|----------------|
| `PyJWT` | Built-in HMAC-SHA256 JWT (`tina4_python.auth`) |
| `bcrypt` | Built-in PBKDF2-HMAC-SHA256 (`tina4_python.auth`) |
| `Jinja2` | Built-in Frond engine (`tina4_python.frond`) |
| `python-dotenv` | Built-in dotenv loader (`tina4_python.dotenv`) |

---

## New Features (v3 Only)

These did not exist in v2:

- **Event system** — `on`, `emit`, `once`, `off` from `tina4_python.core.events`
- **Response cache** — `ResponseCache`, `@cached` middleware
- **DI container** — `Container` for transient/singleton registration
- **Error overlay** — rich HTML error page in dev mode
- **GraphQL** — zero-dep engine with ORM auto-generation
- **WSDL/SOAP** — SOAP 1.1 server with auto WSDL
- **i18n** — JSON-based translations
- **AI context** — auto-detect and install context files for AI coding tools
- **ORM relationships** — `has_many`, `has_one`, `belongs_to`
- **Session backends** — file, Redis, Valkey, MongoDB
- **Queue backends** — env-driven SQLite, RabbitMQ, Kafka
- **Cache backends** — memory, Redis, file
- **Messenger** — SMTP/IMAP messaging
- **Inline testing** — `@tests` decorator with assertions

---

## Step-by-Step Migration Checklist

1. **Update your package manager.** Switch from `pip install tina4-python` (v2) to `uv add tina4-python` (v3). Remove `PyJWT`, `bcrypt`, `Jinja2`, and `python-dotenv` from your dependencies.

2. **Rename your entry point.** Replace `run_web_server("0.0.0.0", 7145)` with `run()`. Import from `tina4_python.core` instead of `tina4_python`.

3. **Update all imports.** Use the import table above. Search your project for `from tina4_python.Router`, `from tina4_python.Database`, `from tina4_python.ORM`, `from tina4_python.Template`, etc. Replace with the v3 paths.

4. **Fix database connection strings.** Change `driver:host/port:schema` to `driver://host:port/database`. Update `DATABASE_PATH` to `DATABASE_URL` in `.env`.

5. **Update ORM binding.** Replace `orm(db)` with `orm_bind(db)`. Update field imports from `tina4_python.FieldTypes` to `tina4_python.orm`.

6. **Replace Template with Frond.** Change `Template.render()` to `Frond.render()`. Move `add_filter`, `add_global` calls to use `Frond`. Your Twig templates work without changes.

7. **Update Auth usage.** `get_token()` is unchanged. Replace `valid()` with `valid_token()`. Create an `Auth()` instance instead of using the global `tina4_auth`. Plan to re-hash user passwords (bcrypt to PBKDF2).

8. **Migrate Queue code.** Remove `Config` objects. Set `TINA4_QUEUE_BACKEND` in `.env`. Replace `produce()` with `push()`. Replace `messages()` with `poll()`.

9. **Update environment variables.** Replace `TINA4_DEBUG_LEVEL` with `TINA4_DEBUG=true` and `TINA4_LOG_LEVEL=ALL`. Replace `TINA4_AUTO_COMMIT` with `TINA4_AUTOCOMMIT`. Replace `DATABASE_PATH` with `DATABASE_URL`.

10. **Replace Debug with Log.** Change `Debug.info()`, `Debug.error()` to `Log.info()`, `Log.error()`. Import from `tina4_python.debug`.

11. **Update CLI commands.** Replace `tina4` with `tina4python` in your scripts and Dockerfiles.

12. **Test your routes.** Start the server with `tina4python serve`. Hit each route. Check the error overlay for any remaining v2 references.

13. **Run your tests.** Execute `tina4python test` or `.venv/bin/python -m pytest tests/`.
