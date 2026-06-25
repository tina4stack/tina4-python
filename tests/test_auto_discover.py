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

import asyncio
import os
import sys
import textwrap
from pathlib import Path

import pytest

from tina4_python.core import server as _server
from tina4_python.core import router as _router
from tina4_python.core.router import Router


def _reset_routes() -> None:
    """Routes live in a module-level list; clear it so tests don't bleed."""
    _router._routes.clear()
    # The mtime map is module-level state on the server too — wipe it so a
    # leftover key from a prior test can't mask a "changed" file in this one.
    _server._discovered_mtimes.clear()


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


def _bump_mtime(path: Path, seconds: float = 2.0) -> None:
    """Push a file's mtime forward so the change is visible even when the
    filesystem's mtime resolution is coarse (HFS+ is 1s; some CI tmpfs is
    worse). Re-writing the body in the same second can leave mtime unchanged,
    which would make the reload silently no-op — so we set it explicitly."""
    future = path.stat().st_mtime + seconds
    os.utime(path, (future, future))


async def _call_handler(route) -> str:
    """Invoke a discovered route handler with throwaway request/response stubs
    and return whatever value it passed to ``response(...)``. Handlers in these
    tests do ``return response("V1")`` so the captured arg is the version
    string we assert on — this is how we prove the LIVE handler changed, not
    just that some route exists."""
    captured = {}

    class _Resp:
        def __call__(self, body, *a, **k):
            captured["body"] = body
            return body

    await route["handler"](object(), _Resp())
    return captured.get("body")


def test_changed_route_file_is_reimported_on_rediscover(project):
    """The core hot-reload contract: editing an EXISTING route file and
    re-running discovery makes the Router resolve to the NEW handler, not the
    stale in-memory one. This is the bug behind 'live-reload serves stale
    bytes' — discovery used to skip anything already in sys.modules."""
    path = _write_route(project, "ver", """
        from tina4_python.core.router import get
        @get("/ver")
        async def ver(request, response):
            return response("V1")
    """)

    _server._auto_discover("src")
    route, _ = Router.match("GET", "/ver")
    assert route is not None
    assert asyncio.run(_call_handler(route)) == "V1"

    # Edit the same file to return V2, with a strictly newer mtime.
    path.write_text(textwrap.dedent("""
        from tina4_python.core.router import get
        @get("/ver")
        async def ver(request, response):
            return response("V2")
    """))
    _bump_mtime(path)

    _server._auto_discover("src")

    # Still exactly one route for /ver — the replace semantics collapsed the
    # re-registration onto the existing slot instead of appending a duplicate.
    assert sum(1 for r in Router.get_routes() if r["path"] == "/ver") == 1
    route2, _ = Router.match("GET", "/ver")
    assert asyncio.run(_call_handler(route2)) == "V2"


def test_unchanged_file_is_not_reimported_on_second_pass(project):
    """An unchanged file must NOT be re-executed on a second discovery pass —
    that keeps reload cheap and preserves module-level side effects. We prove
    it with a side-effect counter incremented at import time: it must stay 1
    across two passes when the file hasn't changed."""
    import builtins
    # A counter that survives re-import only if the module body re-runs.
    builtins._tina4_import_counter = 0
    _write_route(project, "once", """
        import builtins
        builtins._tina4_import_counter += 1
        from tina4_python.core.router import get
        @get("/once")
        async def once(request, response):
            return response("ok")
    """)

    _server._auto_discover("src")
    assert builtins._tina4_import_counter == 1
    mtime_after_first = _server._discovered_mtimes["src.routes.once"]

    # Second pass, file untouched — body must not re-run.
    _server._auto_discover("src")
    assert builtins._tina4_import_counter == 1
    assert _server._discovered_mtimes["src.routes.once"] == mtime_after_first
    del builtins._tina4_import_counter


def test_framework_modules_are_never_reimported(project):
    """Scope guard: even if a tina4_python.* module's source mtime looks newer
    than what we recorded, discovery must never del+reimport it. We seed the
    mtime map with a framework module at mtime 0 (so 'now' looks newer) and
    assert its sys.modules identity is unchanged after a discovery pass."""
    import tina4_python.core.router as _r
    sentinel = sys.modules["tina4_python.core.router"]
    _server._discovered_mtimes["tina4_python.core.router"] = 0.0

    _write_route(project, "guard", """
        from tina4_python.core.router import get
        @get("/guard")
        async def guard(request, response):
            return response("ok")
    """)
    _server._auto_discover("src")

    # The framework module object is the very same instance — never evicted.
    assert sys.modules["tina4_python.core.router"] is sentinel
    assert _r is sentinel


