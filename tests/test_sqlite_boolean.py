# Regression: a boolean field must round-trip through the real SQLite driver as
# 0/1. Python's sqlite3 binds bool natively (bool subclasses int), so this is a
# lock-in test for the cross-framework boolean-coercion contract (Node and Ruby
# coerce at their bind boundary; Python is the master and already correct). No
# mocks — a real in-memory SQLite database.
from tina4_python.database import Database


def test_raw_boolean_binds_as_0_1():
    db = Database("sqlite::memory:")
    db.execute("CREATE TABLE flags (id INTEGER PRIMARY KEY, flag INTEGER, name TEXT)")
    db.execute("INSERT INTO flags (flag, name) VALUES (?, ?)", [True, "on"])
    db.execute("INSERT INTO flags (flag, name) VALUES (?, ?)", [False, "off"])
    rows = db.fetch("SELECT flag FROM flags ORDER BY id").records
    assert [r["flag"] for r in rows] == [1, 0]


def test_seed_table_boolean_column_coerces():
    from tina4_python.seeder import seed_table

    db = Database("sqlite::memory:")
    db.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, active INTEGER)")
    seed_table(db, "widgets", count=4, field_map={
        "name": lambda: "w",
        "active": lambda: True,
    })
    rows = db.fetch("SELECT active FROM widgets").records
    assert len(rows) == 4
    assert all(r["active"] in (0, 1) for r in rows)
