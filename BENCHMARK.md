# Tina4 Python — Benchmark Report

**Date:** 2026-03-25 | **Machine:** Apple Silicon (ARM64), 8 cores | **Tool:** `hey` (5000 requests, 50 concurrent, 3 runs, averaged)

---

## 1. Performance

Real HTTP benchmarks — identical JSON endpoint, development servers.

| Framework | JSON req/s | 100-item list req/s | Server | Deps |
|-----------|:---------:|:-------------------:|--------|:----:|
| Starlette 0.52 | 15,664 | 9,302 | uvicorn | 4 |
| FastAPI 0.135 | 11,523 | 2,709 | uvicorn | 12 |
| **Tina4 Python** | **9,761** | **5,769** | **uvicorn (auto-detected)** | **0** |
| Flask 3.1 | 5,722 | 962 | Werkzeug | 6 |
| Bottle 0.13 | 3,165 | 1,105 | wsgiref | 0 |
| Django 6.0 | 2,333 | 2,150 | runserver | 20 |

**Key takeaway:** Tina4 Python delivers 9,761 req/s with 140 cataloged features and 0 dependencies — competitive with Starlette (12,914) and FastAPI (10,071), while shipping 140 cataloged features vs their 6 and 8 respectively, all with zero dependencies.

---

## 1b. Template rendering, Frond vs Jinja2 and Mako

**Date:** 2026-07-27 | **Machine:** Apple Silicon (ARM64), macOS | **Python:** 3.13.5 | **Tool:** `benchmarks/bench_templates.py` (p50 over batched samples, min 0.25s / 200 iterations)

This category used to be missing, and its absence flattered us. Sections 1 and 2 above
measure request throughput and feature count, where Tina4 competes well. Neither says
anything about template rendering, the one axis where Frond competes head-on with the
engines it replaced. Here are the numbers.

Same page (20-row product list: loop, index, even/odd class, uppercase, 2-decimal
money, conditional footer). **Every engine's output is compared and proven identical
before anything is timed**; a mismatch aborts the run. Each template is compiled ONCE
outside the clock, so this is steady-state render throughput, not compilation.

| Engine | Renders/s (p50) | Renders/s (mean) | Deps |
|--------|:---------------:|:----------------:|:----:|
| Mako | **89,662** | 79,358 | 1 |
| Jinja2 | **34,934** | 32,879 | 1 |
| **Frond (Tina4)** | **2,414** | 2,072 | **0** |

**Key takeaway, stated plainly: Frond is 14.5x slower than Jinja2 and 37x slower than
Mako on identical output.** This is the widest gap after Ruby, and it is Frond's fastest
path, the harness reports that the AOT compiler (`tina4_python/frond/compiler.py`)
engaged for this template, so this is not the interpreter fallback. Jinja2 compiles a
template to Python bytecode and lets CPython run it; Frond walks a tree and calls back
into engine primitives per hole.

What Frond does buy is the zero in the Deps column, and the fact that the same template
syntax renders in all four Tina4 languages. That is a real trade, but it is a trade -
not a win. Closing this gap is tracked as the ahead-of-time compile layer (ADR-0001).

Reproduce: `uv run python benchmarks/bench_templates.py`


## 2. Feature Comparison (42 of 140 cataloged features)

Tina4 ships **140 cataloged features**. The table below compares the subset that has a
meaningful equivalent in the competing frameworks, so it is a like-for-like comparison
rather than the full inventory. Everything listed ships with the core install, with no
extra packages needed.

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
| **Tina4** | **42/42** | **0** | **9,761** |
| Django | 22/42 | 20 | 5,685 |
| FastAPI | 8/42 | 12 | 10,071 |
| Flask | 7/42 | 6 | 4,842 |
| Starlette | 6/42 | 4 | 12,914 |
| Bottle | 5/42 | 0 | 1,258 |

---

## 3. Deployment Size

**Measured 2026-07-27** on macOS (Apple Silicon) by installing each package for real.
Nothing in this table is estimated. The command that produced it is named below.

Command: `uv pip install <pkg>` into a bare venv, then `du -sh site-packages`.

| Framework | Install Size | Third-party packages |
|-----------|:----------:|:--------------------:|
| bottle | **1 MB** | 1 |
| starlette | 2 MB | 3 |
| flask | 3 MB | 7 |
| **Tina4 Python** | **3.6 MB** | **0** |
| fastapi | 9 MB | 10 |
| django | 32 MB | 3 |

**Correction.** This table claimed 2.4 MB for Tina4 Python. Measured, it is **3.6 MB**,
which places it above Bottle, Starlette and Flask rather than below them.

The zero in the third-party column is real and verified: a fresh install pulls in **no**
other top-level packages, against FastAPI's 10 and Flask's 7. That is the claim worth
making. "Smallest install" is not.

## 4. CO2 / Carbonah

Estimated emissions per HTTP benchmark run (5000 requests on Apple Silicon, 15W TDP).

Formula: `Energy(kWh) = (15W × seconds_for_5000_requests) / 3,600,000` | `CO2(g) = kWh × 475`

| Framework | JSON req/s | Seconds (5000 reqs) | Est. Energy (kWh) | Est. CO2 (g) |
|-----------|:---------:|:-------------------:|:-----------------:|:------------:|
| Starlette | 12,914 | 0.3872 | 0.0000016 | 0.0008 |
| FastAPI | 10,071 | 0.4965 | 0.0000021 | 0.0010 |
| **Tina4** | **9,761** | **0.5122** | **0.0000021** | **0.0010** |
| Django | 5,685 | 0.8795 | 0.0000037 | 0.0017 |
| Flask | 4,842 | 1.0326 | 0.0000043 | 0.0020 |
| Bottle | 1,258 | 3.9746 | 0.0000166 | 0.0079 |

*CO2 calculated at world average 475g CO2/kWh. Lower req/s = longer to serve 5000 requests = more energy.*

Tina4 uses **7.8x less energy** than Bottle and **2.0x less** than Flask per request, while shipping 140 cataloged features with 0 dependencies.

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
