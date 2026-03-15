# Tina4 Python — Developer Guidelines

This file helps AI assistants and new developers understand how to build with tina4_python.

## What is Tina4?

Tina4 Python is a lightweight, batteries-included web framework that prioritises convention over configuration. It provides routing, templating (Twig/Jinja2), ORM, database migrations, session management, JWT authentication, Swagger/OpenAPI generation, CRUD scaffolding, queues, WebSockets, WSDL/SOAP support, and SCSS compilation — all out of the box with zero boilerplate.

**Official documentation:** https://tina4.com/python — consult this for detailed guides, examples, and API reference beyond what is covered here.

**Key philosophy:** Tina4 already provides solutions for most common web application needs. Always use the framework's built-in features before writing custom implementations. If you're about to write something from scratch (a queue system, an HTTP client, auth logic, etc.), stop and check if Tina4 already has it — it almost certainly does.

---

## IMPORTANT: Coding Principles for AI Assistants

When building with Tina4, follow these principles strictly:

### 1. DRY — Never Copy-Paste Code

Every piece of repeated logic must be centralised. If two routes format a date, create a Twig filter or a helper function in `app.py` — do NOT duplicate the logic.

**Bad — duplicated formatting in every route:**
```python
@get("/api/orders")
async def list_orders(request, response):
    orders = Order().select().to_array()
    for o in orders:
        o["total"] = f"${abs(float(o['total'])):,.2f}"  # duplicated
    return response(orders)

@get("/api/invoices")
async def list_invoices(request, response):
    invoices = Invoice().select().to_array()
    for i in invoices:
        i["amount"] = f"${abs(float(i['amount'])):,.2f}"  # duplicated!
    return response(invoices)
```

**Good — centralised in app.py as a Twig filter:**
```python
# app.py
from tina4_python.Template import Template

def _money_filter(value):
    try:
        val = float(value or 0)
        sign = "-" if val < 0 else ""
        return f"{sign}{abs(val):,.2f}"
    except (ValueError, TypeError):
        return "0.00"

Template.add_filter("money", _money_filter)
```
Then in templates: `{{ order.total | money }}`

### 2. Use Template Inheritance — Always

Every HTML page must extend a base template. Never produce standalone HTML files with repeated `<head>`, nav bars, or footers.

- Create `src/templates/base.twig` with the full page shell
- Create partial templates for reusable UI components (nav, sidebar, cards)
- Use `{% block %}` for page-specific content
- Use `{% include %}` for reusable partials

### 3. Always Add Placeholders to Form Inputs

**Every** `<input>`, `<textarea>`, and `<select>` element must have a meaningful `placeholder` attribute that tells the user what to enter. Inputs without placeholders look incomplete and hurt usability.

**Bad — no placeholders:**
```twig
<input type="text" name="email" class="form-control">
<input type="text" name="phone" class="form-control">
```

**Good — descriptive placeholders:**
```twig
<input type="email" name="email" class="form-control" placeholder="you@example.com">
<input type="tel" name="phone" class="form-control" placeholder="+27 82 123 4567">
```

Rules:
- Use realistic example values as placeholders (e.g. `placeholder="you@example.com"`) rather than repeating the label (e.g. `placeholder="Email"`)
- Use the correct `type` attribute (`email`, `tel`, `url`, `number`, `date`, etc.) — never use `type="text"` for structured data
- Always include `<label>` elements alongside inputs for accessibility

### 4. No Inline Styles — Use SCSS/CSS Classes

Never use `style="..."` attributes in Twig templates. All styling must live in SCSS files under `src/scss/` (compiled to `src/public/css/`) or in external CSS. Inline styles are unmaintainable, cannot be overridden cleanly, and bypass the framework's SCSS workflow.

**Bad — inline styles:**
```twig
<div style="background: #2c3e50; padding: 20px; border-radius: 8px;">
    <h1 style="color: white; font-size: 2rem;">Dashboard</h1>
</div>
```

**Good — use CSS classes:**
```twig
<div class="dashboard-header">
    <h1 class="dashboard-title">Dashboard</h1>
</div>
```
```scss
// src/scss/dashboard.scss
.dashboard-header {
    background: $primary;
    padding: 1.25rem;
    border-radius: 0.5rem;
}

.dashboard-title {
    color: $white;
    font-size: 2rem;
}
```

Rules:
- Use Bootstrap 5 utility classes (e.g. `mt-4`, `text-center`, `d-flex`) for spacing, alignment, and layout instead of inline styles
- Use SCSS variables for colours, spacing, and font sizes — never hardcode hex values in templates
- One SCSS file per page or component (e.g. `dashboard.scss`, `user-card.scss`)
- Prefer semantic class names (`.product-card`, `.nav-sidebar`) over generic ones (`.box`, `.wrapper`)

### 5. Centralise Configuration in app.py

`app.py` is the single entry point. Register all custom filters, global functions, middleware classes, and ORM setup here — before `run_web_server()`.

```python
# app.py
import tina4_python
from tina4_python import run_web_server, orm
from tina4_python.Template import Template
from tina4_python.Database import Database

# 1. Database & ORM
db = Database("sqlite3:app.db")
orm(db)

# 2. Custom Twig filters
Template.add_filter("money", lambda v: f"{float(v or 0):,.2f}")
Template.add_filter("initials", lambda name: "".join(w[0].upper() for w in name.split() if w))

# 3. Custom Twig globals (available in every template)
Template.add_global("APP_NAME", "My Application")
Template.add_global("APP_VERSION", "1.0.0")

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
```

### 6. Use the Api Class for External HTTP Calls

