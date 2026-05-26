"""
Tests for the auto-discover route loader — the path that imports user code
under src/ so route decorators register themselves.

These cover the gotchas that bit real users:
- a parent directory starting with "_" silently skipped everything
- routes added after server boot were invisible until restart
- import failures were swallowed into a console line and never resurfaced
- a routes/ folder full of decorator-free functions gave no feedback
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import textwrap
from pathlib import Path

import pytest

from tina4_python.core import server as _server
from tina4_python.core import router as _router
from tina4_python.core.router import Router


def _reset_routes() -> None:
    """Routes live in a module-level list; clear it so tests don't bleed."""
    _router._routes.clear()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A scratch project directory with src/routes/ pre-created and cwd set."""
    src = tmp_path / "src"
    (src / "routes").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    # Clear any cached `src.routes.*` modules from previous tests so import_module re-runs.
    for mod in list(sys.modules):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]
    _reset_routes()
    yield tmp_path


def _write_route(project: Path, name: str, body: str) -> Path:
    p = project / "src" / "routes" / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return p


def test_auto_discover_imports_route_files(project):
    """The baseline: a route file with a real decorator is loaded and
    registered."""
    _write_route(project, "hello", """
        from tina4_python.core.router import get
        @get("/hello-discover")
        async def hello(request, response):
            return response({"ok": True})
    """)

    before = len(Router.get_routes())
    _server._auto_discover("src")
    after = len(Router.get_routes())

    assert after == before + 1
    patterns = [r["path"] for r in Router.get_routes()]
    assert "/hello-discover" in patterns


def test_auto_discover_is_idempotent(project):
    """Calling discover twice does not double-register routes — the in
    `sys.modules` check skips already-imported files."""
    _write_route(project, "idem", """
        from tina4_python.core.router import get
        @get("/idem")
        async def idem(request, response):
            return response({"ok": True})
    """)

    _server._auto_discover("src")
    first = len(Router.get_routes())
    _server._auto_discover("src")
    second = len(Router.get_routes())

    assert first == second
    assert sum(1 for r in Router.get_routes() if r["path"] == "/idem") == 1


def test_auto_discover_picks_up_new_files_on_reload(project):
    """Re-running discover after a new file appears registers its routes —
    this is what /__dev/api/reload relies on so users do not need to
    restart the server every time they add a route."""
    _write_route(project, "first", """
        from tina4_python.core.router import get
        @get("/first")
        async def first(request, response):
            return response({"ok": True})
    """)

    _server._auto_discover("src")
    initial_count = len(Router.get_routes())
    assert any(r["path"] == "/first" for r in Router.get_routes())

    # Simulate the user dropping a new file after boot.
    _write_route(project, "second", """
        from tina4_python.core.router import get
        @get("/second")
        async def second(request, response):
            return response({"ok": True})
    """)

    _server._auto_discover("src")

    assert len(Router.get_routes()) == initial_count + 1
    assert any(r["path"] == "/second" for r in Router.get_routes())


def test_underscore_parent_directory_does_not_block_discovery(tmp_path, monkeypatch):
    """Regression: ``py_file.parts`` used to include absolute path
    components. A project under ``/Users/me/_archive/myapp`` had every
    file silently skipped because ``_archive`` starts with ``_``. The
    filter now operates on parts relative to ``src/`` only."""
    root = tmp_path / "_archive" / "myapp"
    (root / "src" / "routes").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(root))
    for mod in list(sys.modules):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]
    _reset_routes()

    (root / "src" / "routes" / "deep.py").write_text(textwrap.dedent("""
        from tina4_python.core.router import get
        @get("/deep")
        async def deep(request, response):
            return response({"ok": True})
    """))

    _server._auto_discover("src")

    assert any(r["path"] == "/deep" for r in Router.get_routes())


def test_zero_routes_warning_when_routes_folder_has_undecorated_files(project, capsys):
    """If src/routes/ has Python files but none of them registered a route,
    the user almost certainly forgot the @get / @post decorator. The
    framework now warns instead of staying silent."""
    _write_route(project, "missing_decorator", """
        # No @get / @post anywhere — the user forgot.
        async def hello(request, response):
            return response({"ok": True})
    """)

    _server._auto_discover("src")
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "no routes registered" in combined or "no routes" in combined


def test_import_failure_writes_a_broken_sentinel(project):
    """A SyntaxError or ImportError inside a route file used to be a single
    Log.error line that scrolled away. The framework now drops a
    ``.broken`` sentinel so /health and the dev dashboard surface it."""
    _write_route(project, "broken", """
        from tina4_python.core.router import get
        @get("/will-not-load"
        # ^ deliberate syntax error
        async def broken(request, response):
            return response({"ok": True})
    """)

    _server._auto_discover("src")

    broken_dir = project / "data" / ".broken"
    assert broken_dir.is_dir()
    sentinels = list(broken_dir.glob("discover_*.broken"))
    assert sentinels, "expected a .broken sentinel for the failed import"
    payload = sentinels[0].read_text()
    assert "auto_discover_failure" in payload
    assert "broken.py" in payload
