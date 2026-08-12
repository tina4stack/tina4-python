"""Feature 23 - ORM scopes: the shared conformance contract.

Shared fixture: tina4-documentation/plan/v3/fixtures/scopes_contract.json

SCOPE-DEC-01 (OWNER-DECISIONS.md Batch 4): fix PHP's scope global-registry
collision. Python's `scope()` is a `@classmethod` that closes over the exact
`cls` it was called on and `setattr`s the generated method onto THAT class, so
it is already per-class -- this suite proves it, it does not fix anything here.
SCOPE-DEC-02: scopes stay TERMINAL LISTS (no compose/rebind/global-scope added;
the ledger did not separately ratify it).

Proves the scope BEHAVIOUR against a REAL database, NO MOCKS. Every case runs
on real SQLite AND real PostgreSQL (:55432, tina4/tina4 by default). Row
identity is asserted by reading real columns back, not a double.

Case names are shared verbatim (each language's own idiom) across the four
frameworks and gated by scripts/audit-contract-fixtures.py. Under
TINA4_REQUIRE_SERVICES a postgres skip is a hard failure (tests/conftest.py),
so PG is exercised for real, never silently skipped.
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


# ── Models (unique table names; two DIFFERENT tables/filters share the SAME
#    scope NAME "active" on purpose -- that is the SCOPE-PHP-COLLISION case) ──
class ScopeUser(ORM):
    table_name = "scope_users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    active = IntegerField(default=0)


class ScopeProduct(ORM):
    table_name = "scope_products"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    discontinued = IntegerField(default=0)


class ScopeArticle(ORM):
    table_name = "scope_articles"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    category = StringField()


class ScopeWidget(ORM):
    table_name = "scope_widgets"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


# ── SCOPE-DEC-01: two models, SAME scope name, DIFFERENT filters -- no collision ─
@pytest.mark.parametrize("engine", _ENGINES)
def test_two_models_same_scope_name_return_different_rows(engine):
    with _engine(engine) as db:
        _drop(db, "scope_users", "scope_products")
        assert ScopeUser.create_table() is True, f"create_table failed: {db.get_error()}"
        assert ScopeProduct.create_table() is True, f"create_table failed: {db.get_error()}"
        try:
            ScopeUser.create({"name": "Alice", "active": 1})
            ScopeUser.create({"name": "Bob", "active": 0})
            ScopeUser.create({"name": "Carol", "active": 1})

            ScopeProduct.create({"name": "Widget", "discontinued": 0})
            ScopeProduct.create({"name": "Gadget", "discontinued": 1})
            ScopeProduct.create({"name": "Gizmo", "discontinued": 0})

            # SAME scope name ("active") registered on TWO different models with
            # DIFFERENT filters. This is the exact SCOPE-PHP-COLLISION scenario
            # from the feature doc: the second registration must never leak into
            # or overwrite the first model's filter.
            ScopeUser.scope("active", "active = ?", [1])
            ScopeProduct.scope("active", "discontinued = ?", [0])

            users = ScopeUser.active()
            products = ScopeProduct.active()

            assert sorted(u.name for u in users) == ["Alice", "Carol"], \
                f"ScopeUser.active() collided: got {[u.name for u in users]}"
            assert sorted(p.name for p in products) == ["Gizmo", "Widget"], \
                f"ScopeProduct.active() collided: got {[p.name for p in products]}"
        finally:
            _drop(db, "scope_users", "scope_products")


# ── SCOPE-DEC-02: a scope respects the soft-delete filter (via where()) ───────
@pytest.mark.parametrize("engine", _ENGINES)
def test_scope_excludes_a_soft_deleted_row(engine):
    with _engine(engine) as db:
        _drop(db, "scope_articles")
        assert ScopeArticle.create_table() is True, f"create_table failed: {db.get_error()}"
        try:
            one = ScopeArticle.create({"name": "One", "category": "news"})
            ScopeArticle.create({"name": "Two", "category": "news"})
            ScopeArticle.create({"name": "Three", "category": "news"})

            ScopeArticle.scope("news", "category = ?", ["news"])
            assert len(ScopeArticle.news()) == 3

            assert one.delete() is True

            visible = ScopeArticle.news()
            assert len(visible) == 2
            assert "One" not in [a.name for a in visible]

            # Negative: the row is still PHYSICALLY present (raw, unfiltered).
            row = db.fetch_one("SELECT COUNT(*) AS c FROM scope_articles")
            assert int(row["c"]) == 3
        finally:
            _drop(db, "scope_articles")


# ── SCOPE-DEC-02: a scope pushes limit/offset to the database ─────────────────
@pytest.mark.parametrize("engine", _ENGINES)
def test_scope_honours_limit_and_offset(engine):
    with _engine(engine) as db:
        _drop(db, "scope_widgets")
        assert ScopeWidget.create_table() is True, f"create_table failed: {db.get_error()}"
        try:
            for i in range(15):
                ScopeWidget.create({"name": f"w{i}"})

            ScopeWidget.scope("everything", "1=1")

            # Negative: an explicit smaller limit is honoured exactly (proves the
            # argument reaches the DB rather than being silently discarded).
            small = ScopeWidget.everything(limit=3)
            assert len(small) == 3

            # Two pages of the SAME scope, from the SAME 15-row set, are DISJOINT
            # -- proves offset reaches the database, not a client-side no-op.
            page1 = ScopeWidget.everything(limit=5, offset=0)
            page2 = ScopeWidget.everything(limit=5, offset=5)
            assert len(page1) == 5
            assert len(page2) == 5
            ids1 = {w.id for w in page1}
            ids2 = {w.id for w in page2}
            assert ids1.isdisjoint(ids2), f"pages overlap: {ids1} & {ids2}"
        finally:
            _drop(db, "scope_widgets")
