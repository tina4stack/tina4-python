"""Feature 26 - ORM instance loading / hydration: the shared conformance contract.

LOAD-DEC-01 (Python): hydration (_populate) used to call ``Field.validate()``,
RE-ENFORCING write-path business constraints (required/length/range/choices) on
every READ -- a stored row that violated a constraint (or one TIGHTENED after the
row was written) raised out of ``cls(row)`` and aborted the WHOLE ``select()``.
Fixed: ``_populate`` now calls the new ``Field.coerce()`` (type coercion + JSON
parse only); ``Field.validate()`` (business constraints) stays write-path-only,
used by ``save()``/``ORM.validate()`` and AutoCrud's PUT handler -- unchanged.

LOAD-JSON-ONLY (LOAD-DEC-02): the scalar read-coercion contract is PINNED as
JSON-only (OWNER-DECISIONS.md Batch 5: "pin the scalar read-coercion contract
(JSON-only today)") -- only JSON columns parse to a native object on read;
non-JSON scalars are driver-typed and NOT reconstituted to Date/bool beyond what
the driver already returns. Python's own coercion (int/bool/datetime normalising
across driver shapes) is a separate, pre-existing, Python-specific enhancement
documented in fields.py -- not something this fixture asks the other three to
match, and not itself a business constraint.

Case names are shared verbatim across all four frameworks (PHP
InstanceLoadingContractTest.php, Ruby instance_loading_contract_spec.rb, Node
instanceLoadingContract.test.ts) and gated by scripts/audit-contract-fixtures.py.

NO MOCKS: real SQLite (always) + real PostgreSQL :55432 tina4/tina4 (gated --
skips cleanly when unreachable locally, a hard failure under
TINA4_REQUIRE_SERVICES, e.g. on the lab).
"""
from __future__ import annotations

import os
import socket

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, JSONField, BooleanField, bind_database


# ── real SQLite (no service) ────────────────────────────────────────────────


@pytest.fixture
def sqlite_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'instance_loading.db'}")
    bind_database(db)
    yield db
    db.close()


# ── real PostgreSQL :55432 tina4/tina4 (gated) ──────────────────────────────

_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


@pytest.fixture
def pg_db():
    if not _reachable(_PG["host"], _PG["port"]):
        pytest.skip(f"postgres unreachable at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)")
    db = Database(f"postgres://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])
    bind_database(db)
    try:
        db.execute("DROP TABLE IF EXISTS load_contract_item")
    except Exception:
        pass
    yield db
    try:
        db.execute("DROP TABLE IF EXISTS load_contract_item")
    except Exception:
        pass
    db.close()


# ── Models ───────────────────────────────────────────────────────────────────
#
# V1 ("loose"): defines the table's DDL. `name` carries NO required constraint,
# so the column stays nullable -- a legitimate pre-existing row CAN hold NULL.
# V2 ("tight"): the SAME table, but `name` is `required=True` -- simulating a
# constraint TIGHTENED after the row already existed (LOAD-PY-REVALIDATE). Only
# V2 is used to prove the read-hydrate-still-works / write-still-rejects split.

class LoadContractItemV1(ORM):
    table_name = "load_contract_item"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    payload = JSONField()
    active = BooleanField(default=True)


class LoadContractItemV2(ORM):
    table_name = "load_contract_item"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)
    payload = JSONField()
    active = BooleanField(default=True)


def _run_cases(db):
    """Run every shared case against whichever real database *db* is bound to
    (SQLite or PostgreSQL) -- one body, so the two engines can never drift."""
    LoadContractItemV1.create_table()

    # ── json_column_round_trips_via_finder ──────────────────────────────
    saved = LoadContractItemV1(name="alice", payload={"tags": ["a", "b"], "n": 1})
    assert saved.save() is not False
    got = LoadContractItemV1.find(saved.id)
    assert isinstance(got.payload, dict), f"expected a native dict, got {type(got.payload)}"
    assert got.payload == {"tags": ["a", "b"], "n": 1}

    # ── json_column_round_trips_via_load ────────────────────────────────
    reloaded = LoadContractItemV1()
    reloaded.id = saved.id
    assert reloaded.load() is True
    assert isinstance(reloaded.payload, dict), f"expected a native dict, got {type(reloaded.payload)}"
    assert reloaded.payload == {"tags": ["a", "b"], "n": 1}

    # ── constraint_violating_stored_row_still_hydrates ──────────────────
    # V1 (no `required` on `name`) legitimately stores a NULL name -- an
    # ordinary nullable-column row, saved through the NORMAL write path.
    stored = LoadContractItemV1(name=None, payload={"k": "v"})
    assert stored.save() is not False
    # V2 (SAME table, `name` now `required=True`) reads it back. Pre-fix this
    # raised ValueError out of cls(row) and aborted the whole select(); now it
    # must hydrate -- the stored row still exists and is still readable.
    still_readable = LoadContractItemV2.find(stored.id)
    assert still_readable is not None, "a required-but-NULL stored row must still hydrate via find()"
    assert still_readable.name is None
    # The SAME row must also survive a full select() (not just a single find),
    # proving one non-conforming row does not abort a page of results.
    all_rows = LoadContractItemV2.all()
    assert any(r.id == stored.id for r in all_rows), "select() aborted instead of returning every row"

    # Prove the write path is UNCHANGED: V2's OWN save() still rejects a NEW
    # row missing the now-required `name` -- this is a read-only fix, not a
    # deleted constraint.
    rejected = LoadContractItemV2(payload={})
    result = rejected.save()
    assert result is False, "save() must still reject a missing required field"
    assert rejected.get_error() and "required" in rejected.get_error().lower()

    # ── partial_select_yields_partial_instance ──────────────────────────
    full = LoadContractItemV1(name="partial-target", payload={"z": 9})
    assert full.save() is not False
    partial = LoadContractItemV1.select(
        "SELECT id, name FROM load_contract_item WHERE id = ?", [full.id]
    )
    assert len(partial) == 1
    inst = partial[0]
    assert inst.name == "partial-target"
    # `payload` and `active` were NOT selected -- they must sit at their
    # declared class defaults, not crash and not carry a stale/wrong value.
    assert inst.active is True
    assert inst.payload is None


def test_json_column_round_trips_via_finder_and_load_sqlite(sqlite_db):
    _run_cases(sqlite_db)


def test_json_column_round_trips_via_finder_and_load_postgres(pg_db):
    _run_cases(pg_db)
