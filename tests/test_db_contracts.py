"""Database contract tests - the behaviours apps depend on, locked against drift.

Named after the contracts a real upgrade relies on (and that a silent regression
like the 3.13.37 `execute` change - raise -> return False - would have broken):

  * execute() RAISES on a SQL error (never silently returns False), so a failing
    write propagates and a transaction rolls back.
  * read-after-write within a request is consistent (the request-scoped cache is
    off by default and never serves a pre-write value).
  * get_next_id() is strictly monotonic + unique across repeated calls (no
    duplicate keys from a cached MAX(id)).
  * transactions bracket correctly: commit persists, rollback discards.

These run against a real SQLite database. They are engine-agnostic in intent -
the same contracts are mirrored in the PHP/Ruby/Node suites.
"""
import pytest

from tina4_python.database import Database


@pytest.fixture
def db():
    d = Database("sqlite:///:memory:")
    d.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, qty INTEGER)")
    return d


class TestExecuteRaises:
    def test_bad_sql_raises_not_returns_false(self, db):
        with pytest.raises(Exception):
            db.execute("INSERT INTO does_not_exist (x) VALUES (1)")

    def test_cause_captured_on_get_error(self, db):
        try:
            db.execute("THIS IS NOT VALID SQL")
        except Exception:
            pass
        assert db.get_error()  # the real cause is still readable after the raise

    def test_constraint_violation_raises(self, db):
        db.execute("INSERT INTO items (id, name) VALUES (1, 'a')")
        with pytest.raises(Exception):
            db.execute("INSERT INTO items (id, name) VALUES (1, 'dup')")  # duplicate PK

    def test_successful_write_is_truthy(self, db):
        result = db.execute("INSERT INTO items (name, qty) VALUES ('a', 1)")
        assert result  # never False on success


class TestReadAfterWrite:
    def test_insert_is_immediately_visible(self, db):
        db.execute("INSERT INTO items (name, qty) VALUES ('widget', 5)")
        row = db.fetch_one("SELECT name, qty FROM items WHERE name = ?", ["widget"])
        assert row["qty"] == 5

    def test_update_is_immediately_visible(self, db):
        db.execute("INSERT INTO items (id, name, qty) VALUES (1, 'a', 1)")
        db.execute("UPDATE items SET qty = 99 WHERE id = 1")
        assert db.fetch_one("SELECT qty FROM items WHERE id = 1")["qty"] == 99

    def test_max_id_reflects_latest_write(self, db):
        for i in range(1, 6):
            db.execute("INSERT INTO items (id, name) VALUES (?, ?)", [i, f"n{i}"])
            mx = db.fetch_one("SELECT MAX(id) AS m FROM items")["m"]
            assert mx == i  # no stale pre-write MAX from a request cache


class TestGeneratorMonotonicity:
    def test_get_next_id_strictly_increasing_and_unique(self, db):
        ids = [db.get_next_id("orders") for _ in range(50)]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)  # no duplicates
        assert all(b - a == 1 for a, b in zip(ids, ids[1:]))  # contiguous

    def test_independent_sequences_per_table(self, db):
        a = db.get_next_id("table_a")
        b = db.get_next_id("table_b")
        assert a == b == 1  # separate counters, both start fresh


class TestTransactionBracketing:
    def test_commit_persists(self, db):
        db.start_transaction()
        db.execute("INSERT INTO items (name) VALUES ('kept')")
        db.commit()
        assert db.fetch_one("SELECT count(*) AS c FROM items WHERE name='kept'")["c"] == 1

    def test_rollback_discards(self, db):
        db.execute("INSERT INTO items (name) VALUES ('before')")
        db.start_transaction()
        db.execute("INSERT INTO items (name) VALUES ('rolled')")
        db.rollback()
        assert db.fetch_one("SELECT count(*) AS c FROM items WHERE name='rolled'")["c"] == 0
        assert db.fetch_one("SELECT count(*) AS c FROM items WHERE name='before'")["c"] == 1

    def test_failed_write_in_txn_can_roll_back(self, db):
        db.start_transaction()
        db.execute("INSERT INTO items (id, name) VALUES (1, 'a')")
        try:
            db.execute("INSERT INTO items (id, name) VALUES (1, 'dup')")  # raises
        except Exception:
            db.rollback()
        assert db.fetch_one("SELECT count(*) AS c FROM items")["c"] == 0
