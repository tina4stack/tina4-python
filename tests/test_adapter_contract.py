"""The adapter contract (feature 3 of the feature audit).

``tests/fixtures/adapter_contract.json`` is byte-identical in all four
frameworks. This is the RATCHET: it pins today's implemented count per adapter,
so the number can go UP but never down, and a new adapter cannot ship at the old
level.

Measured 2026-07-30. Every Python adapter sits at the same level and is missing
the same methods, which is what having a real base class produces - contrast
Ruby, where seven drivers sat at three different levels because there was no
interface at all.
"""
import importlib
import inspect
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "adapter_contract.json"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))

# The REDESIGNED contract: five small contracts, 14 methods. It replaced a
# 20-method list assembled from PHP's and Node's interfaces - see the plan for
# why that list was wrong in a way none of the four frameworks showed alone.
METHODS = [m["name"] for c in CONTRACT["contracts"].values() for m in c["methods"]]

# Contract name -> the spellings Python accepts. snake_case is idiomatic here,
# and `connect` for `open` is the existing name, not a divergence to fix.
SPELLINGS = {
    "open": ("open", "connect"),
    "close": ("close",),
    "getDatabaseType": ("get_database_type",),
    "execute": ("execute",),
    "fetch": ("fetch",),
    "startTransaction": ("start_transaction",),
    "commit": ("commit",),
    "rollback": ("rollback",),
    "autocommit": ("autocommit",),
    "getTables": ("get_tables",),
    "getColumns": ("get_columns",),
    "tableExists": ("table_exists",),
    "lastInsertId": ("last_insert_id", "get_last_id"),
    "error": ("error", "get_error", "last_error"),
}

# FLOORS, measured 2026-07-30. Raise one when you implement a method; never
# lower one. A drop here means an adapter lost a method it used to have.
# Measured against the REDESIGNED 14-method contract. Python already implements
# almost all of it, because the redesign kept only what genuinely differs per
# engine - which is what these adapters were already doing.
# All six are 12/14, missing the same two: lastInsertId and error. Under the OLD
# 20-method list they read 15/20 and the gap looked like six scattered holes;
# against a contract of only what genuinely differs per engine, the real gap is
# two methods, identical everywhere. That is the redesign paying for itself
# before a line of adapter code moves.
FLOORS = {
    "SQLiteAdapter": 12,
    "PostgreSQLAdapter": 12,
    "MySQLAdapter": 12,
    "MSSQLAdapter": 12,
    "FirebirdAdapter": 12,
    "ODBCAdapter": 12,
}


def _adapters():
    found = {}
    for mod_name in ("sqlite", "postgres", "mysql", "mssql", "firebird", "odbc"):
        try:
            mod = importlib.import_module(f"tina4_python.database.{mod_name}")
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and name.endswith("Adapter") and obj.__module__ == mod.__name__:
                found[name] = obj
    return found


def _implemented(cls):
    """How many contract methods this adapter provides, under any spelling.

    A property counts: `autocommit` is a property on the Python base rather than
    a method, and that is a shape difference worth recording rather than a
    missing capability.
    """
    count = 0
    for names in SPELLINGS.values():
        if any(hasattr(cls, n) for n in names):
            count += 1
    return count


ADAPTERS = _adapters()


def test_the_fixture_declares_five_contracts_and_fourteen_methods():
    assert len(CONTRACT["contracts"]) == 5
    assert len(METHODS) == 14


def test_crud_and_ddl_are_not_on_the_adapter():
    """The redesign's central claim, pinned.

    insert/update/delete/createTable/addColumn are composable above the adapter
    and were duplicated per adapter in three of four frameworks. If one reappears
    in the contract, the 4.3x comes back with it.
    """
    for gone in ("insert", "update", "delete", "createTable", "addColumn", "executeMany", "fetchOne", "query"):
        assert gone not in METHODS, f"{gone} is back on the adapter contract"
        assert gone in CONTRACT["not_on_the_adapter"], f"{gone} left the contract without a recorded reason"


def test_every_adapter_module_was_found():
    """A missing adapter would silently shrink the ratchet's coverage."""
    assert set(FLOORS) <= set(ADAPTERS), f"not found: {set(FLOORS) - set(ADAPTERS)}"


@pytest.mark.parametrize("name", sorted(FLOORS))
def test_adapter_implements_at_least_its_recorded_floor(name):
    cls = ADAPTERS.get(name)
    if cls is None:
        pytest.skip(f"{name} not importable (driver package absent)")
    assert _implemented(cls) >= FLOORS[name], (
        f"{name} dropped below its recorded floor - it lost a contract method"
    )


def test_every_adapter_sits_at_the_same_level():
    """Consistency is the property having a base class buys.

    Ruby's seven drivers sat at three different levels because it had no
    interface; Python's sit at one. If this starts failing, an adapter has
    drifted from the others and the contract is no longer doing its job.
    """
    levels = {name: _implemented(cls) for name, cls in ADAPTERS.items() if name in FLOORS}
    assert len(set(levels.values())) == 1, f"adapters have drifted apart: {levels}"
