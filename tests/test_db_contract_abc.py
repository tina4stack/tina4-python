"""DB-contract fixes A + B + C (v3.13.37) — fail-loud / correctness contract.

These complete the contract that ``Database.execute()`` already sets (it raises
on a SQL error). Three themes, all engine-agnostic so they run on SQLite locally
and in CI with no database server:

  A — fetch / fetch_one / fetch_all FAIL LOUD on a SQL error (parity with
      execute): a bad query RAISES (never silently returns empty/None), and the
      cause is captured on ``db.get_error()`` / ``db.last_error``. The COUNT
      probe in fetch() must NOT mask a real main-query failure. A failed read is
      never stored in the query cache.

  B — get_next_id() is ATOMIC: N concurrent callers for the same table get all
      DISTINCT ids (no duplicate primary keys). Exercised with threads on SQLite.

  C — commit() failure RE-RAISES (and populates last_error), RETAINS the
      transaction pin so a follow-up rollback() lands on the SAME connection,
      and clears the pin only on success / rollback. Nested start_transaction()
      is guarded (depth counter) so a double-begin doesn't silently leave a
      connection mid-transaction.
"""
from __future__ import annotations

import threading

import pytest

from tina4_python.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path}/contract.db")
    database.execute(
        "CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
    )
    database.commit()
    yield database
    database.close()


# ── THEME A — fetch / fetch_one fail loud + capture last_error ──────────────


def test_fetch_raises_on_bad_sql_and_populates_get_error(db):
    """A SELECT against a missing table RAISES — it does NOT return an empty
    result — and the cause is readable via the public API after the raise."""
    with pytest.raises(Exception):
        db.fetch("SELECT * FROM no_such_table")
    assert db.get_error() is not None
    assert db.get_error() == db.last_error


def test_fetch_one_raises_on_bad_sql_and_populates_get_error(db):
    """fetch_one must FAIL LOUD too (it used to raise but leave get_error None
    because it bypassed the error-capturing wrapper)."""
    with pytest.raises(Exception):
        db.fetch_one("SELECT * FROM no_such_table")
    assert db.get_error() is not None
    assert db.get_error() == db.last_error


def test_fetch_all_raises_on_bad_sql(db):
    """fetch_all inherits fetch() — it raises too (never returns [])."""
    with pytest.raises(Exception):
        db.fetch_all("SELECT * FROM no_such_table")
    assert db.get_error() is not None


def test_fetch_one_bad_column_raises_not_empty(db):
    """A typo'd column name is a SQL error — it must raise, not look like
    'no matching row' (None)."""
    with pytest.raises(Exception):
        db.fetch_one("SELECT no_such_column FROM widget")
    assert db.get_error() is not None


def test_count_probe_failure_does_not_mask_main_query_success(db):
    """A valid query still returns rows even though the COUNT(*) probe wrapper
    is best-effort — the main query is what matters."""
    db.execute("INSERT INTO widget (id, name) VALUES (1, 'a')")
    db.execute("INSERT INTO widget (id, name) VALUES (2, 'b')")
    db.commit()
    result = db.fetch("SELECT * FROM widget ORDER BY id")
    assert result.count == 2
    assert [r["name"] for r in result.records] == ["a", "b"]
    assert db.get_error() is None


def test_successful_read_clears_last_error(db):
    """After a failed read raises (last_error set), a subsequent good read
    clears it again."""
    with pytest.raises(Exception):
        db.fetch("SELECT * FROM no_such_table")
    assert db.get_error() is not None
    db.fetch("SELECT * FROM widget")
    assert db.get_error() is None


def test_failed_read_is_not_cached(tmp_path, monkeypatch):
    """A null/empty result from a FAILED read must never be served from cache —
    the failure raises before any cache store, so a later valid query against
    the now-existing table sees real rows, not a cached empty."""
    monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
    database = Database(f"sqlite:///{tmp_path}/cache.db")
    try:
        # Query a table that doesn't exist yet — must raise, not cache an empty.
        with pytest.raises(Exception):
            database.fetch("SELECT * FROM late_table")
        # Now create it and insert a row.
        database.execute(
            "CREATE TABLE late_table (id INTEGER PRIMARY KEY, name TEXT)"
        )
        database.execute("INSERT INTO late_table (id, name) VALUES (1, 'real')")
        database.commit()
        # The identical query must now return the real row — proving the failed
        # read was NOT cached as empty.
        result = database.fetch("SELECT * FROM late_table")
        assert result.count == 1
        assert result.records[0]["name"] == "real"
    finally:
        database.close()


# ── THEME B — atomic get_next_id (no duplicate ids under concurrency) ───────


