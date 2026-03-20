# Tina4 Python — Feature Demos

Complete working examples for every feature in the Tina4 Python framework.
Each file below covers one feature category with copy-paste-ready code snippets.

## Getting Started

```bash
pip install tina4-python
tina4python init my-project
cd my-project
tina4python serve
```

Visit [https://tina4.com](https://tina4.com) for full documentation.

---

## Table of Contents

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
