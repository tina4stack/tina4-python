# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The startup-migration boot log must tell the truth about the database.

Before the fix, ANY failure to open the database at boot was logged as
``Startup migrations skipped (no database configured)`` - including a
TINA4_DATABASE_URL that IS set but points at a server that refuses the
connection, so the operator went looking for a missing setting that was in fact
present (found reviewing tina4-ruby#172).

Every case drives the real ``_auto_migrate_on_startup()`` against a real
database target - a closed local port, a sqlite path whose parent is a regular
file, a reachable sqlite file - and reads the real console log. No mocks.
"""
import os

import pytest

from tina4_python.core.server import _auto_migrate_on_startup

_KEYS = ("TINA4_DATABASE_URL", "TINA4_AUTO_MIGRATE", "TINA4_LOG_LEVEL", "TINA4_LOG_OUTPUT")


@pytest.fixture
def project(tmp_path):
    """A temp project with one pending migration, console logging at DEBUG."""
    saved = {k: os.environ.get(k) for k in _KEYS}
    old_cwd = os.getcwd()
    for k in _KEYS:
        os.environ.pop(k, None)
    os.environ["TINA4_LOG_LEVEL"] = "DEBUG"
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "000001_items.sql").write_text(
        "CREATE TABLE items (id INTEGER PRIMARY KEY);", encoding="utf-8")
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _skip_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if "Startup migrations skipped" in line]


def test_unreachable_configured_url_is_not_reported_as_unconfigured(project, capsys):
    """A SET url on a closed port: the log names it (no credentials), never 'no database configured'."""
    os.environ["TINA4_DATABASE_URL"] = "postgres://tina4user:s3cret@127.0.0.1:1/tina4_nodb"

    _auto_migrate_on_startup()  # must not raise

    lines = _skip_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "no database configured" not in line, line
    assert "database configured but could not connect to postgres://127.0.0.1:1/tina4_nodb" in line, line
    assert "s3cret" not in line and "tina4user" not in line, line


def test_unopenable_configured_sqlite_is_not_reported_as_unconfigured(project, capsys):
    """A SET sqlite url whose parent is a regular file is a real connect failure, not 'unconfigured'."""
    (project / "afile").write_text("not a directory", encoding="utf-8")
    os.environ["TINA4_DATABASE_URL"] = "sqlite:///afile/sub/app.db"

    _auto_migrate_on_startup()

    lines = _skip_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert "no database configured" not in lines[0], lines[0]
    assert "database configured but could not connect to sqlite:///afile/sub/app.db" in lines[0], lines[0]


def test_unset_url_still_says_no_database_configured(project, capsys):
    """No TINA4_DATABASE_URL and the framework default cannot open: that IS 'no database configured'."""
    # The default is sqlite:///data/tina4.db; a regular FILE named data makes it unopenable.
    (project / "data").write_text("not a directory", encoding="utf-8")

    _auto_migrate_on_startup()

    lines = _skip_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert "Startup migrations skipped (no database configured)" in lines[0], lines[0]
    assert "could not connect to" not in lines[0].split("):")[0], lines[0]


def test_reachable_database_logs_no_skip_and_migrates(project, capsys):
    """Positive: a reachable sqlite file migrates and logs no skip line at all."""
    db_path = project / "app.db"
    os.environ["TINA4_DATABASE_URL"] = f"sqlite:///{db_path}"

    _auto_migrate_on_startup()

    out = capsys.readouterr().out
    assert _skip_lines(out) == [], out
    assert "Applied 1 pending migration(s) on startup" in out, out
