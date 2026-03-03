# Tina4 Python — Developer Guidelines

This file helps AI assistants and new developers understand how to build with tina4_python.

## Project Structure

```
project/
├── app.py                  # Entry point — starts the web server
├── .env                    # Environment variables (SECRET, API_KEY, etc.)
├── migrations/             # SQL migration files (000001_description.sql)
├── src/
│   ├── __init__.py         # Auto-loaded on startup — import your route files here
│   ├── routes/             # Route handlers (one file per resource)
│   ├── orm/                # ORM model classes (one file per model)
│   ├── templates/          # Twig/Jinja2 templates
│   ├── public/             # Static files served at / (css/, js/, images/)
│   └── scss/               # SCSS files — auto-compiled to src/public/css/
└── secrets/                # Auto-generated RSA keys for JWT (do not commit)
```

## Package Manager

Use `uv` for dependency management:
```bash
uv add tina4-python          # Add dependency
uv run tina4 start            # Start dev server on port 7145
uv run tina4 init .           # Scaffold project structure
uv run tina4 migrate          # Run pending SQL migrations
uv run tina4 migrate:create "description"  # Create a migration file
```

## Routing

Routes live in `src/routes/`. Import them in `src/__init__.py`.

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

```python
from tina4_python.Router import post, noauth, secured

@noauth()
@post("/api/webhook")
async def public_webhook(request, response):
    return response({"ok": True})

@secured()
@get("/api/admin/stats")
async def protected_get(request, response):
    return response({"secret": True})
```

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

## Templates (Twig)

Templates use Jinja2/Twig syntax and live in `src/templates/`.

### Base template pattern — `src/templates/base.twig`

```twig
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="/css/default.css">
    {% block stylesheets %}{% endblock %}
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="/js/tina4helper.js"></script>
</head>
<body>
{% block content %}{% endblock %}
{% block javascripts %}{% endblock %}
</body>
</html>
```

Extend it in page templates:
```twig
{% extends "base.twig" %}
{% block content %}
<div class="container">
    <h1>{{ title }}</h1>
</div>
{% endblock %}
```

Render from a route:
```python
@get("/dashboard")
async def dashboard(request, response):
    return response.render("dashboard.twig", {"title": "Dashboard"})
```

### Twig features available
- Variables: `{{ name }}`
- Loops: `{% for item in items %}...{% endfor %}`
- Conditions: `{% if condition %}...{% endif %}`
- Filters: `{{ value | upper }}`, `{{ date | datetime_format("%Y-%m-%d") }}`
- Form tokens: `{{ form_token() }}` or `{{ ("Page" ~ RANDOM()) | form_token }}`

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

## Database

```python
from tina4_python.Database import Database

db = Database("sqlite3:app.db")        # SQLite
db = Database("postgresql:host=localhost;dbname=mydb;user=me;password=secret")
```

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

```bash
uv run tina4 migrate:create "create users table"   # Creates migrations/000001_create_users_table.sql
uv run tina4 migrate                                 # Runs all pending migrations
```

Or run on startup:
```python
from tina4_python.Migration import migrate
migrate(db)
```

## Middleware

```python
from tina4_python.Router import get, middleware

class AuthMiddleware:
    @staticmethod
    def before_route(request, response):
        # Runs before the route handler
        return request, response

    @staticmethod
    def after_route(request, response):
        # Runs after the route handler
        return request, response

@middleware(AuthMiddleware)
@get("/protected")
async def protected(request, response):
    return response("OK")
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

## Queues (Long-Running Tasks)

Use queues for background processing. Supports: litequeue (default/SQLite), RabbitMQ, Kafka, MongoDB.

### Producer (send work)

```python
from tina4_python.Queue import Queue, Producer

queue = Queue(topic="emails")
producer = Producer(queue)
producer.produce({"to": "alice@example.com", "subject": "Welcome"})
```

### Consumer (process work)

```python
from tina4_python.Queue import Queue, Consumer

def handle_email(message):
    print(f"Sending email: {message.data}")

queue = Queue(topic="emails", callback=handle_email)
consumer = Consumer(queue)
consumer.run_forever()  # Blocking loop
```

### Batch consumption

```python
queue = Queue(topic="reports", batch_size=10)
consumer = Consumer(queue)
for batch in consumer.messages():
    # batch is a list of Message objects when batch_size > 1
    process_batch(batch)
```

## Environment Variables

Key `.env` settings:

```bash
SECRET=your-jwt-secret          # JWT signing (default uses insecure placeholder)
API_KEY=your-api-key            # Static bearer token for API auth
TINA4_DATABASE_NAME=sqlite3:app.db
TINA4_DEBUG_LEVEL=All           # All, Debug, Info, Warning, Error
SWAGGER_TITLE=My API
HOST_NAME=localhost:7145
```

## CORS

Built-in — all origins allowed by default. CORS headers and OPTIONS pre-flight are handled automatically.

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
