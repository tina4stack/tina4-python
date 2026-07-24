"""A table/column named with a SQL reserved word must work.

`CREATE TABLE order (...)` / `SELECT * FROM order` are syntax errors on every
engine. The generator avoids reserved names when it scaffolds, but a developer
can still set `table_name = "order"` by hand — the ORM has to quote identifiers
for the bound dialect so that works.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from tina4_python.database.adapter import DatabaseAdapter
from tina4_python.database.connection import Database
from tina4_python.orm.fields import IntegerField, NumericField, StringField
from tina4_python.orm.model import ORM, bind_database


class Order(ORM):
    table_name = "order"          # reserved word, set by hand
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    total = NumericField()


@pytest.fixture
def sqlite_db():
    path = tempfile.mktemp(suffix=".db")
    db = Database(f"sqlite:///{path}")
    bind_database(db)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


class TestReservedTableName:
    def test_full_crud_against_a_reserved_table(self, sqlite_db):
        assert Order.create_table(), "CREATE TABLE on a reserved name must succeed"

        order = Order({"name": "first", "total": 9.5})
        assert order.save(), f"save failed: {order.last_error}"

        rows = Order.all()
        assert len(rows) == 1 and rows[0].name == "first"

        found = Order.find_by_id(order.id)
        assert found is not None and found.total == 9.5

        found.total = 20.0
        assert found.save(), f"update failed: {found.last_error}"
        assert Order.find_by_id(order.id).total == 20.0

        assert Order.count() == 1
        assert found.delete()
        assert Order.count() == 0


class TestIdentifierQuoting:
    """Dialect rules, and the cases quoting must NOT touch."""

    def test_ansi_default(self):
        q = DatabaseAdapter().quote_identifier
        assert q("order") == '"order"'
        assert q("plain_name") == '"plain_name"'

    def test_mysql_uses_backticks(self):
        from tina4_python.database.mysql import MySQLAdapter
        assert MySQLAdapter.IDENTIFIER_QUOTE == ("`", "`")

    def test_mssql_uses_brackets(self):
        from tina4_python.database.mssql import MSSQLAdapter
        assert MSSQLAdapter.IDENTIFIER_QUOTE == ("[", "]")

    def test_idempotent(self):
        q = DatabaseAdapter().quote_identifier
        assert q('"order"') == '"order"', "quoting twice must not double-quote"

    def test_dotted_names_quote_each_part(self):
        assert DatabaseAdapter().quote_identifier("schema.order") == '"schema"."order"'

    def test_expressions_are_left_alone(self):
        q = DatabaseAdapter().quote_identifier
        for expr in ("*", "COUNT(*)", "SUM(total)", "a + b"):
            assert q(expr) == expr, f"{expr} must pass through untouched"
