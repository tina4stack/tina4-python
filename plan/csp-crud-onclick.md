# Task: De-inline crud component onclick handlers (CSP-clean under default-src 'self')

Outcome: the CRUD component's buttons fire under the strict default CSP
(`default-src 'self'`). A CSP nonce covers `<script>`/`<style>` ELEMENTS but NOT
inline `on*=` event-handler attributes, so every `onclick="..."` the component
emits is dead under the policy. Replace each with `data-*` attributes +
`addEventListener` wiring inside the already-nonce'd `<script>`. Follow-up to
[plan/csp-nonce-inline.md](tina4-python/plan/csp-nonce-inline.md).

## Scope
- [x] Python: `tina4_python/templates/components/crud.twig` — de-inline 5 onclick
      HTML attrs + the form's onsubmit + the JS-generated pagination onclick
- [x] Python: event delegation (click + submit) on `#crudTarget{{table_name}}` (survives AJAX reload)
- [x] Python: pagination link rebuilt with createElement + addEventListener
- [x] Ruby (parity): `lib/tina4/crud.rb` — de-inline all 9 onclick + the modal form onsubmit
- [x] PHP / Node: AutoCrud is REST-only, NO HTML crud component with onclick → nothing to de-inline (finding)
- [x] Real test (no mocks) renders the component, asserts zero on*= + buttons wired (Python + Ruby)

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| crud HTML component exists | ✅ crud.twig | ❌ REST-only | ✅ crud.rb | ❌ REST-only |
| onclick de-inlined (CSP-clean) | ✅ | n/a | ✅ | n/a |

## Tests (real, no mocks, positive + negative)
- [x] Python: render crud.twig via real Frond → 0 on*= attrs, data-crud-action add/edit/delete present, pagination + delegation wired + source scan (tests/test_crud_csp_onclick.py, 6 passed)
- [x] Python negative: record JSON rides in `data-record` (JSON-safe, `'`); mutation (restore an onclick) turns the gate red — proven
- [x] Ruby: render Crud.to_crud + generate_table (real SQLite, real Request) → 0 on*=, data-crud-action/-inline wired (spec/crud_csp_onclick_spec.rb, 6 examples); mutation-proven

## Bugs
- [x] crud component buttons never fire under strict default CSP (inline onclick blocked) — fixed; no-on*= gate green + mutation-proven in Python and Ruby

## Commits
- (py)   <hash>  crud.twig de-inline on*= → data-* + delegation; real CSP render test
- (ruby) <hash>  crud.rb de-inline on*= → data-* + delegation; real CSP render spec

## Status: Complete (Python + Ruby). PHP/Node have no HTML crud component (REST-only). PR to v3, do not merge.
```
Branch: fix/csp-nonce-inline (all four repos). PR to v3, do not merge.
```
