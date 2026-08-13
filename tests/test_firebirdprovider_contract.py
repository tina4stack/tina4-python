"""Firebird provider contract -- feature 12 (FB-DEC-01/02/03).

Pins the Firebird write-path + resilience behaviours against a REAL Firebird 5,
no mocks. The SAME cases are proven in all four frameworks; the shared fixture is
tina4-documentation/plan/v3/fixtures/firebirdprovider_contract.json.

  * FB-DEC-02: db.insert() returns the GENERATOR-assigned last-id (non-`id` PK
    too); update/delete report the REAL affected count.
  * FB-DEC-03: a binary blob round-trips byte-for-byte.
  * FB-DEC-01: a forced server-side disconnect transparently reconnects; a
    logical SQL error does NOT.

Firebird has no generic last_insert_id, so each table is created with a
GEN_<TABLE>_ID generator + a BEFORE INSERT trigger -- the real Firebird idiom the
adapter derives the last-id from. TINA4_TEST_FIREBIRD_URL unset -> skip (a
machine with no Firebird is the skip case, not the design). Firebird is excluded
from the require-services gate, so a skip here stays green.
"""
import os

import pytest

from tina4_python.database import Database
from tina4_python.database.firebird import FirebirdAdapter

FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")

pytestmark = pytest.mark.skipif(
    not FIREBIRD_URL, reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)"
)

# A binary payload that a naive text decode or an unread blob handle corrupts:
# a NUL byte, high bytes 0xFD..0xFF, an embedded NUL, and ASCII.
BLOB = bytes([0, 1, 2, 253, 254, 255, 65, 66, 0, 67])


def _db() -> Database:
    return Database(FIREBIRD_URL)


def _drop(db: Database, name: str) -> None:
    for stmt in (
        f"DROP TRIGGER {name}_bi",
        f"DROP TABLE {name}",
        f"DROP GENERATOR gen_{name}_id",
    ):
        try:
            db.execute(stmt)
        except Exception:
            pass


def _make_table(db: Database, name: str, pk: str = "id", extra: str = "") -> None:
    """A table whose PK is assigned by a GEN_<TABLE>_ID generator via a BEFORE
    INSERT trigger -- the real Firebird auto-key idiom."""
    _drop(db, name)
    cols = f"{pk} INTEGER NOT NULL PRIMARY KEY, name VARCHAR(50)"
    if extra:
        cols += f", {extra}"
    db.execute(f"CREATE TABLE {name} ({cols})")
    db.execute(f"CREATE GENERATOR gen_{name}_id")
    db.execute(
        f"CREATE TRIGGER {name}_bi FOR {name} ACTIVE BEFORE INSERT POSITION 0 "
        f"AS BEGIN IF (NEW.{pk} IS NULL) THEN NEW.{pk} = GEN_ID(gen_{name}_id, 1); END"
    )


# ---- FB-DEC-02: generator last-id ---------------------------------------


def test_an_insert_returns_the_generator_last_id():
    db = _db()
    _make_table(db, "fbc_gen")
    result = db.insert("fbc_gen", {"name": "alpha"})
    assert result.last_id == 1, f"expected generator id 1, got {result.last_id!r}"
    db.close()


def test_a_second_insert_returns_the_next_generated_id():
    db = _db()
    _make_table(db, "fbc_gen2")
    first = db.insert("fbc_gen2", {"name": "a"})
    second = db.insert("fbc_gen2", {"name": "b"})
    assert first.last_id == 1
    assert second.last_id == 2, f"expected the NEXT id 2, got {second.last_id!r}"
    # Durable + correctly keyed, read on a SECOND fresh connection.
    reader = _db()
    row = reader.fetch_one("SELECT name FROM fbc_gen2 WHERE id = ?", [2])
    assert row is not None and row["name"] == "b"
    reader.close()
    db.close()


def test_an_insert_reports_affected_rows_of_one():
    db = _db()
    _make_table(db, "fbc_ins1")
    result = db.insert("fbc_ins1", {"name": "x"})
    assert result.affected_rows == 1
    db.close()


# ---- FB-DEC-02: real affected count -------------------------------------


def test_a_multi_row_update_reports_the_real_affected_count():
    db = _db()
    _make_table(db, "fbc_upd")
    for name in ("a", "b", "c", "d"):
        db.insert("fbc_upd", {"name": name})
    result = db.update("fbc_upd", {"name": "Z"}, "id <= ?", [3])
    assert result.affected_rows == 3, f"expected 3 rows changed, got {result.affected_rows}"
    db.close()


