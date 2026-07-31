# Changelog

Tina4 keeps ONE version across all four frameworks (Python, PHP, Ruby, Node.js), so a version
number means the same thing everywhere.

**The authoritative release notes for every shipped version live in the documentation:**
https://tina4.com/python/36-releases

This file is deliberately NOT a copy of those notes. Duplicating them is exactly how a
changelog rots into claiming a version that was never cut, so this file records only
UNRELEASED work. When a version ships, its notes go to the release notes above.

## Unreleased

### Breaking: one return-value contract for every middleware hook

What a `before_*` / `after_*` hook RETURNS now decides what happens next, the
same way for every hook, at every scope (global and per-route), through both
public entry points (`Middleware.run_before` / `run_after` and the dispatcher in
`core.server`):

| the hook returns | what happens |
|---|---|
| a `Response` object | SHORT-CIRCUIT. That object IS the response, at ANY status. |
| `(request, response)` | rebind both, continue |
| `False` | SHORT-CIRCUIT. Send the response as set; a still-default/empty response becomes a 403. |
| `None` | continue |

The `Response`-object rule is PRIMARY. The retained legacy path - a response
status >= 400 short-circuits even when the hook returned `None` - stays because
real middleware takes that shape (Rails decides on response state), but it can
only ever express an error. A hook that wants to redirect has no 4xx to set, so
before this change `return response.redirect("/login")` from a `before_*` hook
could not stop the handler at all.

Two of these returns were not merely unsupported, they were CRASHES. The
dispatcher did `request, response = result` for any non-`None` return, so
`return False` raised `TypeError: cannot unpack non-iterable bool object` and
returning a `Response` raised `TypeError: cannot unpack non-iterable Response
object` - a middleware saying "deny" produced a 500. The orchestrator had the
opposite bug: it silently IGNORED both, so the chain ran on and the handler
executed anyway.

`Middleware.run_before` / `run_after` also gained the exception gate the other
three frameworks' orchestrators already had: a hook that raises is logged via
`Log.error` and becomes the canonical clean 500
(`{"error": "Internal Server Error", "status": 500}`) instead of escaping to the
caller. A throwing BEFORE hook short-circuits; a throwing AFTER hook is logged
and the remaining after hooks still run.

**Migration:** a hook that returned a bare `Response` object or `False` used to
crash (dispatcher) or be ignored (orchestrator); it now short-circuits. If you
have an `after_*` hook that returns a bare `response` instead of the
`(request, response)` pair, it will now stop the remaining after hooks - return
the pair to keep them running.


### CORS preflight responses now carry `Allow`

A CORS preflight (`OPTIONS` with an `Origin`) returned 204 with the
`Access-Control-*` headers but no `Allow`, while a bare `OPTIONS` to the same
path returned `Allow`. A preflight IS an OPTIONS response, so it now carries
`Allow` too, derived from the router's real method set (RFC 9110 s9.3.7).

This is conformance, not a deviation - see ADR-0013. The frameworks' own
OPTIONS handlers already emit `Allow` (Django's `View.options()`, Express's
router). The add-on CORS libraries omit it only because they short-circuit
ahead of the framework and skip its OPTIONS handler. Tina4 owns both paths in
one dispatcher.

`Allow` and `Access-Control-Allow-Methods` are NOT interchangeable: `Allow` is
what the RESOURCE supports, `Access-Control-Allow-Methods` is what the CORS
POLICY permits cross-origin (`TINA4_CORS_METHODS`, a static list as in every
mainstream library). A policy naming DELETE on a GET-only route is still a 405.

Non-breaking: one added response header on a 204; no existing header changes.


### Breaking: global middleware now runs before the auth gate

Dispatch order is now identical in all four frameworks:

```
pre-match globals -> match -> post-match globals -> auth gate -> route middleware -> handler
```

Python (and Ruby) previously ran the auth gate FIRST, so a global middleware
never saw a rejected request. That made a global rate limiter unable to throttle
a brute-force login, and dropped every 401 from an access log. Node and PHP
already ran the globals first; every mainstream framework does the same (Django
ships `CsrfViewMiddleware` ahead of `AuthenticationMiddleware` and enforces auth
in a view decorator after all `MIDDLEWARE`; Laravel runs the `web` group before
the `auth` route middleware; ASP.NET puts `UseAuthorization` last before the
endpoint). See ADR-0012.

**Migration:** a global middleware (registered via `Middleware.use` /
`Router.use`) now runs on requests that are about to be rejected, including
401s. If yours assumes an authenticated request, check for it - `request.user`
is only populated after the gate. A middleware that must NOT see rejected
requests should be attached to the route instead of registered globally; route
middleware still runs after the gate.

Also fixed: the pre-match pass re-ran the post-match set, so every post-match
middleware fired TWICE per request (once before matching, once after). A
middleware that increments a counter or charges a rate-limit bucket was
double-counting. Locked by `test_a_pre_match_global_does_not_run_twice`.


### Changed

- **Breaking: the metrics payload is now the native engine's shape.** `full_analysis` no
  longer returns a `violations` key. The ranked `offenders` list replaces it and
  `--fail-on` reads that same list, so one concept has one name instead of two.
  Verified before removal: zero consumers outside the tests.