def test_get_next_id_sequential(db):
    """Sequential ids increment by one and seed from MAX(pk)."""
    db.execute("INSERT INTO widget (id, name) VALUES (5, 'seed')")
    db.commit()
    ids = [db.get_next_id("widget") for _ in range(4)]
    assert ids == [6, 7, 8, 9]


def test_get_next_id_concurrent_no_duplicates(tmp_path):
    """REQUIRED TEST (Theme B): N concurrent get_next_id() calls for the SAME
    table return ALL DISTINCT ids — no duplicate primary keys under the
    read-increment-read race the old path had."""
    database = Database(f"sqlite:///{tmp_path}/concurrent.db")
    database.execute("CREATE TABLE thing (id INTEGER PRIMARY KEY, name TEXT)")
    database.commit()

    n = 100
    results: list[int] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker():
        try:
            value = database.get_next_id("thing")
            with lock:
                results.append(value)
        except Exception as exc:  # pragma: no cover - only on failure
            with lock:
                errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"get_next_id raised under concurrency: {errors[:3]}"
    assert len(results) == n
    # The core guarantee: every returned id is DISTINCT.
    assert len(set(results)) == n, "duplicate ids returned under concurrency!"
    # And because the table started empty, the ids are exactly 1..n.
    assert sorted(results) == list(range(1, n + 1))
    database.close()


# ── THEME C — commit failure handling + transaction pin guard ───────────────


def test_commit_failure_raises_retains_pin_then_rollback_cleans_up(db):
    """REQUIRED TEST (Theme C): a failed commit RAISES, populates last_error,
    RETAINS the transaction pin (so the follow-up rollback lands on the SAME
    connection), and the rollback then clears the pin."""
    adapter = db._get_adapter()
    original_commit = adapter.commit
    state = {"calls": 0}

    def flaky_commit():
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("simulated commit failure")
        return original_commit()

    adapter.commit = flaky_commit
    try:
        db.start_transaction()
        db.execute("INSERT INTO widget (id, name) VALUES (1, 'x')")
        pin_before = getattr(db._tx_local, "adapter", None)
        assert pin_before is not None, "pin must be set during the transaction"

        with pytest.raises(RuntimeError, match="simulated commit failure"):
            db.commit()

        # last_error captured for get_error().
        assert db.get_error() is not None
        assert "simulated commit failure" in db.get_error()

        # Pin RETAINED on failure so rollback reaches the same connection.
        pin_after = getattr(db._tx_local, "adapter", None)
        assert pin_after is pin_before

        # The follow-up rollback (now that commit is healthy again) cleans up.
        db.rollback()
        assert getattr(db._tx_local, "adapter", None) is None
    finally:
        adapter.commit = original_commit


def test_successful_commit_clears_pin(db):
    """The pin is released on a SUCCESSFUL commit."""
    db.start_transaction()
    assert getattr(db._tx_local, "adapter", None) is not None
    db.execute("INSERT INTO widget (id, name) VALUES (1, 'ok')")
    db.commit()
    assert getattr(db._tx_local, "adapter", None) is None
    assert db.fetch("SELECT * FROM widget").count == 1


def test_rollback_always_clears_pin(db):
    """Rollback is terminal cleanup — it always clears the pin."""
    db.start_transaction()
    db.execute("INSERT INTO widget (id, name) VALUES (1, 'x')")
    db.rollback()
    assert getattr(db._tx_local, "adapter", None) is None
    # The insert was rolled back.
    assert db.fetch("SELECT * FROM widget").count == 0


def test_nested_start_transaction_is_guarded(db):
    """A nested start_transaction() does NOT silently re-begin — it bumps a
    depth counter (with a warning), the inner commit unwinds the depth, and the
    OUTER commit is what actually commits and releases the pin."""
    db.start_transaction()
    assert getattr(db._tx_local, "depth", None) == 1
    pin = getattr(db._tx_local, "adapter", None)

    db.start_transaction()  # nested — guarded
    assert getattr(db._tx_local, "depth", None) == 2
    # Same pin — the nested begin did not rotate to a new connection.
    assert getattr(db._tx_local, "adapter", None) is pin

    db.execute("INSERT INTO widget (id, name) VALUES (1, 'nested')")

    db.commit()  # inner — just unwinds the depth, does NOT release the pin
    assert getattr(db._tx_local, "depth", None) == 1
    assert getattr(db._tx_local, "adapter", None) is pin

    db.commit()  # outer — real commit, releases the pin
    assert getattr(db._tx_local, "depth", None) == 0
    assert getattr(db._tx_local, "adapter", None) is None

    # The write persisted through the single real transaction.
    assert db.fetch("SELECT * FROM widget").count == 1
