"""Regression tests for v3.13.11 — ORM correctness pass.

Covers issues #49 (PG error visibility follow-on) and #50 (callable
defaults + natural-key INSERT), plus the engine-aware BooleanField
DDL change.

Tests that don't need a real database run against SQLite in-memory.
PG-specific contracts are exercised in :mod:`test_postgres_error_visibility`.
"""
from __future__ import annotations

import datetime as _dt
import os
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import (
    ORM,
    BooleanField,
    DateTimeField,
    IntegerField,
    StringField,
    bind_database,
)


# ── Test fixtures ──────────────────────────────────────────────────


@pytest.fixture
def db():
    """A fresh in-memory SQLite for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite:///{path}")
    yield database
    try:
        database.close()
    except Exception:
        pass
    os.unlink(path)


# ── Issue #50 Bug 1 — callable defaults ────────────────────────────


class TestCallableDefaults:
    """``DateTimeField(default=lambda: datetime.now())`` must invoke the
    callable per instance, not store the function object."""

    def test_lambda_default_is_called_on_instance(self):
        class Widget(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            created_at = DateTimeField(default=lambda: _dt.datetime(2026, 1, 1, 12, 0))

        w = Widget()
        assert isinstance(w.created_at, _dt.datetime), \
            f"created_at should be datetime, got {type(w.created_at).__name__}"
        assert w.created_at == _dt.datetime(2026, 1, 1, 12, 0)

    def test_function_reference_default_is_called(self):
        def fixed_time():
            return _dt.datetime(2026, 6, 11, 14, 30)

        class Widget(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            created_at = DateTimeField(default=fixed_time)

        w = Widget()
        assert w.created_at == _dt.datetime(2026, 6, 11, 14, 30)

    def test_each_instance_gets_a_fresh_value(self):
        """Critical for per-row timestamps: every instance must invoke
        the callable separately. Two widgets created back-to-back must
        not share the same datetime object identity."""
        counter = [0]

        def fresh():
            counter[0] += 1
            return counter[0]

        class Widget(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            seq = IntegerField(default=fresh)

        a = Widget()
        b = Widget()
        c = Widget()
        assert a.seq == 1
        assert b.seq == 2
        assert c.seq == 3, "callable defaults must be invoked per instance"

    def test_static_default_still_works(self):
        """Backward-compat: non-callable defaults are unchanged."""
        class Widget(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            count = IntegerField(default=42)

        assert Widget().count == 42

    def test_type_default_is_not_called(self):
        """``default=int`` is almost never intended to mean ``int()`` —
        excluded from the auto-call behaviour for sanity. If a user
        truly wants ``int()``, they can spell it ``default=lambda: int()``."""
        class Widget(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            n = IntegerField(default=int)  # weird but valid

        w = Widget()
        assert w.n is int, "type-as-default is preserved verbatim"


# ── Issue #50 Bug 2 — natural-key INSERT ───────────────────────────


class TestNaturalKeyInsert:
    """``save()`` on a model with a user-supplied (non-auto-increment)
    primary key must INSERT a new row instead of silently UPDATE-ing
    zero rows."""

    def _setup(self, db, *, with_seed=False):
        bind_database(db)

        class GiftCard(ORM):
            gift_card_number = StringField(primary_key=True, max_length=50)
            owner = StringField(max_length=120)

        GiftCard.create_table()
        if with_seed:
            seed = GiftCard()
            seed.gift_card_number = "GC-SEED"
            seed.owner = "seed@example.com"
            seed.save()
        return GiftCard

    def test_first_save_inserts_natural_key(self, db):
        GiftCard = self._setup(db)

        gc = GiftCard()
        gc.gift_card_number = "GC-100"
        gc.owner = "alice@example.com"
        result = gc.save()

        assert result is not False, f"save returned False; last_error={db.last_error!r}"
        found = GiftCard.find_by_id("GC-100")
        assert found is not None, "natural-key row not inserted"
        assert found.owner == "alice@example.com"

    def test_second_save_on_same_pk_updates(self, db):
        GiftCard = self._setup(db)

        gc = GiftCard()
        gc.gift_card_number = "GC-200"
        gc.owner = "first@example.com"
        gc.save()

        # Second save (with same PK) must UPDATE, not duplicate INSERT.
        gc.owner = "second@example.com"
        result = gc.save()
        assert result is not False

        rows = GiftCard.find()
        gc200 = [r for r in rows if r.gift_card_number == "GC-200"]
        assert len(gc200) == 1, "second save must not produce a duplicate row"
        assert gc200[0].owner == "second@example.com"

    def test_auto_increment_pk_behaviour_unchanged(self, db):
        """Regression guard: the natural-key fix must not affect
        auto-increment models. PK is None → INSERT, PK assigned by
        engine, second save with that PK → UPDATE."""
        bind_database(db)

        class User(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField(max_length=80)

        User.create_table()

        u = User()
        u.name = "Alice"
        u.save()
        assert u.id is not None, "auto-increment PK should be set after save"
        first_id = u.id

        u.name = "Alice Wonder"
        u.save()
        assert u.id == first_id, "auto-increment PK must not change on update"

        rows = User.find()
        assert len(rows) == 1
        assert rows[0].name == "Alice Wonder"


# ── BooleanField engine-aware DDL ──────────────────────────────────


class TestBooleanFieldDDL:
    """Verify create_table writes the right SQL type per engine.

    We don't spin up PG/MySQL/MSSQL for this — just stub get_database_type
    on the bound DB and re-read the rendered DDL via SQLite (which doesn't
    care what column type strings look like, so the SQL still runs)."""

    def test_sqlite_keeps_integer(self, db):
        bind_database(db)

        class Flagged(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            active = BooleanField(default=True)

        # SQLite returns "sqlite" from get_database_type
        Flagged.create_table()
        # Inspect the stored DDL via sqlite_master (PRAGMA doesn't route
        # through db.fetch — it'd get wrapped in SELECT).
        row = db.fetch_one(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='flagged'"
        )
        assert row is not None, "table should have been created"
        ddl = row["sql"]
        assert "active INTEGER" in ddl, (
            f"SQLite BooleanField should map to INTEGER, DDL: {ddl}"
        )

    @pytest.mark.parametrize(
        "engine,expected",
        [
            ("postgres", "BOOLEAN"),
            ("mysql", "BOOLEAN"),
            ("mssql", "BIT"),
            ("sqlite", "INTEGER"),
            ("firebird", "INTEGER"),
        ],
    )
    def test_engine_dispatch(self, db, engine, expected, monkeypatch):
        """create_table must pick the right SQL type per engine."""
        bind_database(db)

        class Flagged(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            active = BooleanField(default=True)

        # Monkeypatch get_database_type — we can't easily spin up every
        # engine, but the dispatch logic is what we're testing here.
        # We also stub execute so the rendered DDL goes nowhere (SQLite
        # would reject "active BIT" etc.).
        captured = {}

        def fake_execute(sql, params=None):
            captured["sql"] = sql
            return True

        def fake_table_exists(_t):
            return False

        monkeypatch.setattr(db, "get_database_type", lambda: engine)
        monkeypatch.setattr(db, "execute", fake_execute)
        monkeypatch.setattr(db, "table_exists", fake_table_exists)

        Flagged.create_table()

        assert "sql" in captured, "create_table must call db.execute"
        # The column line should include the expected SQL type.
        assert expected in captured["sql"], (
            f"engine={engine}: expected '{expected}' in DDL, got:\n{captured['sql']}"
        )
