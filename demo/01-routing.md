# Routing

Tina4 uses decorator-based routing. Route files live in `src/routes/` and are auto-discovered on startup -- no manual imports needed. Each decorator registers a handler for a specific HTTP method and path pattern.

## Basic Routes

```python
# src/routes/users.py
from tina4_python.core.router import get, post, put, delete

@get("/api/users")
async def list_users(request, response):
    return response({"users": []})

@post("/api/users")
async def create_user(request, response):
    data = request.body
    return response({"created": True, "name": data["name"]}, 201)

@put("/api/users/{id}")
async def update_user(request, response):
    return response({"updated": True})

@delete("/api/users/{id}")
async def delete_user(request, response):
    return response({"deleted": True})
```

## Path Parameters

Path parameters are defined with `{name}` syntax. Type hints auto-convert the value.

```python
from tina4_python.core.router import get

# String param (default)
@get("/api/users/{username}")
async def get_by_username(request, response):
    username = request.params["username"]
    return response({"username": username})

# Integer param — auto-converted to int
@get("/api/users/{id:int}")
async def get_user(request, response):
    user_id = request.params["id"]  # Already an int
    return response({"id": user_id})

# Float param
@get("/api/products/{price:float}")
async def get_by_price(request, response):
    price = request.params["price"]  # Already a float
    return response({"price": price})

# Greedy path param — matches remaining URL segments
@get("/files/{path:path}")
async def serve_file(request, response):
    file_path = request.params["path"]  # e.g. "docs/2024/report.pdf"
    return response({"file": file_path})
```

## Any Method

Use `any_method` to handle all HTTP methods on one path.

```python
from tina4_python.core.router import any_method

@any_method("/api/echo")
async def echo(request, response):
    return response({
        "method": request.method,
        "body": request.body,
        "params": request.params,
    })
```

## Auth Defaults

GET routes are public by default. POST/PUT/PATCH/DELETE require a Bearer token. Override with `@noauth()` or `@secured()`.

```python
from tina4_python.core.router import get, post, noauth, secured

# This POST is public (no token needed)
@noauth()
@post("/api/webhook")
async def public_webhook(request, response):
    return response({"received": True})

# This GET requires auth
@secured()
@get("/api/admin/stats")
async def protected_stats(request, response):
    return response({"secret": 42})
```

## Decorator Order

The correct order from outermost to innermost is:

1. `@noauth()` / `@secured()` (auth control)
2. `@description()` / `@tags()` / `@example()` (Swagger metadata)
3. `@middleware(...)` (middleware attachment)
4. `@get()` / `@post()` / etc. (route registration -- always innermost)

```python
from tina4_python.core.router import post, noauth, middleware
from tina4_python.swagger import description, tags, example

@noauth()
@description("Register a new user account")
@tags(["users"])
@example({"name": "Alice", "email": "alice@example.com"})
@post("/api/register")
async def register(request, response):
    return response({"registered": True}, 201)
```

## Request Object

```python
@post("/api/data")
async def handle(request, response):
    body = request.body        # Parsed JSON dict or form data dict
    params = request.params    # Query string parameters dict
    headers = request.headers  # HTTP headers dict (lowercase keys)
    files = request.files      # Uploaded files dict
    url = request.url          # Request URL path
    session = request.session  # Session object
    return response({"ok": True})
```

## Response Patterns

```python
from tina4_python.core.router import get

@get("/api/json")
async def json_response(request, response):
    return response({"key": "value"})           # JSON (auto-detected)

@get("/api/html")
async def html_response(request, response):
    return response("<h1>Hello</h1>")           # HTML

@get("/api/error")
async def error_response(request, response):
    return response("Not found", 404)           # Status code

@get("/redirect")
async def redirect(request, response):
    return response.redirect("/login")          # Redirect

@get("/page")
async def render_page(request, response):
    return response.render("page.twig", {"title": "Home"})  # Template

@get("/download")
async def download(request, response):
    return response.file("report.pdf")          # File download
```

## Tips

- Keep one resource per route file (`src/routes/users.py`, `src/routes/products.py`).
- Route handlers should be thin wrappers -- put business logic in service classes under `src/app/`.
- Always wrap route logic in `try/except` and return appropriate error responses.
- Use `response()` not `response.json()` -- this is the Tina4 convention.
