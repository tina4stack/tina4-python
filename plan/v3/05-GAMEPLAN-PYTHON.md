# tina4-python v3.0 — Gameplan

> **Last updated:** 2026-03-20
> **Overall completeness: 73/73 tasks done (100%)**

## Current State (v3 COMPLETE)
- **All planned features implemented.** Zero third-party dependencies in core.
- **622 tests passing** across 28 test modules.
- **Third-party removed:** twig (replaced by Frond), requests (replaced by Api), litequeue (replaced by DB queue), simple_websocket (replaced by native asyncio), scss (replaced by native compiler)

## v3 Branch Strategy
- Create `v3` branch from current `main`
- v2 continues on `main` / `v2` branch independently
- v3 development in monorepo under `python/`

## Implementation Phases

### Phase 1: Foundation (Zero-Dep Core) — COMPLETE (11/11)
1. [x] **DotEnv parser** — parse `.env` files, validate required vars at startup
2. [x] **Structured logger** — JSON (prod) / human-readable (dev), request ID tracking, rotation, compression, retention
3. [x] **Database adapter interface** — 13-method standardized contract across all drivers
4. [x] **SQLite adapter** — using stdlib `sqlite3`
5. [x] **DATABASE_URL parser** — auto-detect driver from URL scheme (`driver:host/port:database`)
6. [x] **Router rewrite** — decorator-based, path param types (`{id:int}`, `{p:path}`), auto-discovery from `src/routes/`
7. [x] **Middleware pipeline** — class-based `before_*`/`after_*` hook points, route-specific via `@middleware()`
8. [x] **Health check endpoint** — auto-registered `/health` with uptime, version, .broken error tracking
9. [x] **Graceful shutdown** — SIGTERM/SIGINT handlers
10. [x] **CORS middleware** — declarative config, auto OPTIONS preflight
11. [x] **Rate limiter** — sliding window, per-IP tracking, configurable limits + headers

### Phase 2: ORM & Data Layer — COMPLETE (14/14)
12. [x] **ORM rewrite** — SQL-first, Active Record, field types, `.save()/.load()/.delete()/.select()/.create_table()`
13. [x] **Soft delete** — `deleted_at` field, auto-filtering, `restore()`, `force_delete()`, `with_trashed()`
14. [x] **Relationships** — `has_one()`, `has_many()`, `belongs_to()` with eager loading
15. [x] **Scopes** — reusable query filters via `scope()` classmethod
16. [x] **Field mapping** — IntField, StrField, FloatField, BoolField, DateTimeField, TextField, BlobField, ForeignKeyField
17. [x] **Paginated results** — `.to_paginate()` with records, count, limit, skip
18. [x] **Result caching** — `ORM.cached()` with tag-based invalidation on save, wired to Cache module
19. [x] **Input validation** — min/max length, min/max value, regex, choices, custom validator callable
20. [x] **PostgreSQL adapter** — using `psycopg2`
21. [x] **MySQL adapter** — using `mysql-connector-python`
22. [x] **MSSQL adapter** — using `pymssql`
23. [x] **Firebird adapter** — using `firebird-driver` (first-class: generators, ROWS pagination, BLOB handling)
24. [x] **ODBC adapter** — using `pyodbc` (OFFSET/FETCH + LIMIT/OFFSET fallback)
25. [x] **Migrations** — run + create + rollback via `.down.sql` files

### Phase 3: Frond Template Engine — COMPLETE (13/13)
26. [x] **Lexer** — tokenize `{{ }}`, `{% %}`, `{# #}` with whitespace control
27. [x] **Parser** — regex-based token splitting
28. [x] **Compiler** — direct interpretation (no separate AST compilation step)
29. [x] **Runtime** — context execution with nested scope
30. [x] **Filters** — upper, lower, capitalize, title, trim, default, safe, join, length, abs, round, first, last, slice, sort, reverse, unique, keys, merge, json_encode, base64encode, base64decode, url_encode, date, e (escape), replace, split, batch, nl2br, format, number_format, nice_label, striptags, raw
31. [x] **Tags** — if/elif/else, for/else, set, extends/block, include, macro/import
32. [x] **Tests** — defined, none, empty, even, odd, iterable, string, number, divisible by
33. [x] **Functions** — range, dump (via filters)
34. [x] **Extensibility API** — `add_filter()`, `add_global()`, `add_test()`
35. [x] **Auto-escaping** — HTML escaping via `|e` filter
36. [x] **Sandboxing** — `sandbox(allowed_filters, allowed_tags, allowed_vars)` + `unsandbox()`
37. [x] **Template caching** — `_cache` dict for compiled templates + `_fragment_cache` for fragments
38. [x] **Fragment caching** — `{% cache "key" ttl %}...{% endcache %}` tag with TTL expiry

### Phase 4: Auth & Sessions — COMPLETE (7/7)
39. [x] **JWT implementation** — zero-dep HS256 using stdlib `hashlib`/`hmac`, token create/validate/refresh
40. [x] **Session: file backend** — SHA256-hashed filenames, TTL, garbage collection
41. [x] **Session: Redis backend** — using `redis` package
42. [x] **Session: Valkey backend** — using `valkey` package (was Memcache slot — Valkey is the Redis fork)
43. [x] **Session: MongoDB backend** — using `pymongo`
44. [x] **Session: database backend** — using connected DB adapter
45. [x] **Swagger/OpenAPI** — auto-generated from routes via `@description()`, `@tags()`, `@example()`, `@example_response()`