def test_changed_route_served_through_api_reload_endpoint(project):
    """End-to-end: POST /__dev/api/reload triggers re-discovery, and a changed
    existing route is then served by its NEW handler. This exercises the exact
    path the Rust CLI hits on every file save."""
    from tina4_python.dev_admin import _api_reload

    path = _write_route(project, "e2e", """
        from tina4_python.core.router import get
        @get("/e2e")
        async def e2e(request, response):
            return response("V1")
    """)
    _server._auto_discover("src")
    assert asyncio.run(_call_handler(Router.match("GET", "/e2e")[0])) == "V1"

    path.write_text(textwrap.dedent("""
        from tina4_python.core.router import get
        @get("/e2e")
        async def e2e(request, response):
            return response("V2")
    """))
    _bump_mtime(path)

    # Drive the real reload endpoint with a minimal request/response pair.
    class _Req:
        body = {"type": "reload", "file": "src/routes/e2e.py"}

    class _Resp:
        def __call__(self, body, *a, **k):
            return body

    asyncio.run(_api_reload(_Req(), _Resp()))

    assert asyncio.run(_call_handler(Router.match("GET", "/e2e")[0])) == "V2"


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


def test_transitively_imported_module_is_not_reimported(project):
    """Issue #53 — a module pulled in TRANSITIVELY (imported by another src
    file before the walk reaches its own file) must NOT be del+re-imported by
    discovery. Re-importing mints a fresh module object while the earlier
    importer keeps the stale one, so module-level singletons silently diverge.

    Setup: ``aaa_importer`` sorts before ``zzz_state`` in the walk, so the
    importer is loaded first and drags ``zzz_state`` into sys.modules before
    discovery reaches ``zzz_state.py`` directly — the exact trigger condition.
    """
    # The shared module with a module-level singleton (object identity is the tell).
    _write_route(project, "zzz_state", """
        SENTINEL = object()
    """)
    # An earlier-sorted file that imports it transitively and captures the singleton.
    _write_route(project, "aaa_importer", """
        from tina4_python.core.router import get
        import src.routes.zzz_state as _state
        CAPTURED = _state.SENTINEL
        @get("/uses-state")
        async def uses_state(request, response):
            return response({"ok": True})
    """)

    _server._auto_discover("src")

    importer = sys.modules["src.routes.aaa_importer"]
    state = sys.modules["src.routes.zzz_state"]

    # The singleton the importer captured must be the SAME object the live
    # module still exposes — i.e. zzz_state was never del+re-imported.
    assert importer.CAPTURED is state.SENTINEL, (
        "transitively-imported module was re-imported by discovery — its "
        "module-level singleton diverged (issue #53)"
    )
    # And the importer's reference IS the module in sys.modules (no duplicate).
    assert importer._state is state
    # Discovery still worked — the route registered.
    assert any(r["path"] == "/uses-state" for r in Router.get_routes())


def test_genuinely_edited_module_still_reloads_after_transitive_load(project):
    """The #53 guard must not block a REAL edit: once a transitively-loaded
    module has its baseline recorded, a later edit (mtime increases) still
    hot-reloads on the next discovery pass."""
    import os as _os
    import time as _time

    state_path = _write_route(project, "zzz_state2", """
        VALUE = "v1"
    """)
    _write_route(project, "aaa_importer2", """
        import src.routes.zzz_state2 as _s2
    """)

    _server._auto_discover("src")
    assert sys.modules["src.routes.zzz_state2"].VALUE == "v1"

    # Edit the transitively-loaded module and bump its mtime into the future
    # so the change is unambiguously newer than the recorded baseline.
    state_path.write_text("VALUE = \"v2\"\n")
    future = _time.time() + 10
    _os.utime(state_path, (future, future))

    _server._auto_discover("src")
    assert sys.modules["src.routes.zzz_state2"].VALUE == "v2", (
        "a genuine edit to a transitively-loaded module did not hot-reload"
    )
