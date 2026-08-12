"""ODBC provider contract -- feature 13 (ODBC-DEC-01 provision a REAL ODBC source
+ run the shared write-path fixture through it; ODBC-DEC-02 the latent fixes).

Pins the ODBC write-path behaviours against a REAL ODBC source, no mocks. The
SAME cases are proven in all four frameworks; the shared fixture is
tina4-documentation/plan/v3/fixtures/odbcprovider_contract.json.

ODBC is the generic escape hatch: no single dialect, unreliable last-insert-id.
Its query/CRUD path had NEVER run against a real ODBC source in any language, so
every finding here was latent. The lab provisions unixODBC + the PostgreSQL ODBC
driver (psqlodbc) pointing at the lab's real PostgreSQL, and this suite drives
SELECT/INSERT/UPDATE/DELETE through it.

  * ODBC-PK-STUB: get_columns() reported primary_key=False for every column, so a
    PK-keyed update(table, data) with no explicit filter could not introspect the
    key and threw. Fixed to query the ODBC catalog (SQLPrimaryKeys).
  * ODBC-PY-QUIRKS: execute() ran `SELECT @@IDENTITY` after EVERY statement (a
    SQL-Server-ism) which errored on a non-SQL-Server source and clobbered the
    real affected count; and connect() IGNORED the username/password params.
  * ODBC-FAILLOUD: a fetch on a bad query must RAISE, not swallow to empty.
  * ODBC-NODE-QUIRKS (cross-language lock): a string-WHERE update targets the
    right rows.

Env: TINA4_TEST_ODBC_DSN is the connection-string body (after odbc:///) for a
loopback/trust source; unset -> skip (a machine with no ODBC is the skip case,
not the design). TINA4_TEST_ODBC_AUTH_DSN (a password-protected source, no
UID/PWD in the string) + TINA4_TEST_ODBC_USERNAME/_PASSWORD drive the
credentials case.
"""
import os

import pytest

from tina4_python.database import Database

ODBC_DSN = os.environ.get("TINA4_TEST_ODBC_DSN")
ODBC_AUTH_DSN = os.environ.get("TINA4_TEST_ODBC_AUTH_DSN")
ODBC_USER = os.environ.get("TINA4_TEST_ODBC_USERNAME", "")
ODBC_PASS = os.environ.get("TINA4_TEST_ODBC_PASSWORD", "")

pytestmark = pytest.mark.skipif(
    not ODBC_DSN, reason="TINA4_TEST_ODBC_DSN not set (needs a live ODBC source)"
)


def _db() -> Database:
    return Database("odbc:///" + ODBC_DSN)


def _make_table(db: Database, name: str, pk: str = "id") -> None:
    """A plain table with an explicit INTEGER primary key. ODBC has no reliable
    last-insert-id, so the write-path fixture supplies the key explicitly - which
    is exactly what exercises the PK-catalog introspection."""
    db.execute(f"DROP TABLE IF EXISTS {name}")
    db.execute(f"CREATE TABLE {name} ({pk} INTEGER PRIMARY KEY, name VARCHAR(50))")


# ---- ODBC-DEC-01: SELECT round-trips real rows ---------------------------


def test_a_select_returns_rows():
    db = _db()
    _make_table(db, "odbc_py_select")
    db.insert("odbc_py_select", {"id": 1, "name": "alpha"})
    db.insert("odbc_py_select", {"id": 2, "name": "beta"})
    db.insert("odbc_py_select", {"id": 3, "name": "gamma"})
    result = db.fetch("SELECT id, name FROM odbc_py_select ORDER BY id")
    assert result.count == 3
    assert [r["name"] for r in result.records] == ["alpha", "beta", "gamma"]
    db.close()


# ---- ODBC-PY-QUIRKS: real affected count (no @@IDENTITY clobber) ----------


def test_an_insert_round_trips_on_a_fresh_connection():
    # With the old code `SELECT @@IDENTITY` ran on the same cursor after the
    # INSERT and overwrote rowcount (and errored on PostgreSQL), so affected_rows
    # was wrong. Now the count is read before any secondary query.
    db = _db()
    _make_table(db, "odbc_py_ins1")
    result = db.insert("odbc_py_ins1", {"id": 1, "name": "x"})
    assert result.affected_rows == 1, f"expected 1 affected, got {result.affected_rows}"
    # Durable + keyed, read back on a SECOND fresh connection.
    reader = _db()
    row = reader.fetch_one("SELECT name FROM odbc_py_ins1 WHERE id = ?", [1])
    assert row is not None and row["name"] == "x"
    reader.close()
    db.close()


def test_a_multi_row_update_reports_the_real_affected_count():
    db = _db()
    _make_table(db, "odbc_py_upd")
    for i, nm in enumerate(("a", "b", "c", "d"), start=1):
        db.insert("odbc_py_upd", {"id": i, "name": nm})
    result = db.update("odbc_py_upd", {"name": "Z"}, "id <= ?", [3])
    assert result.affected_rows == 3, f"expected 3 changed, got {result.affected_rows}"
    db.close()


