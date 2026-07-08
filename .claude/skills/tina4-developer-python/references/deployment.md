# Deployment Recipes (Python)

## Docker Base Image

Tina4 provides an official Docker Hub base image. It's a lean, Alpine-based, SQLite-only image.
Your app Dockerfile extends it and adds only what it needs.

| Framework | Base Image | Default Port | Size |
|-----------|-----------|-------------|------|
| Python | `tina4stack/tina4-python:v3` | 7146 | ~56MB |

## Python App Dockerfile

Every Python Tina4 app uses this exact pattern:

```dockerfile
FROM tina4stack/tina4-python:v3
WORKDIR /app

# Copy application code
COPY app.py .
COPY .env .
COPY migrations/ migrations/
COPY src/ src/

# Create data directories
RUN mkdir -p data data/sessions data/queue data/mailbox

EXPOSE 7146
CMD ["python", "app.py"]
```

### .dockerignore

```
.venv
__pycache__
*.pyc
data/
tests/
.tina4/
.DS_Store
*.db
*.db-wal
*.db-shm
logs/
```

### Build and Run

```bash
docker build -t my-app .
docker run -d -p 7146:7146 -v $(pwd)/data:/app/data my-app
```

## Adding Database Drivers

The base image ships with SQLite only. Add drivers in your app's Dockerfile.

### PostgreSQL

```dockerfile
FROM tina4stack/tina4-python:v3
WORKDIR /app

# Add PostgreSQL driver (pure Python, no system deps on Alpine)
RUN python -m pip install --no-cache-dir psycopg2-binary

COPY app.py .
COPY .env .
COPY migrations/ migrations/
COPY src/ src/
RUN mkdir -p data data/sessions data/queue data/mailbox
EXPOSE 7146
CMD ["python", "app.py"]
```

### MySQL

```dockerfile
FROM tina4stack/tina4-python:v3
WORKDIR /app

# Add MySQL driver
RUN apk add --no-cache mariadb-connector-c-dev && \
    python -m pip install --no-cache-dir mysqlclient

COPY app.py .
COPY .env .
COPY migrations/ migrations/
COPY src/ src/
RUN mkdir -p data data/sessions data/queue data/mailbox
EXPOSE 7146
CMD ["python", "app.py"]
```

### MSSQL

```dockerfile
FROM tina4stack/tina4-python:v3
WORKDIR /app

# Add MSSQL driver
RUN apk add --no-cache unixodbc-dev freetds-dev && \
    python -m pip install --no-cache-dir pymssql

COPY app.py .
COPY .env .
COPY migrations/ migrations/
COPY src/ src/
RUN mkdir -p data data/sessions data/queue data/mailbox
EXPOSE 7146
CMD ["python", "app.py"]
```

### Firebird

```dockerfile
FROM tina4stack/tina4-python:v3
WORKDIR /app

# Firebird driver is pure Python — no system deps needed
RUN python -m pip install --no-cache-dir firebird-driver

COPY app.py .
COPY .env .
COPY migrations/ migrations/
COPY src/ src/
RUN mkdir -p data data/sessions data/queue data/mailbox
EXPOSE 7146
CMD ["python", "app.py"]
```

## Docker Compose

```yaml
services:
  app:
    build: .
    ports:
      - "7146:7146"
    environment:
      - TINA4_DEBUG=false
      - JWT_SECRET=${JWT_SECRET}
      - TINA4_DATABASE_URL=sqlite:///data/app.db
    volumes:
      - app-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:7146/health')"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  app-data:
```

## Environment Variables

Pass secrets at runtime, never bake them into images:

```bash
docker run -d \
  -p 7146:7146 \
  -e JWT_SECRET=your-secret \
  -e TINA4_DATABASE_URL=sqlite:///data/app.db \
  -e TINA4_DEBUG=false \
  -v $(pwd)/data:/app/data \
  my-app
```

## Key Environment Variables for Docker

| Variable | Default | Purpose |
|----------|---------|---------|
| `TINA4_OVERRIDE_CLIENT` | `true` (set in base image) | Bypass the CLI guard in Docker |
| `TINA4_DEBUG` | `false` (set in base image) | Disable debug mode |
| `TINA4_NO_BROWSER` | `true` (base image) | Prevent browser open |
| `PYTHONUNBUFFERED` | `1` (base image) | Flush stdout for Docker logs |
| `HOST` | `0.0.0.0` (base image) | Bind address |
| `PORT` | `7146` | Listen port |

## Production Checklist

1. Use `tina4stack/tina4-python:v3` as the base
2. Mount a volume for `/app/data` (SQLite database, sessions, queue)
3. Set `TINA4_DEBUG=false`
4. Pass `JWT_SECRET` via environment variable (not `.env` in the image)
5. Add a health-check endpoint at `/health`
6. Configure the Docker restart policy (`unless-stopped` or `always`)
7. Set up log rotation via the Docker logging driver
8. Use a reverse proxy (nginx/Traefik) for SSL termination in front
