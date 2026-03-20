# Logging

Tina4 includes a structured logger with JSON output for production and human-readable output for development. It supports log levels, request ID tracking, file rotation, compression, and configurable retention.

## Basic Usage

```python
from tina4_python.debug import Log

Log.info("Server started", host="localhost", port=7145)
Log.debug("Route matched", method="GET", path="/api/users")
Log.warning("Slow query", query="SELECT *", duration_ms=1200)
Log.error("Database failed", error="connection refused", host="db.example.com")
```

## Log Levels

| Level | Use Case |
|-------|----------|
| `DEBUG` | Detailed diagnostic info (route matching, SQL queries) |
| `INFO` | General operational events (server start, request completed) |
| `WARNING` | Unexpected but recoverable situations (slow queries, deprecations) |
| `ERROR` | Failures that need attention (database errors, auth failures) |

Set the minimum level in `.env`:

```bash
TINA4_DEBUG_LEVEL=ALL     # Show everything (DEBUG + INFO + WARNING + ERROR)
TINA4_DEBUG_LEVEL=DEBUG   # Same as ALL
TINA4_DEBUG_LEVEL=INFO    # INFO + WARNING + ERROR
TINA4_DEBUG_LEVEL=WARNING # WARNING + ERROR only
TINA4_DEBUG_LEVEL=ERROR   # Errors only
```

## Output Formats

### Development (Human-Readable)

```
2024-03-15 10:30:45 [INFO] Server started host=localhost port=7145
2024-03-15 10:30:46 [DEBUG] Route matched method=GET path=/api/users
2024-03-15 10:30:47 [ERROR] Database failed error="connection refused"
```

Output goes to stdout AND `logs/tina4.log`.

### Production (JSON Lines)

```json
{"ts":"2024-03-15T10:30:45Z","level":"INFO","msg":"Server started","host":"localhost","port":7145}
{"ts":"2024-03-15T10:30:46Z","level":"DEBUG","msg":"Route matched","method":"GET","path":"/api/users"}
```

JSON output goes to `logs/tina4.log` only.

## Request ID Tracking

Each request gets a unique ID for tracing through logs.

```python
from tina4_python.debug import set_request_id, get_request_id

# Set in middleware (automatically done by Tina4)
set_request_id("req-abc123")

# Access anywhere during the request
Log.info("Processing", request_id=get_request_id())
```

## Structured Fields

Pass keyword arguments to add structured data to log entries.

```python
Log.info("Request completed",
    method="POST",
    path="/api/users",
    status=201,
    duration_ms=45,
    user_id=42,
)
```

## Log Rotation

Logs rotate automatically based on date and file size.

```python
# Default configuration:
# - Max file size: 10 MB
# - Rotation: daily + size-based
# - Retention: 30 days
# - Compression: gzip on rotated files

# logs/
#   tina4.log              # Current log file
#   tina4-2024-03-14.log.gz  # Yesterday's log (compressed)
#   tina4-2024-03-13.log.gz  # Older logs...
```

## Error Logging in Routes

```python
from tina4_python.core.router import post
from tina4_python.debug import Log

@post("/api/orders")
async def create_order(request, response):
    try:
        order = Order(request.body)
        order.save()
        Log.info("Order created", order_id=order.id, user_id=request.body.get("user_id"))
        return response(order.to_dict(), 201)
    except Exception as e:
        Log.error("Order creation failed",
            error=str(e),
            body=request.body,
        )
        return response({"error": "Failed to create order"}, 500)
```

## Tips

- Use `Log.error()` for failures, `Log.info()` for normal operations, `Log.debug()` for diagnostics.
- Always include context fields (user_id, order_id, etc.) for easier debugging.
- In production, set `TINA4_DEBUG_LEVEL=INFO` or `WARNING` to reduce log volume.
- In development, set `TINA4_DEBUG_LEVEL=ALL` for full visibility.
- Log files are stored in the `logs/` directory by default.
- Old log files are compressed with gzip and retained for 30 days.
