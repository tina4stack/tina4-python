# Tina4 Python — Release Notes

All notable changes to tina4-python are documented here.

---

## v0.2.198 — 2026-03-14

**Fix Swagger noauth crash, CLI port override, decorator docs**

### Bug fixes

- **Fix `set_swagger_value` crash**: using swagger decorators (`@description`, `@tags`, `@example`) above route decorators (`@post`, `@get`) caused `TypeError: 'NoneType' object does not support item assignment`. Root cause: `Router.add()` initializes `swagger: None` but `set_swagger_value` only checked key existence, not `None` value
- **Fix `Swagger.noauth()` not bypassing auth**: the Swagger version of `noauth()` only set documentation metadata (`secure: False`), but never set the route-level `noauth` flag that the router actually checks. Anyone importing `noauth` from `tina4_python.Swagger` instead of `tina4_python.Router` would silently get no auth bypass
- **Fix CLI port ignored by `run_web_server()`**: running `python app.py 7112` would use the hardcoded port instead of 7112. CLI arguments (`sys.argv`) were only parsed in the auto-start path, not in `run_web_server()`. Now both paths respect CLI port/host arguments

### Documentation

- **CLAUDE.md**: documented correct decorator ordering (route decorators must be innermost) and warned against importing `noauth` from `Swagger`

### Tests

- Added 4 tests verifying `@noauth()` actually bypasses auth without tokens
- Added test confirming POST without `@noauth()` returns 403

---

## v0.2.197 — 2026-03-11

**Security hardening: HTTP headers and cookie attributes**

### Security fixes

- **Session cookie attributes**: added `Path=/`, `HttpOnly`, `SameSite=Lax` to the session cookie. Added conditional `Secure` flag when behind HTTPS (detected via `X-Forwarded-Proto` header)
- **CORS fix**: `Access-Control-Allow-Origin: *` combined with `Access-Control-Allow-Credentials: true` is invalid per spec. Now reflects the request `Origin` header when credentials are needed, falls back to `*` for simple requests
- **Security headers**: added `X-Content-Type-Options: nosniff` and `X-Frame-Options: SAMEORIGIN` to all responses to prevent MIME-sniffing and clickjacking
- **Cache-Control fix**: replaced non-standard `max-age=-1` with `no-store, no-cache, must-revalidate` for uncached responses. Prevents authenticated content from leaking via shared proxies or browser disk cache
- **Response splitting prevention**: `Response.redirect()` and `Response.add_header()` now strip CR/LF characters to prevent HTTP header injection attacks

---

## v0.2.196 — 2026-03-11

**Fix: session cookie not sent on redirect responses**

### Bug fixes

- **Session cookie now sent on 301/302/303 redirects**: when a route saved data to the session and returned `Response.redirect()`, the `Set-Cookie` header was skipped because it was inside the non-redirect code path. This meant the browser never received the session cookie, so the next request (after the redirect) had no session. The cookie is now sent regardless of response code.

### Added

- Session form test pages (`/session-form` and `/session-info`) for manual verification of form POST → session → redirect flow

---

## v0.2.195 — 2026-03-11

**Fix: session and FreshToken issues from v0.2.194**

### Bug fixes

- **FreshToken now sent for Authorization header auth**: `tina4helper.js` sends `formToken` via the `Authorization: Bearer` header for AJAX calls. v0.2.194 only checked for `formToken` in body/params, causing the token to expire after `TINA4_TOKEN_LIMIT` minutes without being refreshed. Now any valid Bearer token triggers FreshToken generation
- **LazySession.start() cookie sync**: calling `session.start()` explicitly (e.g. session regeneration after login) now correctly updates the cookie dict. Previously the new session hash was not synced to the `Set-Cookie` header, causing session data loss on the next request
- **LazySession.load() cookie sync**: calling `session.load(hash)` explicitly now updates the cookie dict to match the loaded session hash

### Tests

- Added 22 new LazySession tests covering: deferred activation, cookie synchronisation, data persistence across request instances, explicit start/load hash syncing, close/save no-op when not activated

---

## v0.2.194 — 2026-03-11

**Performance: LazySession + conditional FreshToken**

This release delivers a major performance improvement — up to 60x faster for API routes.

### Performance

