"""Feature 20 - Soft delete: the shared conformance contract.

Proves the soft-delete BEHAVIOUR against a REAL database, NO MOCKS. Every case
runs on real SQLite AND real PostgreSQL (:55432, tina4/tina4 by default) so the
row presence/absence is asserted by querying the real table, not a double: a
soft-deleted row is COUNT=1 in the raw table but ABSENT from the finders; a
force-deleted row is COUNT=0.

Case names are shared verbatim (each language's own idiom) across the four
frameworks and gated by scripts/audit-contract-fixtures.py.

Coordinates use the canonical TINA4_TEST_PG_* convention (same as the provider
contract suites). Under TINA4_REQUIRE_SERVICES a postgres skip is a hard failure
(tests/conftest.py), so PG is exercised for real, never silently skipped.

SOFTDEL-DEC-01 / SOFTDEL-DEC-02:
  * delete() FLAGS not removes; the finders exclude it; with_trashed() includes
    it; restore() un-deletes; force_delete() ALWAYS hard-removes (the regression
    that catches the PHP-class $whereParams throw-instead-of-delete bug).
  * create_table() INJECTS the is_deleted column for a soft-delete model that
    never declared it (SOFTDEL-CREATETABLE-COLUMN), so a full round-trip works on
    the generated schema with no manual column.
  * the soft-delete finder filter routes the column through field_mapping
    (SOFTDEL-PY-FILTER-MAPPING, Python-only), so a model that remaps is_deleted
    filters and writes on the mapped column.
"""
from __future__ import annotations

import contextlib
import os
import socket
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, bind_database


_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)

_ENGINES = ["sqlite", "postgres"]


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


