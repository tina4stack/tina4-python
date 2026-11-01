# Task: #265 — public form can be @noauth AND CSRF-protected (Option 3)

Outcome: `@noauth()` stops disabling the CSRF check. A public form (`@noauth()` +
`{{ form_token() }}`) posts successfully AND stays CSRF-protected. A new `@no_csrf()`
opt-out skips CSRF for server-to-server webhooks so they don't regress to 403 when
`TINA4_CSRF=true`. Docs clarified: form_token is CSRF, not auth. Parity in all 4.

Decision: owner chose Option 3 + docs (reaffirms ADR-0079 s1 — a form token is NOT an
identity; the auth gate is unchanged). This is a CSRF-middleware behaviour change, not an
auth-contract change.

## Scope
- [x] Python: CsrfMiddleware no longer skips @noauth; honor new `_no_csrf` flag
- [x] Python: add `@no_csrf()` decorator (router) + export
- [x] Python: fix CsrfMiddleware docstring ("off by default" wording + @no_csrf)
- [x] Python: tests updated to new contract + mutation-proven (63 passed)
- [x] PHP: same (CsrfMiddleware + ->noCsrf() route modifier) — 60+44 green
- [x] Ruby: same (CsrfMiddleware + .no_csrf chain / .no_csrf? reader) — 48+51 green
- [x] Node: same (CsrfMiddleware + .noCsrf() / export const noCsrf) — 50 green + typecheck
- [ ] Fixture + CSRF-DEC-03 ADR + CONTRACT-MAP (tina4-documentation)
- [ ] Docs: public form = @noauth + form_token; webhook = @noauth + @no_csrf; form_token ≠ auth

## Parity
| Behaviour | Python | PHP | Ruby | Node |
|-----------|--------|-----|------|------|
| @noauth form is CSRF-checked | ✅ | ✅ | ✅ | ✅ |
| @no_csrf opt-out skips CSRF   | ✅ | ✅ | ✅ | ✅ |

## Tests (written first, real — no mocks, positive + negative)
- [ ] public @noauth POST with valid form token → 200 (not 401, not 403)
- [ ] public @noauth POST with NO/invalid form token → 403 (CSRF enforced)
- [ ] @noauth + @no_csrf POST with no token → 200 (opt-out honored)
- [ ] protected POST (no @noauth) still needs identity → 401 without one
- [ ] Bearer identity still skips CSRF (API client) → 200

## Bugs
- [ ] (log here)

## Commits
-

## Status: In Progress
