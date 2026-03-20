# DotEnv

Tina4 includes a zero-dependency `.env` file parser that loads environment variables into `os.environ` on startup. It supports quoted values, inline comments, the `export` prefix, and override control.

## Basic Usage

```python
from tina4_python.dotenv import load_env, get_env, require_env

# Load .env from current directory
load_env()

# Load a specific file
load_env(".env.staging")

# Get a variable (None if missing)
db_url = get_env("DATABASE_URL")

# Require a variable (raises if missing)
secret = require_env("JWT_SECRET")
```

## .env File Format

```bash
# Database
DATABASE_URL=sqlite:///data/app.db
DATABASE_USERNAME=admin
DATABASE_PASSWORD=secret123

# Authentication
SECRET=my-jwt-signing-key
API_KEY=sk-live-abc123
TINA4_TOKEN_LIMIT=30

# Framework
TINA4_DEBUG_LEVEL=ALL
TINA4_LANGUAGE=en
HOST_NAME=localhost:7145

# Quoted values (preserves spaces)
APP_NAME="My Application"
GREETING='Hello World'

# Inline comments (unquoted values only)
PORT=7145  # Default port

# Export prefix (stripped automatically)
export NODE_ENV=development

# Empty lines and comments are ignored
```

## Override Behavior

By default, existing environment variables are NOT overwritten:

```python
# .env has: SECRET=from-file
# os.environ already has: SECRET=from-system

load_env()
print(os.environ["SECRET"])  # "from-system" — existing value preserved
```

Set `override=True` to always use file values:

```python
load_env(override=True)
print(os.environ["SECRET"])  # "from-file" — file takes precedence
```

## Return Value

`load_env()` returns a dict of all loaded key-value pairs:

```python
loaded = load_env()
print(loaded)
# {"DATABASE_URL": "sqlite:///data/app.db", "SECRET": "my-key", ...}
```

## Common Variables

### Authentication

```bash
SECRET=your-jwt-signing-secret     # JWT signing key (required for production)
API_KEY=your-api-key               # Static bearer token for API auth
TINA4_TOKEN_LIMIT=30               # Token lifetime in minutes
```

### Database

```bash
DATABASE_URL=sqlite:///data/app.db
# Or separate variables:
DATABASE_NAME=mydb
DATABASE_USERNAME=admin
DATABASE_PASSWORD=secret
```

### Framework

```bash
TINA4_DEBUG_LEVEL=ALL              # ALL, DEBUG, INFO, WARNING, ERROR
TINA4_LANGUAGE=en                  # Localization language
TINA4_SESSION_HANDLER=SessionFileHandler
HOST_NAME=localhost:7145
```

### Swagger

```bash
SWAGGER_TITLE=My API
SWAGGER_VERSION=1.0.0
SWAGGER_DESCRIPTION=REST API documentation
SWAGGER_DEV_URL=http://localhost:7145
```

### CORS

```bash
TINA4_CORS_ORIGINS=*                           # Allowed origins
TINA4_CORS_METHODS=GET,POST,PUT,DELETE          # Allowed methods
TINA4_CORS_HEADERS=Content-Type,Authorization   # Allowed headers
TINA4_CORS_MAX_AGE=86400                        # Preflight cache seconds
```

### Rate Limiting

```bash
TINA4_RATE_LIMIT=100   # Requests per window
TINA4_RATE_WINDOW=60   # Window in seconds
```

### Email

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=app-password
SMTP_FROM=you@gmail.com
SMTP_FROM_NAME=My App
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
```

## Multiple Environments

Use separate `.env` files per environment:

```
.env                # Default (loaded first)
.env.development    # Development overrides
.env.staging        # Staging overrides
.env.production     # Production overrides
```

```python
import os

env = os.environ.get("TINA4_ENV", "development")
load_env()               # Load defaults
load_env(f".env.{env}")  # Override with environment-specific values
```

## Tips

- Never commit `.env` files to version control -- add `.env` to `.gitignore`.
- Use `require_env()` for critical variables that must be set (e.g., `SECRET`).
- In production, set variables through your hosting platform's environment configuration.
- Quoted values preserve spaces and special characters.
- Inline comments only work on unquoted values (`KEY=value # comment`).
