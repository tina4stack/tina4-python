<p align="center">
  <img src="https://tina4.com/logo.svg" alt="Tina4" width="200">
</p>

<h1 align="center">Tina4 Python</h1>
<h3 align="center">This is not a framework</h3>

<p align="center">
  Laravel joy. Python speed. 10x less code. Zero third-party dependencies.
</p>

<p align="center">
  <a href="https://tina4.com">Documentation</a> &bull;
  <a href="#getting-started">Getting Started</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="#cli-reference">CLI Reference</a> &bull;
  <a href="https://tina4.com">tina4.com</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-3.0.0-blue" alt="Version 3.0.0">
  <img src="https://img.shields.io/badge/tests-1633%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/carbonah-A%2B%20rated-00cc44" alt="Carbonah A+">
  <img src="https://img.shields.io/badge/zero--dep-core-blue" alt="Zero Dependencies">
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT License">
</p>

---

## Quickstart

```bash
pip install tina4-python
tina4python init my-app
cd my-app
tina4python serve
# -> http://localhost:7145
```

That's it. Zero configuration, zero classes, zero boilerplate.

> **Prefer uv?** Replace `pip install tina4-python` with `uv add tina4-python`, then use `uv run tina4python serve`.

---

## What's Included

Every feature is built from scratch -- no pip install, no node_modules, no third-party runtime dependencies in core.

| Category | Features |
|----------|----------|
| **HTTP** | ASGI server, decorator routing, path params (`{id:int}`, `{p:path}`), middleware pipeline, CORS, rate limiting, graceful shutdown |
| **Templates** | Frond engine (Twig-compatible), inheritance, partials, 35+ filters, macros, fragment caching, sandboxing |
| **ORM** | Active Record, typed fields with validation, soft delete, relationships (`has_one`/`has_many`/`belongs_to`), scopes, result caching, multi-database |
| **Database** | SQLite, PostgreSQL, MySQL, MSSQL, Firebird -- unified adapter interface, query caching (TINA4_DB_CACHE=true for 4x speedup) |
| **Auth** | Zero-dep JWT (HS256), sessions (file/Redis/Valkey/MongoDB/database), password hashing, form tokens |
| **API** | Swagger/OpenAPI auto-generation, GraphQL with ORM auto-schema and GraphiQL IDE, WSDL/SOAP with auto WSDL |
| **Background** | Queue (SQLite/RabbitMQ/Kafka) with priority, delayed jobs, retry, batch processing |
| **Real-time** | Native asyncio WebSocket (RFC 6455), per-path routing, connection manager |
| **Frontend** | tina4-css (~24 KB), frond.js helper, SCSS compiler, live reload, CSS hot-reload |
| **DX** | Dev admin dashboard (11 tabs), error overlay, request inspector, AI tool integration, Carbonah green benchmarks |
| **Data** | Migrations with rollback, 50+ fake data generators, ORM and table seeders |
| **Mail** | SMTP send (plain/HTML/attachments), IMAP read/search, dev mailbox capture |
| **Other** | REST client, localization (6 languages), cache (memory/Redis/file), event system, inline testing, messenger (.env driven), configurable error pages, HTML element builder |

**1,633 tests across 38 built-in features. Zero dependencies. All Carbonah benchmarks rated A+.**

