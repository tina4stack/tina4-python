# Task: Mongo replica-set replies, sqlsrv getLastId, uv.lock drift, test-run browser default (Mac testbed findings, 2026-09-24)

**Outcome:** every zero-dependency Mongo client decodes replica-set replies (mongo 7 and 8), PHP ext-sqlsrv returns the generated id, tina4-python's lock matches pyproject, and no test run opens a browser. The fixes are at parity and proven red to green on real services.

## Scope
- [x] Capture real OP_MSG replies: standalone mongo:7/8 vs replica-set mongo:7/8 (the root cause is the topology, not the version)
- [x] Python: decode 0x05/0x07/0x09/0x11; an unknown type stops at the document boundary
- [x] PHP: one shared `Tina4\MongoBson` codec (Session + Cache), same types
- [x] Ruby/Node: already decode them; the same captured-bytes + live `hello` tests lock that in (Ruby); Node verified live
- [x] CI in all four: a mongo:8 single-node replica set on 27018, and the Mongo suites re-run against it
- [x] PHP ext-sqlsrv: SCOPE_IDENTITY in the INSERT's own batch (parity with py/rb/node)
- [x] tina4-python: `uv lock` (drift, not extras); pyproject unchanged
- [x] Test runners default TINA4_NO_BROWSER=true (PHP bootstrap, Ruby spec_helper, Node run-all/vitest; Python conftest owned by another worker), with guard tests
- [x] PHP: ADR-0070 gate (8 CI vars, false/0/no/off = not CI) + fixture runner

## Parity
| Feature | Python | PHP | Ruby | Node |
|---|---|---|---|---|
| replica-set BSON decode | ✅ fixed | ✅ fixed | ✅ already, locked in | ✅ already |
| CI mongo:8 replica set | ✅ | ✅ | ✅ | ✅ |
| MSSQL last id | ✅ | ✅ fixed (sqlsrv) | ✅ | ✅ |
| runner NO_BROWSER default + guard | other worker (conftest) | ✅ | ✅ | ✅ |

## Tests (real, no mocks)
- [x] captured replica-set reply decodes every field (py, php, rb)
- [x] unknown type does not corrupt later fields (py, php, rb)
- [x] live `hello` through the wire client's own command path (py, php, rb)
- [x] existing Mongo session/cache/queue/docstore suites green on mongo:7/8 standalone + replica set (all four)
- [x] php sqlsrv: MssqlProviderContractTest x2, MySQLMSSQLLiveTest::testMSSQLGetLastIdReturnsIdentity
- [x] NO_BROWSER guard tests, mutation-proved (php, rb, node)

## Bugs
- [x] Python/PHP BSON decoder did not consume unknown-type bytes (replica sets)
- [x] PHP sqlsrv getLastId() always 0
- [x] tina4-python uv.lock drift
- [x] test_session_ttl_contract built the Mongo handler with ignored host=/port=
- [x] Mac testbed: memcached clock drift from the VM's fast monotonic clock (services.sh clock-sync)

## Commits (tina4-python, branch fix/mongo8-sqlsrv-lastid)
- cc640f0  Decode every BSON type a MongoDB reply carries (replica sets)
- 6fbd8bf  Relock uv.lock: it had drifted from pyproject.toml


## Status: Complete (PRs open, not merged)
