# Tina4 Python — This is not a framework

Laravel joy. Python speed. 10x less code.

## Quickstart

```bash
pip install tina4-python
tina4 init my_project
cd my_project
python app.py
```

You've just built your first Tina4 app — zero configuration, zero classes, zero boilerplate!

> **Prefer uv?** Replace `pip install tina4-python` with `uv add tina4-python`, then use `uv run tina4 start` to launch the dev server.

## Features

- **ASGI compliant** — works with any ASGI server (uvicorn, hypercorn, daphne)
- **Full async** — every route handler is `async` by default
- **Routing** — decorator-based with path parameters, type hints, and auto-discovery
- **Twig/Jinja2 templates** — with inheritance, partials, custom filters, and globals
- **tina4-css** — lightweight CSS framework (~24 KB) ships built-in, Bootstrap-compatible class names
- **ORM** — define models with typed fields, save/load/select/delete with one line
- **Database** — SQLite, PostgreSQL, MySQL, MariaDB, MSSQL, Firebird, MongoDB
- **Migrations** — versioned SQL files, CLI scaffolding
- **Data seeder** — zero-dependency fake data generation with ORM and table support
- **Sessions** — file, Redis, Valkey, or MongoDB backends
- **JWT authentication** — HS256 tokens signed with your `SECRET` env var, form tokens
- **Swagger/OpenAPI** — auto-generated docs at `/swagger`
- **CRUD scaffolding** — instant searchable admin UI with one line of code
- **GraphQL** — zero-dependency engine with ORM auto-schema and GraphiQL IDE
- **Middleware** — before/after hooks per route or globally
- **Queues** — background processing with litequeue, RabbitMQ, Kafka, or MongoDB
- **WebSockets** — built-in support via `simple-websocket`
- **WSDL/SOAP** — auto-generated WSDL from Python classes
- **REST client** — built-in `Api` class for external HTTP calls
- **SCSS compilation** — auto-compiled to CSS on save
- **Live reload** — browser auto-refreshes during development
- **Inline testing** — decorator-based test cases with `@tests`
- **Localization** — i18n via gettext (English, French, Afrikaans, Chinese, Japanese, Spanish)

## Install

```bash
pip install tina4-python
```

Or with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv add tina4-python
```

### Optional extras

Install only the database driver you need:

```bash
pip install tina4-python[postgres]    # PostgreSQL (psycopg2-binary)
pip install tina4-python[mysql]       # MySQL / MariaDB (mysql-connector-python)
pip install tina4-python[mssql]       # Microsoft SQL Server (pymssql)
pip install tina4-python[firebird]    # Firebird (firebird-driver)
pip install tina4-python[mongo]       # MongoDB (pymongo)
pip install tina4-python[all-db]      # all of the above
pip install tina4-python[dev-reload]  # hot-patching via jurigged
```

## Routing

Routes live in `src/routes/` and are auto-discovered on startup.

```python
# src/routes/hello.py
from tina4_python import get

@get("/hello")
async def get_hello(request, response):
    return response("Hello, Tina4 Python!")

@get("/hello/{name}")
async def get_hello_name(name, request, response):
    return response(f"Hello, {name}!")

@get("/hello/json")
async def get_hello_json(request, response):
    return response([{"brand": "BMW"}, {"brand": "Toyota"}])

@get("/hello/template")
async def get_hello_template(request, response):
    return response.render("index.twig", {"data": request.params})
```

## ORM

```python
# src/orm/User.py
from tina4_python import ORM, IntegerField, StringField

class User(ORM):
    id    = IntegerField(primary_key=True, auto_increment=True)
    name  = StringField()
    email = StringField()

User({"name": "Alice", "email": "alice@example.com"}).save()
```

## Database

```python
from tina4_python.Database import Database

db = Database("sqlite3:app.db")
db = Database("psycopg2:localhost/5432:mydb", "user", "password")      # PostgreSQL
db = Database("mysql.connector:localhost/3306:mydb", "user", "password") # MySQL
db = Database("pymongo:localhost/27017:mydb")                            # MongoDB

result = db.fetch("SELECT * FROM users WHERE age > ?", [18])
```

## Migrations

```bash
tina4 migrate:create "create users table"
# Edit the generated SQL file in migrations/
tina4 migrate
```

## Data Seeder

Generate fake data for development and testing:

```python
from tina4_python.Seeder import FakeData, seed_orm, seed_table

fake = FakeData()
fake.name()    # "Alice Johnson"
fake.email()   # "alice.johnson@example.com"
fake.phone()   # "+27 82 123 4567"

