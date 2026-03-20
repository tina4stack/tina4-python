# Deployment

Tina4 applications are standard Python ASGI apps. This guide covers Docker deployment, health checks, graceful shutdown, and production configuration.

## Dockerfile

The `tina4python init` command generates a Dockerfile. Here is a typical setup:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files first (better layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Expose the port
EXPOSE 7145

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7145/health')"

# Run the application
CMD ["uv", "run", "python", "app.py"]
```

## Docker Compose

```yaml
version: "3.8"

services:
  app:
    build: .
    ports:
      - "7145:7145"
    env_file:
      - .env.production
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:7145/health')"]
      interval: 30s
      timeout: 5s
      retries: 3

  # Optional: PostgreSQL
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: secret
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  pgdata:
```

## Health Check Endpoint

Tina4 auto-registers a `/health` endpoint that returns:

```json
{
    "status": "healthy",
    "version": "3.0.0-dev",
    "uptime": 3600,
    "errors": 0
}
```

The health endpoint also tracks errors via the BrokenTracker. If errors are accumulating, monitoring tools can detect degradation.

## Graceful Shutdown

Tina4 handles `SIGTERM` and `SIGINT` signals for graceful shutdown:

1. Stops accepting new connections
2. Completes in-flight requests
3. Closes database connections
4. Shuts down cleanly

No configuration needed -- it is built into the framework.

## Production .env

```bash
# .env.production

# CRITICAL: Set a strong secret
SECRET=your-256-bit-secret-here

# Disable debug features
TINA4_DEBUG_LEVEL=WARNING

# Database
DATABASE_URL=postgresql://admin:secret@db:5432/myapp

# Rate limiting
TINA4_RATE_LIMIT=100
TINA4_RATE_WINDOW=60

# CORS (restrict to your domain)
TINA4_CORS_ORIGINS=https://myapp.com

# Session
TINA4_SESSION_HANDLER=SessionRedisHandler
TINA4_TOKEN_LIMIT=30

# Swagger (optional: disable in production)
SWAGGER_TITLE=My API
SWAGGER_VERSION=1.0.0
```

## Dev vs Production Checklist

| Setting | Development | Production |
|---------|-------------|------------|
| `TINA4_DEBUG_LEVEL` | `ALL` | `WARNING` or `ERROR` |
| `SECRET` | Any value | Strong random secret |
| `TINA4_CORS_ORIGINS` | `*` | Specific domains |
| `TINA4_RATE_LIMIT` | High or disabled | Appropriate limit |
| Dev admin (`/__dev/`) | Enabled | Disabled (auto) |
| Error overlay | Enabled | Disabled (auto) |
| Hot reload | Enabled | Disabled (auto) |

## Running with ASGI Server

For production, run behind an ASGI server:

```bash
# With uvicorn
pip install uvicorn
uvicorn app:app --host 0.0.0.0 --port 7145 --workers 4

# With gunicorn + uvicorn workers
pip install gunicorn uvicorn
gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:7145
```

## Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name myapp.com;

    location / {
        proxy_pass http://127.0.0.1:7145;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support
    location /ws/ {
        proxy_pass http://127.0.0.1:7146;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Static files (optional — Tina4 serves these too)
    location /css/ {
        alias /app/src/public/css/;
        expires 30d;
    }

    location /js/ {
        alias /app/src/public/js/;
        expires 30d;
    }
}
```

## Database Migrations in CI/CD

Run migrations as part of your deployment pipeline:

```bash
# In your CI/CD script or Docker entrypoint
tina4python migrate
```

Or run on startup in `app.py`:

```python
from tina4_python.database import Database
from tina4_python.orm import orm_bind

db = Database()
orm_bind(db)

# Run pending migrations on startup
from tina4_python.migration import migrate
migrate(db)
```

## Logging in Production

Production logs go to `logs/tina4.log` as JSON lines:

```json
{"ts":"2024-03-15T10:30:45Z","level":"INFO","msg":"Request completed","method":"GET","path":"/api/users","status":200,"duration_ms":12}
```

Configure log rotation:
- Default max file size: 10 MB
- Rotation: daily + size-based
- Retention: 30 days
- Compression: gzip on rotated files

## Tips

- Always set `TINA4_DEBUG_LEVEL=WARNING` or `ERROR` in production -- debug mode exposes sensitive information.
- Use a strong, random `SECRET` for JWT signing in production.
- Run database migrations as part of your deployment pipeline, not on every startup.
- Use Docker health checks to enable automatic container restarts.
- Set specific CORS origins in production -- never use `*`.
- Consider using Redis for sessions in multi-process deployments.
- Place Nginx or a load balancer in front for SSL termination and static file caching.
