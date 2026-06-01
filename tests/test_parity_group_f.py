"""Parity Group F — top-level re-exports and scaffolder template fixes."""
from __future__ import annotations

import pytest


# ─── tina4_python.* re-exports ────────────────────────────────────────────


class TestTopLevelReexports:
    """Confirm every symbol the docs assume can be imported from `tina4_python`
    is actually re-exported (audit found `from tina4 import` everywhere — but
    even the correct `from tina4_python import X` was sometimes broken).
    """

    def test_api_class(self):
        from tina4_python import Api
        assert Api.__name__ == "Api"

    def test_wsdl_class_and_decorator(self):
        from tina4_python import WSDL, wsdl_operation
        assert WSDL.__name__ == "WSDL"
        assert callable(wsdl_operation)

    def test_graphql_class(self):
        from tina4_python import GraphQL
        assert GraphQL.__name__ == "GraphQL"

    def test_autocrud_class(self):
        from tina4_python import AutoCrud
        assert AutoCrud.__name__ == "AutoCrud"

    def test_messenger_class(self):
        from tina4_python import Messenger
        assert Messenger.__name__ == "Messenger"

    def test_events_module_level(self):
        from tina4_python import on, emit, once, off
        assert callable(on)
        assert callable(emit)
        assert callable(once)
        assert callable(off)

    def test_inline_tests_decorator(self):
        from tina4_python import tests
        assert callable(tests)

    def test_all_existing_exports_still_present(self):
        """Smoke-test the existing surface didn't break in 3.13.0."""
        from tina4_python import (
            get, post, put, patch, delete,
            ORM, IntegerField, StringField,
            Database, Auth, Queue, Frond,
            Container, ResponseCache,
            run, background,
        )
        assert all(callable(x) for x in (get, post, put, patch, delete, run, background))


# ─── Model.select() with default SQL ──────────────────────────────────────


def _make_thing_model():
    from tina4_python.database import Database
    from tina4_python.orm import ORM, IntegerField, StringField, orm_bind

    db = Database("sqlite:///:memory:")
    orm_bind(db)

    class Thing(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()

    Thing().create_table()
    return Thing, db


class TestModelSelectDefaultSQL:
    def test_select_no_sql_returns_all(self):
        Thing, db = _make_thing_model()
        try:
            Thing({"name": "A"}).save()
            Thing({"name": "B"}).save()
            results = Thing.select()
            assert isinstance(results, list)
            assert len(results) == 2
            assert {r.name for r in results} == {"A", "B"}
        finally:
            db.close()

    def test_select_with_explicit_sql_still_works(self):
        Thing, db = _make_thing_model()
        try:
            Thing({"name": "A"}).save()
            Thing({"name": "B"}).save()
            table = Thing._get_table()
            results = Thing.select(f"SELECT * FROM {table} WHERE name = ?", ["A"])
            assert len(results) == 1
            assert results[0].name == "A"
        finally:
            db.close()

    def test_select_default_respects_limit_offset(self):
        Thing, db = _make_thing_model()
        try:
            for i in range(10):
                Thing({"name": f"T{i}"}).save()
            page1 = Thing.select(limit=3, offset=0)
            page2 = Thing.select(limit=3, offset=3)
            assert len(page1) == 3
            assert len(page2) == 3
            assert {r.id for r in page1} != {r.id for r in page2}
        finally:
            db.close()