def test_an_update_matching_no_rows_reports_zero_affected():
    db = _db()
    _make_table(db, "fbc_upd0")
    db.insert("fbc_upd0", {"name": "a"})
    result = db.update("fbc_upd0", {"name": "Z"}, "name = ?", ["nope"])
    assert result.affected_rows == 0, f"expected 0 rows changed, got {result.affected_rows}"
    db.close()


def test_a_delete_reports_the_real_affected_count():
    db = _db()
    _make_table(db, "fbc_del")
    for name in ("a", "b", "c"):
        db.insert("fbc_del", {"name": name})
    result = db.delete("fbc_del", "id <= ?", [2])
    assert result.affected_rows == 2, f"expected 2 rows deleted, got {result.affected_rows}"
    db.close()


# ---- FB-DEC-03: blob round-trip -----------------------------------------


def test_a_binary_blob_round_trips_byte_for_byte():
    db = _db()
    _make_table(db, "fbc_blob", extra="payload BLOB SUB_TYPE 0")
    db.insert("fbc_blob", {"name": "b", "payload": BLOB})
    # Read back on a SECOND fresh connection.
    reader = _db()
    row = reader.fetch_one("SELECT payload FROM fbc_blob WHERE name = ?", ["b"])
    reader.close()
    db.close()
    assert row is not None
    got = bytes(row["payload"])
    assert got == BLOB, f"blob corrupted: {list(got)} != {list(BLOB)}"


# ---- FB-DEC-01: real reconnect ------------------------------------------


def test_a_forced_disconnect_reconnects_and_the_next_query_succeeds():
    db = _db()
    _make_table(db, "fbc_recon")
    db.insert("fbc_recon", {"name": "before"})
    # The adapter's OWN attachment id, then kill it server-side from a SECOND
    # connection -- a genuine forced disconnect, no mock.
    conn_id = db.fetch_one("SELECT CURRENT_CONNECTION AS c FROM RDB$DATABASE")["c"]
    killer = _db()
    killer.execute("DELETE FROM MON$ATTACHMENTS WHERE MON$ATTACHMENT_ID = ?", [conn_id])
    killer.close()
    # The next query on the dead attachment must transparently reconnect + succeed.
    row = db.fetch_one("SELECT COUNT(*) AS n FROM fbc_recon")
    assert row is not None and row["n"] == 1, "adapter did not reconnect after a forced disconnect"
    db.close()


def test_a_logical_sql_error_does_not_trigger_a_reconnect():
    # The dead-connection matcher must classify a real SQL error as NOT dead, so
    # a syntax/logical error surfaces to the caller instead of a reconnect loop.
    assert FirebirdAdapter._is_dead_connection(Exception("Dynamic SQL Error: syntax error at line 1")) is False
    assert FirebirdAdapter._is_dead_connection(Exception("Table FBC_NOPE does not exist")) is False
    # And a genuinely bad query RAISES through the adapter (does not silently retry).
    db = _db()
    with pytest.raises(Exception):
        db.fetch_one("SELECT * FROM fbc_table_that_does_not_exist_xyz")
    # The connection is still usable -- no spurious reconnect churn broke it.
    assert db.fetch_one("SELECT 1 AS x FROM RDB$DATABASE")["x"] == 1
    db.close()


# ---- FB-DEC-02: non-`id` primary key ------------------------------------


def test_a_non_id_primary_key_insert_returns_the_generated_last_id():
    db = _db()
    _make_table(db, "fbc_thing", pk="thing_key")
    result = db.insert("fbc_thing", {"name": "hi"})
    # The generator read is column-name-independent, so the last-id is correct
    # even though the PK is not named `id`.
    assert result.last_id == 1, f"expected generator id 1, got {result.last_id!r}"
    db.close()


def test_a_non_id_primary_key_returning_re_select_uses_the_real_pk():
    # Python-only witness for the hardcoded-`id` re-select fix: the emulated
    # RETURNING re-selects by the REAL pk (thing_key), so the returned record is
    # populated. Revert the fix -> `WHERE id = ?` raises a Firebird Dynamic SQL
    # Error, the try/except swallows it, and records comes back EMPTY -> RED.
    db = _db()
    _make_table(db, "fbc_thing2", pk="thing_key")
    dialect_result = db.execute("INSERT INTO fbc_thing2 (name) VALUES (?) RETURNING *", ["hi"])
    records = getattr(dialect_result, "records", [])
    assert records, "RETURNING re-select returned no record -- the WHERE clause used the wrong PK column"
    assert records[0]["thing_key"] == 1
    assert records[0]["name"] == "hi"
    db.close()
