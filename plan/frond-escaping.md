# Task: Frond escaping hardening (F1-F8) across Python/PHP/Ruby/Node

Outcome: Frond auto-escaping is safe by default in all four frameworks; trusted output is marked ONLY by a real SafeString type; normal templates render byte-identically (frond_expression corpus unchanged). Branch fix/frond-escaping from origin/v3; ADR-0077; shared frond_escaping_contract.json + 4 runners.

## Scope
- [x] F1 PHP: replace in-band RAW_MARKER with SafeString class end-to-end
- [x] F2 PHP+Node: filter output after e/escape/raw is plain string -> re-escaped
- [x] F3 PHP: data_uri sanitises client MIME type
- [x] F4 Py/Ruby/Node: escape list/dict/object string form on output
- [x] F5 all4: js_escape also neutralises <, >, &, / and quotes for attr+script safety
- [x] F6 sandbox: block dunder/callable-by-name/inherited methods; gate set/for/if against allow-list
- [x] F7 all4: e('js'|'url'|'css'|'html_attr') implement Twig strategies
- [x] F8 all4: document json_encode safe contexts in ADR (keep Twig semantics)
- [x] ADR-0077 + frond_escaping_contract.json + runners (py/php/ruby/node)
- [x] positive: frond_expression corpus byte-identical before/after (all 4)

## Parity
| Finding | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| F1 | n/a | ❌ | n/a | n/a |
| F2 | ✅ ok | ❌ | ✅ ok | ❌ |
| F3 | ✅ ok | ❌ | ✅ ok | ✅ ok |
| F4 | ❌ | ✅ ok | ❌ | ❌ |
| F5 | ❌ | ❌ | ❌ | ❌ |
| F6 | ❌ | ❌ | ❌ | ❌ |
| F7 | ❌ | ❌ | ❌ | ❌ |

## Tests (written first, real render, no mocks, positive + negative, mutation-proved)
- [ ] escape_list_dict_object (Py/Ruby/Node)
- [ ] js_escape_neutralises_markup (all4)
- [ ] filter_after_escape_reescapes (PHP/Node)
- [ ] safestring_not_forgeable_by_marker_bytes (PHP)
- [ ] data_uri_mime_sanitised (PHP)
- [ ] sandbox_blocks_dunder / set_for_if_allow_list / callable_by_name / inherited (per lang)
- [ ] e_strategy_js_url_css_html_attr (all4)
- [ ] corpus byte-identical (all4)

## Bugs
- (log here)

## Commits
- (hash desc)

## Status: Frond complete (local, macOS); lab full-suite + PRs pending
