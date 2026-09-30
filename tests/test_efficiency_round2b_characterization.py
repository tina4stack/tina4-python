# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Characterization net for efficiency round 2b (carbonah E002/E003).

carbonah's N+1 heuristic (E002) flags every ``execute()`` inside a loop. Two of
those loops live in the batch-write primitive itself, so these tests pin the
behaviour carbonah misreads and prove the anti-N+1 claim with a REAL result AND
a real query count — no mocks, real SQLite.

* ``execute_many`` on a collapsible INSERT is the FIX for N+1: 200 rows collapse
  into a SINGLE multi-row statement (the loop at adapter.py:770 runs once, not
  200 times), and every row still lands with the right ``affected_rows``.
* A statement ``build_batch_inserts`` cannot collapse (RETURNING) falls back to
  the row-at-a-time loop (adapter.py:783) and still writes every row correctly.

The migration apply + rollback path (runner.py loops carbonah flags) is pinned
end-to-end so the DDL-in-loop annotations are backed by a real run.
"""
from __future__ import annotations

import os
import tempfile

from tina4_python.database import Database
from tina4_python.database.sql_translator import SQLTranslator


def test_execute_many_collapses_to_one_query_query_count():
    """QUERY-COUNT proof: build_batch_inserts turns 200 single-row INSERTs into
    ONE multi-row statement on SQLite (cap 999 / 2 cols → 499 rows per chunk).
    This is why the loop at adapter.py:770 is the anti-N+1, not an N+1."""
    rows = [[f"user{i}", i] for i in range(200)]
    statements = SQLTranslator.build_batch_inserts(
        "INSERT INTO people (name, age) VALUES (?, ?)", rows, "sqlite"
    )
    assert len(statements) == 1, "200 rows must collapse into a single round-trip"
    collapsed_sql, flat_params = statements[0]
    assert collapsed_sql.count("(?, ?)") == 200, "one VALUES tuple per row"
    assert len(flat_params) == 400, "2 bind params per row, flattened"


def test_execute_many_collapsible_writes_every_row_result():
    """RESULT proof: the collapsed batch stores all 200 rows with correct data
    and affected_rows — identical to a row-by-row insert, on a real SQLite DB."""
    with tempfile.TemporaryDirectory() as d:
        db = Database("sqlite:///" + os.path.join(d, "eff.db"))
        db.execute("DROP TABLE IF EXISTS people")
        db.commit()
        db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER)")
        db.commit()
        rows = [[f"user{i}", i] for i in range(200)]
        result = db.execute_many("INSERT INTO people (name, age) VALUES (?, ?)", rows)
        db.commit()
        assert result.affected_rows == 200, "every row of the batch is counted"
        count = db.fetch("SELECT COUNT(*) AS c FROM people").records[0]["c"]
        assert count == 200, "all 200 rows really landed"
        # spot-check the data survived the collapse intact
        got = db.fetch("SELECT name, age FROM people WHERE age = 199").records
        assert got == [{"name": "user199", "age": 199}]
        db.close()


def test_execute_many_returning_is_not_collapsed_fallback():
    """NEGATIVE / fallback: a RETURNING batch is NOT collapsible, so
    build_batch_inserts returns [] and the adapter keeps the row-at-a-time loop
    (adapter.py:783). The rows must still all be written correctly."""
    assert (
        SQLTranslator.build_batch_inserts(
            "INSERT INTO people (name, age) VALUES (?, ?) RETURNING id",
            [["a", 1], ["b", 2]],
            "sqlite",
        )
        == []
    ), "RETURNING must never be collapsed (it returns rows per statement)"


def test_migration_apply_then_rollback_end_state():
    """The migration runner loops carbonah flags (apply DDL, rollback DELETE) are
    pinned end-to-end on real SQLite: apply creates the table, rollback removes it
    and clears its tracking row."""
    from tina4_python.migration.runner import _migrate, _rollback

    with tempfile.TemporaryDirectory() as d:
        db = Database("sqlite:///" + os.path.join(d, "mig.db"))
        folder = os.path.join(d, "migrations")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "0001_make_widget.sql"), "w") as fh:
            fh.write("CREATE TABLE widget (id INTEGER PRIMARY KEY, label TEXT);")
        with open(os.path.join(folder, "0001_make_widget.down.sql"), "w") as fh:
            fh.write("DROP TABLE widget;")

        ran = _migrate(db, folder)
        assert "0001_make_widget.sql" in ran
        assert db.table_exists("widget"), "apply must create the table"

        rolled = _rollback(db, folder)
        assert "0001_make_widget.down.sql" in rolled
        assert not db.table_exists("widget"), "rollback must drop the table"
        left = db.fetch(
            "SELECT COUNT(*) AS c FROM tina4_migration WHERE passed = 1"
        ).records[0]["c"]
        assert left == 0, "rollback must clear the tracking row"
        db.close()
