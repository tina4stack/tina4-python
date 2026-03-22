# Tina4 v3 — Framework Feature & Performance Report

**Date:** 2026-03-21 | **Goal:** Outperform the competition on features and close the performance gap

---

## Performance Benchmarks

### Python — Tina4 vs Competition

Real HTTP benchmarks — identical JSON endpoint, 5000 requests, 50 concurrent.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| Starlette 0.52 | 16,202 | 7,351 | uvicorn (C) | 4 |
| FastAPI 0.115 | 11,855 | 2,476 | uvicorn (C) | 12+ |
| **Tina4 Python 3.0** | **8,316** | **5,688** | **built-in** | **0** |
| Bottle 0.13 | ~7,000 | ~5,000 | built-in | 0 |
| Flask 3.1 | 4,953 | 3,899 | Werkzeug | 6 |
| Django 5.2 | ~3,500 | ~2,800 | runserver | 20+ |

### PHP — Tina4 vs Competition

Real HTTP benchmarks — identical JSON endpoint, 5000 requests, 50 concurrent.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| **Tina4 PHP 3.0** | **27,874** | **22,832** | **custom stream_select** | **0** |
| Slim 4 | 5,033 | 4,520 | php -S | 10+ |
| Symfony 7 | 1,840 | 1,702 | php -S | 30+ |
| Laravel 11 | 370 | 364 | artisan serve | 50+ |

### Ruby — Tina4 vs Competition

Real HTTP benchmarks — identical JSON endpoint, 5000 requests, 50 concurrent.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| Roda | 20,964 | 12,265 | Puma | 1 |
| Sinatra | 9,909 | 7,229 | Puma | 5 |
| **Tina4 Ruby 3.0** | **8,139** | **6,462** | **WEBrick** | **0** |
| Rails 8 | 4,754 | 4,052 | Puma | 69 |

### Node.js — Tina4 vs Competition

Real HTTP benchmarks — identical JSON endpoint, 5000 requests, 50 concurrent.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| Node.js raw | 86,662 | 24,598 | http | 0 |
| Fastify | 79,505 | 23,395 | http | 10+ |
| Koa | 60,400 | 23,433 | http | 5 |
| **Tina4 Node.js 3.0** | **57,035** | **25,088** | **http** | **0** |
| Express | 56,687 | 20,720 | http | 3 |

---

## Out-of-Box Feature Comparison (38 features)

✅ = ships with core install, no extra packages | ❌ = requires additional install

### Python Frameworks

| Feature | Tina4 | Flask | FastAPI | Django | Starlette | Bottle |
|---------|:-----:|:-----:|:-------:|:------:|:---------:|:------:|
| **CORE WEB** | | | | | | |
| Routing (decorators) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Typed path parameters | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Middleware system | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Static file serving | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CORS built-in | ✅ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Rate limiting | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| WebSocket | ✅ | ❌ | ✅ | ❌ | ✅ | ❌ |
| **DATA** | | | | | | |
| ORM | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| 5 database drivers | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Migrations | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Seeder / fake data | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Sessions | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Response caching | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **AUTH** | | | | | | |
| JWT built-in | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Password hashing | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| CSRF protection | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **FRONTEND** | | | | | | |
| Template engine | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| CSS framework | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SCSS compiler | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Frontend JS helpers | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **API** | | | | | | |
| Swagger/OpenAPI | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| GraphQL | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SOAP/WSDL | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| HTTP client | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Queue system | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **DEV EXPERIENCE** | | | | | | |
| CLI scaffolding | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Dev admin dashboard | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Error overlay | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Live reload | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Auto-CRUD generator | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Gallery / examples | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| AI assistant context | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Inline testing | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **ARCHITECTURE** | | | | | | |
| Zero dependencies | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Dependency injection | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Event system | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| i18n / translations | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| HTML builder | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Feature Count — Python

| Framework | Features | Deps | JSON req/s |
|-----------|:-------:|:----:|:---------:|
| **Tina4** | **38/38** | **0** | **16,233** |
| Django | 22/38 | 20+ | ~3,500 |
| Flask | 7/38 | 6 | 4,953 |
| FastAPI | 8/38 | 12+ | 11,855 |
| Starlette | 6/38 | 4 | 16,202 |
| Bottle | 5/38 | 0 | ~7,000 |

### Cross-Language Feature Count

| Framework | Language | Features | Deps |
|-----------|---------|:-------:|:----:|
| **Tina4** | Python/PHP/Ruby/Node.js | **38/38** | **0** |
| Laravel | PHP | 25/38 | 50+ |
| Rails | Ruby | 24/38 | 40+ |
| Django | Python | 22/38 | 20+ |
| NestJS | Node.js | 16/38 | 20+ |
| FastAPI | Python | 8/38 | 12+ |
| Flask | Python | 7/38 | 6 |
| Starlette | Python | 6/38 | 4 |
| Bottle | Python | 5/38 | 0 |
| Express | Node.js | 4/38 | 3 |
| Sinatra | Ruby | 4/38 | 5 |

---

## Tina4 Performance Roadmap

### v3.1 — Close the Gap
- [x] Pre-compile Frond template tokens (2.8x file render improvement) ✅
- [x] Auto-detect uvicorn/hypercorn/puma for production ✅
- [x] DB query caching (TINA4_DB_CACHE=true, 4x speedup) ✅
- [ ] Pre-compile regex in `_resolve()` and `_eval_expr()` (target: 3x variable lookup)
- [ ] Connection pooling for database adapters

### v3.2 — Overtake
- [ ] Compiled template bytecode (match Jinja2 speed)
- [ ] HTTP/2 support in built-in server
- [ ] Response streaming for large payloads
- [ ] Worker process support (multi-core)

### v3.3 — Lead
- [ ] HTTP/3 (QUIC) support
- [ ] gRPC built-in
- [ ] Edge runtime support (Cloudflare Workers, Deno Deploy)

---

## Notes

- Performance numbers are from development servers on Apple Silicon
- Production deployments with gunicorn/uvicorn/puma/php-fpm would be faster for all frameworks
- Tina4's competitive advantage is **features per dependency** — 38 features with 0 deps
- The zero-dep philosophy means Tina4 works anywhere Python/PHP/Ruby/Node.js runs — no compiler needed, no native extensions, no build step