@contextlib.contextmanager
def _engine(engine):
    """A real Database for the named engine. SQLite is a fresh temp file; a
    postgres skip trips the require-services gate (reason names it 'unreachable')
    so PG is never silently skipped on the lab."""
    path = None
    if engine == "sqlite":
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = Database(f"sqlite:///{path}")
    elif engine == "postgres":
        if not _reachable(_PG["host"], _PG["port"]):
            pytest.skip(f"postgres unreachable at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)")
        db = Database(f"postgres://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])
    else:  # pragma: no cover - guard
        raise AssertionError(engine)
    bind_database(db)
    try:
        yield db
    finally:
        with contextlib.suppress(Exception):
            db.close()
        if path:
            with contextlib.suppress(OSError):
                os.unlink(path)


def _drop(db, *tables):
    for table in tables:
        with contextlib.suppress(Exception):
            db.execute(f"DROP TABLE IF EXISTS {table}")


def _raw_count(db, table) -> int:
    """Raw COUNT(*) with NO soft-delete filter — sees flagged rows too."""
    row = db.fetch_one(f"SELECT COUNT(*) AS c FROM {table}")
    return int(row["c"]) if row else 0


def _soft_declared(db, table):
    """A soft-delete model that DECLARES is_deleted (behaviour is independent of
    the create_table injection, so a mutation to the injection cannot mask it)."""
    class Item(ORM):
        table_name = table
        soft_delete = True
        id = IntegerField(primary_key=True, auto_increment=True)
        title = StringField()
        is_deleted = IntegerField(default=0)

    bind_database(db)
    _drop(db, table)
    assert Item.create_table() is True, f"create_table failed: {db.get_error()}"
    return Item


def _soft_auto(db, table):
    """A soft-delete model with NO is_deleted declared -- create_table must
    INJECT the column (SOFTDEL-CREATETABLE-COLUMN)."""
    class Item(ORM):
        table_name = table
        soft_delete = True
        id = IntegerField(primary_key=True, auto_increment=True)
        title = StringField()

    bind_database(db)
    _drop(db, table)
    assert Item.create_table() is True, f"create_table failed: {db.get_error()}"
    return Item


# ── delete() FLAGS, does not remove ──────────────────────────────────────────


@pytest.mark.parametrize("engine", _ENGINES)
def test_delete_flags_the_row_instead_of_removing_it(engine):
    with _engine(engine) as db:
        table = "sd_flags"
        Item = _soft_declared(db, table)
        try:
            it = Item.create({"title": "keep-me"})
            assert it.delete() is True
            # The row is STILL in the raw table, with the flag set to 1.
            assert _raw_count(db, table) == 1
            raw = db.fetch_one(f"SELECT is_deleted FROM {table} WHERE id = ?", [it.id])
            assert raw is not None and int(raw["is_deleted"]) == 1
        finally:
            _drop(db, table)


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_soft_deleted_row_is_excluded_from_the_default_finder(engine):
    with _engine(engine) as db:
        table = "sd_excluded"
        Item = _soft_declared(db, table)
        try:
            it = Item.create({"title": "hide-me"})
            assert Item.count() == 1 and len(Item.all()) == 1
            it.delete()
            # Present in the raw table (negative control) ...
            assert _raw_count(db, table) == 1
            # ... but excluded from every high-level finder.
            assert Item.count() == 0
            assert len(Item.all()) == 0
            assert Item.find_by_id(it.id) is None
            assert len(Item.where("id = ?", [it.id])) == 0
        finally:
            _drop(db, table)


# ── with_trashed() includes; restore() un-deletes ────────────────────────────


@pytest.mark.parametrize("engine", _ENGINES)
def test_with_trashed_returns_the_soft_deleted_row(engine):
    with _engine(engine) as db:
        table = "sd_trashed"
        Item = _soft_declared(db, table)
        try:
            it = Item.create({"title": "trashed"})
            it.delete()
            assert len(Item.all()) == 0                     # excluded by default
            trashed = Item.with_trashed()
            assert len(trashed) == 1                        # included with_trashed
            assert trashed[0].id == it.id
        finally:
            _drop(db, table)


@pytest.mark.parametrize("engine", _ENGINES)
def test_restore_undeletes_the_row_so_it_reappears_in_the_finder(engine):
    with _engine(engine) as db:
        table = "sd_restore"
        Item = _soft_declared(db, table)
        try:
            it = Item.create({"title": "comeback"})
            it.delete()
            assert Item.count() == 0
            assert it.restore() is True
            # Restored: the finder sees it again and the flag is cleared.
            assert Item.count() == 1
            assert Item.find_by_id(it.id) is not None
            raw = db.fetch_one(f"SELECT is_deleted FROM {table} WHERE id = ?", [it.id])
            assert int(raw["is_deleted"]) == 0
        finally:
            _drop(db, table)


# ── force_delete() ALWAYS hard-removes (the PHP-class regression) ─────────────


@pytest.mark.parametrize("engine", _ENGINES)
def test_force_delete_hard_removes_the_row_even_from_with_trashed(engine):
    with _engine(engine) as db:
        table = "sd_force"
        Item = _soft_declared(db, table)
        try:
            it = Item.create({"title": "gone"})
            assert _raw_count(db, table) == 1
            assert it.force_delete() is True
            # Physically removed: gone from the raw table AND from with_trashed().
            assert _raw_count(db, table) == 0
            assert len(Item.with_trashed()) == 0
        finally:
            _drop(db, table)


# ── create_table() INJECTS the column (SOFTDEL-CREATETABLE-COLUMN) ────────────


@pytest.mark.parametrize("engine", _ENGINES)
def test_create_table_injects_a_usable_is_deleted_column_for_a_soft_delete_model(engine):
    with _engine(engine) as db:
        table = "sd_auto"
        # The model declares NO is_deleted; create_table() injected it above.
        Item = _soft_auto(db, table)
        try:
            # The injected column is real and usable: a full round-trip works with
            # no manual column declaration.
            it = Item.create({"title": "auto"})
            assert it.delete() is True                      # soft-flag on injected col
            assert _raw_count(db, table) == 1               # row still present
            assert len(Item.all()) == 0                     # excluded from finder
            assert len(Item.with_trashed()) == 1            # visible with_trashed
            assert it.restore() is True
            assert len(Item.all()) == 1                     # reappears
            assert it.force_delete() is True
            assert _raw_count(db, table) == 0               # hard-removed
        finally:
            _drop(db, table)


# ── SOFTDEL-PY-FILTER-MAPPING (Python-only) ──────────────────────────────────


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_soft_delete_finder_filters_through_field_mapping(engine):
    with _engine(engine) as db:
        table = "sd_mapped"

        class Item(ORM):
            table_name = table
            soft_delete = True
            # is_deleted is remapped to a DIFFERENT db column; create_table must
            # inject the MAPPED column and the finder/write must address it.
            field_mapping = {"is_deleted": "deleted_flag"}
            id = IntegerField(primary_key=True, auto_increment=True)
            title = StringField()

        bind_database(db)
        _drop(db, table)
        assert Item.create_table() is True, f"create_table failed: {db.get_error()}"
        try:
            # The injected column carries the MAPPED name, not the literal.
            it = Item.create({"title": "mapped"})
            it.delete()
            # The write went to the mapped column ...
            raw = db.fetch_one(f"SELECT deleted_flag FROM {table} WHERE id = ?", [it.id])
            assert raw is not None and int(raw["deleted_flag"]) == 1
            # ... and the finder filters on the mapped column (excludes it).
            assert Item.count() == 0
            assert len(Item.all()) == 0
            assert len(Item.with_trashed()) == 1
            it.restore()
            assert Item.count() == 1
        finally:
            _drop(db, table)