# Seed an ORM model
seed_orm(User, count=50)

# Seed a raw table
seed_table(db, "products", columns, count=100)
```

CLI:

```bash
tina4 seed                        # run all files in src/seeds/
tina4 seed:create "initial users" # scaffold a new seed file
```

## CRUD Scaffolding

Generate a searchable, paginated admin UI with one call:

```python
from tina4_python.CRUD import CRUD

@get("/admin/users")
async def admin_users(request, response):
    return response(CRUD.to_crud(request, {
        "sql": "SELECT id, name, email FROM users",
        "title": "User Management",
        "primary_key": "id",
    }))
```

## Sessions

Built-in session management with pluggable backends:

| Handler | Backend | Package |
|---------|---------|---------|
| `SessionFileHandler` (default) | File system | — |
| `SessionRedisHandler` | Redis | `redis` |
| `SessionValkeyHandler` | Valkey | `valkey` |
| `SessionMongoHandler` | MongoDB | `pymongo` |

```python
request.session.set("user_id", 42)
user_id = request.session.get("user_id")
```

## JWT Authentication

Tokens are signed with HS256 using your `SECRET` env var. Set it in `.env`:

```bash
SECRET=your-strong-random-secret-32-chars-min
```

```python
from tina4_python import tina4_auth

token = tina4_auth.get_token({"user_id": 42})
is_valid = tina4_auth.valid(token)
payload = tina4_auth.get_payload(token)
hashed = tina4_auth.hash_password("mypassword")
ok = tina4_auth.check_password(hashed, "mypassword")
```

## Queues

Background processing with litequeue (default), RabbitMQ, Kafka, or MongoDB.

```python
from tina4_python.Queue import Queue, Producer, Consumer

# Enqueue from a route
Producer(Queue(topic="emails")).produce({"to": "alice@example.com"})

# Process in a worker
for msg in Consumer(Queue(topic="emails")).messages():
    send_email(msg.data)
```

## GraphQL

Zero-dependency GraphQL engine with ORM auto-schema:

```python
from tina4_python.GraphQL import GraphQL

gql = GraphQL()
gql.schema.from_orm(User)     # auto-generates type, queries, and mutations
gql.schema.from_orm(Product)
gql.register_route("/graphql") # GET = GraphiQL IDE, POST = queries
```

## Middleware

```python
from tina4_python.Router import get, middleware

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

## Swagger / OpenAPI

Auto-generated at `/swagger`. Add metadata with decorators:

```python
from tina4_python import description, tags

@get("/users")
@description("Get all users")
@tags(["users"])
async def users(request, response):
    return response(User().select("*"))
```

## REST Client

```python
from tina4_python import Api

api = Api("https://api.example.com", auth_header="Bearer xyz")
result = api.send_request("/users/42")
```

## WSDL / SOAP

```python
from tina4_python.WSDL import WSDL, wsdl_operation
from tina4_python import get, post

class Calculator(WSDL):
    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}

@get("/calculator")
@post("/calculator")
async def calculator(request, response):
    return response(Calculator(request).handle())
```

## Inline Testing

```python
from tina4_python import tests, assert_equal, assert_raises

@tests(
    assert_equal((7, 7), 1),
    assert_raises(ZeroDivisionError, (5, 0)),
)
def divide(a: int, b: int) -> float:
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b
```

Run with `tina4 test` or `uv run pytest`.

## Environment

Key `.env` settings:

```bash
SECRET=your-jwt-secret-32-chars-min
API_KEY=your-api-key
DATABASE_NAME=sqlite3:app.db
TINA4_DEBUG_LEVEL=ALL
TINA4_LANGUAGE=en
TINA4_SESSION_HANDLER=SessionFileHandler
SWAGGER_TITLE=My API
```

## Further Documentation

https://tina4.com/python

## Community

- GitHub: https://github.com/tina4stack/tina4-python

## License

MIT (c) 2007-2025 Tina4 Stack
https://opensource.org/licenses/MIT

---

**Tina4** — The framework that keeps out of the way of your coding.

---

## Our Sponsors

**Sponsored with 🩵 by Code Infinity**

[<img src="https://codeinfinity.co.za/wp-content/uploads/2025/09/c8e-logo-github.png" alt="Code Infinity" width="100">](https://codeinfinity.co.za/about-open-source-policy?utm_source=github&utm_medium=website&utm_campaign=opensource_campaign&utm_id=opensource)

*Supporting open source communities <span style="color: #1DC7DE;">•</span> Innovate <span style="color: #1DC7DE;">•</span> Code <span style="color: #1DC7DE;">•</span> Empower*
