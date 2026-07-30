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

# Contract name -> the spellings Python accepts. snake_case is idiomatic here,
# and `connect` for `open` is the existing name, not a divergence to fix.
SPELLINGS = {
    "open": ("open", "connect"),
    "close": ("close",),
    "execute": ("execute",),
    "executeMany": ("execute_many",),
    "fetch": ("fetch",),
    "fetchOne": ("fetch_one",),
    "insert": ("insert",),
    "update": ("update",),
    "delete": ("delete",),
    "startTransaction": ("start_transaction",),
    "commit": ("commit",),
    "rollback": ("rollback",),
    "getTables": ("get_tables",),
    "getColumns": ("get_columns",),
    "tableExists": ("table_exists",),
    "createTable": ("create_table",),
    "addColumn": ("add_column",),
    "lastInsertId": ("last_insert_id", "get_last_id"),
    "error": ("error", "get_error", "last_error"),
    "autocommit": ("autocommit",),
}

# FLOORS, measured 2026-07-30. Raise one when you implement a method; never
# lower one. A drop here means an adapter lost a method it used to have.
FLOORS = {
    "SQLiteAdapter": 15,
    "PostgreSQLAdapter": 15,
    "MySQLAdapter": 15,
    "MSSQLAdapter": 15,
    "FirebirdAdapter": 15,
    "ODBCAdapter": 15,
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


def test_the_fixture_declares_twenty_methods():
    assert len(CONTRACT["methods"]) == 20


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
