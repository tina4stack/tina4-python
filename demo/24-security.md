# Security

Tina4 includes built-in security features: CORS handling, rate limiting, auto-escaping in templates, form tokens, and input validation via ORM fields. All zero-dependency.

## CORS

CORS is handled automatically. By default, all origins are allowed. Configure via `.env`:

```bash
# Allow all origins (default)
TINA4_CORS_ORIGINS=*

# Restrict to specific origins
TINA4_CORS_ORIGINS=https://myapp.com,https://admin.myapp.com

# Allowed methods
TINA4_CORS_METHODS=GET,POST,PUT,PATCH,DELETE,OPTIONS

# Allowed headers
TINA4_CORS_HEADERS=Content-Type,Authorization,X-Request-ID

# Preflight cache duration (seconds)
TINA4_CORS_MAX_AGE=86400

# Allow credentials
TINA4_CORS_CREDENTIALS=true
```

The framework automatically handles OPTIONS preflight requests and injects the appropriate CORS headers.

### Programmatic Access

```python
from tina4_python.core.middleware import CorsMiddleware

cors = CorsMiddleware()

# Check if a request is a preflight
if cors.is_preflight(request):
    # Handled automatically by the framework
    pass

# Check allowed origin
allowed = cors.allowed_origin("https://myapp.com")
```

## Rate Limiting

Sliding-window rate limiter with per-IP tracking. Configure via `.env`:

```bash
TINA4_RATE_LIMIT=100    # Max requests per window
TINA4_RATE_WINDOW=60    # Window in seconds
```

When a client exceeds the limit, they receive a `429 Too Many Requests` response with headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1710500100
Retry-After: 45
```

### Programmatic Access

```python
from tina4_python.core.middleware import RateLimiter

limiter = RateLimiter()

# Check if a request is allowed
allowed, headers = limiter.check("192.168.1.1")
if not allowed:
    return response("Too Many Requests", 429)
```

## Form Tokens (CSRF Protection)

Tina4 includes built-in CSRF protection via form tokens.

### In Templates

```twig
<form id="userForm" method="post">
    {{ form_token() }}
    <input type="text" name="name" placeholder="Full name">
    <button type="submit">Save</button>
</form>
```

### With tina4helper.js

The `saveForm()` function automatically includes the form token:

```twig
<form id="userForm">
    {{ form_token() }}
    <input type="text" name="name" placeholder="Full name">
    <button type="button" onclick="saveForm('userForm', '/api/users', 'msg')">
        Save
    </button>
</form>
<div id="msg"></div>
```

`tina4helper.js` handles:
- Sending the token in the `Authorization: Bearer` header
- Refreshing the token from the `FreshToken` response header
- Updating token values in forms before submission

## Template Auto-Escaping

Use the `|e` filter to HTML-escape output and prevent XSS:

```twig
{# Escaped — safe from XSS #}
<p>{{ user_input|e }}</p>

{# Unescaped — only for trusted content #}
<div>{{ trusted_html|safe }}</div>
```

The `|e` filter escapes `<`, `>`, `&`, `"`, and `'` to their HTML entities.

## Input Validation via ORM

ORM fields provide declarative input validation.

```python
from tina4_python.orm import ORM, Field

class User(ORM):
    id    = Field(int, primary_key=True, auto_increment=True)
    name  = Field(str, required=True, min_length=2, max_length=100)
    email = Field(str, required=True, regex=r'^[^@]+@[^@]+\.[^@]+$')
    age   = Field(int, min_value=13, max_value=150)
    role  = Field(str, choices=["admin", "user", "editor"])

# Validate before saving
user = User(request.body)
errors = user.validate()
if errors:
    return response({"errors": errors}, 422)
user.save()
```

## Parameterized Queries

Always use parameterized queries to prevent SQL injection.

```python
# SAFE — parameterized
db.fetch("SELECT * FROM users WHERE email = ?", [email])

# UNSAFE — string interpolation (NEVER do this)
# db.fetch(f"SELECT * FROM users WHERE email = '{email}'")
```

## Auth Defaults

Tina4 enforces auth by default on write operations:

| Method | Default |
|--------|---------|
| GET | Public (no auth required) |
| POST | Auth required |
| PUT | Auth required |
| PATCH | Auth required |
| DELETE | Auth required |

Override with `@noauth()` (make public) or `@secured()` (protect GET).

## Security Headers Middleware

Add security headers to all responses.

```python
class SecurityHeaders:
    @staticmethod
    def after_security(request, response):
        from tina4_python.core.response import Response
        Response.add_header("X-Content-Type-Options", "nosniff")
        Response.add_header("X-Frame-Options", "DENY")
        Response.add_header("X-XSS-Protection", "1; mode=block")
        Response.add_header("Strict-Transport-Security", "max-age=31536000")
        Response.add_header("Referrer-Policy", "strict-origin-when-cross-origin")
        return request, response
```

## Tips

- Set a strong `SECRET` in production for JWT signing.
- Always use `{{ form_token() }}` in forms that submit data.
- Use `|e` filter on all user-generated content in templates.
- Never use string formatting in SQL queries -- always use `?` placeholders.
- Configure CORS with specific origins in production -- never use `*` in production.
- Set appropriate rate limits to prevent abuse without blocking legitimate users.
