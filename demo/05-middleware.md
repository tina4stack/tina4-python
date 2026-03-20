# Middleware

Middleware intercepts requests before and after route handlers. Tina4 uses class-based middleware with method naming conventions: `before_*` methods run pre-handler, `after_*` methods run post-handler, and other names run as general middleware.

## Basic Middleware Class

```python
# src/app/middleware.py

class LoggingMiddleware:
    @staticmethod
    def before_log(request, response):
        """Runs before the route handler."""
        print(f"[{request.method}] {request.url}")
        return request, response

    @staticmethod
    def after_log(request, response):
        """Runs after the route handler."""
        from tina4_python.core.response import Response
        Response.add_header("X-Processed-By", "Tina4")
        return request, response
```

## Attaching Middleware to Routes

Use the `@middleware()` decorator to attach middleware to specific routes.

```python
from tina4_python.core.router import get, post, middleware
from src.app.middleware import LoggingMiddleware

@middleware(LoggingMiddleware)
@get("/api/users")
async def list_users(request, response):
    return response({"users": []})
```

## Auth Middleware

A common pattern: block unauthenticated requests.

```python
class AuthMiddleware:
    @staticmethod
    def before_auth(request, response):
        """Check for valid token before the route runs."""
        if "authorization" not in request.headers:
            return request, response("Unauthorized", 401)
        return request, response
```

```python
from tina4_python.core.router import get, middleware

@middleware(AuthMiddleware)
@get("/api/protected")
async def protected(request, response):
    return response({"secret": True})
```

If a `before_*` method returns an error response (401, 403, 500), the route handler is skipped entirely.

## Admin-Only Middleware

```python
class AdminOnly:
    @staticmethod
    def before_check_admin(request, response):
        role = request.headers.get("x-role", "")
        if role != "admin":
            return request, response("Forbidden", 403)
        return request, response
```

```python
@middleware(AdminOnly)
@get("/admin/dashboard")
async def admin_dashboard(request, response):
    return response.render("admin/dashboard.twig")
```

## Multiple Middleware

Stack multiple middleware classes on a single route. They execute in order.

```python
@middleware(LoggingMiddleware, AuthMiddleware, AdminOnly)
@get("/admin/settings")
async def admin_settings(request, response):
    return response({"settings": {}})
```

## Middleware Lifecycle

```
Request
  -> before_* methods (in order)
  -> general methods (no prefix)
  -> Route Handler
  -> general methods (no prefix)
  -> after_* methods (in order)
Response
```

## Adding Response Headers

Use `Response.add_header()` in `after_*` methods to inject headers.

```python
from tina4_python.core.response import Response

class SecurityHeaders:
    @staticmethod
    def after_security(request, response):
        Response.add_header("X-Content-Type-Options", "nosniff")
        Response.add_header("X-Frame-Options", "DENY")
        Response.add_header("X-XSS-Protection", "1; mode=block")
        return request, response
```

## Request Timing Middleware

```python
import time

class TimingMiddleware:
    @staticmethod
    def before_start_timer(request, response):
        request._start_time = time.time()
        return request, response

    @staticmethod
    def after_add_timing(request, response):
        elapsed = time.time() - getattr(request, "_start_time", time.time())
        from tina4_python.core.response import Response
        Response.add_header("X-Response-Time", f"{elapsed:.3f}s")
        return request, response
```

## Tips

- Define middleware classes in `src/app/middleware.py` and import where needed.
- Method naming matters: `before_` prefix = pre-handler, `after_` prefix = post-handler.
- Keep middleware focused on one concern (auth, logging, headers, etc.).
- Return `request, response` from every middleware method -- even if you do not modify them.
- To short-circuit a request, return a response with an error status in a `before_*` method.