Never use raw `requests` or `urllib` directly. Use the built-in `Api` class — it handles auth headers, JSON serialisation, error handling, and SSL consistently.

### 7. Use Queues for Long-Running Work

Route handlers must respond fast. Any operation that takes more than a second (sending emails, generating reports, calling slow external APIs, processing files) must be pushed to a Queue and processed by a Consumer.

**Bad — blocking the request:**
```python
@post("/api/reports")
async def generate_report(request, response):
    data = fetch_all_data()      # 10 seconds
    pdf = render_pdf(data)        # 5 seconds
    send_email(pdf)               # 3 seconds
    return response({"ok": True}) # User waited 18 seconds!
```

**Good — queue it:**
```python
@post("/api/reports")
async def generate_report(request, response):
    producer = Producer(Queue(topic="reports"))
    producer.produce({"user_id": request.body["user_id"], "type": "monthly"})
    return response({"status": "queued"})
```

### 8. One Responsibility Per File

- One route resource per file in `src/routes/` (e.g., `users.py`, `products.py`)
- One ORM model per file in `src/orm/` (filename matches class name)
- Shared helpers go in `src/app/` (utility modules, service classes)

### 9. Always Use Migrations for Database Changes

**Every** schema change — creating tables, adding columns, modifying indexes, inserting seed data — **must** go through a migration file. Never execute raw DDL in route handlers, app.py, or one-off scripts. Migrations are the single source of truth for the database schema and ensure changes are repeatable, versioned, and safe across environments.

**Bad — creating tables directly in code:**
```python
# app.py
db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
```

**Good — create a migration:**
```bash
uv run tina4 migrate:create "create users table"
```
```sql
-- migrations/000001_create_users_table.sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
```
```bash
uv run tina4 migrate
```

Rules:
- One logical change per migration file (don't mix unrelated schema changes)
- Never modify an existing migration that has already been run — create a new one
- Use `ORM.create_table()` only for rapid prototyping; production schemas must use migrations
- When adding ORM models, always create a corresponding migration for the table
- Run `uv run tina4 migrate` after creating migration files to apply them

### 10. Use Tina4 Built-in Features — Never Reinvent

Tina4 provides a full toolkit. Before writing custom code, check if the framework already solves the problem. **Never** build your own version of something Tina4 already provides.

| Need | Use this — don't build your own |
|------|--------------------------------|
| Background jobs / async work | `Queue`, `Producer`, `Consumer` from `tina4_python.Queue` |
| HTTP calls to external APIs | `Api` from `tina4_python.Api` |
| JWT tokens & auth | `tina4_python.tina4_auth` (get_token, valid, get_payload) |
| Password hashing | `tina4_python.tina4_auth.hash_password()` / `check_password()` |
| Session management | `request.session` (set, get, unset, close) |
| Database queries & CRUD | `Database` from `tina4_python.Database` |
| ORM models | Subclass `ORM` from `tina4_python` |
| Template rendering | `response.render()` with Twig/Jinja2 |
| Form token validation | `{{ form_token() }}` in templates + built-in middleware |
| CRUD admin interfaces | `result.to_crud(request)` or `CRUD.to_crud()` |
| Swagger/OpenAPI docs | `@description()`, `@tags()`, `@example()` decorators |
| SOAP/WSDL services | `WSDL` class from `tina4_python.WSDL` |
| Database migrations | `tina4 migrate:create` + `tina4 migrate` |
| WebSockets | `Websocket` from `tina4_python.Websocket` |
| SCSS compilation | Drop `.scss` in `src/scss/` — auto-compiled |
| Static file serving | Put files in `src/public/` — auto-served |
| Translations / i18n | `localize()` from `tina4_python.Localization` |
| HTML generation in code | `HTMLElement` from `tina4_python.HtmlElement` |
| Inline testing | `@tests`, `assert_equal`, `assert_raises` from `tina4_python.Testing` |

**Bad — writing a custom queue:**
```python
import threading, queue
task_queue = queue.Queue()  # Don't do this!
```

**Good — use Tina4's Queue:**
```python
from tina4_python.Queue import Queue, Producer
Producer(Queue(topic="tasks")).produce({"action": "send_email"})
```

### 11. Key tina4_python Gotchas

1. **Database import**: Use `from tina4_python.Database import Database` (NOT `from tina4_python import Database`)
2. **noauth/secured import**: Use `from tina4_python import noauth` or `from tina4_python.Router import noauth` (there is NO `tina4_python.Decorators` module). **Never** import `noauth` from `tina4_python.Swagger` — that version only affects documentation, not actual auth.
2b. **Decorator ordering**: Route decorators (`@get`, `@post`, etc.) must be the **innermost** (closest to the function). Swagger/meta decorators (`@description`, `@tags`, `@noauth`, `@secured`) go above. Correct: `@noauth()` → `@description(...)` → `@post(...)` → `def handler`. Wrong: `@post(...)` → `@description(...)` → `def handler` (will crash).
3. **Jinja2 template syntax** (common mistakes):
    - **No ternary operator**: Use `{% if x %}...{% endif %}` NOT `{{ x ? 'a' : 'b' }}`
    - **elif not elseif**: Use `{% elif %}` NOT `{% elseif %}`
    - **safe not raw**: Use `{{ var | safe }}` NOT `{{ var | raw }}` for unescaped output
    - **format filter**: Use `{{ "%.2f" | format(value) }}` for number formatting
    - **e() filter has NO arguments**: Use `{{ var|e }}` NOT `{{ var|e('js') }}` — Jinja2's `|e` is HTML-only with no mode parameter (that's PHP Twig syntax)
    - **JS string escaping**: Use `{{ var|replace("'", "\\'") }}` to escape single quotes for inline JS onclick handlers
    - **No `|escape('js')` or `|e('js')`**: These will throw `escape() takes 1 positional argument but 2 were given`
    - **Ternary inline**: Use `{{ 's' if count != 1 else '' }}` NOT `{{ count != 1 ? 's' : '' }}`
    - **Default values**: Use `{{ var|default('fallback') }}` — works on undefined and None
    - **Chaining filters**: `{{ var|default('')|replace("'", "\\'") }}` — left to right
    - **Loop variables**: `loop.index` (1-based), `loop.index0` (0-based), `loop.first`, `loop.last`, `loop.length`
    - **Whitespace control**: `{%- -%}` and `{{- -}}` trim surrounding whitespace
    - **String concatenation**: Use `~` operator: `{{ "hello " ~ name }}` NOT `{{ "hello " + name }}`
    - **include with context**: `{% include "partial.twig" %}` inherits parent context automatically
    - **Macro imports**: `{% from "macros/forms.twig" import field_group %}` — macros do NOT inherit parent context, pass variables explicitly
