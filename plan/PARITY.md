# Tina4 Python — Feature Parity Checklist

Version: 3.10.37 | Last updated: 2026-03-31

This checklist tracks feature parity across all 4 Tina4 frameworks. Every feature must be implemented with equivalent logic AND tests in Python, PHP, Ruby, and Node.js.

## Core HTTP Engine

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| Router (GET/POST/PUT/PATCH/DELETE/ANY) | [x] | [x] | `core/router.py` — 435 lines |
| Path params ({id:int}, {price:float}, {path:path}) | [x] | [x] | |
| Wildcard routes (*) | [x] | [x] | |
| Route grouping | [x] | [x] | |
| Server (HTTP bootstrap) | [x] | [x] | `core/server.py` — 1389 lines |
| Request object | [x] | [x] | body, params, headers, files, session |
| Response object | [x] | [x] | JSON/HTML auto-detect, redirect, render, file |
| Static file serving | [x] | [x] | Auto-serves from `src/public/` |
| CORS middleware | [x] | [x] | All origins by default |
| Health endpoint | [x] | [x] | |
| ASGI/production mode | [x] | [x] | uvicorn auto-detection |

## Auth & Security

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| JWT auth (HMAC-SHA256, zero-dep) | [x] | [x] | `auth/__init__.py` |
| Password hashing (PBKDF2) | [x] | [x] | |
| RSA key auto-generation | [x] | [x] | |
| @secured / @noauth decorators | [x] | [x] | |
| Form token (CSRF) | [x] | [x] | With nonce for uniqueness |
| CSRF middleware | [x] | [x] | |
| Rate limiter | [x] | [x] | |
| Validator | [x] | [x] | `validator/__init__.py` |

## Database

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| URL-based multi-driver connection | [x] | [x] | `database/connection.py` |
| Connection pooling | [x] | [x] | |
| SQLite driver | [x] | [x] | |
| PostgreSQL driver | [x] | [x] | |
| MySQL driver | [x] | [x] | |
| MSSQL driver | [x] | [x] | |
| Firebird driver | [x] | [x] | |
| ODBC driver | [x] | [x] | |
| DatabaseResult (to_json, to_array, to_csv, to_paginate) | [x] | [x] | |
| SQL translation (cross-engine portability) | [x] | [x] | |
| Query caching | [x] | [x] | |
| get_next_id (race-safe sequences) | [x] | [x] | Uses tina4_sequences table |
| Transactions (start/commit/rollback) | [x] | [x] | |

## ORM

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| Active Record (save/load/delete/select) | [x] | [x] | `orm/model.py` |
| Field types (Integer, String, Text, DateTime, etc.) | [x] | [x] | |
| Relationships (has_many, has_one, belongs_to) | [x] | [x] | With eager loading |
| Soft delete (force_delete, restore) | [x] | [x] | |
| create_table() | [x] | [x] | |
| QueryBuilder (fluent queries) | [x] | [x] | With NoSQL/MongoDB support |
| AutoCRUD (REST from ORM) | [x] | [x] | |

## Template Engine (Frond)

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| Jinja2/Twig-compatible syntax | [x] | [x] | `frond/engine.py` — 1969 lines |
| Block inheritance (extends/block) | [x] | [x] | |
| parent()/super() in blocks | [x] | [x] | |
| Include/import/macro | [x] | [x] | |
| Filters (upper, lower, json_encode, etc.) | [x] | [x] | |
| Custom filters/globals/tests | [x] | [x] | |
| SafeString (bypass escaping) | [x] | [x] | |
| Fragment caching ({% cache %}) | [x] | [x] | |
| Raw blocks | [x] | [x] | |
| Sandbox mode | [x] | [x] | |
| form_token / formTokenValue | [x] | [x] | |
| Arithmetic in {% set %} | [x] | [x] | |
| Filter-aware conditions | [x] | [x] | |
| Dev mode cache bypass | [x] | [x] | |

## API & Protocols

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| API client (zero-dep HTTP client) | [x] | [x] | `api/__init__.py` |
| Swagger/OpenAPI 3.0.3 generator | [x] | [x] | |
| GraphQL engine (zero-dep) | [x] | [x] | With ORM auto-generation |
| WSDL/SOAP 1.1 server | [x] | [x] | |
| MCP server (JSON-RPC 2.0 over SSE) | [x] | [x] | 24 built-in dev tools |

## Real-time & Messaging

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| WebSocket server (RFC 6455) | [x] | [x] | |
| WebSocket backplane (Redis/NATS) | [x] | [x] | |
| Messenger (SMTP/IMAP email) | [x] | [x] | |

## Queue

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| Database-backed job queue | [x] | [x] | |
| Kafka backend | [x] | [x] | |
| RabbitMQ backend | [x] | [x] | |
| MongoDB backend | [x] | [x] | |

## Sessions

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| File session handler | [x] | [x] | |
| Database session handler | [x] | [x] | |
| Redis session handler | [x] | [x] | |
| Valkey session handler | [x] | [x] | |
| MongoDB session handler | [x] | [x] | |

## Infrastructure

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| Migrations (SQL-file, batch tracking) | [x] | [x] | |
| Seeder / FakeData | [x] | [x] | |
| i18n / Localization (JSON-based) | [x] | [x] | |
| SCSS compiler (zero-dep) | [x] | [x] | |
| Events (observer pattern) | [x] | [x] | |
| DotEnv loader | [x] | [x] | |
| Structured logging | [x] | [x] | |
| Error overlay (dev mode) | [x] | [x] | |
| DI Container | [x] | [x] | |
| Response cache (LRU, TTL) | [x] | [x] | |
| Service runner | [x] | [x] | |

## Dev Tools

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| DevAdmin dashboard | [x] | [x] | `dev_admin/__init__.py` — 1965 lines |
| DevMailbox | [x] | [x] | |
| DevReload (live-reload + hot-patch) | [x] | [x] | |
| Gallery (7 interactive examples) | [x] | [x] | |
| Metrics (AST-based code analysis) | [x] | [x] | `dev_admin/metrics.py` |
| Version check (proxy) | [x] | [x] | |

## Testing & CLI

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| TestClient (route testing without server) | [x] | [x] | |
| Inline testing (@tests decorator) | [x] | [x] | |
| CLI (init, serve, migrate, generate, test) | [x] | [x] | |
| AI context detection & scaffolding | [x] | [x] | |

## Static Assets

| Feature | Present | Up to scratch | Notes |
|---------|---------|---------------|-------|
| Minified CSS (tina4.min.css) | [x] | [x] | |
| Minified JS (tina4.min.js, frond.min.js) | [x] | [x] | |
| HtmlElement builder | [x] | [x] | |

## Summary

- **Total features**: 75
- **Present**: 75/75
- **Up to scratch**: 75/75
- **Python is the reference implementation** — all features originate here
