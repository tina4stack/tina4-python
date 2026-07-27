# Task: `generate model/crud` migration-missing-fields — fix at parity

Filed four times (one per language), same subsystem (CLI generators):
python#101, php#186, ruby#33, nodejs#38.

## Goal
`generate model/crud <Name>` WITHOUT `--fields` must write a migration whose DDL
creates **every column the generated model declares** (incl. the default `name`),
so the first write does not 500 with "table X has no column named name".

## The bug (two stacked defects, from python#101)
1. **Migration drops declared fields.** The default field set lived only in the
   model template; the migration was built from the *parsed* `--fields` list,
   which was empty → migration got only `id` + `created_at`, model got `name`.
2. **Route masks the DB error.** The generated route did `item = X.create(...)`
   then `item.to_dict()` with no success check, so the clean DB error surfaced as
   `'bool' object has no attribute 'to_dict'` — a 500 hiding the real cause.

## Reference fix (Python — ALREADY DONE on 3.13.91, verified)
`tina4-python/tina4_python/cli/__init__.py`:
- `DEFAULT_FIELDS = [("name","string")]` + `_fields_or_default(fields_str)` — the
  default lives in ONE place and flows into model, migration, template, test.
- The route generator guards `create()`/`save()` before `to_dict()` (defect #2).
Regression test: `tina4-python/tests/test_cli_generate.py` →
`TestGeneratedMigrationMatchesModel` (parses the generated model's fields via AST
and the UP migration SQL, asserts every declared field is in the DDL — real, no
mocks).

## The contract each framework must satisfy (mirror the Python test)
- `generate model X` and `generate crud X` with NO `--fields`:
  parse the generated model's declared fields; parse the generated UP migration;
  assert EVERY declared field (incl. `name`) appears in the migration DDL.
- The generated write route checks create/save succeeded before serialising.

## Method — diagnose BEFORE fixing (per the parity mandate)
PHP builds DDL "from the model's typed public fields" (`tina4-php/Tina4/ORM.php:1560`),
so it may be model-driven and already correct. REPRODUCE each against current HEAD
first; only fix the ones that actually break. A green in one language is not a fix.

## Parity dashboard (verified on current v3 HEAD — independent re-run)
| Framework | Migration incl. all fields | Route guards create() | Regression test | My re-run | Issue |
|-----------|----------------------------|-----------------------|-----------------|-----------|-------|
| Python    | ✅ (`_fields_or_default`)  | ✅                    | ✅ present       | 5 passed  | #101 closed |
| PHP       | ✅ (model-driven DDL)      | ✅                    | ✅ present       | 20/20     | #186 closed |
| Ruby      | ✅ (`fields_or_default`)   | ✅                    | ✅ (+in-process mirror added) | 78 ex, 0 fail | #33 closed |
| Node.js   | ✅ (landed 3.13.90 `2390e6f`) | ✅                 | ✅ present       | 38 passed | #38 closed |

Outcome: the bug was already fixed across the whole family in the 3.13.x line —
reproduction found it live in NONE of the four. No production code changed; the
only net-new artifact is the Ruby in-process regression in `spec/cli_generate_spec.rb`.

## Verification (real — no mocks; independently re-run at HEAD)
- Reproduce: run the generator without `--fields`, inspect the migration DDL.
- Add the regression test mirroring the Python class; confirm it FAILS on current
  code (red = bug reproduced) BEFORE the fix, passes after.
- Re-run the FULL suite in each fixed framework (phpunit / rspec / `tsx
  test/run-all.ts`) — the main session re-runs, does not trust the worker's green.

## Branches / release
Framework repos are on `v3` (active release line). Land the fix on a
`fix/generate-migration-fields` branch per repo; the maintainer reviews the diff +
re-runs the suite before merge. Workers do NOT commit or push.

## Status: ✅ Complete — all four verified fixed on HEAD; issues #101/#186/#33/#38 closed