4. **DatabaseResult**: `dba.fetch()` returns a `DatabaseResult` object, NOT a plain list
    - Use `.records` to get list of dicts: `result.records`
    - Use `.count` for row count (no `len()` support)
    - Iteration works: `for row in result` or `list(result)`
    - Other methods: `.to_json()`, `.to_array()`, `.to_csv()`, `.to_paginate()`
4. **fetch_one()**: Returns a plain dict (or None), NOT a DatabaseResult
5. **Dict access**: All query results use dict access `row["column"]` not attribute access `row.column`
6. **Firebird connection string**: `firebird.driver:<host>/<port>:<database_path>` — note the `firebird.driver:` prefix (the module name), NOT `firebird:`
6b. **MongoDB connection string**: `pymongo:<host>/<port>:<database_name>` — uses the same SQL API as all other engines (SQL is translated to MongoDB queries internally). JOINs are not supported. Install: `pip install pymongo`
7. **Running the app**: `uv run python app.py <port> <name>` — port and name are CLI args handled by tina4_python
8. **SCSS**: Files in `src/scss/` are auto-compiled to `src/public/css/` on startup


---

## Project Structure

```
project/
├── app.py                  # Entry point — filters, ORM, run_web_server()
├── .env                    # Environment variables
├── migrations/             # SQL migration files (000001_description.sql)
├── src/
│   ├── __init__.py         # Runs on import (optional, for legacy manual imports)
│   ├── app/                # Shared helpers and service classes
│   ├── routes/             # Route handlers (one file per resource)
│   ├── orm/                # ORM model classes (one file per model)
│   ├── templates/          # Twig/Jinja2 templates
│   ├── public/             # Static files served at / (css/, js/, images/)
│   └── scss/               # SCSS files — auto-compiled to src/public/css/
└── secrets/                # Auto-generated RSA keys for JWT (do not commit)
```

## Starting the Server

```python
# app.py
from tina4_python import run_web_server

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
```

`run_web_server()` automatically discovers and imports all Python files in `src/` — no manual imports needed. Route decorators (`@get`, `@post`, etc.) register themselves on import.

**Auto-start:** If your script does NOT call `run_web_server()` and has no `main()` function, Tina4 will auto-start on port 7145. When you call `run_web_server()` explicitly, auto-start is disabled.

### Package Manager

```bash
uv add tina4-python          # Add dependency
uv run tina4 start            # Start dev server on port 7145
uv run tina4 init .           # Scaffold project structure
uv run tina4 migrate          # Run pending SQL migrations
uv run tina4 migrate:create "description"  # Create a migration file
```

## Development Mode (DevReload)

Set `TINA4_DEBUG_LEVEL=ALL` or `DEBUG` in `.env` to enable development features:

- **Live-reload** — Browser auto-refreshes when `.py`, `.twig`, `.html`, or `.js` files change
- **CSS hot-reload** — SCSS/CSS changes refresh stylesheets without full page reload
- **SCSS auto-compile** — `.scss` files in `src/scss/` are compiled to `src/public/css/` on save
- **Error overlay** — Runtime errors display a rich, syntax-highlighted overlay in the browser
- **Hot-patching** — Python code changes are live-patched via jurigged (no server restart)

DevReload connects via WebSocket at `/__dev_reload`. No configuration needed.

## Routing

Routes are auto-discovered from `src/routes/`. Each file defines handlers with decorators.

```python
from tina4_python.Router import get, post, put, delete, patch

@get("/api/users")
async def list_users(request, response):
    return response({"users": []})

@get("/api/users/{id:int}")
async def get_user(id, request, response):
    return response({"id": id})

@post("/api/users")
async def create_user(request, response):
    data = request.body  # Already parsed as dict for JSON
    return response({"created": True}, 201)
```

### Path parameter types
- `{id}` — string
- `{id:int}` — integer (auto-converted)
- `{price:float}` — float
- `{path:path}` — greedy, matches remaining path segments

### Auth defaults
- **GET** routes are public
- **POST/PUT/PATCH/DELETE** require `Authorization: Bearer <token>`
- Use `@noauth()` to make a write route public
- Use `@secured()` to protect a GET route
- Make sure you use formToken filter in forms when you need to POST data.

