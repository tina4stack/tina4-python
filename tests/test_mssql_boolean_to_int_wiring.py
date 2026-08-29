"""The MSSQL adapter (and Firebird) wire ``boolean_to_int`` into apply-time
translation, so a bare ``TRUE``/``FALSE`` reaches a BIT-backed engine as ``1``/``0``.
A ``TRUE``/``FALSE`` inside a string literal is data and must survive untouched.

No mocks: ``_translate_sql`` is a pure function over its input string. The adapter
constructors open no connection, so this exercises the real translation path.
Regression guard for the wiring gap where MSSQL translated AUTOINCREMENT and the
DDL types but never the boolean literal (Firebird already did).
"""
from tina4_python.database.mssql import MSSQLAdapter
from tina4_python.database.firebird import FirebirdAdapter


class TestMssqlBooleanWiring:
    def _t(self, sql):
        return MSSQLAdapter()._translate_sql(sql)

    def test_bare_true_and_false_become_1_and_0(self):
        assert "(1)" in self._t("INSERT INTO flags (active) VALUES (TRUE)")
        assert "TRUE" not in self._t("INSERT INTO flags (active) VALUES (TRUE)")
        assert "= 0" in self._t("UPDATE flags SET active = FALSE")

    def test_true_inside_a_string_literal_is_preserved(self):
        out = self._t("SELECT id FROM flags WHERE label = 'TRUE'")
        assert "'TRUE'" in out


class TestFirebirdBooleanWiring:
    """Firebird was already wired; pin it so the parity does not regress."""

    def _t(self, sql):
        return FirebirdAdapter()._translate_sql(sql)

    def test_bare_true_becomes_1(self):
        out = self._t("INSERT INTO flags (active) VALUES (TRUE)")
        assert "(1)" in out and "TRUE" not in out

    def test_string_literal_true_is_preserved(self):
        assert "'TRUE'" in self._t("SELECT id FROM flags WHERE label = 'TRUE'")
