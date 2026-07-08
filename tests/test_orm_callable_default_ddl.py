"""Regression for issue #61: create_table() must OMIT callable field defaults from DDL.

A callable default (e.g. ``DateTimeField(default=lambda: datetime.now())``, a documented
timestamp idiom) was stringified into the CREATE TABLE DDL as ``DEFAULT <function ...>``,
which is invalid SQL. ``create_table()`` logged the error but did not raise, so the table
was silently never created and a later ``.save()`` / ``.all()`` failed with "no such table".

Callable defaults are already resolved per-row at insert time (``_resolve_default``, #50),
so they must not appear in the DDL at all. A static default still belongs in the DDL.

NOT a mock: real SQLite Database, real create_table DDL execution, real save/all round-trip.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

from tina4_python.database import Database
from tina4_python.orm import bind_database, ORM, IntegerField, StringField, DateTimeField


class TestCallableDefaultDdl:
    def setup_method(self, _method):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._db_path = tmp.name
        bind_database(Database(f"sqlite:///{self._db_path}"))

    def teardown_method(self, _method):
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def test_create_table_omits_callable_default_and_round_trips(self):
        class NoteCd61(ORM):
            table_name = "note_cd61"
            id = IntegerField(primary_key=True, auto_increment=True)
            title = StringField(default="untitled")                 # static -> stays in DDL
            created_at = DateTimeField(default=lambda: datetime.now())  # callable -> omitted

        # Before #61 this returned False (DDL had `DEFAULT <function ...>`, sqlite syntax error).
        assert NoteCd61.create_table() is True, \
            "create_table must succeed: a callable default is omitted from the DDL, not stringified"

        # The table really exists and a row round-trips; the callable default is
        # resolved per-row at insert (not by the database).
        note = NoteCd61(title="hello")
        assert note.save() is not False, "save() must succeed against the created table"

        rows = NoteCd61.all()
        assert len(rows) == 1
        assert rows[0].title == "hello"
        assert rows[0].created_at is not None, "callable default resolved at insert time (#50)"