For full documentation visit **[tina4.com](https://tina4.com)**.

---

## Install

```bash
pip install tina4-python
```

Or with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv add tina4-python
```

### Optional database drivers

Install only what you need:

```bash
pip install tina4-python[postgres]    # PostgreSQL (psycopg2-binary)
pip install tina4-python[mysql]       # MySQL / MariaDB (mysql-connector-python)
pip install tina4-python[mssql]       # Microsoft SQL Server (pymssql)
pip install tina4-python[firebird]    # Firebird (firebird-driver)
pip install tina4-python[mongo]       # MongoDB (pymongo)
pip install tina4-python[odbc]        # ODBC (pyodbc)
pip install tina4-python[all-db]      # All of the above
pip install tina4-python[dev-reload]  # Hot-patching via jurigged
```

---

## Getting Started

### 1. Create a project

```bash
tina4python init my-app
cd my-app
```

This creates:

```
my-app/
├── app.py              # Entry point
├── .env                # Configuration
├── src/
│   ├── routes/         # API + page routes (auto-discovered)
│   ├── orm/            # Database models
│   ├── app/            # Service classes and shared helpers
│   ├── templates/      # Frond/Twig templates
│   ├── seeds/          # Database seeders
│   ├── scss/           # SCSS (auto-compiled to public/css/)
│   └── public/         # Static assets served at /
├── migrations/         # SQL migration files
└── tests/              # pytest tests
```

### 2. Create a route

Create `src/routes/hello.py`:

```python
from tina4_python.core.router import get, post

@get("/api/hello")
async def hello(request, response):
    return response({"message": "Hello from Tina4!"})

@get("/api/hello/{name}")
async def hello_name(name, request, response):
    return response({"message": f"Hello, {name}!"})
```

Visit `http://localhost:7145/api/hello` -- routes are auto-discovered, no imports needed.

### 3. Add a database

Edit `.env`:

```bash
DATABASE_URL=sqlite:///data/app.db
```

Create and run a migration:

```bash
tina4python migrate:create "create users table"
```

Edit the generated SQL:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

```bash
tina4python migrate
```

### 4. Create an ORM model

Create `src/orm/User.py`:

```python
from tina4_python.orm import ORM, IntegerField, StringField, DateTimeField

class User(ORM):
    table_name = "users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True, min_length=1, max_length=100)
    email = StringField(regex=r'^[^@]+@[^@]+\.[^@]+$')
    created_at = DateTimeField()
```

### 5. Build a REST API

Create `src/routes/users.py`:

```python
from tina4_python.core.router import get, post, noauth

@get("/api/users")
async def list_users(request, response):
    from src.orm.User import User
    return response(User().select(limit=100).to_array())

@get("/api/users/{id:int}")
async def get_user(id, request, response):
    from src.orm.User import User
    user = User()
    if user.load("id = ?", [id]):
        return response(user.to_dict())
    return response({"error": "Not found"}, 404)

@noauth()
@post("/api/users")
async def create_user(request, response):
    from src.orm.User import User
    user = User(request.body)
    user.save()
    return response(user.to_dict(), 201)
```

### 6. Add a template

Create `src/templates/base.twig`:

```twig
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}My App{% endblock %}</title>
    <link rel="stylesheet" href="/css/tina4.min.css">
    {% block stylesheets %}{% endblock %}
</head>
<body>
    {% block content %}{% endblock %}
    <script src="/js/frond.js"></script>
    {% block javascripts %}{% endblock %}
</body>
</html>
```

Create `src/templates/pages/home.twig`:

```twig
{% extends "base.twig" %}
{% block content %}
<div class="container mt-4">
    <h1>{{ title }}</h1>
    <ul>
    {% for user in users %}
        <li>{{ user.name }} -- {{ user.email }}</li>
    {% endfor %}
    </ul>
</div>
{% endblock %}
```

Render it from a route:

```python
@get("/")
async def home(request, response):
    from src.orm.User import User
    users = User().select(limit=20).to_array()
    return response.render("pages/home.twig", {"title": "Users", "users": users})
```

### 7. Seed, test, deploy

```bash
tina4python seed                          # Run seeders from src/seeds/
tina4python test                          # Run test suite
tina4python build                         # Build distributable
```

For the complete step-by-step guide, visit **[tina4.com](https://tina4.com)**.

---

## Features

### Routing

```python
from tina4_python.core.router import get, post, put, delete, noauth, secured, middleware

@get("/api/items")               # Public by default
async def list_items(request, response):
    return response({"items": []})

@noauth()                         # Make a write route public
@post("/api/webhook")
async def webhook(request, response):
    return response({"ok": True})

@secured()                        # Protect a GET route
@get("/api/admin/stats")
async def admin_stats(request, response):
    return response({"secret": True})
```

Path parameter types: `{id}` (string), `{id:int}`, `{price:float}`, `{path:path}` (greedy).

### ORM

Active Record with typed fields, validation, soft delete, relationships, scopes, and multi-database support.

```python
from tina4_python.orm import ORM, IntegerField, StringField, Field, orm_bind

class User(ORM):
    table_name = "users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True, min_length=1, max_length=100)
    email = StringField(regex=r'^[^@]+@[^@]+\.[^@]+$')
    role = StringField(choices=["admin", "user", "guest"], default="user")
    age = Field(int, min_value=0, max_value=150)

# CRUD
user = User({"name": "Alice", "email": "alice@example.com"})
user.save()
user.load("email = ?", ["alice@example.com"])
user.delete()

# Relationships
orders = user.has_many("Order", "user_id")
profile = user.has_one("Profile", "user_id")

# Soft delete, scopes, caching
user.soft_delete()
active_admins = User.scope("active").scope("admin").select()
users = User.cached("SELECT * FROM users", ttl=300)

# Multi-database
orm_bind(main_db)                     # Default
orm_bind(audit_db, name="audit")      # Named

class AuditLog(ORM):
    _db = "audit"                     # Uses named connection
```

### Database

Unified interface across 7 engines:

```python
from tina4_python.database.connection import Database

db = Database("sqlite:///data/app.db")
db = Database("postgresql://user:pass@localhost:5432/mydb")
db = Database("mysql://user:pass@localhost:3306/mydb")
db = Database("mssql://sa:pass@localhost:1433/mydb")
db = Database("firebird://SYSDBA:masterkey@localhost:3050//path/to/db")
db = Database("mongodb://localhost:27017/mydb")
db = Database("odbc://DSN=mydsn")

result = db.fetch("SELECT * FROM users WHERE age > ?", [18], limit=20, skip=0)
row = db.fetch_one("SELECT * FROM users WHERE id = ?", [1])
db.insert("users", {"name": "Alice", "email": "alice@test.com"})
db.commit()
```

### Middleware

```python
class AuthCheck:
    @staticmethod
    def before_auth(request, response):
        if "authorization" not in request.headers:
            return request, response("Unauthorized", 401)
        return request, response

@middleware(AuthCheck)
@get("/protected")
async def protected(request, response):
    return response({"secret": True})
```

### JWT Authentication

```python
from tina4_python.auth import Auth

auth = Auth(secret="your-secret")
token = auth.create_token({"user_id": 42})
payload = auth.validate_token(token)
```

POST/PUT/PATCH/DELETE routes require `Authorization: Bearer <token>` by default. Use `@noauth()` to make public, `@secured()` to protect GET routes.

### Sessions

```python
request.session.set("user_id", 42)
user_id = request.session.get("user_id")
```

Backends: file (default), Redis, Valkey, MongoDB, database. Set via `TINA4_SESSION_HANDLER` in `.env`.

### Queues

```python
from tina4_python.queue import Queue, Producer, Consumer

Producer(Queue(topic="emails")).produce({"to": "alice@example.com"})

for msg in Consumer(Queue(topic="emails")).messages():
    send_email(msg.data)
```

### GraphQL

```python
from tina4_python.graphql import GraphQL

gql = GraphQL()
gql.schema.from_orm(User)
gql.register_route("/graphql")   # GET = GraphiQL IDE, POST = queries
```

### WebSocket

```python
from tina4_python.websocket import WebSocketManager

ws = WebSocketManager()

@ws.route("/ws/chat")
async def chat(connection, message):
    await ws.broadcast("/ws/chat", f"User said: {message}")
```

### Swagger / OpenAPI

Auto-generated at `/swagger`:

```python
@description("Get all users")
@tags(["users"])
@get("/api/users")
async def users(request, response):
    return response(User().select().to_array())
```

### Event System

```python
from tina4_python.core.events import on, emit, once

@on("user.created", priority=10)
def notify_admin(user):
    send_notification(f"New user: {user['name']}")

emit("user.created", {"name": "Alice"})
```

### Template Engine (Frond)

Twig-compatible, 35+ filters, macros, inheritance, fragment caching, sandboxing:

```twig
{% extends "base.twig" %}
{% block content %}
<h1>{{ title | upper }}</h1>
{% for item in items %}
    <p>{{ item.name }} -- {{ item.price | number_format(2) }}</p>
{% endfor %}

{% cache "sidebar" 300 %}
    {% include "partials/sidebar.twig" %}
{% endcache %}
{% endblock %}
```

### CRUD Scaffolding

```python
@get("/admin/users")
async def admin_users(request, response):
    return response(CRUD.to_crud(request, {
        "sql": "SELECT id, name, email FROM users",
        "title": "User Management",
        "primary_key": "id",
    }))
```

### WSDL / SOAP

```python
from tina4_python.wsdl import WSDL, wsdl_operation

class Calculator(WSDL):
    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}
```

### REST Client

```python
from tina4_python.api import Api

api = Api("https://api.example.com", auth_header="Bearer xyz")
result = api.send_request("/users/42")
```

### Data Seeder

```python
from tina4_python.seeder import FakeData, seed_orm

fake = FakeData()
fake.name()      # "Alice Johnson"
fake.email()     # "alice.johnson@example.com"

seed_orm(User, count=50)
```

### Email / Messenger

```python
from tina4_python.messenger import create_messenger

mail = create_messenger()
mail.send(to="user@test.com", subject="Welcome", body="<h1>Hi!</h1>", html=True)
```

### In-Memory Cache

```python
from tina4_python.core.cache import Cache

cache = Cache()
cache.set("key", "value", ttl=300)
cache.tag("users").flush()
```

### SCSS, Localization, Inline Testing

- **SCSS**: Drop `.scss` in `src/scss/` -- auto-compiled to CSS. Variables, nesting, mixins, `@import`, `@extend`.
- **i18n**: JSON translation files, 6 languages (en, fr, af, zh, ja, es), placeholder interpolation.
- **Inline tests**: `@tests(assert_equal((5, 3), 8))` decorator on any function.

---

## Dev Mode

Set `TINA4_DEBUG=true` in `.env` to enable:

- **Live reload** -- browser auto-refreshes on code changes
- **CSS hot-reload** -- SCSS changes apply without page refresh
- **Error overlay** -- rich error display in the browser
- **Dev admin** at `/__dev/` with 11 tabs: Routes, Queue, Mailbox, Messages, Database, Requests, Errors, WebSocket, System, Tools, Tina4

---

## CLI Reference

```bash
tina4python init [dir]             # Scaffold a new project
tina4python serve [port]           # Start dev server (default: 7145)
tina4python serve --production     # Auto-install and use best production server (uvicorn)
tina4python migrate                # Run pending migrations
tina4python migrate:create <desc>  # Create a migration file
tina4python migrate:rollback       # Rollback last batch
tina4python generate model <name>  # Generate ORM model scaffold
tina4python generate route <name>  # Generate route scaffold
tina4python generate migration <d> # Generate migration file
tina4python generate middleware <n># Generate middleware scaffold
tina4python seed                   # Run seeders from src/seeds/
tina4python routes                 # List all registered routes
tina4python test                   # Run test suite
tina4python build                  # Build distributable package
tina4python ai [--all]             # Detect AI tools and install context
```

### Production Server Auto-Detection

`tina4 serve` automatically detects and uses the best available production server:

- **Python**: uvicorn (if installed), otherwise built-in asyncio
- Use `tina4python serve --production` to auto-install the production server

### Scaffolding with `tina4 generate`

Quickly scaffold new components:

```bash
tina4python generate model User          # Creates src/orm/User.py with field stubs
tina4python generate route users         # Creates src/routes/users.py with CRUD stubs
tina4python generate migration "add age" # Creates migration SQL file
tina4python generate middleware AuthLog   # Creates middleware class
```

### ORM Relationships & Eager Loading

```python
# Define relationships
orders = user.has_many("Order", "user_id")
profile = user.has_one("Profile", "user_id")
customer = order.belongs_to("Customer", "customer_id")

# Eager loading with include=
users = User().select(include=["orders", "profile"])
```

### DB Query Caching

Enable query caching for up to 4x speedup on read-heavy workloads:

```bash
# .env
TINA4_DB_CACHE=true
```

```python
# Check cache stats
from tina4_python.orm import cache_stats, cache_clear
stats = cache_stats()   # {"hits": 42, "misses": 7, "size": 15}
cache_clear()           # Flush all cached queries
```

### Frond Pre-Compilation

Templates are pre-compiled for 2.8x faster rendering. Clear the cache when needed:

```python
from tina4_python.frond import Frond
Frond.clear_cache()
```

### Gallery

7 interactive examples with **Try It** deploy — visit the dev admin at `/__dev/` to explore.

## Environment

```bash
SECRET=your-jwt-secret
DATABASE_URL=sqlite:///data/app.db
TINA4_DEBUG=true                     # Enable dev toolbar, error overlay
TINA4_LOG_LEVEL=ALL                  # ALL, DEBUG, INFO, WARNING, ERROR
TINA4_LANGUAGE=en                    # en, fr, af, zh, ja, es
TINA4_SESSION_HANDLER=SessionFileHandler
SWAGGER_TITLE=My API
```

## AI Tool Integration

```bash
tina4python ai              # Detect and install context
tina4python ai --all        # Install for ALL supported tools
```

Supported: Claude Code, Cursor, GitHub Copilot, Windsurf, Aider, Cline, OpenAI Codex CLI. Generates framework-aware context so AI assistants understand Tina4's conventions.

## Carbonah Green Benchmarks

All 9 benchmarks rated **A+** (South Africa grid, 1000 iterations each):

| Benchmark | SCI (gCO2eq) | Grade |
|-----------|-------------|-------|
| JSON Hello World | 0.000864 | A+ |
| Single DB Query | 0.000538 | A+ |
| Multiple DB Queries | 0.001350 | A+ |
| Template Rendering | 0.003237 | A+ |
| Large JSON Payload | 0.000983 | A+ |
| Plaintext Response | 0.000377 | A+ |
| CRUD Cycle | 0.000456 | A+ |
| Paginated Query | 0.000990 | A+ |
| Framework Startup | 0.000801 | A+ |

Run locally: `python benchmarks/run_carbonah.py`

---

## Documentation

Full guides, API reference, and examples at **[tina4.com](https://tina4.com)**.

## License

MIT (c) 2007-2026 Tina4 Stack
https://opensource.org/licenses/MIT

---

<p align="center"><b>Tina4</b> -- The framework that keeps out of the way of your coding.</p>

---

## Our Sponsors

**Sponsored with 🩵 by Code Infinity**

[<img src="https://codeinfinity.co.za/wp-content/uploads/2025/09/c8e-logo-github.png" alt="Code Infinity" width="100">](https://codeinfinity.co.za/about-open-source-policy?utm_source=github&utm_medium=website&utm_campaign=opensource_campaign&utm_id=opensource)

*Supporting open source communities <span style="color: #1DC7DE;">•</span> Innovate <span style="color: #1DC7DE;">•</span> Code <span style="color: #1DC7DE;">•</span> Empower*