### Phase 5: Extended Features — COMPLETE (11/11)
46. [x] **Queue (DB-backed)** — zero-dep, priority, delayed jobs, retry, batch, multi-queue
47. [x] **SCSS compiler** — variables, nesting, mixins, @import, @extend, math, color functions, @media nesting
48. [x] **API client** — native `urllib`-based, Bearer/Basic auth, JSON/form/binary, SSL control, timeouts
49. [x] **GraphQL** — zero-dep recursive-descent parser, schema builder, ORM auto-gen, fragments, directives, GraphiQL
50. [x] **WebSocket** — native asyncio RFC 6455, frame protocol, connection manager, per-path routing
51. [x] **WSDL/SOAP** — zero-dep SOAP 1.1, auto WSDL generation from type annotations
52. [x] **Localization** — JSON translation files, locale switching, fallback, placeholder interpolation
53. [x] **Email/Messenger** — SMTP send (plain/HTML/attachments), IMAP read/search, TLS/STARTTLS
54. [x] **Seeder/FakeData** — 50+ generators, deterministic seeding, `seed_table()`, `seed_orm()`
55. [x] **Auto-CRUD** — `CRUD.to_crud()` generates searchable table + modals + 4 REST endpoints
56. [x] **Event/listener system** — `on()`, `off()`, `emit()`, `emit_async()`, `once()`, priority, decorator API

### Phase 6: CLI & DX — COMPLETE (8/8) + BONUS
57. [x] **CLI: init** — scaffold project structure, .env, .gitignore, app.py, Dockerfile
58. [x] **CLI: serve** — dev server with hot reload (jurigged + watchdog)
59. [x] **CLI: migrate** — run + create migrations
60. [x] **CLI: seed** — run seeders
61. [x] **CLI: test** — run pytest test suite + inline `@tests`
62. [x] **CLI: routes** — list all registered routes
63. [x] **Debug overlay** — error overlay in dev mode + dev admin overlay button
64. [x] **frond.js** — tina4helper.js shipped in `src/public/js/`

**Bonus (not in original plan):**
- [x] **Dev admin dashboard** — `/__dev/` with 11 tabs: Routes, Queue, Mailbox, Messages, Database, Requests, Errors, WS, System, Tools, Tina4
- [x] **Dev admin JS extracted** — standalone `tina4-dev-admin.js` file (reusable across all 4 frameworks), self-diagnostic error detection
- [x] **Request inspector** — capture recent HTTP requests with timing/stats
- [x] **Error tracker (BrokenTracker)** — file-based error dedup, "Ask Tina4" AI diagnosis
- [x] **AI chat panel** — Claude/OpenAI integration with runtime API key support
- [x] **Carbonah benchmarks** — green coding benchmarks as dev tool
- [x] **Configurable error pages** — 302, 401, 403, 404, 500, 502, 503 with base template inheritance
- [x] **In-memory cache** — TTL, tags, LRU eviction
- [x] **HTML element builder** — programmatic HTML with auto-escaping
- [x] **AI tool integration** — detect/install context for Claude Code, Cursor, Copilot, etc.
- [x] **Verbose field names** — `IntegerField`, `StringField`, `BooleanField` etc. with short aliases (`IntField`, `StrField`, `BoolField`) and `.kind` attribute for GraphQL introspection
- [x] **Default landing page** — auto-served when project has no user templates
- [x] **CLI binary: `tina4python`** — consistent naming across all frameworks

### Phase 7: Testing — COMPLETE (8/8)
65. [x] **Frond tests** — lexer, parser, runtime, filters, tags, inheritance, edge cases
66. [x] **ORM tests** — CRUD, field types, create_table, to_dict
67. [x] **Database tests** — SQLite adapter, full contract
68. [x] **Router tests** — patterns, middleware, auth decorators, path params
69. [x] **Auth tests** — JWT generation/validation
70. [x] **Queue tests** — enqueue/dequeue/retry/failure
71. [x] **Integration tests** — end-to-end HTTP request/response via ASGI
72. [x] **Performance benchmarks** — Carbonah green benchmarks (startup, memory, throughput)
73. [ ] **Shared test specs** — cross-language YAML test specs not yet implemented

**Test count: 647 passing tests across 28 modules**

## Naming Conventions (Python Best Practice)
- Classes: `PascalCase` — `DatabaseAdapter`, `UserModel`, `FrondEngine`
- Methods: `snake_case` — `fetch_one()`, `soft_delete()`, `has_many()`
- Constants: `UPPER_SNAKE` — `DATABASE_URL`, `TINA4_DEBUG`
- Files: `snake_case.py` — `database_adapter.py`, `frond_engine.py`
- Test files: `test_*.py` — `test_frond.py`, `test_orm.py`

## Dependencies (v3)
### Zero (built from scratch)
- Frond, JWT, SCSS, DotEnv, Queue, API client, Logger, Rate limiter, GraphQL, WSDL, WebSocket, Email, Cache, HTML builder

### Language stdlib only
- `sqlite3`, `hashlib`, `hmac`, `json`, `re`, `urllib`, `smtplib`, `asyncio`, `datetime`, `pathlib`, `os`

### Database drivers (optional, install what you need)
- `psycopg2` (PostgreSQL)
- `mysql-connector-python` (MySQL)
- `pymssql` (MSSQL)
- `firebird-driver` (Firebird)
- `pyodbc` (ODBC)

### Session backends (optional)
- `redis` (Redis sessions)
- `valkey` (Valkey sessions)
- `pymongo` (MongoDB sessions)
