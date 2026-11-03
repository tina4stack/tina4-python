# Task: Purge security-scan noise from tina4-python's uv.lock

## Problem
uv.lock pins 81 packages and the scanner (Dependabot, reading uv.lock) flags CVEs
in them — most visibly **pillow 12.3.0**. Core `dependencies = []` ships NOTHING,
so none of this is a shipped vulnerability, but the dev tree drags it into the lock.

## Root cause (measured, not guessed)
`[dependency-groups] dev` carried packages that are NOT test infrastructure:
- `reportlab` → sole reverse-dep of **pillow** (+ charset-normalizer). Imported by
  nothing (framework, tests, benchmark). Dead. → pillow in the lock for free.
- `cython` → no `.pyx`/`cythonize`/import anywhere. Dead.
- `setuptools` → unused (build backend is hatchling; no pkg_resources import).
- `bottle` / `django` / `fastapi` / `flask` → COMPETITOR frameworks used only by
  `benchmarks/*.py`. Dragged starlette, pydantic-core, werkzeug, jinja2, asgiref,
  sqlparse, blinker … into uv.lock. A group move won't help: `uv lock` pins every
  group, so they must leave pyproject entirely to clear the scan.

## Load-bearing — KEPT (would break `tina4 test` / CI / ASGI)
- `pytest`, `pytest-asyncio` (asyncio_mode=auto), `pytest-cov` — the test runner.
- `uvicorn` — server.py's ASGI launcher (`import uvicorn`, server.py:3786) + 14 ASGI
  tests import it. Tiny tree (h11 + click), no CVE surface.

## Plan
- [x] Measure every dev dep's real usage (done)
- [x] pyproject: dev group → {pytest, pytest-asyncio, pytest-cov, uvicorn} only
- [x] benchmarks/requirements.txt: the competitor frameworks (own venv, NOT in uv.lock)
- [x] benchmarks/README.md: document the competitor-install step
- [x] `uv lock` — 81 → 62 packages; pillow, reportlab, cython, django, fastapi,
      flask, bottle, starlette, werkzeug, jinja2, asgiref, sqlparse, blinker,
      itsdangerous, mako, sqlalchemy, setuptools ALL gone from the lock.
      (pydantic/pydantic-settings remain — now sourced from openapi-spec-validator,
      the `test` extra's OpenAPI-schema validator; legitimate test infra, untouched.)
- [x] Verified at HEAD (no mocks): full suite COLLECTS clean (7201 tests, 0 import
      errors); no test imports any removed package; dep-relevant slices green —
      swagger-contract + ASGI/uvicorn (41 passed). Full live-service green is CI/lab
      (needs mongo/kafka/postgres/firebird), unchanged by a dev-dep prune.

## Verification
| Check | Result |
|-------|--------|
| `uv lock` resolves | ok, 81 → 62 packages |
| pillow / reportlab / cython / competitor tree in lock | gone |
| full suite collection | 7201 tests, 0 import errors |
| test files importing a removed pkg | none |
| swagger-contract + ASGI/uvicorn slice | 41 passed |

## Parity note
uv.lock is python-only; this is a python-scoped fix. The same "dead/benchmark dev
dep in the lockfile" hygiene is worth a sweep in php (composer.lock), ruby
(Gemfile.lock), node (package-lock.json) — offered as a follow-up, not ported blind.

## Status: Done — verified locally; ready to commit/PR off v3
