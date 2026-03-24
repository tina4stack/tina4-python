# Auth

Tina4 includes zero-dependency JWT authentication, password hashing (PBKDF2), and pluggable session backends. No PyJWT or cryptography packages required -- everything uses Python stdlib (`hmac`, `hashlib`, `secrets`).

## JWT Token Creation

```python
from tina4_python.auth import Auth

auth = Auth(secret="my-secret-key")

# Create a token with custom claims
token = auth.get_token({"user_id": 1, "role": "admin"})
# "eyJhbGciOi..."

# Custom expiry (in minutes)
token = auth.get_token({"user_id": 1}, expires_in=60)
```

## JWT Token Validation

```python
# Validate and get payload (returns None if invalid or expired)
payload = auth.valid_token(token)
if payload:
    print(payload["user_id"])  # 1
    print(payload["role"])     # "admin"
    print(payload["iat"])      # Issued-at timestamp
    print(payload["exp"])      # Expiry timestamp

# Decode payload WITHOUT validating (for debugging)
payload = auth.get_payload(token)
```

## Token Refresh

```python
# Issue a new token with the same claims and fresh expiry
new_token = auth.refresh_token(old_token)
if new_token is None:
    print("Original token was invalid")
```

## Password Hashing

Uses PBKDF2-HMAC-SHA256 with 260,000 iterations by default.

```python
from tina4_python.auth import Auth

# Hash a password
hashed = Auth.hash_password("secret123")
# "pbkdf2_sha256$260000$<salt>$<hash>"

# Verify a password
if Auth.check_password(hashed, "secret123"):
    print("Password correct")
else:
    print("Password wrong")
```

## API Key Authentication

Set an `API_KEY` in your `.env` and validate Bearer tokens against it.

```python
# .env
# API_KEY=sk-live-abc123

from tina4_python.auth import Auth

is_valid = Auth.validate_api_key("sk-live-abc123")  # True
```

## Request Authentication Helper

Handles Bearer JWT, Bearer API key, and Basic auth automatically.

```python
auth = Auth(secret="my-secret")

result = auth.authenticate_request(request.headers)
if result is None:
    return response("Unauthorized", 401)

# JWT token returns the payload dict
# API key returns {"auth_type": "api_key"}
# Basic auth returns {"auth_type": "basic", "username": "...", "password": "..."}
```

## Login Route Example

```python
from tina4_python.core.router import post, noauth
from tina4_python.auth import Auth

auth = Auth()

@noauth()
@post("/api/login")
async def login(request, response):
    email = request.body.get("email")
    password = request.body.get("password")

    # Look up user
    user = db.fetch_one("SELECT * FROM users WHERE email = ?", [email])
    if not user:
        return response({"error": "Invalid credentials"}, 401)

    # Verify password
    if not Auth.check_password(user["password_hash"], password):
        return response({"error": "Invalid credentials"}, 401)

    # Issue token
    token = auth.get_token({"user_id": user["id"], "role": user["role"]})
    return response({"token": token})
```

## Configuration

Set these in your `.env` file:

```bash
SECRET=your-jwt-signing-secret     # JWT signing key
API_KEY=your-api-key               # Static bearer token for API auth
TINA4_TOKEN_EXPIRES_IN=60          # Token lifetime in minutes (default: 60)
```

## Session Backends

Sessions are managed through `request.session` in route handlers.

```python
@get("/api/profile")
async def profile(request, response):
    user_id = request.session.get("user_id")
    if not user_id:
        return response("Not logged in", 401)
    return response({"user_id": user_id})

@post("/api/login")
async def login(request, response):
    # After verifying credentials...
    request.session.set("user_id", user["id"])
    request.session.set("role", user["role"])
    return response({"ok": True})

@post("/api/logout")
async def logout(request, response):
    request.session.unset("user_id")
    return response({"ok": True})
```

### Backend Configuration

Set `TINA4_SESSION_HANDLER` in `.env`:

| Handler | Backend | Install |
|---------|---------|---------|
| `SessionFileHandler` (default) | File system | None |
| `SessionRedisHandler` | Redis | `pip install redis` |
| `SessionValkeyHandler` | Valkey | `pip install valkey` |
| `SessionMongoHandler` | MongoDB | `pip install pymongo` |

### MongoDB Session Config

```bash
TINA4_SESSION_HANDLER=SessionMongoHandler
TINA4_SESSION_MONGO_HOST=localhost
TINA4_SESSION_MONGO_PORT=27017
TINA4_SESSION_MONGO_DB=tina4_sessions
TINA4_SESSION_MONGO_COLLECTION=sessions
```

## Tips

- Always set a strong `SECRET` in production -- the default is insecure.
- Use `Auth.hash_password()` and `Auth.check_password()` -- never hash passwords with raw `hashlib`.
- GET routes are public by default; POST/PUT/PATCH/DELETE require a Bearer token.
- Use `@noauth()` on public write routes (login, registration, webhooks).
- Use `@secured()` on sensitive GET routes that need auth.
