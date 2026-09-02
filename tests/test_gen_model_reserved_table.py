"""`generate model` on a reserved-word class name (issue #123).

The scaffolder no longer renames silently: it auto-pluralises a reserved-word
table (`Order` -> `orders`, the SAFE choice, because Tina4 interpolates table
names UNQUOTED) but says so out loud, and `--table-name` lets the developer force
their own name (owning the quoting in raw SQL if it is itself reserved). No ORM
quoting change -- identifier quoting is a global storage invariant, not a local
fix, so that footgun stays shut.

No mocks: the resolver is a pure function; the end-to-end tests generate a REAL
model file and read it back.
"""
import pytest

from tina4_python.cli import _gen_model, _resolve_table


class TestResolveTable:
    def test_non_reserved_stays_singular_and_silent(self, capsys):
        assert _resolve_table("Product", {}, announce=True) == "product"
        assert capsys.readouterr().out == ""

    def test_reserved_pluralised_with_a_loud_note(self, capsys):
        assert _resolve_table("Order", {}, announce=True) == "orders"
        out = capsys.readouterr().out
        assert "order" in out and "reserved" in out and "--table-name" in out

    def test_reserved_is_silent_when_not_announcing(self, capsys):
        # Composite / existing-table generators resolve the same name without repeating the note.
        assert _resolve_table("Order", {}) == "orders"
        assert capsys.readouterr().out == ""

    def test_table_name_override_wins_verbatim(self, capsys):
        assert _resolve_table("Order", {"table-name": "customer_orders"}, announce=True) == "customer_orders"
        assert capsys.readouterr().out == ""  # a non-reserved override needs no warning

    def test_forcing_a_reserved_override_warns_but_obeys(self, capsys):
        assert _resolve_table("Order", {"table-name": "select"}, announce=True) == "select"
        out = capsys.readouterr().out
        assert "select" in out and "reserved" in out and "UNQUOTED" in out

    def test_bare_table_name_flag_is_ignored(self):
        # `--table-name` with no value parses to True; it must not become the table.
        assert _resolve_table("Order", {"table-name": True}, announce=True) == "orders"


class TestGenerateModelEndToEnd:
    def test_reserved_class_gets_plural_table_and_a_note(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        _gen_model("Order", {"no-migration": True}, emit_test=False)
        content = (tmp_path / "src" / "orm" / "Order.py").read_text()
        assert 'table_name = "orders"' in content
        assert "reserved" in capsys.readouterr().out

    def test_table_name_override_is_used_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _gen_model("Order", {"no-migration": True, "table-name": "my_orders"}, emit_test=False)
        content = (tmp_path / "src" / "orm" / "Order.py").read_text()
        assert 'table_name = "my_orders"' in content
