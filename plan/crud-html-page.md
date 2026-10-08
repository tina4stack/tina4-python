# Feature: Crud.to_crud — frontend over AutoCrud (ADR-0094), tina4-python

Outcome: `Crud.to_crud(request, model=, sql=None, title=, prefix="/api", limit=10)` renders a
searchable/sortable/paginated CRUD admin page from overridable Frond templates, delegating the whole
backend to AutoCrud. Mirrors the Ruby master + ADR-0094. Python only.

## Scope
- [x] Read ADR-0094 + Ruby master (crud.rb, templates, auto_crud.rb, cli.rb, specs)
- [x] Ground in Python source (AutoCrud, Router, Frond, ORM, CLI, csp)
- [x] AutoCrud list handler: add ?search (LIKE across string/text cols, filtered total) + ?sort/?sort_dir (ADR-0069 safe)
- [x] `Crud` class in tina4_python/crud/ — to_crud (model required, sql optional), generate_table, generate_form
- [x] Templates tina4_python/templates/crud/{page,table,form,modals}.twig (app override via src/templates/crud/)
- [x] CLI `generate crud <Model>`: AutoCrud-backed /admin/<table> page via to_crud, secure by default (--public opens), copies crud/* templates, model+migration+gate test
- [x] Tests: tests/test_crud_to_crud.py (real SQLite, real Request)
- [x] Tests: AutoCrud search/sort real-data test
- [x] Tests: CSP on*=/style= gate + mutation proof
- [x] Tests: update test_cli_generate.py crud section to ADR-0094 table-name/admin-page design
- [x] Live render script → scratchpad/tocrud-python.html

## Tests (written first, real — no mocks)
- [x] page renders, rows present, title
- [x] AutoCrud routes registered (GET list + GET/{id} + POST/PUT/DELETE)
- [x] to_crud registers no bespoke routes of its own; idempotent
- [x] live search input present, no Search button
- [x] AbortController + data-crud-body + data-crud-sort/page present
- [x] alignment: numeric text-end, text text-start, no inline style=
- [x] validation wiring: data-crud-errors + showErrors + res.ok
- [x] model required → raises; sql-only → raises
- [x] app override: src/templates/crud/table.twig wins
- [x] zero on*= / style= (regex) + mutation proof
- [x] AutoCrud ?search filters real rows with filtered total; ?sort/?sort_dir orders
- [x] CLI crud: admin route secure_get /admin/<table>, renders to_crud, copies templates, --public, --no-templates

## Bugs
- (none)

## Commits
- (this commit)  Crud.to_crud frontend over AutoCrud + ?search/?sort list support + crud/*.twig + generate crud + real tests

## Verify
- Required suites (crud, autocrud, csp, cli/generate): 184 passed, 0 failed, 0 skipped (macOS, Python 3.13.11)
- Live render: scratchpad/tocrud-python.html — 19648 bytes, 5 AutoCrud routes, on*=0 / style=0
- CSP on*=/style= gate mutation-proven (test_gates_are_real_mutation_proof)

## Status: Complete
