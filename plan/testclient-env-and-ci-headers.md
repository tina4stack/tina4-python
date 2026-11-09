# Task: TestClient loads .env (#296) + case-insensitive response headers (#300)

Outcome: fix two TestClient DX-footgun bugs at parity across all four frameworks,
each proven by a no-mock regression test confirmed red before the fix.

## Bugs (both confirmed present in ALL FOUR at HEAD 3.13.160)
- [ ] #296 — `TestClient` dispatches through the real front controller but never
      loads `.env` (loaded only in `run()`/`App::start`/server boot), so a route
      that signs a token raises `InsecureSecretError` though `.env` sets a valid
      `TINA4_SECRET`. Fix: TestClient loads `.env` the way the app does, FIRST-WINS
      (override=false) so a test's own env is never clobbered; once per client.
- [ ] #300 — `TestResponse.headers` is a plain map with lowercased keys, so
      `headers.get("Location")` (canonical case) misses while `get_all`/`getList`
      is already case-insensitive. Fix: case-insensitive single-value lookup that
      KEEPS the shape (lowercase keys, last value, emission order).

## Design (idiomatic per language; keep stored shape)
- Python: `headers` -> dict subclass lowercasing lookup (still `isinstance dict`);
  `TestClient.__init__` calls `load_env(override=False)` once (module guard).
- Ruby:   `@headers` -> Hash subclass downcasing `[]`/`fetch`/`key?`/`dig`;
  TestClient loads `.env` first-wins on build.
- Node:   `headers` -> Proxy lowercasing property get/has (Object.keys stay lower);
  TestClient `loadEnv()` once.
- PHP:    arrays cannot subscript case-insensitively, so keep `$headers` array AND
  add `header(string $name): ?string` case-insensitive scalar getter (sibling of
  `getList()`); TestClient calls `DotEnv::loadEnv(overwrite:false)` (+.env.local).

## Parity
| Fix | Python | PHP | Ruby | Node |
|-----|--------|-----|------|------|
| #296 .env load    | ✅ | ✅ | ✅ | ✅ |
| #300 CI headers   | ✅ | ✅ | ✅ | ✅ |

Python: _HeaderMap(dict) CI lookup + TestClient.__init__ load_env(override=False).
PHP: TestClient::__construct DotEnv::loadEnv(overwrite:false) + TestResponse::header() CI getter.
Ruby: TestClient#initialize Tina4::Env.load_env + CaseInsensitiveHeaders < Hash.
Node: TestClient ctor loadEnv() + headers Proxy (lowercases lookup only).
All mutation-proven; broader TestClient suites green (py per-file, php 11 suites,
rb 399 ex, node 16 files + typecheck clean).

## Status: Complete

Python: _HeaderMap(dict) CI lookup + TestClient.__init__ load_env(override=False);
tests/test_test_client_env_and_headers.py (4 tests, both fixes mutation-proven red).

## Tests (written first, real — no mocks, proven red by mutation)
- [ ] #296: TestClient (no app import) + .env TINA4_SECRET -> token route returns 200, not InsecureSecretError
- [ ] #296 negative: a real env var set before the client is NOT clobbered (first-wins)
- [ ] #300: headers.get("Location")/["Location"]/header("Location") finds a lowercase-emitted header
- [ ] #300 negative: a header never sent returns None/null/nil/[] (not a false hit)

## Commits
- (per-repo feature branch fix/testclient-env-and-ci-headers -> PR to v3)
