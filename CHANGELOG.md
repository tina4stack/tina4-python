# Changelog

Tina4 keeps ONE version across all four frameworks (Python, PHP, Ruby, Node.js), so a version
number means the same thing everywhere.

**The authoritative release notes for every shipped version live in the documentation:**
https://tina4.com/python/36-releases

This file is deliberately NOT a copy of those notes. Duplicating them is exactly how a
changelog rots into claiming a version that was never cut, so this file records only
UNRELEASED work. When a version ships, its notes go to the release notes above.

## Unreleased

### Breaking: the rate limiter keys on the socket peer, not X-Forwarded-For

`X-Forwarded-For` is written by whoever sends it. Reading it unconditionally let
any client pick its own rate-limit bucket, and - worse - pick SOMEONE ELSE'S,
exhausting a third party's quota. Measured with `TINA4_RATE_LIMIT=3`: a rotating
`X-Forwarded-For` scored 200,200,200,200,200,200 where a fixed one correctly
scored 200,200,200,429,429,429.

`X-Forwarded-For` and `X-Real-IP` are now read ONLY when the raw socket peer is
listed in the new `TINA4_TRUSTED_PROXIES`. Within the chain the RIGHTMOST hop
that is not itself a trusted proxy wins, matching Rack and Express (a client can
prepend its own hop, so the leftmost entry is attacker-controlled even behind a
real proxy).

**Migration.** If your app runs behind a proxy, load balancer or ingress, set
`TINA4_TRUSTED_PROXIES` to that proxy's address or range. It accepts a
comma-separated mix of exact addresses and CIDR ranges, IPv4 and IPv6:

```
TINA4_TRUSTED_PROXIES=10.0.0.0/8
TINA4_TRUSTED_PROXIES=192.168.1.5, ::1, fd00::/8
```

It is EMPTY by default, which means trust nothing. If you leave it unset behind a
proxy, every client is bucketed under the proxy's address and you will
over-limit. That is deliberate: over-limiting is a degraded service, while the
previous behaviour was an open door. Direct-to-internet apps need no change.

See ADR-0019.

### Breaking: middleware no longer disables a route's auth gate

Attaching middleware to a route or a route GROUP used to set
`auth_required = False`, so an ordinary logging or audit middleware on a group
silently made every `POST`/`PUT`/`PATCH`/`DELETE` inside it PUBLIC. Measured: an
unauthenticated POST to a grouped route returned 200 where the identical
ungrouped route returned 401.

Middleware is now purely additive and never changes the gate, matching
tina4-php, tina4-ruby and tina4-nodejs, which were all already correct.

**Migration.** If you relied on middleware to open a write route, mark it
explicitly with `@noauth()` (or `auth_required=False`). If you did not, you were
serving an unintentionally public endpoint and it is now closed.

### Breaking: a nested route group registers at the path it declares

`RouteGroup.group()` built a correct nested prefix and nothing ever read it, so
`Router.group("/api", lambda g: g.group("/admin", ...))` registered
`/api/stats` instead of `/api/admin/stats`. Nested prefixes now compose.

Group middleware also ran TWICE per request (merged once by the group and again
by the router), so a counter or a rate-limit bucket double-counted and would
throttle at half its configured limit. It now runs once.

**Migration.** Routes in nested groups move to the path you declared. If you had
worked around the old behaviour by flattening a prefix, remove the workaround.
### Security: a session id is opaque and can never steer a filesystem path

The session cookie value reached the file session backend as a path component.
Tina4 for Python hashes the id into the filename, so it was NOT vulnerable to
the arbitrary file write proven in PHP and the arbitrary `.json` read/overwrite
proven in Node - but it did ADOPT any attacker-supplied cookie id verbatim.

**Breaking.** `Session.start()` now adopts a supplied session id only when it
passes BOTH gates, and mints a fresh id otherwise:

1. It is a well-formed opaque identifier (`[A-Za-z0-9_-]`, up to 128
   characters). The restriction is on the ALPHABET, not on length.
2. STRICT MODE: the store already holds that session. A well-formed id the store
   has never seen is discarded, because adopting one is session fixation. This
   matches PHP's own `session.use_strict_mode=1` default, Django and Rails, and
   the behaviour Tina4 for Node already had.

A backend that is UNREACHABLE is not treated as "unknown id". Strict mode
discards an id the store does not know; an outage is not evidence of that, and
rotating on it would log every user out over a blip and orphan their stored
sessions. The documented policy stays log-loud + degrade.

`is_valid_session_id()` is exported for apps that want the same check.

Migration: `session.start("some-new-id")` no longer returns that id for a
session the store does not hold. Write the session first, or let the framework
mint the id and read it back from `session.session_id`. Deploying this also logs
every existing session out once.

### Security: an unverified Basic credential is no longer an auth result

**Breaking:** `Auth.authenticate_request()` no longer has a `Basic` branch. It
used to decode `Authorization: Basic` and return a truthy
`{"auth_type": "basic", "username": ..., "password": ...}` without checking
those credentials against anything, so an app following the documented
`if auth is None: return 401` idiom authenticated every caller that sent a
base64 string. PHP, Ruby and Node all returned `None` there.

