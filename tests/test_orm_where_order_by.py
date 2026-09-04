# Lock-in tests for Model.where(order_by=...) — v3.13.66 ORM where-ordering parity.
#
# where() was the only filtered finder that could not order its results
# (find / all / QueryBuilder all could). These tests pin the new behaviour:
#   * order_by sorts the filtered result (ASC and DESC)
#   * omitting order_by injects NO ORDER BY (rows come back in natural order)
#   * the ModelCollection total (get_total_records) is right even with order_by,
#     because the fetch COUNT probe strips the trailing ORDER BY (a leaked ORDER
#     BY would make the ordinal form raise)
#
# Real SQLite, no mocks. Rows are inserted OUT OF alphabetical order so a
# missing or extra ORDER BY is directly observable in the output.
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, Field


class WPerson(ORM):
    table_name = "wpeople"
    id = Field(int, primary_key=True, auto_increment=True)
    name = Field(str)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'where_order.db'}")
    d.execute("CREATE TABLE wpeople (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    # Inserted out of alphabetical order: Charlie(id=1), Alice(id=2), Bob(id=3)
    d.execute("INSERT INTO wpeople (name) VALUES (?)", ["Charlie"])
    d.execute("INSERT INTO wpeople (name) VALUES (?)", ["Alice"])
    d.execute("INSERT INTO wpeople (name) VALUES (?)", ["Bob"])
    d.commit()
    bind_database(d)
    yield d
    d.close()


def test_order_by_asc_sorts_results(db):
    rows = WPerson.where("1=1", order_by="name ASC")
    assert [r.name for r in rows] == ["Alice", "Bob", "Charlie"]


def test_order_by_desc_reverses_results(db):
    # id DESC -> 3, 2, 1 -> Bob, Alice, Charlie
    rows = WPerson.where("1=1", order_by="id DESC")
    assert [r.name for r in rows] == ["Bob", "Alice", "Charlie"]


def test_without_order_by_is_unchanged(db):
    # negative: no order_by -> no ORDER BY injected -> natural (insertion) order
    rows = WPerson.where("1=1")
    assert [r.name for r in rows] == ["Charlie", "Alice", "Bob"]


def test_collection_returns_ordered_rows_and_total(db):
    rows = WPerson.where("1=1", order_by="name ASC")
    assert [r.name for r in rows] == ["Alice", "Bob", "Charlie"]
    assert rows.get_total_records() == 3


def test_order_by_does_not_break_the_total(db):
    # The COUNT probe must NOT carry the ORDER BY. Proven for real via an ordinal
    # ORDER BY: "SELECT * ... ORDER BY 2" is valid (orders by the 2nd column,
    # name), but "SELECT COUNT(*) FROM (... ORDER BY 2)" is out of range in SQLite
    # (a single output column) and raises. The fetch probe strips the trailing
    # ORDER BY, so the total computes cleanly. If that strip regresses, this reds.
    rows = WPerson.where("1=1", order_by="2")
    assert [r.name for r in rows] == ["Alice", "Bob", "Charlie"]
    assert rows.get_total_records() == 3