- **LazySession**: sessions are now deferred until first use. API routes that don't call `request.session` skip RSA JWT signing entirely (~1ms saved per request)
- **Conditional FreshToken**: the `FreshToken` response header is now only generated when the request includes a valid `formToken`. Pure API calls with Bearer tokens or API_KEY no longer pay the RSA signing cost
- **Removed redundant FreshToken**: previously generated twice per request — now generated at most once
- **Fixed debug mode override**: `TINA4_DEBUG_LEVEL` was being set to `"DEBUG"` before `.env` was loaded, meaning `.env` settings were always ignored. Now respects your `.env` configuration

### Benchmarks (10,000 requests, 100 concurrent)

| Server | Before | After |
|--------|--------|-------|
| Hypercorn (single) | 155 req/s | 3,016 req/s |
| Uvicorn (single) | — | 3,834 req/s |
| Gunicorn + Uvicorn (4 workers) | 1,873 req/s | 9,350 req/s |

### Breaking changes

- **FreshToken header no longer on every response**: only present when the request contains a `formToken`. If your custom JavaScript reads `FreshToken` from response headers, check for its existence first. `tina4helper.js` already handles this correctly — no changes needed if you use the built-in helper
- **Session cookie (`Set-Cookie`) no longer on every response**: only sent when the session is actually accessed. API-only routes won't set session cookies
- **`TINA4_DEBUG_LEVEL` no longer defaults to `DEBUG`**: if you relied on debug mode being on by default, explicitly set `TINA4_DEBUG_LEVEL=Debug` in your `.env`
- **`isinstance(session, Session)` checks may fail**: the session object is now a `LazySession` proxy. Use the session API (`.get()`, `.set()`) directly instead of type-checking

### Migration guide

Most applications require no changes. If you have custom token handling:

```javascript
// Before (assumes FreshToken always present):
const token = response.headers['FreshToken'];

// After (check first):
const token = response.headers['FreshToken'];
if (token) {
    formToken = token;
}
```

### Files changed

- `tina4_python/Router.py` — conditional FreshToken based on `has_form_token` flag
- `tina4_python/Session.py` — new `LazySession` class
- `tina4_python/Webserver.py` — conditional session cookie, LazySession in non-ASGI path
- `tina4_python/__init__.py` — removed premature debug default, LazySession in ASGI app

---

## v0.2.193 — 2026-03-09

### Bug fixes

- **Fix Router: missing Messages import** — secured routes returning 403 would crash with `NameError` because `Messages` was not imported in `Router.py`
- **Fix Dockerfile**: removed `-e` flag from `uv pip install` for multi-stage builds

### Tests

- Added secured route 403 test to catch missing imports
- Added mocked connection tests for charset support

---

## v0.2.192 — 2026-03-07

### Bug fixes

- **Fix Firebird connect**: pass DSN as positional argument instead of keyword argument, fixing connection failures with `firebird-driver`

---

## v0.2.191 — 2026-03-07

### Features

- **Database charset support**: added `charset` parameter to Database connections for MySQL, PostgreSQL, and Firebird
- **Full i18n**: centralized all framework messages into `Messages.py` with translations for 6 languages (English, French, Afrikaans, Chinese, Japanese, Spanish)

### Improvements

- Fixed localization fallback behavior and return values
- Added Afrikaans translations

---

## v0.2.189 — 2026-03-05

### Features

- **MongoDB session backend** (`SessionMongoHandler`): store sessions in MongoDB with configurable host, port, URI, database, and collection via environment variables

---

## v0.2.188 — 2026-03-05

### Bug fixes

- **Fix Swagger bugs**: resolved multiple issues with Swagger/OpenAPI documentation generation
- Added comprehensive Swagger test suite (93 tests)

---

## v0.2.187 — 2026-03-05

### Documentation

- Complete rewrite of CLAUDE.md with coding principles, Api, Queue, DevReload, and WSDL documentation

---

## v0.2.186 — 2026-03-04

### Bug fixes

- **Fix double server**: detect `run_web_server()` in user code to skip auto-start, preventing two servers from launching simultaneously

---

## v0.2.185 — 2026-03-04

### Changes

- **jurigged moved to default dependencies**: hot-reloading now available without installing dev dependencies

---

## v0.2.184 — 2026-03-04

### Bug fixes

- **Disable Hypercorn reloader**: DevReload now handles all file watching, preventing duplicate reload triggers

---

## v0.2.183 — 2026-03-04

### Bug fixes

- **Fix Ctrl+C with active WebSocket**: shared shutdown event between signal handler and WebSocket prevents hanging on exit

---

## v0.2.182 — 2026-03-04

### Bug fixes

- **Fix Ctrl+C shutdown**: handle `CancelledError` in WebSocket handler and restore `KeyboardInterrupt` propagation

