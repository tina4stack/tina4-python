# Routes & API Development (Python)

## Creating Routes

Drop a file in `src/routes/` and it's auto-discovered. No registration needed.

```python
from tina4_python import get, post, put, delete, noauth

@get("/hello")
async def hello(request, response):
    return response("Hello World")

@get("/users/{id}")
async def get_user(request, response):
    user = User.find(request.params["id"])   # int/str arg → PK lookup
    return response(user)                     # auto-converts to JSON

@post("/users")
async def create_user(request, response):
    user = User(request.body)                 # request.body auto-parsed from JSON
    user.save()
    return response(user, 201)

@put("/users/{id}")
async def update_user(request, response):
    user = User.find(request.params["id"])
    user.name = request.body["name"]
    user.save()
    return response(user)

@delete("/users/{id}")
async def delete_user(request, response):
    User.find(request.params["id"]).delete()
    return response("", 204)
```

## Write Routes Are Bearer-Gated by Default

**Tina4 is secure by default.** `GET`, `HEAD`, `OPTIONS`, and `ANY` routes are public;
**`POST` / `PUT` / `PATCH` / `DELETE` routes require a `Bearer` token** and return `401`
automatically when it's missing. So the `create_user` / `update_user` / `delete_user` handlers
above are already protected — you write nothing extra.

- **Make a write route genuinely public** with `@noauth()` (e.g. a public contact form or a
  login endpoint the caller reaches before it has a token):
  ```python
  @noauth()                         # POST is public — no token required
  @post("/contact")
  async def contact(request, response):
      Messenger().send(to="team@example.com", subject="New enquiry",
                       body=request.body["message"])
      return response({"status": "received"})
  ```
- **Protect a GET route** with `@secured()`.
- Never `@noauth()` a route that writes data, costs money, returns another user's data, or is an
  admin action *without* the handler authenticating another way. A 401 while building means auth
  is working — send the token, don't delete the guard.

## Smart Response Types

The framework infers what you want:
- Return an **object/dict** → JSON response with `Content-Type: application/json`
- Return a **string** → HTML response
- Return a **number** → status code only
- Call `response.render("template.twig", data)` → Frond template rendering
- Call `response.redirect("/path")` → HTTP redirect
- Call `response.file("path/to/file")` → file download

## Path Parameters

Use `{name}` syntax in route paths:

```python
@get("/users/{id}/posts/{postId}")
async def user_post(request, response):
    user_id = request.params["id"]
    post_id = request.params["postId"]
```

## Query Parameters

Access via `request.params`:

```python
# GET /search?q=hello&page=2
@get("/search")
async def search(request, response):
    query = request.query.get("q", "")
    page = int(request.query.get("page", 1))
    # `request.params` is ROUTE PARAMS ONLY (e.g. `{id}` in `/api/users/{id}`),
    # not the query string. Query values live on `request.query`. Since v3.13.99
    # this split has been strict — `.params.get("q")` on a route with no `{q}`
    # param silently returns the default and never sees `?q=…`. If you want
    # both surfaces, `request.param(key, default)` reads them in order.
```

## Middleware

Apply authentication, logging, or other cross-cutting concerns. **Middleware hooks are
dispatched by method-name prefix:** static methods named `before_*` run BEFORE the route
handler, `after_*` run AFTER.

> **The prefix matters — a method named exactly `before` never runs.** The dispatcher matches
> `name.startswith("before_")` / `startswith("after_")`, so `before` (no trailing `_...`) is
> silently skipped — an auth check written as `before` is a silent auth bypass. Name it
> `before_auth`.

```python
from tina4_python import middleware
from tina4_python.auth import Auth

class AuthCheck:
    @staticmethod
    async def before_auth(request, response):        # before_* — runs before the handler
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not Auth.valid_token(token):
            return request, response.json({"error": "Unauthorized"}, 401)
        request.user = Auth.get_payload(token)
        return request, response

@middleware(AuthCheck)
@get("/protected")
async def protected(request, response):
    return response({"secret": "data"})
```

A middleware hook returns `(request, response)`. Returning a response with a non-2xx status
short-circuits the route. When a route carries custom middleware, the framework assumes the
middleware handles auth and does not additionally apply the default Bearer gate.

## Swagger / OpenAPI

Auto-generated at `/swagger`. Add metadata with decorators imported from `tina4_python.swagger`:

```python
from tina4_python import get
from tina4_python.swagger import description, tags, example_response

@get("/users")
@description("List all active users")
@tags(["Users"])
@example_response(200, [{"id": 1, "name": "Alice"}])
async def list_users(request, response):
    users = User.where("is_active = ?", [1])
    return response([u.to_dict() for u in users])
```

> Use `@example_response(status, data)` for a response example — `example_response(200, [...])`
> reads the first arg as the status code. (`@example(data, content_type)` from the same module is
> for a request/body example and takes the payload first.) These decorators are **not** exported
> from the top-level `tina4_python` package — import them from `tina4_python.swagger`.

## CSRF / Form Token Protection

State-changing forms must include a CSRF token. Tina4 provides this built-in:

```twig
<form method="post" action="/contact">
    {{ form_token() }}
    <input type="text" name="name">
    <button type="submit">Send</button>
</form>
```

The `{{ form_token() }}` template function renders a hidden input with a secure token. The
framework validates it automatically on `POST` / `PUT` / `DELETE` requests; a missing or invalid
token is rejected. (The function is `form_token()` — snake_case — not `formToken()`.)

frond.js attaches the token automatically on `saveForm` / `sendRequest`.

## CORS

Built-in. Configure in `.env` or it defaults to allowing all origins in development.

## Rate Limiting

Built-in. No configuration needed for sensible defaults. Override in `.env` if needed. The
`RateLimiter` class lives in `tina4_python/core/rate_limiter.py`; a `RateLimiterMiddleware` is
available for route-level limiting.

**Hooks:**
- `before_rate_limit(request, response)` — called before the rate-limit check; returns modified
  request/response
- `check(request, response)` — performs the check and returns a 429 if exceeded
