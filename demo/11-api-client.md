# API Client

Tina4 includes a built-in HTTP client using Python's `urllib` -- no `requests` or `httpx` needed. It handles JSON serialization, authentication headers, SSL control, and timeouts.

## Basic Usage

```python
from tina4_python.api import Api

api = Api("https://api.example.com")

# GET request
result = api.get("/users")
if result["error"] is None:
    users = result["body"]
    print(users)

# POST with JSON body
result = api.post("/users", {"name": "Alice", "email": "alice@example.com"})

# PUT
result = api.put("/users/1", {"name": "Alice Updated"})

# PATCH
result = api.patch("/users/1", {"email": "new@example.com"})

# DELETE
result = api.delete("/users/1")
```

## Response Format

Every request returns a standardized dict:

```python
{
    "http_code": 200,       # HTTP status code (or None on network error)
    "body": {...},           # Auto-parsed JSON, or raw text
    "headers": {...},        # Response headers
    "error": None            # None on success, error message string on failure
}
```

## Authentication

### Bearer Token

```python
api = Api("https://api.example.com", auth_header="Bearer sk-abc123")

# Or set after construction
api.set_bearer_token("sk-abc123")
```

### Basic Auth

```python
api = Api("https://api.example.com")
api.set_basic_auth("username", "password")
```

## Custom Headers

```python
api = Api("https://api.example.com")
api.add_headers({
    "X-Tenant": "acme-corp",
    "X-Request-ID": "req-12345",
})
```

## Query Parameters

```python
result = api.get("/users", params={"page": 1, "per_page": 20, "active": "true"})
# Sends: GET /users?page=1&per_page=20&active=true
```

## POST with Different Content Types

```python
# JSON (default)
result = api.post("/data", {"key": "value"})

# Form data
result = api.post("/form", "name=Alice&age=30", content_type="application/x-www-form-urlencoded")

# Raw bytes
result = api.post("/upload", file_bytes, content_type="application/octet-stream")
```

## Generic Request

```python
result = api.send("PATCH", "/users/1", {"status": "active"})
```

## SSL Configuration

```python
# Disable SSL verification (development only!)
api = Api("https://self-signed.local", ignore_ssl=True)

# Timeout (default: 30 seconds)
api = Api("https://slow-api.example.com", timeout=60)
```

## Error Handling

```python
result = api.get("/users")

if result["error"]:
    print(f"Request failed: {result['error']}")
elif result["http_code"] >= 400:
    print(f"API error {result['http_code']}: {result['body']}")
else:
    process(result["body"])
```

## Payment Gateway Example

```python
from tina4_python.api import Api
from tina4_python.core.router import post

payment_api = Api(
    "https://api.stripe.com/v1",
    auth_header="Bearer sk_live_xxx"
)

@post("/api/charge")
async def charge(request, response):
    result = payment_api.post("/charges", {
        "amount": request.body["amount"],
        "currency": "usd",
        "source": request.body["token"],
    })
    if result["error"] or result["http_code"] >= 400:
        return response({"error": "Payment failed"}, 502)
    return response(result["body"])
```

## OAuth Token Exchange

```python
auth_api = Api("https://oauth.example.com")
auth_api.set_basic_auth("client_id", "client_secret")

result = auth_api.post("/token",
    "grant_type=client_credentials",
    content_type="application/x-www-form-urlencoded"
)

if result["error"] is None:
    access_token = result["body"]["access_token"]
    data_api = Api("https://api.example.com")
    data_api.set_bearer_token(access_token)
```

## Tips

- Always use `Api` for external HTTP calls -- never use raw `urllib` or `requests` directly.
- Centralize API client setup in `app.py` or `src/app/services.py` as module-level singletons.
- Check both `result["error"]` (network failures) and `result["http_code"]` (HTTP errors).
- For slow APIs, push the call to a queue and process it in a worker.
- Only disable SSL verification in development -- never in production.