Migration: an app that relied on this was not authenticating anyone. Decode the
header yourself and verify the credentials against your user store with
`Auth.check_password()`, or move the endpoint to Bearer JWT.

### Breaking: the API-key auth result key is `_auth` in all four frameworks

`Auth.authenticate_request()` returns `{"_auth": "api_key"}` instead of
`{"auth_type": "api_key"}`. PHP and Node already used `_auth` and Ruby used
`api_key`, so one successful authentication read three different ways across
the family.

Migration: replace `payload["auth_type"] == "api_key"` with
`payload["_auth"] == "api_key"`.

### Security: the write-route auth gate compares the API key in constant time

`core.server._check_auth` compared the bearer token against `TINA4_API_KEY`
with a plain `==`, which returns as soon as two bytes differ and leaks the key
prefix through response timing. It now routes through
`Auth.validate_api_key()`, which uses `hmac.compare_digest`.

### Fixed: a malformed `exp` / `nbf` no longer reads as "no constraint"

RFC 7519 s2 defines `exp` and `nbf` as NumericDate. A token carrying
`"exp": true` was compared as the year 1970 (Python treats `bool` as an `int`),
and the expiry clock is now truncated to integer seconds and tested with `>=`
so the boundary is byte-identical to PHP and Ruby - RFC 7519 s4.1.4 requires
the current time to be strictly BEFORE `exp`. A token with no `exp`/`nbf` claim
at all stays unconstrained.
### Breaking: the response cache obeys RFC 9111 (Authorization and Vary)

The response cache keyed entries on method plus URL, with NO request header in
the key. It is a shared, server-side store, so on a secured GET route the first
caller's body was served to every later caller of the same URL. Measured
end-to-end on a real secured route: a valid token for `bob` returned alice's
private body with `X-Cache: HIT`. In Node, where route middleware runs before
the auth gate, an ANONYMOUS request returned 200 with alice's body.

Two RFC 9111 rules now apply, as they do in Varnish, nginx and Rails:

- Section 3 / 3.5: a response to a request carrying `Authorization` is NOT
  stored unless the response carries `Cache-Control: public`, `s-maxage` or
  `must-revalidate`.
- Section 4.1: `Vary` is honoured. The nominated request headers are recorded
  with the entry and must match on lookup; an absent field matches only an
  absent field. `Vary: *` is never stored.

**Migration.** Authenticated GETs are no longer cached by default. If a
response body is genuinely identical for every caller, opt back in per
response:

```python
response.add_header("Cache-Control", "public")
```

Only add it where the body carries nothing user-specific. Public GET caching is
unchanged. See ADR-0020 and `plan/v3/features/043-caching.md`.

### Breaking: an unknown TINA4_CACHE_BACKEND raises instead of falling back to memory

An unrecognised name silently became an in-process memory cache, so a typo
(`TINA4_CACHE_BACKEND=redsi`) produced a running app that shared nothing while the
operator believed it was Redis. It now raises, naming the bad value and the valid
set - the contract `TINA4_SESSION_BACKEND` already uses.

**Migration.** Fix the spelling. Valid: `memory`, `file`, `redis`, `valkey`,
`memcached`, `mongodb`, `database` (plus the aliases `memcache`, `mongo`, `db`).

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

### CORS denies by default, and never pairs the wildcard with credentials

**Breaking:** `TINA4_CORS_ORIGINS` defaulted to `*`, which allowed every origin
on a fresh install. It now defaults to UNSET, which denies every cross-origin
request: no `Access-Control-Allow-Origin` is sent, and the browser's own CORS
check blocks the request. Django, Rails and ASP.NET all require an explicit
policy before emitting any CORS header, and now so does Tina4.

**Migration:** name the origins your frontend runs on.

```
TINA4_CORS_ORIGINS=https://app.example.com
```

Comma-separate several. `TINA4_CORS_ORIGINS=*` restores the old allow-any
behaviour for anyone who wants it: only the DEFAULT changed, not the capability.
Non-browser clients (curl, server-to-server) never consult CORS and are
unaffected. The status code of a denied preflight is unchanged at 204.

Also in this change:

- `Access-Control-Allow-Origin: *` is never sent alongside
  `Access-Control-Allow-Credentials: true`. The Fetch Standard's CORS check
  treats `*` as a literal once the request carries credentials, so every browser
  rejects the pair. When both are configured the wildcard wins, credentials are
  dropped, and a warning names the fix.
- `Vary: Origin` is now sent whenever the allowed origin is computed from the
  request's `Origin` header, including when the origin is REJECTED. Without it a
  shared cache can store one origin's response and serve it to another
  (RFC 9110 s12.5.5). It is not sent for a constant `*`, which does not vary.
- Every rejected cross-origin request logs an actionable warning naming the
  origin, the environment variable, and the fix. Silence was the common thread
  in every defect this audit found.

See ADR-0018.

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
