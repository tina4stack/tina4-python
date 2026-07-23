# Task: D6 — TestClient must dispatch through the real front controller

## Goal
The in-process `TestClient` bypasses the front controller and re-implements
dispatch, so it fabricates responses the server never sends. Route it through
the REAL dispatch path in Python (master), then mirror to PHP and Node.
Ruby is already fixed (commit `417e5a3`) and is the reference shape.

## Measured divergence, Python, live socket (real `tina4_python.core.server.run`
## on 127.0.0.1:17451, uvicorn) vs pre-fix TestClient, same routes:

| Probe                          | live | pre-fix TestClient |
|--------------------------------|------|--------------------|
| GET /swagger                   | 200  | 404 `{"error":"Not found"}` |
| GET /swagger/openapi.json      | 200  | 404 |
| GET /probe.txt (src/public)    | 200  | 404 |
| GET /js/tina4js.min.js         | 200  | 404 |
| PUT /pipeline/get-only         | 405  | 404 |
| GET /pipeline/plain            | 200  | 200 (unaffected) |
| GET /__health, /health         | 200  | 200 (real Router routes — not divergent) |

## Scope
- [x] Prove the divergence against a real socket (above)
- [ ] Python master: TestClient -> `core.server.app()` (ASGI entry), delete the
      re-implemented dispatch
- [ ] Python lock-in test (real subprocess server as the oracle, real socket)
- [ ] Audit the Python suite for tests that only passed via the short-circuit
- [ ] PHP mirror: TestClient -> the real front controller (not `Router::dispatch`)
- [ ] PHP lock-in test
- [ ] Node mirror: TestClient -> the real `dispatch`
- [ ] Node lock-in test
- [ ] Full suites green at final HEAD in all three

## Parity
| Guarantee                        | Python | PHP | Ruby | Node |
|----------------------------------|--------|-----|------|------|
| dispatch via front controller    | [ ]    | [ ] | done | [ ]  |
| static files reachable           | [ ]    | [ ] | done | [ ]  |
| /swagger reachable               | [ ]    | [ ] | done | [ ]  |
| global middleware runs           | [ ]    | [ ] | done | [ ]  |
| RFC 9110 405 + Allow             | [ ]    | [ ] | done | [ ]  |
| unmatched path -> the real 404    | [ ]    | [ ] | done | [ ]  |
| raising handler -> a real 500     | [ ]    | [ ] | done | [ ]  |

## Breaking (record in release notes, all four)
1. Unmatched path via TestClient: fabricated `{"error":"Not found"}` -> the
   server's real 404 (HTML error page in dev, JSON `{"error":"Not Found",...}`
   otherwise).
2. A raising handler via TestClient: the exception propagated out of the client
   -> a real 500 response.

## Status: In Progress