```python
from tina4_python.Router import post, get, noauth, secured

@noauth()
@description("Public webhook")
@post("/api/webhook")
async def public_webhook(request, response):
    return response({"ok": True})

@secured()
@get("/api/admin/stats")
async def protected_get(request, response):
    return response({"secret": True})
```

**Decorator order** (outermost → innermost): `@noauth`/`@secured` → `@description`/`@tags`/`@example` → `@get`/`@post`/`@put`/`@delete`

## Request Object

```python
request.body        # Parsed request body (dict for JSON, dict for form data)
request.params      # Query string parameters (dict)
request.headers     # HTTP headers (dict, lowercase keys)
request.files       # Uploaded files (dict, values are base64-encoded dicts)
request.url         # Request URL path
request.session     # Session object — use .get(key) and .set(key, value)
```

## Response Object

```python
return response({"data": []})              # JSON (auto-detected from dict/list)
return response("<h1>Hello</h1>")          # HTML
return response("Not found", 404)          # With status code
return response.redirect("/login")         # Redirect
return response.render("page.twig", data)  # Render Twig template
return response.file("doc.pdf")            # Serve a file
```

Add custom headers before returning:
```python
from tina4_python.Response import Response
Response.add_header("X-Custom", "value")
```

## Sessions

TINA4_TOKEN_LIMIT is used to set the session time, recommend 15-30 minutes

### Session Backends

Set `TINA4_SESSION_HANDLER` to choose a backend:

| Handler | Backend | Required package |
|---------|---------|-----------------|
| `SessionFileHandler` (default) | File system | — |
| `SessionRedisHandler` | Redis | `redis` |
| `SessionValkeyHandler` | Valkey | `valkey` |
| `SessionMongoHandler` | MongoDB | `pymongo` |

#### MongoDB session env vars

```bash
TINA4_SESSION_HANDLER=SessionMongoHandler
TINA4_SESSION_MONGO_HOST=localhost        # default
TINA4_SESSION_MONGO_PORT=27017            # default
TINA4_SESSION_MONGO_URI=                  # full URI (overrides host/port)
TINA4_SESSION_MONGO_USERNAME=             # optional
TINA4_SESSION_MONGO_PASSWORD=             # optional
TINA4_SESSION_MONGO_DB=tina4_sessions     # default database
TINA4_SESSION_MONGO_COLLECTION=sessions   # default collection
```

### Authentication & Security
- Use `tina4_python.tina4_auth.hash_password()` to hash passwords — never use hashlib directly.
- Use `tina4_python.tina4_auth.check_password(hash, password)` to verify passwords.

## Templates (Twig)

Templates use Jinja2/Twig syntax and live in `src/templates/`.

### REQUIRED: Base template pattern

Every project must have a `src/templates/base.twig`. All pages extend it.

```twig
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}{{ APP_NAME }}{% endblock %}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="/css/default.css">
    {% block stylesheets %}{% endblock %}
</head>
<body>
{% block nav %}{% include "partials/nav.twig" ignore missing %}{% endblock %}
{% block content %}{% endblock %}
{% block javascripts %}
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="/js/tina4helper.js"></script>
{% endblock %}
</body>
</html>
```

Extend it in every page:
```twig
{% extends "base.twig" %}
{% block title %}Dashboard — {{ APP_NAME }}{% endblock %}
{% block content %}
<div class="container mt-4">
    <h1>{{ title }}</h1>
    {% for item in items %}
        {% include "partials/item-card.twig" %}
    {% endfor %}
</div>
{% endblock %}
```

### Partials for reusable UI

Create `src/templates/partials/` for repeated components:
```twig
{# partials/item-card.twig #}
<div class="card mb-3">
    <div class="card-body">
        <h5>{{ item.name }}</h5>
        <p>{{ item.description }}</p>
        <span class="badge bg-primary">{{ item.price | money }}</span>
    </div>
</div>
```

### Custom Filters

Register in `app.py` before `run_web_server()`:

```python
from tina4_python.Template import Template

# Formatting
Template.add_filter("money", lambda v: f"{float(v or 0):,.2f}")
Template.add_filter("truncate", lambda s, n=50: (s[:n] + "...") if len(s) > n else s)

# Use in templates:
# {{ price | money }}         → "1,234.56"
# {{ description | truncate(100) }}
```

### Custom Global Functions

```python
Template.add_global("APP_NAME", "My App")
Template.add_global("current_year", lambda: datetime.now().year)

# Use in templates:
# {{ APP_NAME }}
# {{ current_year() }}
```

### Custom Tests

```python
Template.add_test("positive", lambda x: x > 0)

# Use in templates:
# {% if balance is positive %}...{% endif %}
```

### Built-in Twig features
- Variables: `{{ name }}`
- Loops: `{% for item in items %}...{% endfor %}`
- Conditions: `{% if condition %}...{% endif %}`
- Filters: `{{ value | upper }}`, `{{ date | datetime_format("%Y-%m-%d") }}`
- Encoding: `{{ data | json_encode }}`, `{{ text | base64encode }}`
- Labels: `{{ "user_email" | nice_label }}` → "User Email"
- Form tokens: `{{ form_token() }}` or `{{ ("Page" ~ RANDOM()) | form_token }}`
- Includes: `{% include "partials/nav.twig" %}`
- Inheritance: `{% extends "base.twig" %}` / `{% block content %}{% endblock %}`

### The @template() decorator

Auto-renders a dict return value through a template:
```python
from tina4_python.Router import get
from tina4_python.Template import template

@template("pages/dashboard.twig")
@get("/dashboard")
async def dashboard(request, response):
    return {"title": "Dashboard", "stats": get_stats()}
```

## Frontend — Bootstrap + tina4helper.js