---

## v0.2.181 — 2026-03-04

### Bug fixes

- **Fix Ctrl+C**: added `shutdown_trigger` to Hypercorn serve for clean shutdown

---

## v0.2.180 — 2026-03-04

### Bug fixes

- **Fix DevReload**: thread-safe WebSocket notification prevents race conditions during live reload

---

## v0.2.179 — 2026-03-04

### Improvements

- Suppress duplicate Hypercorn "Running on" banner

---

## v0.2.178 — 2026-03-04

### Improvements

- Show `localhost` in server banner when binding to `0.0.0.0`

---

## v0.2.177 — 2026-03-04

### Tests

- Make integration tests self-contained with inline routes
- Fix integration test skip logic

---

## v0.2.176 — 2026-03-04

### Features

- **DevReload system**: live browser reload via WebSocket when `.py`, `.twig`, `.html`, `.js` files change. CSS hot-reload for SCSS changes. Error overlay for runtime errors. Hot-patching via jurigged
- Added module docstrings and `__all__` exports across the framework

---

## v0.2.174/175 — 2026-03-03

### Features

- **CLAUDE.md developer guidelines**: auto-generated on `tina4 init` to help AI assistants and developers understand project conventions

---

## v0.2.173 — 2026-03-01

### Bug fixes

- **Fix concurrency bugs and security issues** across the framework
- Keep original Auth default secret for backward compatibility

---

## v0.2.172 — 2026-02-28

Maintenance release.

---

## v0.2.170/171 — 2026-02-03 to 2026-02-22

Maintenance releases.

---

## v0.2.168/169 — 2026-01-31

Maintenance releases.

---

## v0.2.167 — 2026-01-28

Maintenance release.

---

## v0.2.166 — 2026-01-16

Maintenance release.

---

## v0.2.165 — 2026-01-14

Maintenance release.

---

## v0.2.163/164 — 2025

### Bug fixes

- **Fix ASGI preflight response**: `tina4_response` was `None` for OPTIONS requests, causing exceptions
- **Fix ASGI redirect headers**: headers containing `:` in the Location value were split incorrectly. Now splits only on the first `:`

---

## v0.2.160/161 — 2025

### Improvements

- Updated Queue handler for better efficiency before adding batching support

---

## v0.2.151–159 — 2025

Maintenance and stability releases.

---

## v0.2.144–150 — 2025

### Improvements

- Request and response arguments can now be in any order in route handlers
- Fix for banner display on non-Unicode terminal systems
- Added GitHub workflow tests

---

## v0.2.141/142 — 2025

### Features

- **Inline testing framework**: `@tests` decorator with `assert_equal` and `assert_raises`
- **WSDL/SOAP services**: auto-generated WSDL from Python classes with `@wsdl_operation`
- WebSocket routing improvements
- SCSS auto-compilation to `default.css`
- Added `to_csv` quoting support on `DatabaseResult`
- Added `requests` to default dependencies

---

## v0.2.134–138 — 2025

### Features

- **Field types refactored** into their own module (`FieldTypes.py`)
- **Template decorator**: `@template()` for auto-rendering dict returns through Twig templates
- **Swagger improvements**: fixes for parameter annotations and custom routes
- **`response.file()`**: serve files directly from route handlers
- **`datetime_format` Twig filter**: format dates in templates
- **Builtins**: reduced import boilerplate with auto-importing of common functions

---

## v0.2.129–133 — 2025

### Features

- **CRUD scaffolding**: `CRUD.to_crud()` generates searchable, paginated admin UI with create/edit/delete modals
- **JSONB field type** for PostgreSQL

---

## v0.2.123–128 — 2025

Initial CRUD implementation and iterations.

---

## v0.2.115–122 — 2025

### Bug fixes

- Middleware fixes: async/await for asynchronous middleware methods
- Router updates for `@noauth()` decorator
- Fix for missing second value on JSON and Text responses

---

## v0.2.113/114 — 2025

### Bug fixes

- **Fix middleware**: async method detection, proper awaiting of async calls, condition checks for middleware method lists

---

## v0.2.111 — 2025

### Improvements

- Better exception handling in Debug mode
- ORM no longer creates migration files automatically (suggests in log instead)
- Files object on request can handle arrays of files
- Proper exception when checking if a table exists

---

## v0.2.110 — 2025

### Features

- **Valkey session handler** (`SessionValkeyHandler`): Redis open-source alternative for session storage with optional SSL

