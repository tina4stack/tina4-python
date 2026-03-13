# Python Web Framework Benchmark: tina4-python vs Flask vs Django vs FastAPI

## Overview

| Metric | tina4-python | Flask | FastAPI | Django |
|---|---|---|---|---|
| **Version** | 0.2.193 | 3.1.3 | 0.135.1 | 6.0.3 |
| **Philosophy** | Batteries-included micro | Micro (BYOB) | API-first micro | Batteries-included mono |

---

## Code Size and Package Weight

| Metric | tina4-python | Flask | FastAPI | Django |
|---|---|---|---|---|
| **Lines of code** | ~10,300 | ~7,000 | ~5,000-7,000 | ~450,000 |
| **Python files** | 31 | ~18 | ~23+ subdirs | Thousands |
| **Wheel size** | 430 KB | 103 KB | 117 KB | 8.4 MB |
| **Wheel + deps** | ~430 KB + deps | ~620 KB | ~117 KB + Starlette + Pydantic | ~8.4 MB + asgiref + sqlparse |

---

## Dependencies

| Metric | tina4-python | Flask | FastAPI | Django |
|---|---|---|---|---|
| **Direct deps** | 13 | 6 | 5 (core) | 2 |
| **Deps for full-stack** | 0 extra | 6-10 extensions | 10-15 extra packages | 2-5 extras (DRF, etc.) |

---

## Batteries Included

| Feature | tina4-python | Flask | FastAPI | Django |
|---|---|---|---|---|
| Routing | Yes | Yes | Yes | Yes |
| Templating (Jinja2) | Yes | Yes | Add-on | Own engine |
| ORM | Yes (6 DBs) | No | No | Yes (built-in) |
| DB Migrations | Yes | No | No | Yes |
| JWT Auth | Yes (auto-gen RS256) | No | Schema only | Session-based |
| CSRF Protection | Yes | No | No | Yes |
| Admin Panel | Yes (CRUD scaffold) | No | No | Yes |
| Swagger/OpenAPI | Yes (auto) | No | Yes (auto) | No |
| WSDL/SOAP | Yes | No | No | No |
| WebSockets | Yes | No | Yes | Channels (ext) |
| Message Queues | Yes (4 backends) | No | No | No |
| Sessions | Yes (4 backends) | Cookie only | No | Yes |
| Middleware | Yes | Limited | Yes | Yes |
| SCSS Compilation | Yes | No | No | No |
| i18n | Yes (6 languages) | No | No | Yes |
| CLI Scaffolding | Yes (`tina4 init`) | No | Yes (fastapi-cli) | Yes (`startproject`) |
| Live Reload | Yes (WebSocket) | Watchdog | Uvicorn reload | runserver |
| HTTP Client | Yes | No | No | No |
| Testing Framework | Yes (inline) | Utilities | TestClient | Yes |
| Password Hashing | Yes (bcrypt) | No | No | Yes |
| Static File Serving | Yes | Yes | Yes | Yes |

**Scorecard**: tina4-python **20/20**, Django **14/20**, FastAPI **7/20**, Flask **3/20**

---

## Complexity (Getting Started)

| Metric | tina4-python | Flask | FastAPI | Django |
|---|---|---|---|---|
| **Min files for hello world** | 1 (`app.py`) | 1 | 1 | ~13 (project+app) |
| **Lines for hello world** | ~6 | ~5 | ~7 | ~20+ across files |
| **Core concepts** | ~6 | ~8 | ~12 | ~14 |
| **CLI scaffolding** | `tina4 init` | None | `fastapi` | `django-admin` |
| **Project structure** | Convention | DIY | DIY | Enforced |

---

## Performance Benchmarks

See `run_benchmarks.sh` to reproduce these results on your own hardware.

Each framework serves a simple JSON endpoint (`{"message": "Hello, World!"}`).
Tested with ApacheBench: 10,000 requests, 100 concurrent connections.

| Framework | Server | Requests/sec | Mean Latency (ms) | Notes |
|---|---|---|---|---|
| tina4-python | Default (Hypercorn) | *run benchmarks* | *run benchmarks* | ASGI |
| tina4-python | Hypercorn (standalone) | *run benchmarks* | *run benchmarks* | ASGI |
| Flask | Gunicorn (4 workers) | *run benchmarks* | *run benchmarks* | WSGI |
| FastAPI | Uvicorn | *run benchmarks* | *run benchmarks* | ASGI |
| Django | Gunicorn (4 workers) | *run benchmarks* | *run benchmarks* | WSGI |

---

## Deployment Size (Docker, Alpine multi-stage)

| Framework | Approx Image Size |
|---|---|
| **tina4-python** | ~60-80 MB |
| **Flask** | ~50-70 MB |
| **FastAPI** | ~80-110 MB |
| **Django** | ~100-170 MB |

---

## Summary

| | tina4-python | Flask | FastAPI | Django |
|---|---|---|---|---|
| **Best for** | Full-stack apps, zero config | Simple apps, pick every piece | High-perf APIs, microservices | Large-scale apps, enterprise |
| **Trade-off** | Smaller ecosystem | Assemble everything yourself | Assemble DB/auth/admin yourself | Heavy, steep learning curve |
| **Time to production** | Fast (everything included) | Slow (research + wire extensions) | Medium (API fast, full-stack slow) | Medium (lots to learn upfront) |
| **Wheel size** | 430 KB | 103 KB (+extensions) | 117 KB (+extensions) | 8.4 MB |
| **Lines of code** | 10.3K | 7K | 5-7K | 450K |

The key differentiator for tina4-python is that it packs 20+ subsystems (ORM, auth, queues, SOAP, Swagger, CRUD scaffolding, sessions, migrations, SCSS, i18n) into 430 KB / 10K lines -- while Flask and FastAPI require assembling 6-15 external packages to reach the same feature set, and Django achieves it at 45x the code size.

---

## How to Run Benchmarks

```bash
# Install dependencies
pip install flask gunicorn fastapi uvicorn django

# Run all benchmarks
cd benchmarks
chmod +x run_benchmarks.sh
./run_benchmarks.sh
```

Results are written to `results/` as text files.
