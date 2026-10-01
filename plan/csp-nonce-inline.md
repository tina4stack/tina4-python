# Task: CSP nonce for framework inline content (fix unstyled fresh-init render)

Outcome: fresh `tina4 init python` renders STYLED under the strict default CSP. Keep
`default-src 'self'`; make the framework's own inline `<style>`/`<script>` CSP-clean via a
per-response nonce, and de-inline every `style="..."` the framework emits. No 'unsafe-inline'.

## Scope
- [x] Per-response nonce module (`tina4_python/core/csp.py`): contextvar + generate + Frond global `csp_nonce`
- [x] `response.csp_nonce` attribute (Response __slots__ + __init__)
- [x] Wire nonce per request in `server.handle()` (set/clear in try/finally, mirror request_id)
- [x] Frond global `csp_nonce()` registered in engine `_register_builtins`
- [x] CSP header: inject `'nonce-X'` into style-src AND script-src (default + user TINA4_CSP) in SecurityHeadersMiddleware
- [x] Update TINA4_CSP one-time warning text (inline now works via nonce)
- [x] Nonce every framework inline `<style>`/`<script>`: welcome page, swagger, error_overlay, error twigs, crud.twig, gallery
- [x] De-inline every `style="..."` the framework emits (classes in the page's nonce'd <style> / bundled CSS)
- [x] De-inline welcome-page + gallery inline `onclick=` → data-* + addEventListener
- [x] Scaffold auth forms (login/register) de-inlined + nonce'd `<style>` demonstrating csp_nonce()
- [x] Document csp_nonce() for app developers (tina4_python/CLAUDE.md)
- [ ] FOLLOW-UP (flagged, out of this scope): de-inline crud.twig's ~6 row-level onclick handlers (dynamic JSON payloads) — its <script> is nonce'd; onclick needs event delegation + its own tests

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| csp-nonce | ❌ BUILD | ❌ (mirror) | ❌ (mirror) | ❌ (mirror) |

## Tests (real, no mocks, positive + negative)
- [x] CSP header on `/` carries 'nonce-' in style-src AND script-src (real boot) — test_csp_nonce_inline.py
- [x] welcome page inline <style>/<script> carry that exact nonce — real child server
- [x] no style= / onclick= emitted by framework welcome page
- [x] negative: two requests get DIFFERENT nonces (per-response)
- [x] updated contract mirrors: test_security_headers_contract.py, test_http_hardening_contract.py, test_csp_default_warning.py

## Bugs
- [x] fresh-init `/` welcome page rendered unstyled under default CSP — fixed via per-response nonce

## Commits
- (squashed on branch fix/csp-nonce-inline — see PR)

## Status: Complete (Python reference). Deterministic verify + metrics gate green. PHP/Ruby/Node mirror pending.
