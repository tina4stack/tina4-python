# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SQLite path-resolution CONTRACT (ADR-0086), the five cases the four
frameworks must agree on. Real resolver, real files, real mkdir — no mocks.

Fixture: tina4-documentation/plan/v3/fixtures/sqlite_path_contract.json
"""
import os
import tempfile

import pytest

from tina4_python.database.connection import Database


def _resolver_for(url):
    """A live :memory: Database whose url is repointed at the case under test.

    ``_connection_path()`` is a pure resolver (no driver call), so a cheap
    :memory: Database resolves any url without connecting."""
    db = Database("sqlite::memory:", pool=1)
    db.url = url
    return db


def test_memory_passthrough():
    assert _resolver_for("sqlite::memory:")._connection_path() == ":memory:"
    assert _resolver_for("sqlite:///:memory:")._connection_path() == ":memory:"


def test_unix_absolute_passthrough_no_mkdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    abs_dir = tempfile.mkdtemp()
    abs_db = os.path.join(abs_dir, "missing", "app.db")   # parent does NOT exist
    # "sqlite:" + one-slash absolute path is the documented one-slash absolute form.
    resolved = _resolver_for("sqlite:" + abs_db)._connection_path()
    assert resolved == abs_db
    assert not os.path.exists(os.path.dirname(abs_db)), "absolute path must NOT auto-mkdir"


def test_drive_letter_absolute_passthrough_no_mkdir():
    # A Windows drive-letter path is recognised as absolute on EVERY OS and
    # returned untouched — never re-rooted under cwd.
    assert _resolver_for("sqlite:///C:/Users/app.db")._connection_path() == "C:/Users/app.db"


def test_relative_under_cwd_creates_parent_mode_0775(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old_umask = os.umask(0)   # so the requested 0775 lands unmasked and can be asserted
    try:
        resolved = _resolver_for("sqlite:///sub/dir/app.db")._connection_path()
    finally:
        os.umask(old_umask)
    parent = os.path.join(os.getcwd(), "sub", "dir")
    assert resolved == os.path.join(parent, "app.db")
    assert os.path.isdir(parent), "parent dir auto-created under cwd"
    assert (os.stat(parent).st_mode & 0o777) == 0o775, "parent created with mode 0775"


def test_relative_escaping_cwd_is_refused_no_mkdir(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    outside = tmp_path / "escaped"
    with pytest.raises(ValueError):
        _resolver_for("sqlite:///../escaped/app.db")._connection_path()
    assert not outside.exists(), "an escaping relative path must NOT create any directory"
