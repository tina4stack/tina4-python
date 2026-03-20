# Tina4 Python — Feature Demos

Complete working examples for every feature in the Tina4 Python framework.

## Running the Interactive Demo

The `demo/` directory contains a runnable application that demonstrates every feature live.

```bash
cd tina4-python/demo
pip install -e ..     # install tina4 from parent directory
python app.py         # start the server on port 7145
```

Then visit [http://localhost:7145](http://localhost:7145) to see all features demonstrated with live JSON output.

### What the demo covers

| Route | Feature | Description |
|-------|---------|-------------|
| `/` | Landing page | HTML index with links to all demos |
| `/demo/routing` | Routing | Route decorators, query params, headers |
| `/demo/routing/{id}` | Path params | Dynamic URL parameters |
| `/demo/orm` | ORM | In-memory SQLite: create, insert, query, find |
| `/demo/templates` | Templates (Frond) | Render .html template with variables, loops, conditions |
| `/demo/auth` | Auth (JWT) | Create/validate JWT tokens, password hashing |
| `/demo/queue` | Queue | DB-backed job queue: push, pop, complete |
| `/demo/graphql` | GraphQL | Auto-generated schema from ORM models |
| `/demo/cache` | Cache | TTL, tags, LRU eviction, remember pattern |
| `/demo/events` | Events | Observer pattern: on, emit, once |
| `/demo/i18n` | Localization | JSON translations in English and French |
| `/demo/scss` | SCSS Compiler | Compile SCSS to CSS with variables, nesting, functions |
| `/demo/email` | Email | Messenger configuration (no actual send) |
| `/demo/faker` | Faker | Deterministic fake data generation |
| `/demo/api-client` | API Client | Self-referencing HTTP call to /health |
| `/demo/logging` | Logging | Structured log output (dev and production formats) |
| `/demo/dotenv` | DotEnv | Loaded environment variables |
| `/demo/swagger` | Swagger | Link to /swagger OpenAPI docs |
| `/demo/health` | Health | Link to /health endpoint |
| `/demo/websocket` | WebSocket | WebSocket server configuration info |
| `/demo/wsdl` | WSDL / SOAP | WSDL service info |
| `/demo/middleware` | Middleware | Before/after middleware with timing |
| `/demo/validation` | Validation | ORM field validation with constraints |
| `/demo/shortcomings` | Shortcomings | Honest JSON about what is missing/incomplete |

### Demo project structure

```
demo/
  app.py                    # Entry point
  .env                      # Environment configuration
  src/
    routes/
      demo_routes.py        # All demo route handlers
    templates/
      demo.html             # Frond template for /demo/templates
    locales/
      en.json               # English translations
      fr.json               # French translations
  data/                     # Created at runtime (SQLite DB)
```

---

## Feature Documentation

Each file below covers one feature category with copy-paste-ready code snippets.

Visit [https://tina4.com](https://tina4.com) for full documentation.

| # | Feature | File | Description |
|---|---------|------|-------------|
| 01 | [Routing](01-routing.md) | `01-routing.md` | Route decorators, path params, methods, auth control |
| 02 | [ORM](02-orm.md) | `02-orm.md` | Model definition, CRUD, field types, serialization |
| 03 | [Database](03-database.md) | `03-database.md` | Multi-driver adapters, queries, transactions |
| 04 | [Templates](04-templates.md) | `04-templates.md` | Frond engine: variables, loops, inheritance, filters |
| 05 | [Middleware](05-middleware.md) | `05-middleware.md` | Class-based hooks, route-specific middleware |
| 06 | [Auth](06-auth.md) | `06-auth.md` | JWT tokens, password hashing, session backends |
| 07 | [ORM Advanced](07-orm-advanced.md) | `07-orm-advanced.md` | Relationships, soft delete, scopes, caching, validation |
| 08 | [Queue](08-queue.md) | `08-queue.md` | DB-backed jobs: push, pop, retry, delayed, priority |
| 09 | [GraphQL](09-graphql.md) | `09-graphql.md` | Schema builder, ORM auto-gen, queries, mutations |
| 10 | [WebSocket](10-websocket.md) | `10-websocket.md` | Native RFC 6455 server, per-path routing, broadcast |
| 11 | [API Client](11-api-client.md) | `11-api-client.md` | HTTP client: GET/POST, auth, JSON, SSL |
| 12 | [Email](12-email.md) | `12-email.md` | SMTP send, IMAP read, attachments, HTML email |
| 13 | [Swagger](13-swagger.md) | `13-swagger.md` | OpenAPI auto-generation from route decorators |
| 14 | [SCSS](14-scss.md) | `14-scss.md` | Zero-dep SCSS compiler: variables, nesting, mixins |
| 15 | [Events](15-events.md) | `15-events.md` | Observer pattern: on, emit, once, priority, async |
| 16 | [Cache](16-cache.md) | `16-cache.md` | In-memory cache: TTL, tags, LRU eviction |
| 17 | [Localization](17-localization.md) | `17-localization.md` | i18n: JSON translations, locale switching, placeholders |
| 18 | [Seeder](18-seeder.md) | `18-seeder.md` | Fake data generators, seed_table, deterministic seeding |
| 19 | [CLI](19-cli.md) | `19-cli.md` | CLI commands: init, serve, migrate, seed, test, routes |
| 20 | [Dev Admin](20-dev-admin.md) | `20-dev-admin.md` | Dev dashboard: 11 tabs, request inspector, error tracker |
| 21 | [DotEnv](21-dotenv.md) | `21-dotenv.md` | .env loading, required vars, type casting |
| 22 | [Logging](22-logging.md) | `22-logging.md` | Structured logger: JSON/text output, rotation |
| 23 | [WSDL](23-wsdl.md) | `23-wsdl.md` | SOAP service generation from type annotations |
| 24 | [Security](24-security.md) | `24-security.md` | CORS, rate limiting, auto-escaping, input validation |
| 25 | [Deployment](25-deployment.md) | `25-deployment.md` | Dockerfile, health checks, graceful shutdown |

---

## Architecture Overview

Tina4 Python v3 is built with zero external dependencies in core. Everything from the template engine (Frond) to JWT authentication to the SCSS compiler is implemented using Python stdlib only. Database drivers and session backends are the only optional installs.

```
tina4_python/
  core/       # Router, middleware, cache, events, server
  orm/        # Active Record ORM with field types
  database/   # Multi-driver adapter (SQLite, PostgreSQL, MySQL, MSSQL, Firebird, ODBC, MongoDB)
  frond/      # Twig-compatible template engine
  auth/       # JWT, password hashing, API key auth
  queue/      # DB-backed job queue
  graphql/    # Zero-dep GraphQL engine
  websocket/  # Native RFC 6455 WebSocket server
  api/        # HTTP client (stdlib urllib)
  messenger/  # Email (SMTP send, IMAP read)
  swagger/    # OpenAPI 3.0.3 spec generator
  scss/       # SCSS-to-CSS compiler
  seeder/     # Fake data generation
  i18n/       # Internationalization
  wsdl/       # SOAP/WSDL service
  session/    # Pluggable session backends
  dotenv/     # .env file parser
  debug/      # Structured logging
  cli/        # CLI commands
  dev_admin/  # Development dashboard
```
