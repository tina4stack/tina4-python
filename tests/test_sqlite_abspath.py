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
