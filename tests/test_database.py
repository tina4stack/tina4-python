# Tests for tina4_python.database
import os
import pytest
from tina4_python.database import Database, DatabaseResult


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite database for each test — autocommit OFF (default)."""
    db_path = tmp_path / "test.db"
    d = Database(f"sqlite:///{db_path}")
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, active INTEGER DEFAULT 1)")
    d.commit()  # Explicit commit — no autocommit by default
    yield d
    d.close()


@pytest.fixture
def db_autocommit(tmp_path):
    """Fresh SQLite database with autocommit ON."""
    db_path = tmp_path / "autocommit.db"
    d = Database(f"sqlite:///{db_path}")
    d.autocommit = True
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, active INTEGER DEFAULT 1)")
    yield d
    d.close()


class TestDatabaseResult:
    """Positive tests for DatabaseResult."""

    def test_iterate(self):
        r = DatabaseResult(records=[{"id": 1}, {"id": 2}], count=2)
        assert list(r) == [{"id": 1}, {"id": 2}]

    def test_len(self):
        r = DatabaseResult(records=[{"id": 1}], count=1)
        assert len(r) == 1

    def test_bool_success(self):
        r = DatabaseResult()
        assert bool(r) is True

    def test_bool_error(self):
        r = DatabaseResult(error="Something failed")
        assert bool(r) is False

    def test_to_paginate(self):
        r = DatabaseResult(records=[{"id": 1}], count=50)
        p = r.to_paginate(page=2, per_page=10)
        assert p["total"] == 50
        assert p["page"] == 2
        assert p["total_pages"] == 5
        assert p["page"] == 2
        assert p["per_page"] == 10


class TestSQLiteAdapter:
    """Positive tests for SQLite database operations (autocommit OFF)."""

    def test_insert_and_fetch_one(self, db):
        db.insert("users", {"name": "Alice", "email": "alice@test.com"})
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Alice"])
        assert row is not None
        assert row["name"] == "Alice"
        assert row["email"] == "alice@test.com"

    def test_insert_returns_last_id(self, db):
        result = db.insert("users", {"name": "Bob"})
        assert result.last_id == 1
        result2 = db.insert("users", {"name": "Eve"})
        assert result2.last_id == 2
        db.commit()

    def test_fetch_pagination(self, db):
        for i in range(25):
            db.insert("users", {"name": f"User{i}"})
        db.commit()
        result = db.fetch("SELECT * FROM users", limit=10, offset=0)
        assert len(result.records) == 10
        assert result.count == 25

    def test_fetch_page_2(self, db):
        for i in range(25):
            db.insert("users", {"name": f"User{i}"})
        db.commit()
        result = db.fetch("SELECT * FROM users", limit=10, offset=10)
        assert len(result.records) == 10
        assert result.records[0]["name"] == "User10"

    def test_update(self, db):
        db.insert("users", {"name": "Alice"})
        db.commit()
        db.update("users", {"name": "Alice Updated"}, "name = ?", ["Alice"])
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE id = ?", [1])
        assert row["name"] == "Alice Updated"

    def test_delete(self, db):
        db.insert("users", {"name": "ToDelete"})
        db.commit()
        db.delete("users", "name = ?", ["ToDelete"])
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["ToDelete"])
        assert row is None

    def test_table_exists(self, db):
        assert db.table_exists("users") is True

    def test_get_tables(self, db):
        tables = db.get_tables()
        assert "users" in tables

    def test_get_columns(self, db):
        cols = db.get_columns("users")
        names = [c["name"] for c in cols]
        assert "id" in names
        assert "name" in names
        assert "email" in names

    def test_transaction_commit(self, db):
        db.start_transaction()
        db.insert("users", {"name": "Committed"})
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Committed"])
        assert row is not None

    def test_transaction_rollback(self, db):
        db.insert("users", {"name": "Before"})
        db.commit()
        db.start_transaction()
        db.insert("users", {"name": "RolledBack"})
        db.rollback()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["RolledBack"])
        assert row is None
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Before"])
        assert row is not None

    def test_database_type(self, db):
        assert db.get_database_type() == "sqlite"

    def test_no_autocommit_by_default(self, db):
        """Without autocommit, uncommitted writes are lost on close."""
        assert db.autocommit is False
        db.insert("users", {"name": "Uncommitted"})
        # Don't commit — data should be visible in same connection...
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Uncommitted"])
        assert row is not None  # visible in same transaction
        # ...but the point is: no silent auto-commit happened

    def test_explicit_commit_persists(self, db):
        """Explicit commit() makes data durable."""
        db.insert("users", {"name": "Persisted"})
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Persisted"])
        assert row is not None


class TestAutocommitEnabled:
    """Tests with autocommit ON (via programmatic toggle)."""

    def test_autocommit_flag(self, db_autocommit):
        assert db_autocommit.autocommit is True

    def test_autocommit_persists_without_explicit_commit(self, db_autocommit):
        db_autocommit.insert("users", {"name": "AutoCommitted"})
        # No explicit commit() call
        row = db_autocommit.fetch_one("SELECT * FROM users WHERE name = ?", ["AutoCommitted"])
        assert row is not None

    def test_autocommit_env_var(self, tmp_path):
        """TINA4_AUTOCOMMIT=true enables autocommit via .env."""
        os.environ["TINA4_AUTOCOMMIT"] = "true"
        try:
            db_path = tmp_path / "env_test.db"
            d = Database(f"sqlite:///{db_path}")
            assert d.autocommit is True
            d.close()
        finally:
            del os.environ["TINA4_AUTOCOMMIT"]


class TestSQLiteAdapterNegative:
    """Negative tests for SQLite database operations."""

    def test_table_not_exists(self, db):
        assert db.table_exists("nonexistent") is False

    def test_fetch_one_no_results(self, db):
        row = db.fetch_one("SELECT * FROM users WHERE id = ?", [9999])
        assert row is None

    def test_fetch_empty_table(self, db):
        result = db.fetch("SELECT * FROM users")
        assert result.count == 0
        assert result.records == []

    def test_invalid_sql(self, db):
        result = db.execute("INVALID SQL STATEMENT")
        assert result is False


class TestDatabaseURL:
    """Test DATABASE_URL parsing."""

    def test_sqlite_url(self, tmp_path):
        db_path = tmp_path / "url_test.db"
        db = Database(f"sqlite:///{db_path}")
        db.execute("CREATE TABLE t (id INTEGER)")
        assert db.table_exists("t")
        db.close()

    def test_invalid_driver(self):
        with pytest.raises(ValueError, match="Unknown database driver"):
            Database("fakedb://localhost/test")


class TestSQLiteConnectionPath:
    """``sqlite:///X`` must resolve relative to the project root (cwd),
    matching the documented convention and the PHP implementation. Absolute
    paths use four slashes (``sqlite:////abs/path``) or a Windows drive
    letter (``sqlite:///C:/Users/app.db``). The directory auto-creation
    must NEVER reach outside cwd — that was the root cause of the
    ``Read-only file system: '/data'`` crash on macOS.

    These tests exercise ``_connection_path`` without opening a real
    connection (the constructor path depends on whether the resolved
    path is writable), by building a stand-in object that owns just the
    ``url`` attribute and binding the method."""

    def _resolve(self, url: str) -> str:
        ns = type("DatabaseStub", (), {"url": url})()
        return Database._connection_path(ns)

    def test_relative_bare_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert self._resolve("sqlite:///app.db") == os.path.join(str(tmp_path), "app.db")

    def test_relative_subdir_bruce_case(self, tmp_path, monkeypatch):
        # The exact string bruceproject had in its .env that used to
        # crash with `Read-only file system: '/data'`.
        monkeypatch.chdir(tmp_path)
        resolved = self._resolve("sqlite:///data/app.db")
        # Normalise both sides — _connection_path stitches the URL "data/app.db"
        # onto cwd with raw "/", leaving mixed separators on Windows; the
        # logical path is what matters.
        assert os.path.normpath(resolved) == os.path.normpath(
            os.path.join(str(tmp_path), "data", "app.db")
        )
        # Subdir auto-created under cwd
        assert os.path.isdir(os.path.join(str(tmp_path), "data"))

    def test_relative_with_dot_prefix(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        resolved = self._resolve("sqlite:///./data/app.db")
        assert os.path.dirname(resolved).endswith("data")

    def test_absolute_unix(self, tmp_path):
        # On POSIX, /tmp/.../absolute.db → sqlite:////tmp/.../absolute.db
        # On Windows the four-slash form encodes a UNIX-shape path (which
        # cannot exist as a Windows drive); skip there. Windows absolute
        # paths use the test_absolute_windows_drive_letter form instead.
        import sys
        if sys.platform.startswith("win"):
            pytest.skip("four-slash absolute form is POSIX-shaped; Windows uses drive-letter form")
        abs_path = str(tmp_path / "absolute.db")
        # Build the four-slash form
        url = f"sqlite:////{abs_path.lstrip('/')}"
        assert self._resolve(url) == abs_path

    def test_absolute_windows_drive_letter(self, tmp_path, monkeypatch):
        # urlparse("sqlite:///C:/Users/app.db").path == "/C:/Users/app.db"
        # Strip one "/" → "C:/Users/app.db" which is_windows_abs=True.
        monkeypatch.chdir(tmp_path)
        assert self._resolve("sqlite:///C:/Users/app.db") == "C:/Users/app.db"

    def test_in_memory_short_form(self):
        assert self._resolve("sqlite::memory:") == ":memory:"

    def test_in_memory_url_form(self):
        assert self._resolve("sqlite:///:memory:") == ":memory:"

    def test_does_not_create_dirs_outside_cwd(self, tmp_path, monkeypatch):
        """Regression guard: the bug that crashed ``tina4 migrate``
        tried to ``os.makedirs('/data')`` on macOS (read-only root).
        Absolute paths must NOT auto-create parent dirs outside cwd."""
        monkeypatch.chdir(tmp_path)
        resolved = self._resolve("sqlite:////does/not/exist/app.db")
        assert resolved == "/does/not/exist/app.db"
        assert not os.path.exists("/does")


class TestProjectFolders:
    """Project-structure audit: ``src/migrations`` must NOT be auto-created.
    The canonical migrations directory lives at the project root (matches
    the CLI's default and the documented layout)."""

    def test_migrations_root_not_src_migrations(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tina4_python.core.server import _ensure_folders
        _ensure_folders()
        assert (tmp_path / "migrations").is_dir(), "project-root migrations/ must exist"
        assert not (tmp_path / "src" / "migrations").exists(), (
            "src/migrations must NOT be auto-created — migrations live at the project root"
        )


class TestPoolTransactionAtomicity:
    """Regression tests for the pool round-robin transaction bug.

    Before the adapter-pin fix, every Database method call rotated to a
    different pooled connection. Result: start_transaction() pinned a flag
    on adapter A, the executes autocommitted on adapters B and C, and the
    final commit/rollback landed on adapter D — meaningless. Rollbacks
    were silently no-op'd and writes leaked through.

    These tests fail (3 rows leaking despite rollback) before the
    _tx_local pin in Database._get_adapter() and pass after it.
    """

    @pytest.fixture
    def pooled_db(self, tmp_path):
        path = tmp_path / "pool.db"
        d = Database(f"sqlite:///{path}", pool=4)
        d.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        d.commit()
        yield d
        d.close()

    def test_rollback_undoes_inserts_under_pool(self, pooled_db):
        """rollback() must actually undo every insert, even with pool>0."""
        pooled_db.start_transaction()
        pooled_db.execute("INSERT INTO t (id, val) VALUES (1, 'a')")
        pooled_db.execute("INSERT INTO t (id, val) VALUES (2, 'b')")
        pooled_db.execute("INSERT INTO t (id, val) VALUES (3, 'c')")
        pooled_db.rollback()

        n = pooled_db.fetch_one("SELECT count(*) AS n FROM t")["n"]
        assert n == 0, (
            f"rollback() leaked {n} of 3 rows under pool=4 — adapter pin not honoured"
        )

    def test_commit_persists_inserts_under_pool(self, pooled_db):
        """commit() must persist every insert as one atomic batch."""
        pooled_db.start_transaction()
        pooled_db.execute("INSERT INTO t (id, val) VALUES (10, 'x')")
        pooled_db.execute("INSERT INTO t (id, val) VALUES (20, 'y')")
        pooled_db.execute("INSERT INTO t (id, val) VALUES (30, 'z')")
        pooled_db.commit()

        n = pooled_db.fetch_one("SELECT count(*) AS n FROM t")["n"]
        assert n == 3, f"commit() persisted only {n} of 3 rows under pool=4"

    def test_pin_releases_after_commit(self, pooled_db):
        """After commit(), _get_adapter() must round-robin again."""
        pooled_db.start_transaction()
        pinned_during = pooled_db._get_adapter()
        pooled_db.commit()

        # After commit, the next call should NOT be pinned to the same adapter.
        # Round-robin should resume.
        seen = set()
        for _ in range(8):
            seen.add(id(pooled_db._get_adapter()))
        assert len(seen) > 1, (
            "after commit() the pin was not released — _get_adapter() never rotated"
        )

    def test_pin_releases_after_rollback(self, pooled_db):
        """After rollback(), _get_adapter() must round-robin again."""
        pooled_db.start_transaction()
        pooled_db.rollback()

        seen = set()
        for _ in range(8):
            seen.add(id(pooled_db._get_adapter()))
        assert len(seen) > 1, (
            "after rollback() the pin was not released — _get_adapter() never rotated"
        )

    def test_no_pool_no_regression(self, tmp_path):
        """Single-connection mode (pool=0) must still work correctly — the
        pin code path should be a no-op when there's no pool to fight."""
        path = tmp_path / "nopool.db"
        d = Database(f"sqlite:///{path}", pool=0)
        d.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        d.commit()

        d.start_transaction()
        d.execute("INSERT INTO t (id, val) VALUES (1, 'r')")
        d.rollback()
        n = d.fetch_one("SELECT count(*) AS n FROM t")["n"]
        d.close()
        assert n == 0, f"pool=0 broke after the pin fix: {n} rows leaked"