The framework includes Bootstrap 5 by default and `tina4helper.js` for AJAX calls.

### tina4helper.js functions

```javascript
// Load HTML into an element
loadPage("/api/partial", "targetElementId");

// POST a form (auto-collects inputs, handles file uploads and tokens)
saveForm("formId", "/api/endpoint", "messageElementId", function(result) {
    console.log(result);
});

// Low-level request
sendRequest("/api/data", {key: "value"}, "POST", function(data, status) {
    console.log(data);
});

// GET a route and process the HTML
getRoute("/api/partial", function(html) {
    console.log(html);
});

// Post data to a URL, render response into element
postUrl("/api/save", {name: "Alice"}, "resultDiv");

// Show a Bootstrap alert
showMessage("Record saved successfully!");
```

### Token handling
`tina4helper.js` automatically:
- Sends `Authorization: Bearer` header with the current `formToken`
- Updates the token from the `FreshToken` response header
- Refreshes token values in forms before submission

## Api Class — External HTTP Calls

Use `Api` for all outbound HTTP requests. Never use raw `requests` directly.

```python
from tina4_python.Api import Api

# Setup
api = Api("https://api.example.com", auth_header="Bearer sk-abc123")

# GET
result = api.send_request("/users")
if result["error"] is None:
    users = result["body"]  # Auto-parsed JSON

# POST with JSON body
result = api.send_request(
    "/users",
    request_type="POST",
    body={"name": "Alice", "email": "alice@example.com"}
)

# With custom headers
api.add_custom_headers({"X-Tenant": "acme-corp"})

# With basic auth instead of bearer
api = Api("https://api.example.com")
api.set_username_password("client_id", "client_secret")

# Disable SSL verification (dev only)
api = Api("https://self-signed.local", ignore_ssl_validation=True)
```

### Return format
Every `send_request()` returns:
```python
{
    "http_code": 200,       # HTTP status (or None on network error)
    "body": {...},           # Auto-parsed JSON, or raw text
    "headers": {...},        # Response headers
    "error": None            # None on success, error message on failure
}
```

### When to use Api
- Calling third-party REST APIs (payment gateways, CRMs, etc.)
- Microservice-to-microservice communication
- OAuth token exchanges
- Webhook delivery

## Database

```python
from tina4_python.Database import Database

db = Database("sqlite3:app.db")        # SQLite
db = Database("psycopg2:localhost/5432:mydb", "user", "password")  # PostgreSQL
db = Database("mysql.connector:localhost/3306:mydb", "user", "password")  # MySQL
db = Database("firebird.driver:localhost/3050:/path/to/db", "SYSDBA", "masterkey")  # Firebird
db = Database("pymssql:localhost/1433:mydb", "sa", "password")  # MSSQL
db = Database("pymongo:localhost/27017:mydb")  # MongoDB
db = Database("pymongo:localhost/27017:mydb", "user", "password")  # MongoDB with auth
```

### MongoDB support

MongoDB uses the same SQL API as all other engines. The `SQLToMongo` module translates SQL to MongoDB queries transparently:

```python
db = Database("pymongo:localhost/27017:mydb")

# All standard operations work — SQL is translated to MongoDB internally
db.execute("CREATE TABLE users (id INTEGER)")  # creates collection
db.insert("users", {"id": 1, "name": "Alice", "email": "alice@test.com"})
result = db.fetch("SELECT * FROM users WHERE name = ?", ["Alice"])
db.execute("UPDATE users SET name = ? WHERE id = ?", ["Bob", 1])
db.execute("DELETE FROM users WHERE id = ?", [1])

# WHERE operators: =, !=, <>, >, >=, <, <=, LIKE, IN, NOT IN, IS NULL, IS NOT NULL, BETWEEN, AND, OR
# Pagination, search, fetch_one, table_exists, get_next_id all work
# RETURNING is emulated (returns affected documents)
```

**Limitations**: MongoDB is document-based — JOINs are not supported. Use embedded documents or application-level joins instead. Migrations (`CREATE TABLE`) map to collection creation (column definitions are ignored — MongoDB is schema-less).

### CRUD operations

```python
# Insert
db.insert("users", {"name": "Alice", "email": "alice@example.com"})

# Insert multiple
db.insert("users", [{"name": "Bob"}, {"name": "Eve"}])

# Update (by primary key — default "id")
db.update("users", {"id": 1, "name": "Alice Updated"})

# Delete
db.delete("users", {"id": 1})

# Raw query
result = db.fetch("SELECT * FROM users WHERE age > ?", [18])
for row in result.records:
    print(row["name"])

# Single row
row = db.fetch_one("SELECT * FROM users WHERE id = ?", [1])

# Result methods
result.to_json()       # JSON string
result.to_array()      # List of dicts
result.to_paginate()   # Dict with records, count, limit, skip
result.to_csv()        # CSV string

# Transactions
db.start_transaction()
try:
    db.insert("orders", {"total": 100})
    db.commit()
except:
    db.rollback()
```

**NEVER use `db.execute("COMMIT")` or `db.execute("ROLLBACK")` or `db.execute("BEGIN")`.**
Always use the proper methods: `db.commit()`, `db.rollback()`, `db.start_transaction()`. Raw SQL transaction commands bypass the framework's connection and transaction state management, leading to unpredictable behaviour and connection leaks.

## ORM

Define models in `src/orm/` (one class per file, filename matches class name).

```python
# src/orm/User.py
from tina4_python import ORM, IntegerField, StringField

class User(ORM):
    id    = IntegerField(primary_key=True, auto_increment=True)
    name  = StringField()
    email = StringField()
```

