# Task: Fix Metrics regression gate on PR #206 (feature/crud-html-page)

Outcome: `tina4 metrics --path tina4_python --fail-on-regression` passes (no
regression vs committed baseline), behaviour unchanged, target tests green.

## Scope
- [x] crud/page.py — HTML/field/row assembly moved to new leaf module
      crud/page_render.py; every function now CC<=7 (new-file ratchet is >=8).
      to_crud 13->7; field/fetch/sort helpers all split.
- [x] crud/__init__.py — _parse_list_pagination / _resolve_list_order_by /
      _build_list_search extracted from list_handler (CC 19->~4). ADR-0043
      envelope + ADR-0069 safe-sort identical. offenders 3->2, worst CC 19->17.
- [x] Local gate (metrics.yml): `tina4 metrics --path tina4_python
      --fail-on-regression` => "no regression against the baseline".

## Tests (real — no mocks)
- [x] test_crud_to_crud.py green
- [x] test_autocrud_search_sort.py green
- [x] test_cli_generate.py green
      (107 passed, 0 failed, 0 skipped; + crud/smoke/parity/dev_surface 163 green)

## Note on the gate rule (learned by iteration)
The `--fail-on-regression` new-file check counts a function whose cyclomatic
complexity is >=8 as an offender (the standalone offenders LIST uses a higher
>=11 "warn" bar; MI/too_many_functions/no_test_reference are NOT counted for the
new-file regression). So the fix is purely: keep every function in the two new
files at CC<=7. Verified: CC counter reproduces the tool exactly (orig to_crud 13,
_build_custom_field 12).

## Bugs
- (none)

## Commits
- (hash  crud: split page.py HTML assembly into page_render + flatten list_handler)

## Status: Complete