# ---- ODBC-PK-STUB: a PK-keyed update introspects the real PK -------------


def test_a_pk_keyed_update_with_no_filter_works():
    # update(table, data) with the PK in data and NO explicit filter: the guard
    # introspects the PK via the ODBC catalog (was hardcoded False -> threw).
    db = _db()
    _make_table(db, "odbc_py_pk")
    db.insert("odbc_py_pk", {"id": 1, "name": "one"})
    db.insert("odbc_py_pk", {"id": 2, "name": "two"})
    db.update("odbc_py_pk", {"id": 1, "name": "ONE"})
    rows = {r["id"]: r["name"] for r in db.fetch("SELECT id, name FROM odbc_py_pk").records}
    assert rows[1] == "ONE", "the PK-keyed row was not updated"
    assert rows[2] == "two", "a non-matching row was changed"
    db.close()


def test_a_non_id_primary_key_update_works():
    db = _db()
    _make_table(db, "odbc_py_pk2", pk="thing_key")
    db.insert("odbc_py_pk2", {"thing_key": 7, "name": "seven"})
    db.update("odbc_py_pk2", {"thing_key": 7, "name": "SEVEN"})
    row = db.fetch_one("SELECT name FROM odbc_py_pk2 WHERE thing_key = ?", [7])
    assert row is not None and row["name"] == "SEVEN"
    db.close()


# ---- feature 4: a filterless write is guarded ----------------------------


def test_a_filterless_update_is_guarded():
    db = _db()
    _make_table(db, "odbc_py_guard")
    db.insert("odbc_py_guard", {"id": 1, "name": "keep"})
    # No filter AND no PK in data -> refuse, do not overwrite every row.
    with pytest.raises(Exception):
        db.update("odbc_py_guard", {"name": "WIPED"})
    row = db.fetch_one("SELECT name FROM odbc_py_guard WHERE id = ?", [1])
    assert row is not None and row["name"] == "keep", "guard let a filterless update through"
    db.close()


def test_a_filterless_delete_is_guarded():
    db = _db()
    _make_table(db, "odbc_py_guard_del")
    db.insert("odbc_py_guard_del", {"id": 1, "name": "keep"})
    with pytest.raises(Exception):
        db.delete("odbc_py_guard_del")
    assert db.fetch("SELECT id FROM odbc_py_guard_del").count == 1
    db.close()


# ---- ODBC-FAILLOUD: a fetch on a bad query RAISES ------------------------


def test_a_fetch_on_a_bad_query_fails_loud():
    db = _db()
    # A genuinely broken query must RAISE, not swallow to an empty result.
    with pytest.raises(Exception):
        db.fetch("SELECT * FROM odbc_py_table_that_does_not_exist_xyz")
    with pytest.raises(Exception):
        db.fetch_one("SELECT * FROM odbc_py_table_that_does_not_exist_xyz")
    # A good query on the same connection still works (no spurious breakage).
    assert db.fetch_one("SELECT 1 AS one")["one"] == 1
    db.close()


# ---- ODBC-NODE-QUIRKS (cross-language lock): string-WHERE update ----------


def test_a_string_where_update_targets_the_right_rows():
    db = _db()
    _make_table(db, "odbc_py_strwhere")
    for i in range(1, 5):
        db.insert("odbc_py_strwhere", {"id": i, "name": "orig"})
    db.update("odbc_py_strwhere", {"name": "Z"}, "id <= ?", [3])
    rows = {r["id"]: r["name"] for r in db.fetch("SELECT id, name FROM odbc_py_strwhere").records}
    assert rows[1] == "Z" and rows[2] == "Z" and rows[3] == "Z"
    assert rows[4] == "orig", "the string WHERE clause changed the wrong rows"
    db.close()


# ---- ODBC-PY-QUIRKS: credentials are honoured ----------------------------


@pytest.mark.skipif(
    not (ODBC_AUTH_DSN and ODBC_USER and ODBC_PASS),
    reason="TINA4_TEST_ODBC_AUTH_DSN / _USERNAME / _PASSWORD not set",
)
def test_credentials_passed_as_params_are_honoured():
    # The connection string carries NO UID/PWD; the creds arrive only as params.
    # connect() used to ignore them -> the password-protected source would reject
    # the connection. Honoured -> it connects and a SELECT works.
    db = Database("odbc:///" + ODBC_AUTH_DSN, ODBC_USER, ODBC_PASS)
    assert db.fetch_one("SELECT 1 AS one")["one"] == 1
    db.close()


@pytest.mark.skipif(
    not (ODBC_AUTH_DSN and ODBC_USER),
    reason="TINA4_TEST_ODBC_AUTH_DSN / _USERNAME not set",
)
def test_a_wrong_password_fails_loud():
    with pytest.raises(Exception):
        Database("odbc:///" + ODBC_AUTH_DSN, ODBC_USER, "definitely-the-wrong-password")
