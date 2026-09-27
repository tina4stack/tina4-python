# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SQLite absolute-path parity — a naive `sqlite:<abs>` (one leading slash) must open
the ABSOLUTE file, not a path relative to cwd. Real driver, real files, no mocks."""
import os
import tempfile

from tina4_python.database.connection import Database


def test_naive_one_slash_absolute_path_opens_the_absolute_file(tmp_path, monkeypatch):
    # Isolate cwd so any (buggy) cwd-relative shadow lands in tmp_path, not the repo.
    monkeypatch.chdir(tmp_path)
    abs_db = os.path.join(tempfile.mkdtemp(), "app.db")   # e.g. /var/folders/.../app.db

    db = Database("sqlite:" + abs_db)                      # sqlite:/var/folders/.../app.db (ONE slash)

    assert db._connection_path() == abs_db, "one-slash absolute path did not resolve to the abs path"
    assert os.path.exists(abs_db), "DB not created at the absolute path (footgun resolved it relative)"
    shadow = tmp_path / abs_db.lstrip("/")
    assert not shadow.exists(), f"footgun: a cwd-relative shadow DB was created at {shadow}"


def test_four_slash_absolute_form_unchanged():
    # Documented absolute form: sqlite:/// + /abs == sqlite:////abs → absolute. Must not regress.
    abs_db = os.path.join(tempfile.mkdtemp(), "app.db")
    db = Database("sqlite:///" + abs_db, pool=1)           # lazy: inspect the resolved path only
    assert db._connection_path() == abs_db


def test_three_slash_relative_form_unchanged(tmp_path, monkeypatch):
    # Documented relative form: sqlite:///rel → cwd/rel. Must not regress.
    monkeypatch.chdir(tmp_path)                            # isolate cwd (path resolution mkdirs under it)
    db = Database("sqlite:///data/app.db", pool=1)         # lazy: no connection
    assert db._connection_path() == os.path.join(os.getcwd(), "data", "app.db")


def test_memory_forms_unchanged():
    assert Database("sqlite::memory:", pool=1)._connection_path() == ":memory:"
    assert Database("sqlite:///:memory:", pool=1)._connection_path() == ":memory:"


def _resolver_for(url):
    """A live Database whose _connection_path() resolves `url` without connecting.

    _connection_path() reads self.url and is a pure resolver (no driver call), so
    we build a cheap :memory: Database and point its url at the case under test.
    """
    db = Database("sqlite::memory:", pool=1)
    db.url = url
    return db


def test_windows_absolute_form_passes_through():
    # Drive-letter path is treated as absolute and returned untouched (parity with
    # tina4-php / tina4-ruby / tina4-nodejs), never re-rooted under cwd.
    assert _resolver_for("sqlite:///C:/Users/app.db")._connection_path() == "C:/Users/app.db"


def test_relative_form_creates_parent_dir_under_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resolved = Database("sqlite:///sub/dir/app.db", pool=1)._connection_path()
    assert resolved == os.path.join(os.getcwd(), "sub", "dir", "app.db")
    assert os.path.isdir(os.path.join(os.getcwd(), "sub", "dir")), "parent dir auto-created under cwd"


def test_relative_escaping_cwd_is_not_created(tmp_path, monkeypatch):
    # Python-specific guard: a relative path whose parent resolves OUTSIDE cwd is
    # resolved but its directory is NOT auto-created (os.path.commonpath check).
    # This is the divergence from tina4-php, which mkdirs the parent unconditionally.
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    outside = tmp_path / "escaped"
    resolved = _resolver_for("sqlite:///../escaped/app.db")._connection_path()
    assert resolved == os.path.join(os.getcwd(), "..", "escaped", "app.db")
    assert not outside.exists(), "a relative path escaping cwd must NOT auto-create its dir"
