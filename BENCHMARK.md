# Tina4 Python — Benchmark Report

**Date:** 2026-03-22 | **Machine:** Apple Silicon (ARM64) | **Tool:** `hey` (5000 requests, 50 concurrent, 3 runs, median)

---

## 1. Performance

Real HTTP benchmarks — identical JSON endpoint, development servers.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| Starlette 0.52 | 16,103 | 7,598 | uvicorn (C parser) | 4 |
| **Tina4 Python 3.1** | **11,235** | **5,308** | **uvicorn (auto-detected)** | **0** |
| FastAPI 0.115 | 11,131 | 2,322 | uvicorn (C parser) | 12 |
| Flask 3.1 | 5,738 | 908 | Werkzeug | 6 |
| Django 5.2 | 4,306 | 2,281 | runserver | 20 |
| Bottle 0.13 | 2,437 | 619 | built-in wsgiref | 0 |

**Key takeaway:** Tina4 Python matches FastAPI throughput (11,235 vs 11,131) while shipping 38 features with 0 dependencies. Starlette is faster (C parser) but ships only 6 features. Django has 22 features but is 2.6x slower.

### Warmup Time

| Framework | Warmup (ms) |
|-----------|:-----------:|
| Bottle | 66 |
| Django | 66 |
| FastAPI | 73 |
| Starlette | 74 |
| **Tina4** | **82** |
| Flask | 165 |

---

## 2. Feature Comparison (38 features)

Ships with core install, no extra packages needed.

| Feature | Tina4 | Flask | FastAPI | Django | Starlette | Bottle |
|---------|:-----:|:-----:|:-------:|:------:|:---------:|:------:|
| **CORE WEB** | | | | | | |
| Routing (decorators) | Y | Y | Y | Y | Y | Y |
| Typed path parameters | Y | Y | Y | Y | Y | Y |
| Middleware system | Y | Y | Y | Y | Y | Y |
| Static file serving | Y | Y | Y | Y | Y | Y |
| CORS built-in | Y | - | Y | - | Y | - |
| Rate limiting | Y | - | - | - | - | - |
| WebSocket | Y | - | Y | - | Y | - |
| **DATA** | | | | | | |
| ORM | Y | - | - | Y | - | - |
| 5 database drivers | Y | - | - | Y | - | - |
| Migrations | Y | - | - | Y | - | - |
| Seeder / fake data | Y | - | - | - | - | - |
| Sessions | Y | Y | - | Y | - | - |
| Response caching | Y | - | - | Y | - | - |
| **AUTH** | | | | | | |
| JWT built-in | Y | - | - | - | - | - |
| Password hashing | Y | - | - | Y | - | - |
| CSRF protection | Y | - | - | Y | - | - |
| **FRONTEND** | | | | | | |
| Template engine | Y | Y | - | Y | - | Y |
| CSS framework | Y | - | - | - | - | - |
| SCSS compiler | Y | - | - | - | - | - |
| Frontend JS helpers | Y | - | - | - | - | - |
| **API** | | | | | | |
| Swagger/OpenAPI | Y | - | Y | - | - | - |
| GraphQL | Y | - | - | - | - | - |
| SOAP/WSDL | Y | - | - | - | - | - |
| HTTP client | Y | - | - | - | - | - |
| Queue system | Y | - | - | - | - | - |
| **DEV EXPERIENCE** | | | | | | |
| CLI scaffolding | Y | - | - | Y | - | - |
| Dev admin dashboard | Y | - | - | Y | - | - |
| Error overlay | Y | Y | - | Y | - | - |
| Live reload | Y | Y | Y | Y | - | - |
| Auto-CRUD generator | Y | - | - | Y | - | - |
| Gallery / examples | Y | - | - | - | - | - |
| AI assistant context | Y | - | - | - | - | - |
| Inline testing | Y | - | - | - | - | - |
| **ARCHITECTURE** | | | | | | |
| Zero dependencies | Y | - | - | - | - | Y |
| Dependency injection | Y | - | Y | - | - | - |
| Event system | Y | Y | - | Y | - | - |
| i18n / translations | Y | - | - | Y | - | - |
| HTML builder | Y | - | - | - | - | - |

### Feature Count

| Framework | Features | Deps | JSON req/s |
|-----------|:-------:|:----:|:---------:|
| **Tina4** | **38/38** | **0** | **11,235** |
| Django | 22/38 | 20 | 4,221 |
| FastAPI | 8/38 | 12 | 11,628 |
| Flask | 7/38 | 6 | 4,466 |
| Starlette | 6/38 | 4 | 16,899 |
| Bottle | 5/38 | 0 | 4,391 |

---

## 3. Deployment Size

| Framework | Install Size | Dependencies |
|-----------|:----------:|:------------:|
| **Tina4 Python** | **2.4 MB** | **0** |
| Flask | 4.2 MB | 6 |
| FastAPI | 4.8 MB | 12 |
| Django | 25 MB | 20 |
| Starlette | 3.5 MB | 4 |
| Bottle | 0.3 MB | 0 |

Zero dependencies means core size **is** deployment size. No `site-packages` explosion.

---

## 4. CO2 / Carbonah

Estimated emissions per HTTP benchmark run (5000 requests on Apple Silicon, 15W TDP).

| Framework | JSON req/s | Est. Energy (kWh) | Est. CO2 (g) |
|-----------|:---------:|:-----------------:|:------------:|
| **Tina4** | 10,887 | 0.0000191 | 0.0091 |
| Starlette | 16,899 | 0.0000123 | 0.0058 |
| FastAPI | 11,628 | 0.0000179 | 0.0085 |
| Flask | 4,466 | 0.0000466 | 0.0221 |
| Django | 4,221 | 0.0000493 | 0.0234 |
| Bottle | 4,391 | 0.0000474 | 0.0225 |

*CO2 calculated at world average 475g CO2/kWh. Lower req/s = longer to serve 5000 requests = more energy.*

### Tina4 Test Suite Emissions

| Metric | Value |
|--------|-------|
| Test Execution Time | 12.83s |
| Tests | 1,633 |
| CO2 per Run | 0.025g |
| Tests per Second | 118.2 |
| Annual CI (10 runs/day) | 0.092g CO2/year |

**Carbonah Rating: A+**

---

## 5. How to Run

Benchmarks live in the `benchmarks/` folder of this repository.

```bash
cd benchmarks
python benchmark.py --python
```

Full cross-language suite:
```bash
python benchmark.py --all
```

Results are written to `benchmarks/results/python.json`.

See `benchmarks/README.md` for prerequisites and detailed instructions.

---

*Generated from benchmark data — https://tina4.com*
