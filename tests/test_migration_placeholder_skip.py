# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""An empty, unedited scaffold migration is kept pending (#288, #297).

Startup auto-migrate (and `tina4 migrate`) used to apply a freshly scaffolded
migration whose body was only comments — running nothing and recording it
passed, so the real SQL written later under the same filename never ran and
`tina4 migrate` reported nothing pending. A scaffold with real, runnable DDL
(a CREATE TABLE with id + created_at) still applies, so the ordinary
`generate model` → `migrate` workflow is unaffected. Real SQLite, no mocks.
"""
from tina4_python.database import Database
from tina4_python.migration.runner import (
    _run_pending, _get_executed, _is_unapplied_scaffold, _has_executable_sql,
)

# A comment-only placeholder (the non-create `migrate:create` scaffold, and the
# view stub) — bears a marker AND has no executable statement.
_COMMENT_ONLY = (
    "-- Migration: add_note\n"
    "-- tina4:edit  write the UP migration SQL\n"
    "-- Example: ALTER TABLE widget ADD COLUMN note TEXT DEFAULT '';\n"
)

# A CREATE TABLE scaffold — bears the same marker but IS real, runnable DDL.
_CREATE_TABLE_SCAFFOLD = (
    "-- Migration: create_widget\n"
    "CREATE TABLE IF NOT EXISTS widget (\n"
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
    "    -- tina4:edit  add columns beyond id + created_at\n"
    ");\n"
)


def test_has_executable_sql_distinguishes_comment_only_from_ddl():
    assert _has_executable_sql(_COMMENT_ONLY) is False
    assert _has_executable_sql(_CREATE_TABLE_SCAFFOLD) is True


def test_is_unapplied_scaffold(tmp_path):
    comment = tmp_path / "a.sql"
    comment.write_text(_COMMENT_ONLY)
    assert _is_unapplied_scaffold(comment) is True

    create = tmp_path / "b.sql"
    create.write_text(_CREATE_TABLE_SCAFFOLD)       # marker + real DDL → applies
    assert _is_unapplied_scaffold(create) is False

    written = tmp_path / "c.sql"
    written.write_text("ALTER TABLE widget ADD COLUMN note TEXT;\n")  # no marker
    assert _is_unapplied_scaffold(written) is False


def test_comment_only_migration_is_kept_pending_then_applies(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    mig = migrations / "000001_add_note.sql"
    mig.write_text(_COMMENT_ONLY)
    db = Database(f"sqlite:///{tmp_path}/app.db")
    db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY)")

    # Run 1: the comment-only placeholder must NOT apply or be recorded.
    assert _run_pending(db, str(migrations)) == []
    assert "000001_add_note" not in _get_executed(db)

    # Fill it in (real SQL, marker removed) — now it applies.
    mig.write_text("ALTER TABLE widget ADD COLUMN note TEXT DEFAULT '';\n")
    assert _run_pending(db, str(migrations)) == ["000001_add_note.sql"]
    assert "note" in {c.get("name") for c in db.get_columns("widget")}


def test_create_table_scaffold_still_applies(tmp_path):
    # A CREATE TABLE scaffold carries the tina4:edit hint but is real DDL, so the
    # normal `generate model` → `migrate` workflow must still create the table.
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "000001_create_widget.sql").write_text(_CREATE_TABLE_SCAFFOLD)
    db = Database(f"sqlite:///{tmp_path}/app.db")
    assert _run_pending(db, str(migrations)) == ["000001_create_widget.sql"]
    assert db.table_exists("widget") is True