---

## v0.2.109 — 2025

### Features

- Queues can have their own callbacks in a consumer

---

## v0.2.104–108 — 2025

### Bug fixes

- Fixes for `stdout` flushing and debug output
- File watching refinements

---

## v0.2.99/100 — 2025

### Bug fixes

- Queue fixes and debug filename support

---

## v0.2.98 — 2025

### Changes

- Built-in webserver turned off by default (ASGI via Hypercorn is now the default)
- Package manager changed to UV

---

## v0.2.94–96 — 2025

### Changes

- **Package manager changed to UV** from Poetry
- Minor fixes for built-in webserver

---

## v0.2.92/93 — 2025

### Features

- Added `TINA4_SESSION_REDIS_SECRET` for Redis session handler
- Fix for built-in webserver `NoneType` await error

---

## v0.2.90/91 — 2025

### Bug fixes

- Fix for queue consumer message firing multiple times

---

## v0.2.88/89 — 2025

### Features

- `start_in_thread()` method for background thread routines
- Queue producer returns message ID for tracing
- More data type conversions in templates and responses
- Minor fixes for message status in queue and RabbitMQ topic handling

---

## v0.2.87 — 2025

### Bug fixes

- Fix for ORM when foreign key defaults are not set

---

## v0.2.86 — 2025

### Features

- **MSSQL database support**

---

## v0.2.85 — 2025

Package fixes and ORM import fix for Python 3.13.

---

## v0.2.80–83 — 2025

### Bug fixes

- ORM object cleanup on instantiation
- Removed debug output from ORM

---

## v0.2.78/79 — 2025

### Bug fixes

- Fix ORM objects not being cleaned out correctly on instantiation

---

## v0.2.77 — 2025

### Features

- Added iterator to `DatabaseResult` — use `for row in result` directly

---

## v0.2.76 — 2025

### Features

- **Hypercorn integrated as default ASGI server** with route-based WebSockets using `simple_websockets`

---

## v0.2.74 — 2025

### Features

- **WebSocket support**: route-based WebSockets via `simple-websocket`

---

## v0.2.73 — 2025

### Improvements

- Added filtering/transforming to `DatabaseResult`
- Removed ORM debugging output

---

## v0.2.72 — 2025

### Improvements

- ORM updates and session injection into Twig templates

---

## v0.2.71 — 2025

### Features

- **ASGI support**: run as standard ASGI application. Tested with Hypercorn, Uvicorn, and Granian

---

## v0.2.70 — 2025

### Bug fixes

- ORM migration fixes
- Simplified auto-loading

---

## v0.2.64–69 — 2025

### Bug fixes

- MySQL reconnect on disconnect
- ORM commit on save/delete for MySQL query caching
- Pagination and record counter fixes

---

## v0.2.62/63 — 2025

### Bug fixes

- Pagination and record counter fixes
- Parameter injection fix on `fetch_one`

---

## v0.2.60/61 — 2025

### Bug fixes

- Serialization fix on `DatabaseResult`
- Record counter fix

---

## v0.2.58/59 — 2025

### Features

- **Pagination**: `result.to_paginate()` on `DatabaseResult`
- ORM protected field support

---

## v0.2.57 — 2025

### Improvements

- 500 errors now returned based on `content-type` headers (JSON for API, HTML for browser)

---

## v0.2.56 — 2025

### Bug fixes

- Fix for web server termination

---

## v0.2.55 — 2025

### Improvements

- Better error handling in Webserver
- ORM protected field support
- Response can convert ORM objects to JSON

---

## v0.2.54 — 2025

### Features

- Added `RANDOM()` function to Twig templates
- ORM tweaks and `tina4helper.js` updates

---

## v0.2.51–53 — 2025

### Performance

- Static file serving performance enhancements

---

## v0.2.50 — 2025

### Bug fixes

- Fixed RabbitMQ virtual host configuration

---

## v0.2.48 — 2025

### Changes

- Removed jurigged from default dependencies (re-added in v0.2.185)
- Added RabbitMQ credentials for remote host access

---

## v0.2.47 — 2025

### Improvements

- ORM no longer reads unknown files, forced `orm/` folder creation
- Added prefix to queue topics

---

## v0.2.46 — 2025

Documentation fixes for Database.

---

## v0.2.45 — 2025

### Bug fixes

- Fix Debug logging duplicate timestamps

---

## v0.2.44 — 2025

### Features

