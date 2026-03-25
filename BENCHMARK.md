# Tina4 Python — Benchmark Report

**Date:** 2026-03-25 | **Machine:** Apple Silicon (ARM64), 8 cores | **Tool:** `hey` (5000 requests, 50 concurrent, 3 runs, median)

---

## 1. Performance

Real HTTP benchmarks — identical JSON endpoint, development servers.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| Starlette 0.52 | 12,914 | 7,694 | uvicorn (C parser) | 4 |
| FastAPI 0.115 | 10,071 | 2,435 | uvicorn (C parser) | 12 |
| **Tina4 Python** | **9,730** | **5,590** | **uvicorn (auto-detected)** | **0** |
| Django 5.2 | 5,685 | 4,311 | runserver | 20 |
| Flask 3.1 | 4,842 | 753 | Werkzeug | 6 |
| Bottle 0.13 | 1,258 | 824 | built-in wsgiref | 0 |

**Key takeaway:** Tina4 Python delivers 9,730 req/s with 38 features and 0 dependencies, competitive with FastAPI (10,071) which ships only 8 features and 12 dependencies.

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
| **Tina4** | **38/38** | **0** | **9,730** |
| Django | 22/38 | 20 | 5,685 |
| FastAPI | 8/38 | 12 | 10,071 |
| Flask | 7/38 | 6 | 4,842 |
| Starlette | 6/38 | 4 | 12,914 |
| Bottle | 5/38 | 0 | 1,258 |

---

## 3. Deployment Size

| Framework | Install Size | Dependencies |
|-----------|:----------:|:------------:|
| **Tina4 Python** | **2.4 MB** | **0** |
| Starlette | 3.5 MB | 4 |
| FastAPI | 4.8 MB | 12 |
| Flask | 4.2 MB | 6 |
| Django | 25 MB | 20 |
| Bottle | 0.3 MB | 0 |

Zero dependencies means core size **is** deployment size. No `site-packages` explosion.

---

## 4. CO2 / Carbonah

Estimated emissions per HTTP benchmark run (5000 requests on Apple Silicon, 15W TDP).

Formula: `Energy(kWh) = (15W × seconds_for_5000_requests) / 3,600,000` | `CO2(g) = kWh × 475`

| Framework | JSON req/s | Seconds (5000 reqs) | Est. Energy (kWh) | Est. CO2 (g) |
|-----------|:---------:|:-------------------:|:-----------------:|:------------:|
| Starlette | 12,914 | 0.3872 | 0.0000016 | 0.0008 |
| FastAPI | 10,071 | 0.4965 | 0.0000021 | 0.0010 |
| **Tina4** | **9,730** | **0.5139** | **0.0000021** | **0.0010** |
| Django | 5,685 | 0.8795 | 0.0000037 | 0.0017 |
| Flask | 4,842 | 1.0326 | 0.0000043 | 0.0020 |
| Bottle | 1,258 | 3.9746 | 0.0000166 | 0.0079 |

*CO2 calculated at world average 475g CO2/kWh. Lower req/s = longer to serve 5000 requests = more energy.*

Tina4 uses **3.9x less energy** than Bottle and **2.0x less** than Flask per request.

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
