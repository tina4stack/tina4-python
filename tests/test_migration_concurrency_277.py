# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression for tina4-python#277: startup auto-migration is serialized across
processes, so a data migration applies exactly once under concurrency.

No mocks. This spawns several REAL OS processes (not threads — the bug is
cross-process; threads would share one interpreter and one connection) that each
open the SAME SQLite database and call migrate() at the same moment. A data
migration sleeps before it inserts, to widen the window in which two unsynchronized
runs would both decide the migration is pending and both insert. The assertion is
the observable outcome: the row exists exactly once, and the tracker holds one row
per migration.

Without the run-wide lock in runner._migrate() every overlapping process inserts
its own copy (SQLite's own write lock serializes the INSERT but does not stop two
runs from each deciding to apply); with it, the winner migrates while the rest
block, then re-read the applied set and find nothing pending.

SQLite is the engine exercised here because it is the one a test host always has.
The PostgreSQL/MySQL/MSSQL advisory-lock paths and the Firebird file-lock path are
covered by the lab's real-service concurrency run.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest

WORKERS = 8


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))


@pytest.fixture
def migration_project(tmp_path):
    """A temp project: a shared SQLite file + two migrations, one a slow insert."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()

    _write(migrations / "000001_create_widgets.sql", """
        CREATE TABLE widgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
    """)

    # A data migration that takes a moment before it writes — a real backfill.
    # The sleep guarantees overlap: every worker is inside up() at once, so an
    # unsynchronized run inserts WORKERS copies of 'first'.
    _write(migrations / "000002_seed_first.py", """
        import time
        from tina4_python.migration import MigrationBase

        class SeedFirst(MigrationBase):
            def up(self, db):
                time.sleep(0.6)
                db.execute("INSERT INTO widgets (name) VALUES ('first')")

            def down(self, db):
                db.execute("DELETE FROM widgets WHERE name = 'first'")
    """)

    db_file = tmp_path / "app.db"
    worker = tmp_path / "worker.py"
    _write(worker, f"""
        import os, sys
        os.chdir({str(tmp_path)!r})
        from tina4_python.database import Database
        from tina4_python.migration import migrate
        db = Database("sqlite:///" + {str(db_file)!r})
        try:
            migrate(db)
        except Exception as exc:
            sys.stderr.write("worker error: " + str(exc) + "\\n")
        finally:
            try:
                db.close()
            except Exception:
                pass
    """)

    return {"dir": str(tmp_path), "worker": str(worker), "db": str(db_file)}


def test_concurrent_startup_migrations_apply_each_migration_once(migration_project):
    env = dict(os.environ)
    # Make the child import tina4_python from this checkout regardless of cwd.
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")

    # Launch all workers as close to simultaneously as possible.
    procs = [
        subprocess.Popen(
            [sys.executable, migration_project["worker"]],
            cwd=migration_project["dir"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(WORKERS)
    ]
    deadline = time.monotonic() + 60
    for p in procs:
        p.wait(timeout=max(1, int(deadline - time.monotonic())))

    stderrs = [p.stderr.read() if p.stderr else "" for p in procs]

    conn = sqlite3.connect(migration_project["db"])
    try:
        first_rows = conn.execute(
            "SELECT count(*) FROM widgets WHERE name = 'first'"
        ).fetchone()[0]
        tracker_rows = conn.execute(
            "SELECT count(*) FROM tina4_migration WHERE migration_name = '000002_seed_first'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert first_rows == 1, (
        f"the data migration must apply exactly once under {WORKERS} concurrent "
        f"starts, got {first_rows} rows named 'first'. Worker stderr: {stderrs}"
    )
    assert tracker_rows == 1, (
        f"the tracker must hold exactly one row for the migration, got {tracker_rows}"
    )


def test_file_lock_sidecar_lives_in_system_temp_not_the_migrations_folder(tmp_path):
    """The advisory lock file must NOT be written inside the tracked migrations/
    folder — a dotfile there gets committed by accident and blocks a plain rmdir.
    It lives in the system temp dir, keyed by the ABSOLUTE migrations path, so
    every worker of the same app lands on the same file (parity with the PHP
    reference Migration::fileLockPath()). Mutation: point it back into the folder
    and this test goes red.
    """
    from tina4_python.migration.runner import _file_lock_path

    migrations = tmp_path / "migrations"
    migrations.mkdir()

    path = _file_lock_path(str(migrations))

    temp_root = os.path.realpath(tempfile.gettempdir())
    assert os.path.realpath(path).startswith(temp_root + os.sep), (
        f"lock file must live under the system temp dir {temp_root}, got {path}"
    )
    assert os.path.commonpath([os.path.realpath(path), os.path.realpath(str(migrations))]) != os.path.realpath(str(migrations)), (
        f"lock file must NOT live inside the migrations folder, got {path}"
    )
    assert os.path.basename(path).startswith("tina4-migration-"), (
        f"lock file name must be tina4-migration-<hash>.lock, got {os.path.basename(path)}"
    )
    assert path.endswith(".lock")

    # Stable for a given absolute path, and a relative path resolves to the same
    # file as its absolute form — so workers started with different cwd spellings
    # of the same folder still serialize against one lock.
    assert _file_lock_path(str(migrations)) == path
    cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        assert _file_lock_path("migrations") == path
    finally:
        os.chdir(cwd)

    # A different app (different absolute path) gets a different lock.
    other = tmp_path / "other" / "migrations"
    other.mkdir(parents=True)
    assert _file_lock_path(str(other)) != path