Initialize in `app.py`:
```python
from tina4_python import orm
from tina4_python.Database import Database

orm(Database("sqlite3:app.db"))  # Assigns DB to all ORM subclasses
```

### ORM operations

```python
# Create
user = User({"name": "Alice", "email": "alice@example.com"})
user.save()

# Load (returns bool, populates the instance)
user = User()
if user.load("email = ?", ["alice@example.com"]):
    print(user.name)

# Update
user.name = "Alice Wonder"
user.save()

# Delete
user.delete()

# Query
result = User().select(filter="name = ?", params=["Alice"], limit=10)

# Convert to dict
user.to_dict()
```

### Available field types
`IntegerField`, `StringField`, `TextField`, `DateTimeField`, `NumericField`, `BlobField`, `JSONBField`

Import from `tina4_python` or `tina4_python.FieldTypes`. For foreign keys:
```python
from tina4_python.FieldTypes import ForeignKeyField
```

## Migrations

**CRITICAL:** All database schema changes must go through migrations (see [Principle 9](#9-always-use-migrations-for-database-changes)). Never create or alter tables outside of migration files.

```bash
uv run tina4 migrate:create "create users table"   # Creates migrations/000001_create_users_table.sql
uv run tina4 migrate                                 # Runs all pending migrations
```

Or run on startup:
```python
from tina4_python.Migration import migrate
migrate(db)
```

When adding a new ORM model, always create a matching migration:
```bash
# 1. Create the ORM model in src/orm/Product.py
# 2. Create the migration
uv run tina4 migrate:create "create products table"
# 3. Write the DDL in the generated .sql file
# 4. Run the migration
uv run tina4 migrate
```

## Middleware

Middleware methods are classified by name prefix:
- `before_*` — runs before the route handler (auth checks, validation)
- `after_*` — runs after the route handler (logging, header injection)
- Other names — run as general middleware

```python
from tina4_python.Router import get, post, middleware

class AuthMiddleware:
    @staticmethod
    def before_auth(request, response):
        """Block unauthenticated requests."""
        if "authorization" not in request.headers:
            return request, response("Unauthorized", 401)
        return request, response

    @staticmethod
    def after_headers(request, response):
        """Add custom headers to every response."""
        from tina4_python.Response import Response
        Response.add_header("X-Powered-By", "Tina4")
        return request, response

@middleware(AuthMiddleware)
@get("/api/protected")
async def protected(request, response):
    return response({"secret": True})
```

### Middleware lifecycle

```
Request → before_* methods → any-methods → Route Handler → any-methods → after_* methods → Response
```

If any before-method returns an error status (401, 403, 500), the route handler is skipped.

### Reuse middleware across routes

Define middleware classes in `src/app/middleware.py` and import where needed:
```python
# src/app/middleware.py
class AdminOnly:
    @staticmethod
    def before_check_admin(request, response):
        if request.headers.get("x-role") != "admin":
            return request, response("Forbidden", 403)
        return request, response

# src/routes/admin.py
from src.app.middleware import AdminOnly

@middleware(AdminOnly)
@get("/admin/dashboard")
async def admin_dashboard(request, response):
    return response.render("admin/dashboard.twig")
```

## Queues — Background Processing

**Rule: Any operation that takes more than ~1 second must use a queue.**

Supports: litequeue (default/SQLite, zero-config), RabbitMQ, Kafka, MongoDB.

### Producer — enqueue work from a route

```python
from tina4_python.Queue import Queue, Producer

@post("/api/reports/generate")
async def request_report(request, response):
    queue = Queue(topic="reports")
    producer = Producer(queue)
    producer.produce({
        "user_id": request.body["user_id"],
        "report_type": "monthly",
    })
    return response({"status": "queued"})
```

### Consumer — process work in a background worker

```python
# worker.py (run separately: python worker.py)
from tina4_python.Queue import Queue, Consumer

def handle_report(message):
    data = message.data
    report = generate_report(data["user_id"], data["report_type"])
    send_email(data["user_id"], report)

queue = Queue(topic="reports", callback=handle_report)
consumer = Consumer(queue)
consumer.run_forever()
```

### Batch consumption

```python
queue = Queue(topic="logs", batch_size=50)
consumer = Consumer(queue)
for batch in consumer.messages():
    # batch is a list of Message objects
    bulk_insert(batch)
```

### Multi-queue consumption (round-robin)

```python
consumer = Consumer([
    Queue(topic="emails"),
    Queue(topic="notifications"),
    Queue(topic="reports"),
])
for msg in consumer.messages():
    process(msg)
```

### Backend configuration

```python
from tina4_python.Queue import Queue, Config

# Default: litequeue (SQLite, zero config)
queue = Queue(topic="tasks")

# RabbitMQ
config = Config()
config.queue_type = "rabbitmq"
config.rabbitmq_config = {"host": "rabbitmq", "port": 5672, "username": "guest", "password": "guest"}
queue = Queue(config=config, topic="tasks")

# Kafka
config = Config()
config.queue_type = "kafka"
config.kafka_config = {"bootstrap.servers": "kafka:9092", "group.id": "my-app"}
queue = Queue(config=config, topic="tasks")

# MongoDB
config = Config()
config.queue_type = "mongo-queue-service"
config.mongo_queue_config = {"host": "mongodb://mongo:27017", "timeout": 600}
queue = Queue(config=config, topic="tasks")
```

### When to use queues
- Sending emails or SMS
- Generating PDFs/reports
- Calling slow external APIs
- Processing uploaded files (image resize, CSV import)
- Any operation the user should not wait for

## WSDL / SOAP Services

Tina4 includes zero-config SOAP 1.1 support with automatic WSDL generation.

```python
from typing import List, Optional
from tina4_python.WSDL import WSDL, wsdl_operation
from tina4_python.Router import get, post

class Calculator(WSDL):
    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}

    @wsdl_operation({"Total": int, "Average": float, "Error": Optional[str]})
    def SumList(self, Numbers: List[int]):
        if not Numbers:
            return {"Total": 0, "Average": 0.0, "Error": "Empty list"}
        return {"Total": sum(Numbers), "Average": sum(Numbers) / len(Numbers), "Error": None}

@get("/calculator")
@post("/calculator")
async def calculator_endpoint(request, response):
    service = Calculator(request)
    return response(service.handle())
```

- `GET /calculator?wsdl` returns the WSDL definition
- `POST /calculator` with SOAP XML invokes operations
- Type annotations on method parameters control auto-conversion
- `@wsdl_operation()` declares the response schema for WSDL generation
- Supports `List[T]`, `Optional[T]`, and primitives (`str`, `int`, `float`, `bool`)

### Lifecycle hooks

```python
class SecureService(WSDL):
    def on_request(self, request):
        """Validate or log before method invocation."""
        pass

    def on_result(self, result):
        """Transform or audit after method returns."""
        return result
```

## Localization (i18n)

Tina4 supports translations via Python's `gettext` module. Translation files live in `tina4_python/translations/`.

Set the language in `.env`:
```bash
TINA4_LANGUAGE=en   # Supported: en, fr, af, zh, ja, es
```

### Using localize()

`localize()` initializes the translation system and returns a translation function:

```python
from tina4_python.Localization import localize

_ = localize()
print(_("Server stopped."))  # English: "Server stopped."
                              # French:  "Serveur arrêté."
                              # Afrikaans: "Bediener gestop."
                              # Chinese:  "服务器已停止。"
                              # Japanese: "サーバー停止。"
                              # Spanish:  "Servidor detenido."
```

The returned `_()` function also installs itself as a Python builtin, so after calling `localize()` once, `_()` is available globally.

### Format strings

Translated strings can contain `{placeholder}` format variables:
```python
_ = localize()
msg = _("Server started http://{host_name}:{port}")
print(msg.format(host_name="localhost", port=7145))
```

### Fallback behaviour

If `TINA4_LANGUAGE` is set to an unsupported language, the system falls back gracefully to returning the original English msgid — no crash.

### Available languages

```python
from tina4_python.Localization import AVAILABLE_LANGUAGES
# ['en', 'fr', 'af', 'zh', 'ja', 'es']
```

## HTML Element Builder

Build HTML programmatically without string concatenation:

```python
from tina4_python.HtmlElement import HTMLElement, add_html_helpers

# Direct usage
el = HTMLElement("div", {"class": "card"}, ["Hello"])
print(el)  # <div class="card">Hello</div>

# Builder pattern
el = HTMLElement("div")(HTMLElement("p")("Text"))

# Helper functions — injects _div(), _p(), _a(), _span(), etc.
add_html_helpers(globals())
html = _div({"class": "card"}, _p("Hello"))
```

Supports all HTML tags, void tags (`<br>`, `<img>`, `<input>`, etc.), and auto-escaping.

## Inline Testing

Tina4 includes a decorator-based test framework for inline test cases:

```python
from tina4_python.Testing import tests, assert_equal, assert_raises

@tests(
    assert_equal((5, 3), 8),
    assert_raises(ValueError, (None,))
)
def add(a, b=None):
    if b is None:
        raise ValueError("b required")
    return a + b
```

Run all decorated tests:
```bash
uv run tina4 test                     # Discovers @tests in src/**/*.py
```

Or programmatically:
```python
from tina4_python.Testing import run_all_tests
run_all_tests(quiet=False, failfast=False)
```

## Swagger / OpenAPI

Routes with decorators appear at `/swagger`:

```python
from tina4_python import description, tags, example, example_response

@post("/api/users")
@description("Create a new user")
@tags(["users"])
@example({"name": "Alice", "email": "alice@example.com"})
@example_response({"id": 1, "name": "Alice"})
async def create_user(request, response):
    return response(User(request.body).save())
```

## Environment Variables

Key `.env` settings:

```bash
# Authentication
SECRET=your-jwt-secret            # JWT signing (default uses insecure placeholder)
API_KEY=your-api-key              # Static bearer token for API auth
TINA4_TOKEN_LIMIT=2               # Token lifetime in minutes (default: 2)
TINA4_TOKEN_EXPIRES_IN=2          # Alternative token expiry setting

# Database
DATABASE_NAME=sqlite3:app.db      # Connection string (driver:connection_details)
DATABASE_PATH=sqlite3:app.db      # Alternative to DATABASE_NAME
DATABASE_USERNAME=                 # DB username (for PostgreSQL, MySQL, etc.)
DATABASE_PASSWORD=                 # DB password

# Framework
TINA4_DEBUG_LEVEL=All             # All, Debug, Info, Warning, Error
TINA4_LANGUAGE=en                 # Language for framework messages (en, fr, af, zh, ja, es)
TINA4_DEFAULT_WEBSERVER=FALSE     # Set to TRUE to use Tina4's built-in webserver instead of ASGI
HOST_NAME=localhost:7145

# Sessions
TINA4_SESSION_HANDLER=SessionFileHandler  # SessionFileHandler, SessionRedisHandler, SessionValkeyHandler, SessionMongoHandler

# Swagger/OpenAPI
SWAGGER_TITLE=My API              # API title (default: "Tina4 Python API")
SWAGGER_VERSION=1.0.0             # API version
SWAGGER_DESCRIPTION=              # API description
SWAGGER_CONTACT_TEAM=             # Contact name
SWAGGER_CONTACT_URL=              # Contact URL
SWAGGER_CONTACT_EMAIL=            # Contact email
SWAGGER_DEV_URL=http://localhost:7145  # Dev server URL for Swagger
```

### Debug levels
- `ALL` / `DEBUG` — enables DevReload, hot-patching, verbose logging, error overlay
- `INFO` — standard logging
- `WARNING` — warnings and errors only
- `ERROR` — errors only

## CORS

Built-in — all origins allowed by default. CORS headers and OPTIONS pre-flight are handled automatically.

## SCSS Workflow

Place `.scss` files in `src/scss/`. They auto-compile to `src/public/css/` on save (when DevReload is active).

```
src/scss/default.scss  →  src/public/css/default.css
src/scss/admin.scss    →  src/public/css/admin.css
```

Link in your base template:
```twig
<link rel="stylesheet" href="/css/default.css">
```

Changes to SCSS files trigger CSS-only hot-reload (no full page refresh).

## CLI Snippets & Scaffolding

The `tina4` CLI generates boilerplate so you don't write it from scratch.

### Project scaffolding

```bash
uv run tina4 init my-project    # Creates app.py, pyproject.toml, Dockerfile, CLAUDE.md
uv run tina4 start              # Start server on default port 7145
uv run tina4 start 8080         # Start on custom port
```

### CRUD Generator

Generate a complete CRUD interface (list, create, update, delete) for any database table with one call:

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

This auto-generates:
- Searchable, paginated HTML table with Bootstrap 5
- Create / Edit / Delete modals with form tokens
- 4 RESTful API routes (GET list, POST create, POST update, DELETE)
- Per-table Twig template in `src/templates/crud/` (customisable after generation)

### ORM Table Creation

Generate and execute `CREATE TABLE` from your ORM models:

```python
class Product(ORM):
    id    = IntegerField(primary_key=True, auto_increment=True)
    name  = StringField()
    price = NumericField()

Product().create_table()  # Generates + executes DDL for your database
```

### Migration Files

```bash
uv run tina4 migrate:create "add users table"
# Creates: migrations/000001_add_users_table.sql

uv run tina4 migrate
# Runs all pending .sql files in order
```

### When to use each

| Need | Use |
|------|-----|
| Quick admin UI for a table | `CRUD.to_crud()` |
| Schema-first database design | Migration files |
| Code-first database design | `ORM.create_table()` |
| New project from scratch | `tina4 init` |

## Common Patterns

### REST API with ORM

```python
@get("/api/products")
async def list_products(request, response):
    return response(Product().select(limit=100).to_array())

@post("/api/products")
async def create_product(request, response):
    product = Product(request.body)
    product.save()
    return response(product.to_dict(), 201)
```

### Form submission with AJAX

```twig
<form id="userForm">
    {{ form_token() }}
    <input name="name" class="form-control" required>
    <button type="button" onclick="saveForm('userForm', '/api/users', 'message')">Save</button>
</form>
<div id="message"></div>
```

### File upload handling

```python
import base64, os

@post("/api/upload")
async def upload(request, response):
    uploaded = request.files.get("file")
    if uploaded is None:
        return response({"error": "No file"}, 400)
    file_list = uploaded if isinstance(uploaded, list) else [uploaded]
    for f in file_list:
        content = base64.b64decode(f["content"])
        with open(os.path.join("src/public/uploads", f["file_name"]), "wb") as fh:
            fh.write(content)
    return response({"uploaded": len(file_list)})
```

### External API integration with error handling

```python
from tina4_python.Api import Api

# Centralise API client setup in app.py or src/app/services.py
payment_api = Api(
    "https://api.stripe.com/v1",
    auth_header="Bearer sk_live_xxx"
)

@post("/api/charge")
async def charge(request, response):
    result = payment_api.send_request(
        "/charges",
        request_type="POST",
        body={"amount": request.body["amount"], "currency": "usd"}
    )
    if result["error"]:
        return response({"error": "Payment failed"}, 502)
    return response(result["body"])
```

### Background email with queue

```python
# In route — fast response
@post("/api/invite")
async def invite(request, response):
    producer = Producer(Queue(topic="emails"))
    producer.produce({
        "to": request.body["email"],
        "template": "invite",
        "data": {"name": request.body["name"]}
    })
    return response({"sent": True})

# In worker — separate process
def send_email(message):
    email = message.data
    html = Template.render(f"emails/{email['template']}.twig", email["data"])
    # ... send via SMTP

queue = Queue(topic="emails", callback=send_email)
Consumer(queue).run_forever()
```

### Full page with template inheritance

```python
# src/routes/dashboard.py
from tina4_python.Router import get
from tina4_python.Template import template

@template("pages/dashboard.twig")
@get("/dashboard")
async def dashboard(request, response):
    stats = db.fetch("SELECT count(*) as total FROM orders").to_array()
    return {"title": "Dashboard", "stats": stats}
```

```twig
{# src/templates/pages/dashboard.twig #}
{% extends "base.twig" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<div class="container mt-4">
    <h1>{{ title }}</h1>
    <div class="row">
        {% for stat in stats %}
            {% include "partials/stat-card.twig" %}
        {% endfor %}
    </div>
</div>
{% endblock %}
```


