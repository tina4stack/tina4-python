# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression for tina4-python#277 on the PostgreSQL native-lock path.

The SQLite sibling (test_migration_concurrency_277.py) proves the OS file-lock
fallback. This one proves the PostgreSQL advisory lock — pg_advisory_lock(k) /
pg_advisory_unlock(k) — serializes concurrent startup migrations across real OS
processes.

What the lock changes on PostgreSQL. The tracker's UNIQUE(migration_name) plus the
per-file transaction already backstop the widget double-insert (a losing worker's
tracker INSERT violates the unique key and rolls its whole transaction back), so
the row count alone is a racy signal. The clean, deterministic signal is the BOOT
outcome: without the lock every losing worker hits that UniqueViolation and its
migrate() RAISES — the boot fails — and the data row count wobbles between one and
a few. With the lock the winner migrates while the rest block, then re-read the
applied set, find nothing pending, and every worker boots clean: zero worker
errors AND exactly one data row, every run.

The widget table is pre-created in the fixture, not by a migration, on purpose: a
concurrent CREATE TABLE serializes on PostgreSQL's own catalog locks down to a
single survivor, which would mask the data-migration race this test exists to
catch. Mutation: remove the lock in runner._acquire_migration_lock and the
workers boot with UniqueViolation errors — the test goes red.

No mocks. It boots a live PostgreSQL (env-configurable, default localhost:55432,
same gate as test_migration_postgres.py) and SKIPS when none is reachable, so the
local SQLite proof always runs while the native path runs on the lab/CI where
PostgreSQL is provisioned. Mutation: remove the lock in runner._acquire_migration_lock
and this test goes red with several 'first' rows.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from tina4_python.database import Database

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")

WORKERS = 8
WIDGET_TABLE = "widgets_pg277"
MIGRATION_NAMES = ("000001_seed_first_pg277",)


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"[needs:postgres] PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (skip)",
)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))


def _pg_url() -> str:
    return f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}"


def _clean(db):
    db.execute(f"DROP TABLE IF EXISTS {WIDGET_TABLE}")
    db.commit()
    # Remove only this test's tracker rows — tina4_migration is shared.
    if db.table_exists("tina4_migration"):
        for name in MIGRATION_NAMES:
            db.execute("DELETE FROM tina4_migration WHERE migration_name = ?", [name])
        db.commit()


@pytest.fixture()
def pg_project(tmp_path):
    db = Database(_pg_url(), PG_USER, PG_PASS)
    _clean(db)
    # Pre-create the table so the test isolates the DATA-migration race (see the
    # module docstring) — a concurrent CREATE TABLE would serialize on PG's catalog
    # locks and hide it.
    db.execute(
        f"CREATE TABLE {WIDGET_TABLE} (id SERIAL PRIMARY KEY, name VARCHAR(50) NOT NULL)"
    )
    db.commit()

    migrations = tmp_path / "migrations"
    migrations.mkdir()

    # One data migration that sleeps before it writes — a real backfill. Every
    # worker reads it as pending at once; an unsynchronized run inserts WORKERS
    # copies of 'first', the run-wide advisory lock collapses that to one.
    _write(migrations / f"{MIGRATION_NAMES[0]}.py", f"""
        import time
        from tina4_python.migration import MigrationBase

        class SeedFirstPg277(MigrationBase):
            def up(self, db):
                time.sleep(0.6)
                db.execute("INSERT INTO {WIDGET_TABLE} (name) VALUES ('first')")

            def down(self, db):
                db.execute("DELETE FROM {WIDGET_TABLE} WHERE name = 'first'")
    """)

    worker = tmp_path / "worker.py"
    _write(worker, f"""
        import os, sys
        os.chdir({str(tmp_path)!r})
        from tina4_python.database import Database
        from tina4_python.migration import migrate
        db = Database({_pg_url()!r}, {PG_USER!r}, {PG_PASS!r})
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

    yield {"dir": str(tmp_path), "worker": str(worker), "db": db}
    _clean(db)
    try:
        db.close()
    except Exception:
        pass


def test_concurrent_startup_migrations_apply_once_on_live_postgres(pg_project):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")

    procs = [
        subprocess.Popen(
            [sys.executable, pg_project["worker"]],
            cwd=pg_project["dir"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(WORKERS)
    ]
    deadline = time.monotonic() + 90
    for p in procs:
        p.wait(timeout=max(1, int(deadline - time.monotonic())))

    stderrs = [p.stderr.read() if p.stderr else "" for p in procs]

    verify = Database(_pg_url(), PG_USER, PG_PASS)
    try:
        first_rows = verify.fetch_one(
            f"SELECT count(*) AS c FROM {WIDGET_TABLE} WHERE name = 'first'"
        )["c"]
        tracker_rows = verify.fetch_one(
            "SELECT count(*) AS c FROM tina4_migration WHERE migration_name = ?",
            [MIGRATION_NAMES[0]],
        )["c"]
    finally:
        verify.close()

    failed = [e for e in stderrs if e.strip()]
    assert not failed, (
        f"every one of {WORKERS} concurrent boots must migrate cleanly under the "
        f"advisory lock; {len(failed)} failed with: {failed}"
    )
    assert int(first_rows) == 1, (
        f"the data migration must apply exactly once under {WORKERS} concurrent "
        f"starts on PostgreSQL, got {first_rows} rows named 'first'. Worker stderr: {stderrs}"
    )
    assert int(tracker_rows) == 1, (
        f"the tracker must hold exactly one row for the migration, got {tracker_rows}"
    )
