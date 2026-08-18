"""Regression: Model.clear_cache() must invalidate BOTH cache layers.

PY-06-22 (3.13.105). Before the fix, Model.clear_cache() cleared only the
ORM-layer tag cache (`_query_cache`) and left the DB-layer cache alone --
so a caller using it as a manual escape hatch (an out-of-band write, a
race with another process, a deliberate refresh) still read stale rows
from db.fetch() on the next query.

The invariant: after Model.clear_cache(), db.cache_stats()['size'] on
this model's connection is 0. Named positive AND negative cases; proven
a real gate by mutation (revert the cascade call -- both fail).

NOT a mock: real SQLite Database instances, real query-cache round-trip.
"""
from __future__ import annotations

import os
import tempfile

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField


class Widget622(ORM):
    table_name = "widgets_622"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


def _make_db(path):
    db = Database(f"sqlite:///{path}")
    db.execute(
        "CREATE TABLE widgets_622 "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
    )
    db.execute("INSERT INTO widgets_622 (name) VALUES ('one'), ('two')")
    return db


class TestClearCacheCascadesToDbLayer:
    def setup_method(self, _method):
        # Both cache layers opted in -- the only combination in which
        # PY-06-22 is reachable.
        os.environ["TINA4_AUTO_CACHING"] = "true"
        os.environ["TINA4_DB_CACHE"] = "true"
        os.environ["TINA4_DB_CACHE_BACKEND"] = "memory"
        self._paths = []

    def teardown_method(self, _method):
        for p in self._paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        for k in ("TINA4_AUTO_CACHING", "TINA4_DB_CACHE", "TINA4_DB_CACHE_BACKEND"):
            os.environ.pop(k, None)
        Widget622._db = None

    def _fresh_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._paths.append(tmp.name)
        return _make_db(tmp.name)

    def test_positive_clear_cache_cascades_to_db_layer(self):
        """After Model.clear_cache(), the DB-layer cache is empty."""
        db = self._fresh_db()
        Widget622._db = db
        Widget622.cached("SELECT * FROM widgets_622", ttl=60)
        assert db.cache_stats()["size"] > 0, (
            "prime failed: db cache did not populate on the cached() read"
        )

        Widget622.clear_cache()

        assert db.cache_stats()["size"] == 0, (
            "clear_cache() did not cascade to db.cache_clear(); "
            "db cache still holds stale rows"
        )

    def test_negative_clear_cache_leaves_unrelated_dbs_alone(self):
        """A model bound to db_a calling clear_cache() must NOT touch
        an unrelated db_b (the cascade is scoped to this model's own
        connection, matching how writes already behave)."""
        db_a = self._fresh_db()
        db_b = self._fresh_db()
        Widget622._db = db_a
        db_a.fetch("SELECT * FROM widgets_622")
        db_b.fetch("SELECT * FROM widgets_622")
        assert db_a.cache_stats()["size"] > 0
        assert db_b.cache_stats()["size"] > 0

        Widget622.clear_cache()

        assert db_a.cache_stats()["size"] == 0, (
            "db_a is Widget622's bound connection and must have been cleared"
        )
        assert db_b.cache_stats()["size"] > 0, (
            "db_b (unrelated connection) must NOT be cleared by Widget622.clear_cache()"
        )
