# Lock-in contract: EVERY ORM read path that takes a `limit` caps at 100 by default.
#
# Pagination is a default principle in Tina4: an un-paginated read of a table
# that grew to a million rows is a memory and latency incident waiting for
# production. Before this contract the family disagreed with ITSELF about the
# number -- Python and PHP capped `all`/`find` at 100 but `select`/`where`/
# `with_trashed`/`cached`/`scope` at 20, Ruby's `all`/`select`/`where` passed
# `limit: nil` and so returned EVERYTHING, and Node's `all`/`select` had no
# limit parameter at all. Four frameworks, four answers, same method names.
#
# One number, everywhere: 100.
#
# These tests are deliberately BEHAVIOURAL, never source-reading. They insert
# 150 rows and count what comes back, so the contract cannot be satisfied by a
# signature that says 100 while the body ignores it, and it cannot rot into a
# grep of the default value.
#
# Two paths are EXCLUDED from the cap, on purpose, and each exclusion has its
# own negative test below so the exclusion is a decision on the record rather
# than an oversight:
#
#   * QueryBuilder.get() -- uncapped since v3.13.39. A silent default LIMIT 100
#     there was a data-loss-on-read footgun: `.where(...).get()` dropped the
#     101st row with no signal at all, because get() has no `limit` parameter to
#     make the cap visible. Re-adding it would re-introduce that exact bug.
#   * fetch_all() -- its name IS the request for every row, and its documented
#     `limit=0` sentinel means "no truncation".
#
# The distinction that reconciles the two groups: a path whose signature
# ADVERTISES `limit` caps at 100 (the cap is visible, documented, overridable in
# the call); a path with NO limit parameter must never cap, because there the
# cap can only ever be silent.
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, Field, bind_database
from tina4_python.query_builder import QueryBuilder

ROWS = 150
CAP = 100


class Widget(ORM):
    table_name = "cap_widgets"
    id = Field(int, primary_key=True, auto_increment=True)
    label = Field(str)
    is_deleted = Field(int)

    soft_delete = True


@pytest.fixture
def db(tmp_path):
    """A real SQLite database holding MORE rows than the cap."""
    d = Database(f"sqlite:///{tmp_path / 'row_cap.db'}")
    d.execute(
        "CREATE TABLE cap_widgets ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  label TEXT,"
        "  is_deleted INTEGER DEFAULT 0"
        ")"
    )
    d.execute_many(
        "INSERT INTO cap_widgets (label, is_deleted) VALUES (?, ?)",
        [[f"w{i}", 0] for i in range(ROWS)],
    )
    d.commit()
    bind_database(d)
    assert d.fetch_one("SELECT COUNT(*) AS c FROM cap_widgets")["c"] == ROWS
    yield d
    d.close()


class TestDefaultCapIsOneHundred:
    """Called with NO limit argument, each path returns exactly 100 rows."""

    def test_all(self, db):
        assert len(Widget.all()) == CAP

    def test_find(self, db):
        assert len(Widget.find({})) == CAP

    def test_select(self, db):
        # Was 20. A caller asking for a page got a fifth of one.
        assert len(Widget.select("SELECT * FROM cap_widgets")) == CAP

    def test_where(self, db):
        assert len(Widget.where("1=1")) == CAP

    def test_with_trashed(self, db):
        assert len(Widget.with_trashed()) == CAP

    def test_cached(self, db):
        assert len(Widget.cached("SELECT * FROM cap_widgets")) == CAP

    def test_scope(self, db):
        Widget.scope("every", "1=1")
        assert len(Widget.every()) == CAP

    def test_db_fetch(self, db):
        # len(records), NOT .count -- `count` is the TOTAL matching rows (what
        # pagination needs), so it stays 150 regardless of the cap. Asserting
        # .count here would test nothing about truncation.
        assert len(db.fetch("SELECT * FROM cap_widgets").records) == CAP


class TestAnExplicitLimitStillWins:
    """The negative half: the cap is a DEFAULT, not a ceiling. A caller who
    asks for more gets more, and a caller who asks for less gets less. Without
    these, a hardcoded `LIMIT 100` would satisfy every test above."""

    def test_smaller_limit_is_honoured(self, db):
        assert len(Widget.select("SELECT * FROM cap_widgets", limit=7)) == 7
        assert len(Widget.where("1=1", limit=7)) == 7
        assert len(Widget.all(limit=7)) == 7
        assert len(Widget.with_trashed(limit=7)) == 7
        assert len(Widget.cached("SELECT * FROM cap_widgets", limit=7)) == 7

    def test_larger_limit_reaches_past_the_cap(self, db):
        assert len(Widget.select("SELECT * FROM cap_widgets", limit=ROWS)) == ROWS
        assert len(Widget.where("1=1", limit=ROWS)) == ROWS
        assert len(Widget.all(limit=ROWS)) == ROWS
        assert len(Widget.with_trashed(limit=ROWS)) == ROWS
        assert len(db.fetch("SELECT * FROM cap_widgets", limit=ROWS).records) == ROWS


class TestTheDeliberateExclusions:
    """Paths with NO limit parameter must stay UNCAPPED. A cap that the
    signature cannot express is a silent cap, which is the footgun."""

    def test_query_builder_get_returns_every_row(self, db):
        # v3.13.39 removed a silent LIMIT 100 here. If this goes red, it came back.
        assert len(QueryBuilder.from_table("cap_widgets").get().records) == ROWS

    def test_query_builder_honours_an_explicit_limit(self, db):
        assert len(QueryBuilder.from_table("cap_widgets").limit(9).get().records) == 9

    def test_fetch_all_returns_every_row(self, db):
        # The name is the request. limit=0 is its documented no-truncation value.
        assert len(db.fetch_all("SELECT * FROM cap_widgets")) == ROWS
