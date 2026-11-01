# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""#268: migrate:create's next steps named 'tina4 migrate --rollback'/'--status',
which `migrate` refuses — the real commands are `migrate:rollback`/`migrate:status`.

And the two consistency gaps the reporter found: `migrate` applies both .sql AND
.py migrations, but `migrate:status` listed only .sql as pending and startup
auto-migration only triggered on a .sql file — so a pending .py migration was
invisible to status and never auto-applied at boot. Both now route through one
discovery helper that globs .sql + .py.

Real SQLite throughout (a real dependency — no mocks). This is python-only: the
wrong hint is python's, and .py migrations are a python feature; the other three
frameworks carry neither the hint nor the .py discovery path.
"""
from tina4_python.cli import _next_steps_for
from tina4_python.core.server import _auto_migrate_on_startup
from tina4_python.database import Database
from tina4_python.migration import Migration

PY_MIGRATION = """
from tina4_python.migration import MigrationBase


class CreateWidgets(MigrationBase):
    def up(self, db):
        db.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")

    def down(self, db):
        db.execute("DROP TABLE IF EXISTS widgets")
"""


# ── the reported bug: the next-steps hint names commands that exist ──────────

def test_migration_next_steps_name_commands_that_exist():
    steps = _next_steps_for("migration", "add_widgets", {}, {})
    joined = "\n".join(steps)
    # The commands that actually exist:
    assert "tina4 migrate:rollback" in joined, joined
    assert "tina4 migrate:status" in joined, joined
    # NOT the flags `migrate` refuses (what the hint used to print):
    assert "migrate --rollback" not in joined, joined
    assert "migrate --status" not in joined, joined


# ── .py migrations are visible to status() and get_files() (real SQLite) ─────

def test_status_lists_a_pending_py_migration(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_create_widgets.py").write_text(PY_MIGRATION, encoding="utf-8")
    db = Database(f"sqlite:///{tmp_path / 'app.db'}")
    try:
        status = Migration(db, str(d)).status()
        pending = [m["migration_name"] for m in status["pending"]]
        assert "20260101000000_create_widgets" in pending, pending
    finally:
        db.close()


def test_get_files_includes_py_and_excludes_dunder(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_create_widgets.py").write_text(PY_MIGRATION, encoding="utf-8")
    (d / "__init__.py").write_text("", encoding="utf-8")
    db = Database(f"sqlite:///{tmp_path / 'app.db'}")
    try:
        files = Migration(db, str(d)).get_files()
        assert "20260101000000_create_widgets.py" in files, files
        assert "__init__.py" not in files, files
    finally:
        db.close()


# ── startup auto-migration triggers for a .py-only migrations folder ─────────

def test_startup_auto_migrate_runs_for_a_py_only_folder(tmp_path, monkeypatch):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_create_widgets.py").write_text(PY_MIGRATION, encoding="utf-8")
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("TINA4_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("TINA4_AUTO_MIGRATE", raising=False)
    monkeypatch.chdir(tmp_path)

    _auto_migrate_on_startup()  # must NOT early-return on a .py-only folder

    db = Database(f"sqlite:///{db_path}")
    try:
        assert db.table_exists("widgets"), "startup auto-migrate skipped the .py-only folder"
    finally:
        db.close()
