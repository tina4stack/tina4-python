"""Firebird identifier folding + primary-key introspection (regression).

Both bugs were found by running the real adapter against a LIVE Firebird 5.0.4;
neither was reachable from a unit test that never touched the engine.

1. Firebird folds an UNQUOTED identifier to UPPER CASE and treats a QUOTED one as
   case-sensitive. The base quote_identifier emitted `"probe_t"`, which matches
   nothing after `CREATE TABLE probe_t`, so insert/update/delete/truncate failed
   with "Table unknown" against every conventionally-created table.

2. get_columns hardcoded `primary_key: False` for every column -- it never
   queried the constraint catalogue at all. primary_key() therefore always
   returned [] on Firebird, which silently breaks anything introspecting the key,
   including the filterless-write guard that lifts the PK out of `data`.

The quoting half is pure string logic and needs no server, so it is asserted
unconditionally. The introspection half needs a real Firebird and is gated on
TINA4_TEST_FIREBIRD_URL.
"""

import os

import pytest

from tina4_python.database.firebird import FirebirdAdapter


def _adapter() -> FirebirdAdapter:
    """A bare adapter -- quote_identifier is pure and touches no connection."""
    return object.__new__(FirebirdAdapter)


class TestFirebirdIdentifierFolding:
    def test_plain_name_is_upper_cased_to_match_firebird_storage(self):
        # THE bug: "probe_t" matched nothing because Firebird stored PROBE_T.
        assert _adapter().quote_identifier("probe_t") == '"PROBE_T"'

    def test_an_already_upper_name_is_unchanged(self):
        assert _adapter().quote_identifier("ORDERS") == '"ORDERS"'

    def test_an_already_quoted_name_is_passed_through_untouched(self):
        # The escape hatch for a genuinely case-sensitive CREATE TABLE "orders".
        assert _adapter().quote_identifier('"orders"') == '"orders"'

    def test_a_dotted_name_folds_each_part(self):
        assert _adapter().quote_identifier("schema.tbl") == '"SCHEMA"."TBL"'

    def test_an_expression_is_never_quoted(self):
        # Negative half: hand-written SQL must keep working.
        assert _adapter().quote_identifier("COUNT(*)") == "COUNT(*)"
        assert _adapter().quote_identifier("*") == "*"

    def test_an_empty_name_is_returned_as_is(self):
        assert _adapter().quote_identifier("") == ""


@pytest.mark.skipif(
    not os.environ.get("TINA4_TEST_FIREBIRD_URL"),
    reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)
class TestFirebirdLivePrimaryKey:
    """Real Firebird. No doubles: get_columns must read the actual catalogue."""

    @pytest.fixture
    def db(self):
        from tina4_python.database import Database

        d = Database(os.environ["TINA4_TEST_FIREBIRD_URL"], "SYSDBA", "masterkey")
        try:
            d.execute("DROP TABLE pk_probe")
        except Exception:  # noqa: BLE001 - first run has nothing to drop
            pass
        d.execute(
            "CREATE TABLE pk_probe ("
            "  id INTEGER NOT NULL, "
            "  code VARCHAR(10) NOT NULL, "
            "  label VARCHAR(50), "
            "  PRIMARY KEY (id, code)"
            ")"
        )
        yield d
        try:
            d.execute("DROP TABLE pk_probe")
        except Exception:  # noqa: BLE001
            pass
        d.close()

    def test_get_columns_flags_every_primary_key_column(self, db):
        cols = db.get_columns("pk_probe")
        flagged = {c["name"].strip().upper() for c in cols if c["primary_key"]}
        # A COMPOSITE key: both columns, or a WHERE built from it matches too many
        # rows. This is the same class of bug that truncated the SQLite key.
        assert flagged == {"ID", "CODE"}, f"got {flagged} from {cols}"

    def test_non_key_columns_are_not_flagged(self, db):
        cols = db.get_columns("pk_probe")
        label = next(c for c in cols if c["name"].strip().upper() == "LABEL")
        assert label["primary_key"] is False

    def test_primary_key_helper_returns_the_composite_key(self, db):
        # The public contract the filterless-write guard actually calls.
        assert {c.upper() for c in db.primary_key("pk_probe")} == {"ID", "CODE"}

    def test_insert_targets_the_folded_table_name(self, db):
        # The insert path that raised "Table unknown - pk_probe" before the fix.
        assert db.insert("pk_probe", {"id": 1, "code": "A", "label": "alpha"})
        assert db.fetch("SELECT id FROM pk_probe").count == 1
