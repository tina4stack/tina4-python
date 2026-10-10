# Task: #277 cross-process migration lock — Python parity with PHP reference (ADR-0095)

Outcome: `migrate()` holds one run-wide lock across the whole run so concurrent boots
apply each migration exactly once. The lock engine code and the real multi-process test
already landed in Python (PR #204, merged to v3). The remaining gap is the **file-lock
location**: the amended ADR-0095 and the PHP reference put the sidecar in the SYSTEM TEMP
dir keyed by the ABSOLUTE migrations path; Python still writes `.tina4_migration.lock`
inside the tracked `migrations/` folder. Close that gap.

## Scope
- [x] Read ADR-0095 (governing contract)
- [x] Read PHP reference (Migration.php migrate/runPending/acquireMigrationLock/acquireFileLock/fileLockPath/releaseMigrationLock/pgAdvisoryKey + the test + worker fixture)
- [x] Read Python runner.py (lock already present, merged via PR #204)
- [x] Move the file-lock sidecar to `tempfile.gettempdir()`, named `tina4-migration-<sha256(abs migrations dir)>.lock` (parity with PHP `fileLockPath()`)
- [x] Keep Windows/no-fcntl degrade-to-unlocked behaviour
- [x] Add a focused unit test pinning the new path contract (temp dir, stable, keyed by abs path)
- [x] Mutation-prove the concurrency test (remove the lock → it must fail with duplicate rows)
- [x] Full suite green at HEAD (0 failed, 0 skipped except platform gates)

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| run-wide lock in migrate() | ✅ | ✅ | (sibling) | (sibling) |
| pg/mysql/mssql native locks | ✅ | ✅ | (sibling) | (sibling) |
| file lock in SYSTEM TEMP, keyed by abs path | ✅ | ✅ | (sibling) | (sibling) |
| real multi-process concurrency test | ✅ | ✅ | (sibling) | (sibling) |

## Tests (real, no mocks, mutation-proved)
- [x] test_migration_concurrency_277.py — 8 real processes, SQLite file-lock path, slow data migration (already present); mutation (lock off) → 6 rows
- [x] test_file_lock_sidecar_lives_in_system_temp... — path contract: temp dir, not migrations folder, keyed by abs path, stable across cwd; mutation (lock in folder) → red
- [x] test_migration_concurrency_277_postgres.py — 8 real processes, live PG advisory-lock path, gated on TINA4_TEST_PG_* reachability; asserts every boot clean + one data row; mutation (lock off) → 7 failed boots, 3/3 red, 3/3 green with lock (not flaky)

## Mutation proof (reported)
- SQLite concurrency: lock disabled → 6 duplicate 'first' rows (expected 1). RED. Restored → green.
- Path contract: lock path moved into migrations folder → commonpath assertion RED. Restored → green.
- PostgreSQL concurrency: lock disabled → 7/8 boots fail with UniqueViolation. RED ×3. Restored → green ×3.

## Bugs
- [x] file-lock sidecar written into tracked migrations/ (`.tina4_migration.lock`) — committed by accident, blocks rmdir. Fixed: moved to `tempfile.gettempdir()/tina4-migration-<sha256(abs dir)>.lock` (PHP parity).
- [x] **REAL #277 DEFECT (the lock was being defeated):** `Migration.__init__` eagerly called `_ensure_tracking_table` OUTSIDE the lock, so every worker ran an unprotected `CREATE TABLE tina4_migration` in the constructor before `migrate()` took the lock. On a fresh PostgreSQL, 8 concurrent boots collided on `pg_type/pg_class` (7/8 boots failed) — the exact #277 symptom the lock is supposed to stop. Proven: table absent → 100% fail; fix → 4/4 pass; re-adding eager ensure → fail again. Fixed by removing the eager ensure (PHP reference ensures lazily; every public method ensures under/at its own operation). 12 existing upgrade tests asserted the old eager-construct contract and were re-pointed to trigger the ensure via `.status()` (same behaviour, triggered lazily).
  - **Cross-framework:** PHP already ensures lazily. Ruby/Node sibling ports MUST check their constructors for the same eager-ensure-outside-lock defect (see shared notes).

## Commits
- (pending)

## Status: In Progress
