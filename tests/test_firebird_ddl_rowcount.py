"""Firebird DDL must not crash on the affected-row-count read (regression).

Found by running the real adapter against a LIVE Firebird 5: every DDL
statement (CREATE / DROP / ALTER TABLE) blew up in ``FirebirdAdapter.execute``
at the affected-row-count read. The modern ``firebird-driver`` answers
``cursor.rowcount`` by probing ``get_info(StmtInfoCode.RECORDS)`` on the
cursor, and a DDL statement has no row count, so the server returns an error
response and the driver raises::

    firebird.driver.types.InterfaceError: Result code does not match request code

Reading ``cursor.rowcount`` unconditionally therefore raised on EVERY
``CREATE TABLE`` -- which is exactly what the live-Firebird test fixtures,
``create_table()`` and the migration runner all do first, so the whole
Firebird surface hung/errored. The fix guards the read: DDL (and anything else
without a countable result) yields 0 affected rows instead of raising.

The bug is Python-only. PHP wraps ``ibase_affected_rows`` in try/catch, and
Ruby/Node read the driver's execute return value rather than probing a
separate rowcount, so none of the other three raise on DDL -- verified by
reading each adapter. This regression therefore lives only here.

Needs a real Firebird (no doubles): gated on TINA4_TEST_FIREBIRD_URL.
"""

import os

import pytest

_FB_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


@pytest.mark.skipif(
    not _FB_URL,
    reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)
class TestFirebirdDdlRowcount:
    """Real Firebird. Exercises the exact line the InterfaceError came out of."""

    @pytest.fixture
    def adapter(self):
        from tina4_python.database import Database

        db = Database(_FB_URL, "SYSDBA", "masterkey")
        adapter = db._get_adapter()
        for stmt in ("DROP TABLE ddl_rc_probe",):
            try:
                adapter.execute(stmt)
            except Exception:  # noqa: BLE001 - first run has nothing to drop
                pass
        yield adapter
        try:
            adapter.execute("DROP TABLE ddl_rc_probe")
        except Exception:  # noqa: BLE001
            pass
        db.close()

    def test_create_table_does_not_raise_and_reports_zero_affected(self, adapter):
        # THE regression: pre-fix this raised InterfaceError at cursor.rowcount.
        result = adapter.execute(
            "CREATE TABLE ddl_rc_probe ("
            "  id INTEGER NOT NULL, "
            "  name VARCHAR(20), "
            "  PRIMARY KEY (id)"
            ")"
        )
        # A DDL statement has no row count -- it must degrade to 0, not blow up.
        assert result.affected_rows == 0

    def test_insert_after_ddl_still_counts_one_affected_row(self, adapter):
        # Positive control: guarding the rowcount read must NOT blind the count
        # for a real write. A single-row INSERT still reports affected_rows == 1,
        # proving the DML path the guard sits in front of is intact.
        adapter.execute(
            "CREATE TABLE ddl_rc_probe ("
            "  id INTEGER NOT NULL, "
            "  name VARCHAR(20), "
            "  PRIMARY KEY (id)"
            ")"
        )
        result = adapter.execute(
            "INSERT INTO ddl_rc_probe (id, name) VALUES (?, ?)", [1, "alice"]
        )
        assert result.affected_rows == 1

    def test_drop_table_does_not_raise_and_reports_zero_affected(self, adapter):
        # DROP is DDL too -- same guarded path, same no-raise / zero-count contract.
        adapter.execute(
            "CREATE TABLE ddl_rc_probe (id INTEGER NOT NULL, PRIMARY KEY (id))"
        )
        result = adapter.execute("DROP TABLE ddl_rc_probe")
        assert result.affected_rows == 0
