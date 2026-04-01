# Tina4 Python — Test Coverage Plan

Version: 3.10.37 | Last updated: 2026-03-31

## Summary

- **Test files**: 52
- **Test methods**: 2,018
- **Test runner**: pytest (asyncio_mode = auto)
- **Run all**: `.venv/bin/python -m pytest tests/`
- **Run one**: `.venv/bin/python -m pytest tests/test_file.py::TestClass::test_method`

## Test Inventory

| # | Test File | Tests | Feature | Status |
|---|-----------|-------|---------|--------|
| 1 | test_ai.py | 26 | AI context detection & install | Done |
| 2 | test_api.py | 32 | Api HTTP client | Done |
| 3 | test_auth.py | 51 | Auth (JWT, password hashing) | Done |
| 4 | test_cache.py | 58 | Response cache (LRU, TTL, middleware) | Done |
| 5 | test_container.py | 23 | DI Container | Done |
| 6 | test_cors.py | 25 | CORS middleware | Done |
| 7 | test_crud.py | 20 | AutoCrud REST generator | Done |
| 8 | test_csrf_middleware.py | 29 | CSRF protection middleware | Done |
| 9 | test_database.py | 28 | Database core (connection, CRUD, transactions) | Done |
| 10 | test_database_drivers.py | 75 | All 6 database drivers | Done |
| 11 | test_dev_admin.py | 63 | DevAdmin dashboard & gallery | Done |
| 12 | test_dev_mailbox.py | 18 | Dev mailbox | Done |
| 13 | test_dotenv.py | 21 | DotEnv loader | Done |
| 14 | test_error_overlay.py | 22 | Error overlay (debug/production) | Done |
| 15 | test_events.py | 28 | Event system (on, emit, once, off) | Done |
| 16 | test_fake_data.py | 30 | FakeData generator | Done |
| 17 | test_form_token.py | 21 | Form token generation/validation | Done |
| 18 | test_frond.py | 229 | Frond template engine (all features) | Done |
| 19 | test_gallery.py | 16 | Gallery interactive examples | Done |
| 20 | test_graphql.py | 29 | GraphQL engine | Done |
| 21 | test_health.py | 13 | Health endpoint | Done |
| 22 | test_html_element.py | 29 | HtmlElement builder | Done |
| 23 | test_i18n.py | 22 | i18n / localization | Done |
| 24 | test_live_reload.py | 36 | DevReload / live-reload | Done |
| 25 | test_log.py | 29 | Structured logging | Done |
| 26 | test_mcp.py | 24 | MCP server | Done |
| 27 | test_messenger.py | 34 | Messenger (SMTP/IMAP email) | Done |
| 28 | test_middleware.py | 18 | Middleware lifecycle | Done |
| 29 | test_migration.py | 26 | Migrations | Done |
| 30 | test_new_features.py | 43 | Cross-cutting new feature tests | Done |
| 31 | test_orm.py | 67 | ORM (model, fields, relationships, soft-delete) | Done |
| 32 | test_port_config.py | 11 | Port configuration | Done |
| 33 | test_post_protection.py | 19 | POST route auth protection | Done |
| 34 | test_query_builder.py | 53 | QueryBuilder + NoSQL/Mongo | Done |
| 35 | test_queue.py | 31 | Queue (push, pop, consume, retry) | Done |
| 36 | test_queue_backends.py | 49 | Queue backends (Kafka, RabbitMQ, MongoDB) | Done |
| 37 | test_rate_limiter.py | 17 | Rate limiter middleware | Done |
| 38 | test_response.py | 25 | Response object | Done |
| 39 | test_router.py | 35 | Router (registration, matching, params) | Done |
| 40 | test_scss.py | 26 | SCSS compiler | Done |
| 41 | test_seeder.py | 49 | Seeder (FakeData + seed_table) | Done |
| 42 | test_service.py | 38 | Service layer | Done |
| 43 | test_session.py | 50 | Sessions (file, database) | Done |
| 44 | test_session_handlers.py | 47 | Session handlers (Redis, Valkey, MongoDB) | Done |
| 45 | test_smoke.py | 98 | Smoke tests (end-to-end integration) | Done |
| 46 | test_sql_translation.py | 38 | SQL translation (cross-engine) | Done |
| 47 | test_static.py | 31 | Static file serving | Done |
| 48 | test_swagger.py | 57 | Swagger/OpenAPI generation | Done |
| 49 | test_template_decorator.py | 11 | @template decorator | Done |
| 50 | test_testing.py | 3 | Inline Testing framework | Done |
| 51 | test_websocket.py | 86 | WebSocket server + backplane | Done |
| 52 | test_wsdl.py | 59 | WSDL/SOAP services | Done |

## Coverage by Feature Area

| Area | Tests | % of total |
|------|-------|-----------|
| Template engine (Frond) | 229 | 11.3% |
| Smoke / integration | 98 | 4.9% |
| WebSocket | 86 | 4.3% |
| Database (all) | 103 | 5.1% |
| ORM | 67 | 3.3% |
| DevAdmin | 63 | 3.1% |
| Auth | 51 | 2.5% |
| Sessions (all) | 97 | 4.8% |
| Cache | 58 | 2.9% |
| Queue (all) | 80 | 4.0% |
| Swagger | 57 | 2.8% |
| WSDL | 59 | 2.9% |

## Gaps / Needs Improvement

| Feature | Current | Recommended | Notes |
|---------|---------|-------------|-------|
| Inline Testing | 3 tests | 10+ | Minimal coverage of the Testing.py framework |
| Validator | 0 dedicated | 15+ | No test_validator.py — may be folded into other tests |
| Port config | 11 tests | — | Adequate |
| Gallery | 16 tests | — | Adequate |
| Health | 13 tests | — | Adequate |

## All features have test coverage
Every module in `tina4_python/` has a corresponding test file. The only gap is the Validator module which lacks a dedicated test file (coverage may be in test_new_features.py or test_smoke.py).
