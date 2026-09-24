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
| E. AutoCrud uses the registered connection | ✅ (already correct; lock-in test) | other worker | other worker | other worker |
| F. REQUIRE_SERVICES gate = [needs:X] rule  | ✅ | other worker | other worker | other worker |
| G1. AutoCrud body keys via the find() resolver | ✅ (fixed: column keys were dropped) | other worker | other worker | other worker |
| G2. ORM save writes only declared fields   | ✅ (already correct; lock-in) | other worker | other worker | other worker |
| G3. write helpers reject non-identifier keys | ✅ (fixed) | other worker | other worker | other worker |
| AutoCrud id route / GraphQL id argument     | ✅ (already bound; lock-ins) | other worker | other worker | other worker |
| GraphQL commas insignificant                | ✅ (fixed) | other worker | other worker | other worker |

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

Addendum 2 (Python owns E and F; D is AutoCrud filter/sort, absent in Python):
- [x] E `test_autocrud_list_uses_the_registered_connection` (tests/test_autocrud_registered_connection.py):
      two real SQLite files, model bound directly and by name; list/get/create/update/delete.
      GREEN on unmodified code (ORM._get_db already honours `_db`); proved a gate by mutating
      `_get_db` to prefer the global default (both cases red).
- [x] F gate in tests/conftest.py: a skip passes under TINA4_REQUIRE_SERVICES only with a
      `[needs:X]` tag that is excusable (optional engine only while its coordinate env var is
      unset; always-provisioned service never; any other tag always). Module-level skips gated at
      collection; `continue_on_collection_errors` so one missing service does not abort the run.
      tests/test_require_services_gate.py: predicate cases + a real child pytest per branch
      (gate on / on with the Firebird coordinate set / off). Red on the origin/v3 conftest for
      "untagged fails" and "optional engine only while unset"; 6 mutations all red.
- [x] Tagged skip sites: 69 edits in 44 files (postgres, mysql, mssql, firebird, graph engines,
      oidc; platform os=posix / runtime=ipv6-loopback / runtime=libcrypto / runtime=redis-driver).
- [x] Removed one skip instead of tagging it: the live URL-credential test needed an 'a' in the
      password; it now encodes the first character.

Addendum 3 and follow-ups:
- [x] F: postgis joins the optional-engine map (TINA4_TEST_POSTGIS_URL); the PostGIS skip is tagged.
- [x] G1 `test_autocrud_write_body_accepts_only_declared_fields` (tests/test_autocrud_write_keys_and_ids.py).
      RED before: a body key given as a mapped column was dropped. Fix: ORM._declared_field_for is the one
      resolver for find() filters and AutoCrud bodies. Mutations killed: old name-only resolution, is_deleted
      guard, PK strip. Surviving by design: letting undeclared body keys through (save() writes declared
      fields only, G2).
- [x] G2 `test_orm_save_writes_only_declared_fields` - green before on all 5 engines (lock-in); a mutant that
      writes undeclared attributes is red on all 5.
- [x] G3 `test_db_write_helpers_reject_non_identifier_keys` - RED before on all 5 engines (the key reached
      the SQL unquoted). Fix: `column_key()` in database/adapter.py, used by insert/update/delete (single and
      batch) and Database._as_where. Five mutations, all red.
- [x] `test_autocrud_id_route_addresses_only_that_row`, `test_graphql_id_argument_addresses_only_that_row` -
      green before (lock-ins); interpolating the id, or ignoring it, is red.
- [x] `test_commas_are_insignificant_between_arguments_and_fields` (tests/test_graphql_commas.py) - RED
      before: commas between fields, in lists, repeated, and between top-level fields were parse errors.
      Fix: commas are skipped like whitespace in the tokenizer.

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
- e8df636  ORM find() accepts only declared fields; DocStore validates field paths (code + tests + plan)
- 0b75b1b  plan: record identifier-allow-list commit
- e0e87d9  ORM find() resolves filter keys through get_db_column (lead)
- acb6cba  test: AutoCrud routes use the model's registered connection
- 61178cb  tests: TINA4_REQUIRE_SERVICES excuses only [needs:X]-tagged skips
- d1c19d0  tests: encode any password character in the live credential test
- bf9ea47  tests: tag optional-engine and platform skips with [needs:X]
- b519bf3  tests: update comments that described the old phrase-matching gate
- 89c5150  plan: record addendum 2 (E, F) work and commits
- 230bb9c  tests: postgis is an optional engine in the REQUIRE_SERVICES gate
- e0ca851  test: ORM save() writes only declared fields
- 658b8d1  Database write helpers accept only identifier column keys
- 867fd20  AutoCrud write bodies resolve keys like find() does
- 0c2b7ce  test: AutoCrud id routes and GraphQL id arguments address one row
- 5e33743  GraphQL: commas are insignificant everywhere

Second full run (after E + F, gate on, macOS, Python 3.13.11): 6067 passed, 8 failed, 10 errors,
38 skipped. All 38 skips are tagged and excused (graph engines and OIDC, coordinates unset
locally). The 10 MQTT TLS errors are the same missing CA file as before. The 8 failures fail the
same way on clean origin/v3: MongoDB on localhost:27017 went down during the run (connection
refused), and the memcached container reports TTLs about 79 s short (clock skew).

Full run at 5e33743 (gate on, macOS, Python 3.13.11): 6088 passed, 2 failed, 10 errors, 38 skipped.
The 2 failures are test_session_zero_dependency_fallback (same on clean origin/v3); the 10 errors are the
missing MQTT CA file; the 38 skips are tagged and excused (graph engines, OIDC).

Open for the maintainer:
- Field(column="x") is not hydrated back (see Bugs). A find() -> save() round trip, including an
  AutoCrud PUT, writes NULL to that column. Data loss; not fixed on this security branch.
- GraphQL from_orm() builds its id filter from the primary-key FIELD name, not its column, and unquoted.
  Developer-controlled, not request-controlled, but wrong for a mapped primary key.
- CI (`.github/workflows/test.yml`) sets TINA4_TEST_PG_URL but not TINA4_TEST_MYSQL_URL or
  TINA4_TEST_MSSQL_URL, so under the new rule a MySQL/MSSQL outage in CI is excused (the old
  keyword gate failed it). Add the two URLs to the CI env to keep them strict.
- S3 is always-provisioned under the rule, but CI does not run MinIO, so the two real-MinIO tests
  in tests/test_realtime_files.py will now FAIL in CI until MinIO is provisioned there.
- TINA4_TEST_POSTGRES_URL (in the rule as a postgres alias) is rejected by Python's env-contract
  gate, so the Python gate reads only TINA4_TEST_PG_URL.

## Status: Complete (local; not pushed)
