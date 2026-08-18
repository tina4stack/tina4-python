"""
Regression for https://github.com/tina4stack/tina4-python/issues/102.

Bug: adding a field to an ORM model at runtime, saving the migration and
hitting the endpoint left `to_dict()` silently dropping the new field. The
column was written to the DB correctly and no error surfaced -- the API just
lied about the shape of the record. A full server restart fixed it.

Root cause: `_auto_discover` re-imported the CHANGED model module by
`del sys.modules[...]` + `importlib.import_module(...)`, producing a fresh
`Todo` class object. But every other in-scope module that had done
`from src.orm.Todo import Todo` at ITS first import still held a reference to
the OLD class (Python decorators/imports bind by object, not by name). So a
route file that captured `Todo` and called `Todo({...}).to_dict()` used the
OLD `_fields` list -- the new column was invisible.

Fix: after the changed module re-imports, `_cascade_reload_dependents` scans
every other in-scope module in `sys.modules`, detects any attribute whose
`__module__` matches the reloaded module (the fingerprint of a `from X
import Y` binding), and re-imports those dependents too so their `from`
bindings pick up the FRESH class object. Bounded to the discovery scope,
recursive with a visited-set, so cycles and transitive dependents are safe.

These tests are REAL: they write actual .py files on disk under a tempdir,
call the real `_auto_discover` twice with a real mtime bump, and assert on
`sys.modules` + real class-identity checks. No mocks, no monkeypatching.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest


@pytest.fixture
def temp_project(monkeypatch):
    """Fresh project root per test, on sys.path, chdir'd into.

    Wipes any src.* modules from `sys.modules` so a previous test cannot leak
    a stale class object into this one. The discovery mtime map inside
    `_auto_discover` is also cleared for the same reason.
    """
    root = tempfile.mkdtemp(prefix="tina4_hot_reload_")
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(root)
    # Enable dev mode so the reload branch runs (Log level noise silenced).
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.setenv("TINA4_LOG_LEVEL", "WARNING")

    # Isolate from previous tests: drop any src.* modules and reset the
    # framework's mtime map so we start with a clean discovery state.
    for name in [n for n in list(sys.modules) if n == "src" or n.startswith("src.")]:
        del sys.modules[name]
    from tina4_python.core import server
    server._discovered_mtimes.clear()
    importlib.invalidate_caches()

    yield Path(root)

    # Cleanup: strip our modules again so the next test starts fresh.
    for name in [n for n in list(sys.modules) if n == "src" or n.startswith("src.")]:
        del sys.modules[name]
    server._discovered_mtimes.clear()
    shutil.rmtree(root, ignore_errors=True)


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip("\n"))
    return p


def _bump_mtime(path: Path, seconds: float = 5.0) -> None:
    """Push the file's mtime into the future so the reloader treats it as
    changed. Using a real future time (not `st_mtime + 1e-3`) avoids any
    filesystem timestamp granularity issue on macOS/APFS."""
    future = time.time() + seconds
    os.utime(path, (future, future))


class TestCascadeReloadIssue102:
    """Adding a field to an ORM model must reach every module that captured
    the class via `from X import Y` -- not just the ORM module itself."""

    def test_added_field_reaches_from_import_dependent(self, temp_project):
        _write(temp_project, "src/__init__.py", "")
        _write(temp_project, "src/orm/__init__.py", "")
        _write(temp_project, "src/routes/__init__.py", "")

        todo_py = _write(temp_project, "src/orm/Todo.py", """
            from tina4_python.orm import ORM, IntegerField, StringField

            class Todo(ORM):
                table_name = "todos"
                id = IntegerField(primary_key=True, auto_increment=True)
                title = StringField()
        """)

        # A route-shaped file that captures `Todo` at its first import.
        _write(temp_project, "src/routes/todos.py", """
            from src.orm.Todo import Todo

            def make(data):
                return Todo(data)
        """)

        from tina4_python.core.server import _auto_discover
        _auto_discover("src")

        todos_mod = sys.modules["src.routes.todos"]
        todo_mod = sys.modules["src.orm.Todo"]
        # Baseline: same class object, same _fields.
        assert todos_mod.Todo is todo_mod.Todo
        assert "completed" not in todos_mod.Todo._fields

        # Edit the model to add a field, bump its mtime so the reloader
        # picks the change up.
        todo_py.write_text(textwrap.dedent("""
            from tina4_python.orm import ORM, IntegerField, StringField, BooleanField

            class Todo(ORM):
                table_name = "todos"
                id = IntegerField(primary_key=True, auto_increment=True)
                title = StringField()
                completed = BooleanField(default=False)
        """).lstrip("\n"))
        _bump_mtime(todo_py)

        _auto_discover("src")

        todos_mod_after = sys.modules["src.routes.todos"]
        todo_mod_after = sys.modules["src.orm.Todo"]

        # ORM module got the new field -- baseline sanity, not the gate.
        assert "completed" in todo_mod_after.Todo._fields

        # THE GATE: the route's captured `Todo` reference must now be the
        # SAME class object as the ORM module holds. Without the cascade
        # fix, the route module was never re-imported after Todo.py changed,
        # so its `from src.orm.Todo import Todo` still bound to the OLD
        # class object.
        assert todos_mod_after.Todo is todo_mod_after.Todo, (
            "route module still holds the stale Todo class after reload"
        )

        # And the observable behaviour: `to_dict()` from the route path
        # includes the new field. This is what a user sees over HTTP; if the
        # class identity check above passes but this one fails, the fix has
        # regressed silently.
        instance = todos_mod_after.Todo({"title": "x", "completed": True})
        d = instance.to_dict()
        assert "completed" in d, f"route's to_dict() still drops 'completed': {d}"
        assert d["completed"] is True

    def test_cascade_is_transitive_across_two_hops(self, temp_project):
        """A -> B -> C: a dependent of a dependent must also refresh."""
        _write(temp_project, "src/__init__.py", "")
        _write(temp_project, "src/orm/__init__.py", "")
        _write(temp_project, "src/services/__init__.py", "")
        _write(temp_project, "src/routes/__init__.py", "")

        model_py = _write(temp_project, "src/orm/User.py", """
            from tina4_python.orm import ORM, IntegerField, StringField

            class User(ORM):
                table_name = "users"
                id = IntegerField(primary_key=True, auto_increment=True)
                name = StringField()
        """)
        _write(temp_project, "src/services/user_service.py", """
            from src.orm.User import User

            def build(data):
                return User(data)
        """)
        _write(temp_project, "src/routes/users.py", """
            from src.services.user_service import build

            def handler(data):
                return build(data)
        """)

        from tina4_python.core.server import _auto_discover
        _auto_discover("src")

        model_mod = sys.modules["src.orm.User"]
        service_mod = sys.modules["src.services.user_service"]
        route_mod = sys.modules["src.routes.users"]
        assert service_mod.User is model_mod.User
        assert route_mod.build.__module__ == "src.services.user_service"

        # Edit the model, bump mtime.
        model_py.write_text(textwrap.dedent("""
            from tina4_python.orm import ORM, IntegerField, StringField, BooleanField

            class User(ORM):
                table_name = "users"
                id = IntegerField(primary_key=True, auto_increment=True)
                name = StringField()
                active = BooleanField(default=True)
        """).lstrip("\n"))
        _bump_mtime(model_py)
        _auto_discover("src")

        model_mod_after = sys.modules["src.orm.User"]
        service_mod_after = sys.modules["src.services.user_service"]

        assert "active" in model_mod_after.User._fields
        # First hop: service module refreshed.
        assert service_mod_after.User is model_mod_after.User, (
            "service module (direct dependent) still holds stale User"
        )
        # End-to-end: the route calls the service, which builds a User; the
        # dict must contain the new field.
        route_mod_after = sys.modules["src.routes.users"]
        d = route_mod_after.handler({"name": "alice", "active": False}).to_dict()
        assert "active" in d, f"end-to-end route path drops 'active': {d}"
        assert d["active"] is False

    def test_no_cascade_when_no_dependent(self, temp_project):
        """Reloading a module with no in-scope dependents must NOT spuriously
        re-import an unrelated module. Regression against an over-eager
        cascade that just re-imports everything on every tick."""
        _write(temp_project, "src/__init__.py", "")
        _write(temp_project, "src/orm/__init__.py", "")

        model_py = _write(temp_project, "src/orm/Standalone.py", """
            from tina4_python.orm import ORM, IntegerField

            class Standalone(ORM):
                table_name = "standalone"
                id = IntegerField(primary_key=True, auto_increment=True)
        """)
        # An unrelated module that does NOT import from Standalone.
        _write(temp_project, "src/orm/Unrelated.py", """
            from tina4_python.orm import ORM, IntegerField

            class Unrelated(ORM):
                table_name = "unrelated"
                id = IntegerField(primary_key=True, auto_increment=True)
        """)

        from tina4_python.core.server import _auto_discover
        _auto_discover("src")

        unrelated_before = sys.modules["src.orm.Unrelated"]
        unrelated_class_id = id(unrelated_before.Unrelated)

        _bump_mtime(model_py)
        _auto_discover("src")

        unrelated_after = sys.modules["src.orm.Unrelated"]
        # The unrelated module was NOT re-imported (its class object is the
        # same identity). Without this guard the cascade would spuriously
        # rebuild every ORM class on every tick, breaking anything that
        # relied on class identity elsewhere (isinstance checks, dispatch
        # tables, ORM foreign-key registries).
        assert unrelated_after is unrelated_before
        assert id(unrelated_after.Unrelated) == unrelated_class_id