- **Breaking: `file_detail` returns the engine's per-file shape.** It no longer returns
  `total_lines`, `classes`, `imports` or `warnings`, and `functions` is now a COUNT rather
  than a list. Anything reading those keys must move to the engine's fields, or call
  `full_analysis` and read `most_complex_functions` for per-function detail.

- **Breaking: the empty-class warning is gone and is not coming back.** The old
  hand-rolled analyzer flagged `class Foo {}` with no members. An empty class is usually
  CORRECT rather than a defect: marker classes, base exception types, DTO placeholders.
  Tina4 itself ships `MetricsEngineError` as exactly that, so the check flagged the
  framework's own correct code. A check that fires on correct code is noise, and noise is
  why the offenders list went unread for months. The engine's vocabulary stays the four
  things that are actionable: complexity, large file, low maintainability, untested.

- **Breaking: the column-metadata primary-key flag is `primary_key`.** Python and Ruby use `primary_key`; PHP and Node use `primaryKey`. Each follows its own
  language's paradigm because this is framework API surface, not data. Ruby also dropped a
  dead `:primary` fallback that nothing set.

- **Breaking: metrics REQUIRE the `tina4` CLI on PATH, with no fallback.** All four
  frameworks deleted their own hand-rolled analyzer, so `full_analysis`, `offenders` and
  `file_detail` now shell out to `tina4 metrics --json` (ADR-0002: one engine, so a number
  measured in one language is comparable with the same number measured in another). A
  missing or stale CLI raises and names the install command instead of quietly returning
  worse numbers; the dev-admin endpoints answer 503, or 404 for an unknown file path.
  Previously a failure fell back to the local analyzer, which is exactly how four
  frameworks came to disagree about the same file. The file census behind the dashboard
  (`quick_metrics`) stays in-process and needs no CLI: it is a glob-and-count, and the
  engine is 8x to 37x slower on that path.

- **Breaking: every ORM read path that takes a `limit` now defaults to 100 rows.**
  `select()`, `where()`, `with_trashed()`, `cached()` and a `scope()`-generated method
  defaulted to 20; they now default to 100. `all()`, `find()` and `db.fetch()` already
  capped at 100 and are unchanged. The family disagreed with itself before this: two
  methods differing only in how you spell the filter returned a fifth as many rows.
  Pagination is a default, so every read path that advertises a limit now uses the same
  number.

  Migration: pass the limit explicitly wherever you relied on the old 20, for example
  `Product.select(sql, limit=20)`. Code that already passes a limit is unaffected.

  `QueryBuilder.get()` and `fetch_all()` are deliberately UNCHANGED and stay uncapped.
  Neither takes a `limit`, so a cap there can only ever be silent, and that silent
  `LIMIT 100` was the data-loss-on-read footgun removed in 3.13.39. The rule: a path
  that advertises `limit` caps at 100, a path without one never caps.

### Added

The current tagged release is 3.13.94; everything in this section sits on `v3` untagged.
Its notes ship in the release notes linked above when it is tagged.

In-flight on a feature branch, not yet merged to `v3`:

- `feature/spatial-gis` - `PointField` (SRID-aware, WKT/EWKT/GeoJSON/WKB in, immutable
  lon-first `Point` out), engine-aware spatial DDL with a GiST index, `within_distance()`,
  `order_by_distance()`, `select_distance()`, `intersects()`, `bbox()`, and GeoJSON
  Feature/FeatureCollection output. PostGIS-first; a spatial field on an engine without
  spatial support raises rather than silently creating a wrong column.
- `feature/spatial-gis` - **Fixed** `order_by_distance()` was non-deterministic for
  equidistant rows (distance alone is not a total order and PostgreSQL's sort is not stable),
  which made keyset pagination skip and repeat rows. Now has a stable tiebreak.

### Fixed

- **`tina4 deploy docker` produced images that could not start.** Of the eight
  Dockerfile generators in the stack (four templates in the `tina4` CLI plus one
  in each framework's own CLI), exactly one was correct. Python named
  `python -m tina4_python.cli`, a package with no `__main__.py`, so the container
  died on startup; PHP ran `php index.php <addr>`, but `App::run(?host, port)`
  never reads argv so the address was dropped and production never engaged;
  Node named a path that exists only inside the tina4-nodejs monorepo and
  depended on tsx, which `npm ci --omit=dev` strips. Every generator now names a
  published entry point and requests production. Verified by scaffolding,
  generating, building and running a container for all four languages.
- **`serve` no longer kills PID 1.** The port-reclaim step read `lsof -ti`
  without validating it. Where lsof prints a different shape, a non-numeric field
  coerced to 0 or 1 -- and signalling PID 0 hits every process in the caller's
  own process group. In a container the server IS PID 1, so it killed itself
  (Node logged "Killed existing process on port 7148 (PID: 1 ...)" then exited
  143; PHP logged the same attempt and survived by luck). Reclaiming is now
  skipped inside a container, only all-digit PIDs are accepted, and PID 0, PID 1
  and the current process are never signalled.
