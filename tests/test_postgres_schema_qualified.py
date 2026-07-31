"""Regression test for issue #48 — schema-qualified PostgreSQL tables.

A model whose ``table_name`` is ``"gift_cards.gift_card"`` lives in the
``gift_cards`` schema, not ``public``. The ORM builds correct
schema-qualified SQL for reads (``SELECT * FROM gift_cards.gift_card ...``),
but the adapter's introspection was hardcoded to ``schemaname = 'public'``
and matched the whole dotted string as a flat table name:

    table_exists("gift_cards.gift_card")  -> False   (always)
    get_tables()                          -> []      (non-public invisible)
    get_columns("gift_cards.gift_card")   -> []      (schema ignored)

So ``create_table()`` believed the table didn't exist and misfired, and
ORM introspection couldn't see a table in a non-public schema. Verified
against Schalk's live ``giftcards`` Postgres container.

This test boots a real PostgreSQL (env-configurable, default
localhost:55432) and skips automatically when it isn't reachable, so CI
without postgres just no-ops. The ``_split_schema`` unit test always runs.
"""
from __future__ import annotations

import os
import socket
import pytest

from tina4_python.database.postgres import PostgreSQLAdapter as PostgresAdapter

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


# ── Pure unit — always runs (no PG needed) ──────────────────────────


class TestSplitSchema:
    def test_bare_name_has_no_schema(self):
        assert PostgresAdapter._split_schema("users") == (None, "users")

    def test_schema_qualified(self):
        assert PostgresAdapter._split_schema("gift_cards.gift_card") == ("gift_cards", "gift_card")

    def test_splits_on_first_dot(self):
        # schema.table — first dot wins
        assert PostgresAdapter._split_schema("a.b") == ("a", "b")


# ── SQLite attached-database qualification — always runs ────────────
# SQLite's "schema" is an ATTACH alias; this needs no external server, so
# it gives the schema-qualified path real CI coverage on every run.


class TestSqliteAttachedSchema:
    @pytest.fixture
    def db(self, tmp_path):
        from tina4_python.database import Database
        main = tmp_path / "main.db"
        att = tmp_path / "att.db"
        db = Database(f"sqlite:///{main}")
        db.execute(f"ATTACH DATABASE '{att}' AS extra")
        db.execute("CREATE TABLE extra.widget (id INTEGER PRIMARY KEY, name TEXT, is_deleted INTEGER DEFAULT 0)")
        db.execute("CREATE TABLE local_only (id INTEGER PRIMARY KEY)")
        yield db
        try:
            db.close()
        except Exception:
            pass

    def test_table_exists_attached(self, db):
        assert db.table_exists("extra.widget") is True

    def test_table_exists_attached_absent(self, db):
        assert db.table_exists("extra.nope") is False

    def test_table_exists_bare_still_works(self, db):
        assert db.table_exists("local_only") is True

    def test_get_columns_attached(self, db):
        cols = db.get_columns("extra.widget")
        names = [c["name"] for c in cols]
        assert names == ["id", "name", "is_deleted"]
        assert any(c["primary_key"] for c in cols if c["name"] == "id")


# ── Integration — skipped without a live PostgreSQL ─────────────────

pytestmark_integration = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT}",
)


@pytestmark_integration
class TestSchemaQualifiedIntrospection:
    SCHEMA = "tina4_issue48"
    TABLE = "widget"

    @pytest.fixture
    def db(self):
        from tina4_python.database import Database
        db = Database(
            f"postgres://{PG_HOST}:{PG_PORT}/{PG_DB}",
            username=PG_USER,
            password=PG_PASS,
        )
        db.execute(f"DROP SCHEMA IF EXISTS {self.SCHEMA} CASCADE")
        db.execute(f"CREATE SCHEMA {self.SCHEMA}")
        db.execute(
            f"CREATE TABLE {self.SCHEMA}.{self.TABLE} "
            f"(id SERIAL PRIMARY KEY, name VARCHAR(50), is_deleted INTEGER DEFAULT 0)"
        )
        db.commit()
        yield db
        try:
            db.execute(f"DROP SCHEMA IF EXISTS {self.SCHEMA} CASCADE")
            db.commit()
            db.close()
        except Exception:
            pass

    def test_table_exists_finds_schema_qualified(self, db):
        assert db.table_exists(f"{self.SCHEMA}.{self.TABLE}") is True, (
            "#48: table_exists must find a table in a non-public schema"
        )

    def test_table_exists_false_for_absent(self, db):
        assert db.table_exists(f"{self.SCHEMA}.nope") is False

    def test_table_exists_false_for_bare_non_public(self, db):
        # bare name resolves via search_path (public) — not found there
        assert db.table_exists(self.TABLE) is False

    def test_get_columns_sees_schema_table(self, db):
        cols = db.get_columns(f"{self.SCHEMA}.{self.TABLE}")
        names = [c["name"] for c in cols]
        assert "id" in names and "name" in names and "is_deleted" in names
        assert any(c["primary_key"] for c in cols if c["name"] == "id")

    def test_get_tables_lists_schema_qualified(self, db):
        tables = db.get_tables()
        assert f"{self.SCHEMA}.{self.TABLE}" in tables, (
            "#48: get_tables must surface non-public tables, schema-qualified"
        )

    def test_read_path_still_works(self, db):
        # The reporter's query path — schema-qualified SELECT with the
        # framework's appended LIMIT/OFFSET — must run cleanly.
        result = db.fetch(
            f"SELECT * FROM {self.SCHEMA}.{self.TABLE} WHERE is_deleted = 0", limit=5
        )
        assert result.count == 0
        assert db.get_error() is None
