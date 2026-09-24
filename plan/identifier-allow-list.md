# Task: identifiers that reach SQL come from the model (ADR-0069)

**Outcome:** `ORM.find(dict)` accepts only keys that resolve to a declared field
(by field name or by its column) and emits the resolved column quoted by the
bound adapter; the DocStore SQLite fallback accepts only field paths whose
dot-separated segments match `[A-Za-z0-9_-]+`. Anything else raises
`ValueError` before any SQL is built.

Branch: `fix/identifier-allow-list` off `origin/v3` (local only, not pushed).

## Scope
- [x] Read ADR-0069 contract (sections B and C are Python's; section A is not)
- [x] B - `tina4_python/orm/model.py`: one resolver (`_resolve_filter_column`) used by `find(dict)`
- [x] B - checked sibling finders: `find_by_id`, `load()`, `where()`, `count()`, `with_trashed()`,
      `exists()`, `all()`, `select()` take a PK value or a documented raw SQL string, not a key map;
      no other dict-keyed filter exists in the ORM. Unchanged by design.
- [x] C - `tina4_python/docstore/__init__.py`: validate every segment in `_path()`, the single
      chokepoint for `_extract` / `_type` / `_each` and `Cursor` sort
- [x] Tests written first and seen RED on the unmodified code
- [x] Mutation-proved both guards
- [x] Full suite with services, local (macOS, Python 3.13.11; SQLite, PostgreSQL, MySQL, MSSQL, Firebird, MongoDB over localhost tunnels)

## Parity
| Contract item                              | Python | PHP | Ruby | Node |
|--------------------------------------------|--------|-----|------|------|
| A. AutoCrud filter/sort allow-list         | n/a (no filter/sort in Python AutoCrud) | other worker | other worker | other worker |
| B. ORM `find(map)` rejects unknown keys    | ✅ | other worker | other worker | other worker |
| C. DocStore fallback validates field paths | ✅ | other worker | other worker | other worker |

Open parity question for the maintainer: Python's AutoCrud list route has no
`filter[...]` / `sort` parameters at all, while PHP, Ruby and Node do. Not built
here (the contract says do not add it). Decide whether Python should gain them.

## Tests (written first, real - no mocks, positive + negative)
File: `tests/test_identifier_allow_list_contract.py`
- [x] `orm_find_rejects_undeclared_filter_key` - SQLite, PostgreSQL, MySQL, MSSQL, Firebird.
      Negative: an undeclared-but-real column, and keys containing a space, a quote, a bracket.
      Positive: declared field, `field_mapping` field by name AND by column, `Field(column=)` by
      name AND by column, multi-key filter, raw `order_by` string still honoured.
      An unreachable engine FAILS under `TINA4_REQUIRE_SERVICES=1`.
- [x] `docstore_rejects_unsafe_field_path` - filter key, nested `$or` key, operator field,
      sort key raise `ValueError`; SQLite trace callback proves no statement ran.
- [x] `docstore_accepts_safe_field_paths` - `a_b`, `a-b`, `A1`, `nested.key`, `_id` on the fallback.
- [x] `docstore_safe_paths_match_on_real_mongo` - same data and queries give identical results on
      the fallback and on a real MongoDB (`TINA4_TEST_MONGO_URI`), unique db dropped afterwards.

## Bugs
- [x] `ORM.find(dict)` interpolated an unrecognised key into the WHERE clause.
- [x] DocStore fallback built JSON path literals from unvalidated field names.
- [ ] Surprise (not changed here): `uv.lock` on origin/v3 is stale against the `test` extra
      (`cryptography` is declared but not locked); `uv sync` rewrites the lock. Used
      `uv sync --extra test --frozen` + `uv pip install cryptography` for the local env.
- [ ] Found, NOT changed here (outside this fix's scope; needs a decision): a field declared with
      `Field(column="x")` is written to column `x` but never hydrated back - `_populate()` only
      reverses `field_mapping`, so the attribute reads `None` and the row value lands on an extra
      attribute `x`. Reproduced on clean origin/v3 with SQLite.

Full-suite non-passes (all proven pre-existing or environmental, none from this change):
- `tests/test_session_zero_dependency_fallback.py` 2 failed - same failure on clean origin/v3
  (MongoDB zero-dependency transport UnicodeDecodeError).
- `tests/test_mqtt_auth_tls.py` 10 errors - same on clean origin/v3; the lab env file points
  TINA4_TEST_MQTT_CA_FILE at a path that does not exist on this Mac.
- `tests/test_cli_lint.py` 2 failed - caused by `UV_FROZEN=1` in the run's shell (the test runs its
  own `uv add --dev ruff`); 7/7 pass with it unset.
- 38 skipped - graph engines (neo4j/memgraph/arango/ultipa) not provisioned locally, 1 lab-only
  OIDC gate; same 38 on clean origin/v3.

## Commits
- (pending)

## Status: Complete (local; not pushed)
