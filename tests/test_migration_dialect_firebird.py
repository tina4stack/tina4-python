"""Real Firebird coverage for the migration-dialect fix.

The scaffolding used to emit SQLite-only DDL (``TEXT``, ``REAL``,
``CREATE TABLE IF NOT EXISTS``) that Firebird rejects (-607 on ``TEXT``). The fix
is two parts, both exercised here:

  * the generator emits portable canonical types (``VARCHAR(255)`` for strings,
    ``TIMESTAMP`` for datetimes), and
  * ``SQLTranslator.ddl_types`` completes the apply-time translation so ``TEXT``
    -> ``BLOB SUB_TYPE TEXT``, ``REAL`` -> ``DOUBLE PRECISION``, and
    ``IF NOT EXISTS`` is stripped on Firebird (and ``TIMESTAMP`` -> the right
    datetime type on MSSQL/MySQL).

No mocks: the round-trip runs against a LIVE Firebird (``TINA4_TEST_FIREBIRD_URL``)
and applies the REALLY-generated migration DDL, then inserts and reads a row. The
translation-unit tests are pure functions over strings (no dependency, no double).
"""
import glob
import os
from pathlib import Path

import pytest

from tina4_python.database.sql_translator import SQLTranslator

FB_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


def _generated_create_sql(tmp_path: Path) -> str:
    """Run the REAL migration generator and return its CREATE TABLE statement."""
    from tina4_python.cli import _gen_migration

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        _gen_migration(
            "create_dialect_probe",
            {"fields": "name:string,bio:text,price:float,active:bool,due:datetime"},
        )
    finally:
        os.chdir(cwd)
    up = [f for f in glob.glob(str(tmp_path / "migrations" / "*.sql")) if "down" not in f][0]
    body = Path(up).read_text(encoding="utf-8")
    # The generator writes exactly one CREATE TABLE per up-file.
    return next(s for s in body.split(";") if "CREATE TABLE" in s.upper())


class TestDdlTypesTranslationPure:
    """Pure-function translation — the DRY core that fixes migrations AND
    ORM.create_table AND hand-written DDL."""

    RAW = ("CREATE TABLE IF NOT EXISTS t (\n"
           "  id INTEGER PRIMARY KEY,\n"
           "  bio TEXT,\n"
           "  price REAL,\n"
           "  due TIMESTAMP\n)")

    def test_firebird_maps_text_real_and_strips_if_not_exists(self):
        out = SQLTranslator.ddl_types(self.RAW, "firebird")
        assert "IF NOT EXISTS" not in out
        assert "BLOB SUB_TYPE TEXT" in out
        assert "DOUBLE PRECISION" in out
        # No bare TEXT/REAL survive (BLOB SUB_TYPE TEXT is not a bare TEXT).
        assert out.upper().count("TEXT") == out.upper().count("SUB_TYPE TEXT")
        assert " REAL" not in out.upper()

    def test_mssql_strips_if_not_exists_and_maps_timestamp(self):
        out = SQLTranslator.ddl_types(self.RAW, "mssql")
        assert "IF NOT EXISTS" not in out
        assert "DATETIME2" in out and "TIMESTAMP" not in out.upper()

    def test_mysql_maps_timestamp_to_datetime(self):
        out = SQLTranslator.ddl_types(self.RAW, "mysql")
        assert "DATETIME" in out.upper() and "TIMESTAMP" not in out.upper()

    def test_is_ddl_gated_a_select_is_never_rewritten(self):
        # A query that merely mentions the word TEXT/REAL must pass through
        # unchanged — type translation applies to DDL only.
        q = "SELECT id, note FROM t WHERE kind = 'TEXT' AND ratio > 0.5"
        assert SQLTranslator.ddl_types(q, "firebird") == q

    def test_leading_comments_do_not_defeat_the_gate(self):
        # Migration files prefix the CREATE with `-- ...` comment lines.
        commented = "-- Migration: x\n-- Created: now\n\n" + self.RAW
        out = SQLTranslator.ddl_types(commented, "firebird")
        assert "BLOB SUB_TYPE TEXT" in out and "IF NOT EXISTS" not in out


class TestGeneratorPortableTypes:
    def test_generator_emits_portable_types(self, tmp_path):
        sql = _generated_create_sql(tmp_path)
        assert "name VARCHAR(255)" in sql
        assert "name TEXT" not in sql          # not SQLite-only TEXT
        assert "created_at TIMESTAMP" in sql
        assert "created_at TEXT" not in sql    # Firebird -607 guard


@pytest.mark.skipif(not FB_URL, reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)")
class TestFirebirdLiveRoundTrip:
    """The REAL proof: the generated migration DDL applies on a live Firebird and
    a row round-trips — where the old TEXT/REAL/IF NOT EXISTS DDL raised -607."""

    def _db(self):
        from tina4_python.database import Database

        return Database(FB_URL, "SYSDBA", "masterkey")

    def test_generated_migration_applies_and_row_round_trips(self, tmp_path):
        sql = _generated_create_sql(tmp_path)
        db = self._db()
        try:
            db.execute("DROP TABLE dialect_probe")
        except Exception:  # noqa: BLE001 - first run has nothing to drop
            pass
        # db.execute() runs the adapter's _translate_sql -> ddl_types, so the
        # SQLite-canonical generated DDL is made Firebird-legal on the way in.
        db.execute(sql)
        try:
            db.execute(
                "INSERT INTO dialect_probe (id, name, bio, price, active, due) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [1, "Alice", "a long bio", 9.99, 1, "2026-01-02 03:04:05"],
            )
            row = db.fetch_one("SELECT id, name, bio, price FROM dialect_probe WHERE id = ?", [1])
            assert row is not None
            assert row["name"] == "Alice"
            assert row["bio"] == "a long bio"        # BLOB SUB_TYPE TEXT round-trip
            assert abs(float(row["price"]) - 9.99) < 1e-6   # DOUBLE PRECISION round-trip
        finally:
            try:
                db.execute("DROP TABLE dialect_probe")
            except Exception:  # noqa: BLE001
                pass