- **Queue system**: background processing with litequeue (default), RabbitMQ, and Kafka support
- Updated Debug with `info()`, `warning()`, `error()` methods
- Session dump available in Jinja templates
- SQLite3 datetime functions updated to avoid deprecation

---

## v0.2.43 — 2025

### Features

- Auth serializer for complex objects in JWT payloads

---

## v0.2.41 — 2025

### Features

- **Redis session handler** (`SessionRedisHandler`)

---

## v0.2.39 — 2025

### Improvements

- Migration termination on failure

---

## v0.2.36–38 — 2025

### Features

- **ORM**: initial implementation with typed fields, save/load/select/delete
- Fix for decimal object serialization in database results

---

## v0.2.35 — 2025

### Bug fixes

- Fix for date objects not serializing on database retrieval

---

## v0.2.31–34 — 2025

### Features

- **MySQL database support**
- Migration fixes for MySQL `tina4_migration` table

---

## v0.2.30 — 2025

### Features

- **FreshToken**: automatic token rotation via response headers
- Custom Swagger route support via `.env`
- Advanced request variable interpretation

---

## v0.2.23–27 — 2025

### Features

- **Middleware**: `@middleware()` decorator with before/after hooks
- Refactored Request and Response classes

---

## v0.2.22 — 2025

### Features

- Added `request.url` variable

---

## v0.2.21 — 2025

### Features

- **Route caching**: `@cache(False, max_age=0)` decorator

---

## v0.2.20 — 2025

### Bug fixes

- Fix sessions under Passenger Phusion

---

## v0.2.17–19 — 2025

### Features

- Request object now includes raw content and raw request

---

## v0.2.16 — 2025

### Improvements

- Debug level refinements

---

## v0.2.13 — 2025

### Features

- **File-based debug logging** with rotation for threaded methods

---

## v0.2.11/12 — 2025

### Features

- **`response.redirect()`**: redirect responses from route handlers

---

## v0.2.10 — 2025

### Bug fixes

- Fix for `content-length` under Passenger Phusion

---

## v0.2.9 — 2025

### Bug fixes

- Fix for Passenger Phusion authorization headers (lowercase)

---

## v0.2.8 — 2025

### Bug fixes

- Fix Swagger documentation when no host name is present

---

## v0.2.7 — 2025

### Bug fixes

- Added CR to headers

---

## v0.2.6 — 2025

### Features

- `print()` output can be substituted instead of returning a response

---

## v0.2.2/3 — 2025

### Features

- **Secured GET routes**: `@secured()` decorator
- JSON error responses for API endpoints

---

## v0.1.88–96 — 2025

### Features

- Database insert returns new IDs
- Case-insensitive `content-type` header handling
- Multipart form-data and binary POST support
- Base64 encoding fixes for file uploads on Mac

---

## v1.0.79 — 2025

### Bug fixes

- Fix Auth `hash_password` and `check_password` to accept strings
- Added `to_array()` on `DatabaseResult` for Twig templates (auto-encodes bytes)

---

## v1.0.67–69 — 2025

### Features

- **Swagger/OpenAPI**: auto-generated documentation at `/swagger`
- Form token updates

---

## v1.0.55 — 2025

### Features

- **Migrations**: `Migration.py` for versioned SQL schema changes
- Shell colors for debug output
- Server banner shows `localhost` URL for easy access

---

## v1.0.52 — 2025

### Features

- **Session handling**: cookie-based sessions with file storage
- Improved Debug with multiple inputs and correct debug levels from `.env`
- Added flake8 for static code analysis

---

## v0.2.44–48 (v44–48) — 2025

### Features

- Form token validation with `formToken` in POST bodies
- `TINA4_TOKEN_LIMIT` environment variable for token expiry
- SASS/SCSS compiler

---

## v40–43 — 2025

### Features

- **JWT authentication**: RS256 tokens with auto-generated RSA keys
- Security enforcement on POST, PUT, PATCH, DELETE methods
- `@noauth()` to make write routes public

---

## Pre-release — 2025

### Initial features

- Prototype routing with decorator-based handlers (`@get`, `@post`)
- Async web server
- Static file serving from `src/public/`
- Twig/Jinja2 template rendering from `src/templates/`
- Environment variable loading from `.env` via `python-dotenv`
- Parameterized routing (`{id}`, `{id:int}`)
- CORS support with OPTIONS handling
- Request body parsing (JSON, form data)
- CSS/SCSS support
- Localization framework
- PyPI package publishing

---

*Tina4 — The framework that keeps out of the way of your coding.*
