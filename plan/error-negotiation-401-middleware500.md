# Task: #342 — auth-gate 401 + middleware-500 must go through the negotiated error renderer

Outcome: a browser (Accept: text/html) that hits a secured route without a valid token,
a role-guarded route it may not use, or a route whose middleware hook throws, gets the
framework error PAGE (`errors/{401,403,500}.twig`, app override then framework default),
not a raw JSON body. An API client still gets the standard JSON envelope
(`{error, code, message, status, request_id}`). 500 keeps CWE-209 (no exception text).
Governed by the existing negotiation contract (ERR-DEC-02); these three emit paths were
the non-compliant ones. Parity across all four frameworks.

## Scope
- [x] Read Python reference: `_render_forbidden` (negotiates 403), `_render_negotiated_500`,
      `_json_error_body`, the 404 path — the reference; the 401 gate (server.py:1883),
      RBAC-403 (1899), `middleware_500` (middleware.py:197) are the non-compliant emits
- [ ] Python: generalize negotiated renderer + route 401 / RBAC-403 / middleware-500 through it
- [ ] PHP: Router 401 gate + RBAC-403 + `Middleware::middleware500()` → renderError
- [ ] Ruby: equivalent
- [ ] Node: equivalent
- [ ] frond/errors templates: confirm 401.twig/403.twig/500.twig ship in all 4
- [ ] Docs: note the behaviour where error negotiation is documented
- [ ] Version bump + CHANGELOG + release-notes, all 4, cut 3.13.160, tag, publish

## Parity (all fixed + mutation-proved; full suites verifying)
| Path | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| secured 401 → negotiated | ✅ | ✅ | ✅ | ✅ |
| RBAC 403 (dispatch) → negotiated | ✅ | ✅ | ✅ | ✅ |
| middleware-throw 500 → negotiated | ✅ | ✅ | ✅ | ✅ |
| 401 added to error-code-name map | ✅ | ✅ | ✅ | ✅ |

Design: one shared negotiated-error renderer per framework (py `_render_negotiated_error`,
php `Router::negotiatedError`, rb `RackApp.negotiated_error_tuple`, node `renderNegotiatedError`
in response.ts). The 401 gate, dispatch RBAC-403, and middleware-500 all route through it. JSON
body aligned to the `{error,code,message,status,request_id}` envelope (was a bare body); 500 keeps
CWE-209 (no exception text). Regression test per framework, both branches, each mutation-proved.
Stale-contract tests updated: py 3, php 3, rb 7, node 2.

## Tests (written first, real — no mocks, positive + negative)
- [ ] secured route, no token, Accept: text/html → 401 text/html, body is the 401 page
- [ ] secured route, no token, Accept: application/json → 401 json envelope + request_id
- [ ] middleware before-hook throws, Accept: text/html → 500 text/html page (no exception text)
- [ ] middleware before-hook throws, Accept: application/json → 500 json envelope + request_id
- [ ] (mutation) revert each emit to json-only → the text/html test goes red

## Bugs
- [ ] #342 auth-gate 401 + middleware500 bypass renderError (filed php; same in all 4)

## Commits
- (log hash — description per framework)

## Status: In Progress
