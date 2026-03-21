# Tina4 v3.0.0 — HTTP Benchmark Report

**Date:** 2026-03-21  
**Machine:** Apple Silicon (macOS)  
**Tool:** hey (5000 requests, 50 concurrent)  
**Note:** All frameworks running development servers. Tina4 uses built-in asyncio server (zero deps). Flask uses Werkzeug. Starlette/FastAPI use uvicorn (C-level HTTP parser).

## JSON Endpoint — `GET /api/bench/json`

Returns `{"message": "Hello, World!", "framework": "...", "version": "..."}`

| Framework | Requests/sec | Avg Latency | Fastest | Slowest | Server |
|-----------|:-----------:|:-----------:|:-------:|:-------:|--------|
| Starlette | 16,202 | 3.1ms | 2.5ms | 7.7ms | uvicorn |
| FastAPI | 11,855 | 4.2ms | 3.6ms | 7.4ms | uvicorn |
| **Tina4** | **8,316** | **5.9ms** | **0.1ms** | **160ms** | built-in asyncio |
| Flask | 4,953 | 10.0ms | 2.7ms | 20.6ms | Werkzeug |

## List 100 Items — `GET /api/bench/list`

Returns `{"items": [{id, name, price} x 100], "count": 100}`

| Framework | Requests/sec | Avg Latency |
|-----------|:-----------:|:-----------:|
| Starlette | 7,351 | 6.8ms |
| **Tina4** | **5,688** | **8.7ms** |
| Flask | 3,899 | 12.8ms |
| FastAPI | 2,476 | 20.1ms |

## Key Insights

1. **Tina4 vs Flask**: Tina4 is **1.7x faster** on JSON, **1.5x faster** on large payloads — with zero external dependencies
2. **Tina4 vs Starlette**: Starlette is ~2x faster because uvicorn uses a C-level HTTP parser (httptools). Tina4's server is pure Python asyncio
3. **FastAPI vs Tina4**: Tina4 is **2.3x faster** on large payloads — FastAPI's Pydantic validation adds overhead for large responses
4. **Zero deps matters**: Tina4 achieves competitive performance without any C extensions, compiled modules, or external packages

## What Tina4 includes that others don't

Tina4's 8,316 req/s comes with **all of this built-in** (zero pip install):

- ORM, 5 database drivers, migrations
- JWT auth, sessions, CORS, rate limiting
- Template engine, SCSS compiler
- Queue system, WebSocket, GraphQL, SOAP/WSDL
- Swagger/OpenAPI, dev dashboard, error overlay
- CLI scaffolding, gallery, AI assistant context

Flask at 4,953 req/s includes: routing, Jinja2 templates. Everything else requires pip install.

## Internal Benchmarks (1000 iterations, no HTTP overhead)

| Benchmark | Throughput |
|-----------|-----------|
| Plaintext Response | 6,366,061 ops/sec |
| Single DB Query | 63,752 ops/sec |
| CRUD Cycle | 21,271 ops/sec |
| JSON Hello World | 16,994 ops/sec |
| Large JSON Payload | 12,382 ops/sec |
| Paginated Query | 7,417 ops/sec |
| Multiple DB Queries | 4,277 ops/sec |
| Framework Startup | 4,340 ops/sec |
| Template Rendering | 2,415 ops/sec |

## Optimization Roadmap (v3.1)

- [ ] Pre-compile Frond template expressions (target: 10x template rendering improvement)
- [ ] Optional uvicorn/hypercorn support for production deployment
- [ ] Connection pooling for database adapters
- [ ] Response body streaming for large payloads
