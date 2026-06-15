"""Regression test — DatabaseResult is subscriptable (doc-verification finding F4).

The book (ch5 §4 "Index Access") documents ``result[0]`` to get the first
row, but DatabaseResult had no ``__getitem__`` and raised
``TypeError: 'DatabaseResult' object is not subscriptable``. Index and slice
access now delegate to ``.records``. No database required for the unit checks;
a SQLite round-trip confirms it on a real fetch.
"""
import tempfile

from tina4_python.database.adapter import DatabaseResult
from tina4_python.database import Database


def test_index_access():
    r = DatabaseResult(records=[{"id": 1}, {"id": 2}, {"id": 3}], count=3)
    assert r[0] == {"id": 1}
    assert r[2] == {"id": 3}
    assert r[-1] == {"id": 3}


def test_slice_access():
    r = DatabaseResult(records=[{"id": 1}, {"id": 2}, {"id": 3}], count=3)
    assert r[0:2] == [{"id": 1}, {"id": 2}]
    assert r[1:] == [{"id": 2}, {"id": 3}]


def test_len_and_iter_still_work():
    r = DatabaseResult(records=[{"id": 1}, {"id": 2}], count=2)
    assert len(r) == 2
    assert [row["id"] for row in r] == [1, 2]


def test_index_access_on_real_fetch():
    with tempfile.NamedTemporaryFile(suffix=".db") as tf:
        db = Database(f"sqlite:///{tf.name}")
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        db.execute("INSERT INTO t (name) VALUES ('alice')")
        db.execute("INSERT INTO t (name) VALUES ('bob')")
        db.commit()
        result = db.fetch("SELECT * FROM t ORDER BY id")
        assert result[0]["name"] == "alice"   # the exact documented form
        assert result[1]["name"] == "bob"
        db.close()
