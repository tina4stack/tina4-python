"""Lock-in: column names mirror the DATABASE verbatim, and `auto_map` is INERT here.

Owner rule (2026-07-29): "Keep the column name exactly as it is in the DATABASE.
A language-specific case mapping may be an OPT-IN later, but the default must
mirror the DB so nobody guesses wrong."

Python and Ruby are snake_case-native: the attribute name a developer writes IS
the column name, so there is nothing for a case mapping to do. `auto_map` exists
only so a model ported from PHP (where `autoMap` really does map a camelCase
property onto a snake_case column) does not blow up on an unknown attribute.

It was DEAD in a worse sense than "does nothing": nothing read it at all, so a
developer setting `auto_map = False` to "turn the conversion off" got silence and
could reasonably believe they had changed something. These tests make the
inertness EXPLICIT and VERIFIED, so it cannot quietly grow behaviour later
without a named test going red -- which is what a future opt-in would have to do
deliberately.

Deliberately NOT tested-for, because decision A forbids it: camelCase attribute
-> snake_case column conversion. If that is ever added it must be OPT-IN, and
`test_auto_map_false_changes_nothing` below is the tripwire.

Engine-agnostic (real SQLite).
"""

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, Field, bind_database


class CaseSnake(ORM):
    """Attributes named exactly as the DB columns -- the Python-native way."""

    table_name = "case_probe"
    id = Field(int, primary_key=True, auto_increment=True)
    first_name = Field(str)


class CaseAutoMapOff(ORM):
    """Same model with auto_map explicitly OFF. Must behave IDENTICALLY."""

    table_name = "case_probe"
    auto_map = False
    id = Field(int, primary_key=True, auto_increment=True)
    first_name = Field(str)


class CaseExplicitMap(ORM):
    """field_mapping is the supported way to point an attribute at a column."""

    table_name = "case_probe"
    field_mapping = {"given_name": "first_name"}
    id = Field(int, primary_key=True, auto_increment=True)
    given_name = Field(str)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'case.db'}")
    d.execute(
        "CREATE TABLE case_probe ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  first_name TEXT"
        ")"
    )
    d.commit()
    bind_database(d)
    yield d
    d.close()


class TestColumnNamesAreVerbatim:
    def test_the_column_in_the_database_is_the_declared_name(self, db):
        m = CaseSnake({"first_name": "Ada"})
        assert m.save() is m
        row = db.fetch_one("SELECT id, first_name FROM case_probe")
        assert row["first_name"] == "Ada", "the value must land in the verbatim column"

    def test_a_verbatim_attribute_is_populated_on_read(self, db):
        # The PHP twin of this test caught a real bug: PHP SAVED correctly and
        # READ BACK None, because autoMap re-pointed the column at a camelCase
        # property the model never declared. Python has no such conversion, so
        # this must simply hold -- and now it is pinned.
        CaseSnake({"first_name": "Ada"}).save()
        back = CaseSnake.find(1)
        assert back is not None
        assert back.first_name == "Ada"

    def test_the_field_column_metadata_is_the_attribute_name(self, db):
        # No conversion anywhere in the field metadata either.
        assert CaseSnake._fields["first_name"].column == "first_name"


class TestAutoMapIsInert:
    """`auto_map` is a parity placeholder in Python. If any of these go red,
    someone has given it behaviour -- which decision A says must be OPT-IN."""

    def test_auto_map_defaults_true_for_parity_with_php(self):
        assert CaseSnake.auto_map is True

    def test_auto_map_false_changes_nothing(self, db):
        # THE TRIPWIRE. Same save/read with auto_map off must be identical.
        m = CaseAutoMapOff({"first_name": "Grace"})
        assert m.save() is m
        row = db.fetch_one("SELECT first_name FROM case_probe")
        assert row["first_name"] == "Grace", "auto_map must not affect the column"

        back = CaseAutoMapOff.find(1)
        assert back.first_name == "Grace"
        assert CaseAutoMapOff._fields["first_name"].column == "first_name"


class TestExplicitMappingIsTheSupportedMechanism:
    def test_field_mapping_points_an_attribute_at_a_differently_named_column(self, db):
        m = CaseExplicitMap({"given_name": "Hedy"})
        assert m.save() is m
        row = db.fetch_one("SELECT first_name FROM case_probe")
        assert row["first_name"] == "Hedy", "field_mapping must drive the write"

        back = CaseExplicitMap.find(1)
        assert back.given_name == "Hedy", "field_mapping must drive the read"
