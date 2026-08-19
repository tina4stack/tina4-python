# Task: `from tina4_python import websocket` is callable (PY-FW-03)

## Outcome
Documented `from tina4_python import websocket` + `@websocket("/ws")` works on
3.13.105 without turning `import tina4_python.websocket as ws` into a function.
Review blockers on `fix/websocket-decorator-shadowed` landed before the PR.

## Scope
- [x] Confirm defect on origin/v3 (module not callable)
- [x] Guard `sys.modules` lookup; `__call__(*args, **kwargs)`
- [x] Rewrite false "re-export race" rationale (comment + tests)
- [x] Pointer comment in `tina4_python/__init__.py` eager tuple
- [x] Tests: re-export guard is `isinstance ModuleType` + `WebSocketServer`;
      decorator `__code__` identity; backplane submodule import
- [x] CHANGELOG under 3.13.105
- [x] Flip two `.claude/skills/` lines that still deny the top-level form
- [ ] PR vs `v3` — disclose mypy/pyright `Module not callable`

## Parity
| Surface | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| package-name decorator shadowing | this PR | n/a (no same-name subpackage) | n/a | n/a |

Python-only: CPython binds `tina4_python.websocket` to the subpackage.

## Tests (written first, real — no mocks, positive + negative)
- [x] package attribute callable; `@websocket` registers a path
- [x] `import tina4_python.websocket as ws` stays a ModuleType with `WebSocketServer`
- [x] `from tina4_python.websocket import backplane` still resolves
- [x] package decorator `__code__` is router decorator `__code__`
- [x] negative: four decorator tests fail on unfixed origin/v3 (already measured)
- [x] full suite at HEAD: 13 failed / 5026 passed / 628 skipped (Linux, CPython 3.13). Same 13 env failures as origin/v3 (connect-timeout, port-takeover, queue backend names, redis session). test_swagger_contract.py ignored (no openapi_spec_validator).

## Bugs
- [ ] PY-FW-03: `from tina4_python import websocket` is the module, TypeError at decorate
- [ ] review: commit claimed import-order rebind; measured false after first load
- [ ] review: unguarded `_sys.modules[__name__]` KeyError without sys.modules entry

## Commits
- cf4d676  fix(websocket): make @websocket usable from the package name
- (follow-up hash after review fixes)

## Status: In Progress
