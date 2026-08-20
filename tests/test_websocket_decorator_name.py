"""`from tina4_python import websocket` must give a callable module, not a bare module.

`tina4_python.websocket` is two things at once: the RFC 6455 subpackage, and —
to every reader of the docs — the route decorator that sits beside @get/@post
in ``core.router``. Python binds a submodule onto its parent package the moment
the submodule is imported, so the name resolved to the module and the
documented usage died at decorate time::

    from tina4_python import websocket

    @websocket("/ws")            # TypeError: 'module' object is not callable
    async def chat(connection, event, data): ...

Auto-discovery logged one ERROR and dropped every route from that line onward.
Reproduced on 3.13.105: ``callable(tina4_python.websocket) is False``.

A re-export of ``core.router.websocket`` onto ``tina4_python.websocket`` would
make ``from tina4_python import websocket`` callable, but ``import
tina4_python.websocket as ws`` would then be the function — ``ws.WebSocketServer``
breaks. ``test_still_callable_after_the_submodule_is_imported`` pins the
re-export-killing half: the alias must stay a ``ModuleType`` that still
exposes ``WebSocketServer``.
"""
from __future__ import annotations

import types

import pytest

import tina4_python
from tina4_python.core import router as router_module


@pytest.fixture
def clean_ws_routes():
    """Route registration mutates a module-level list — put it back."""
    saved = list(router_module._ws_routes)
    yield router_module._ws_routes
    router_module._ws_routes[:] = saved


class TestDecoratorSurface:
    def test_package_attribute_is_callable(self):
        assert callable(tina4_python.websocket)

    def test_decorator_registers_the_route(self, clean_ws_routes):
        from tina4_python import websocket

        @websocket("/ws/chat/{room}")
        async def chat(connection, event, data):
            return None

        assert [r["path"] for r in clean_ws_routes if r["path"] == "/ws/chat/{room}"]
        assert chat.__name__ == "chat", "decorator must return the handler unchanged"

    def test_matches_the_router_decorator(self, clean_ws_routes):
        """Package spelling is the router decorator, not a second implementation."""
        from tina4_python.core.router import websocket as router_websocket

        assert tina4_python.websocket("/p").__code__ is router_websocket("/p").__code__

        @router_websocket("/ws/a/{room}")
        async def via_router(connection, event, data):
            return None

        @tina4_python.websocket("/ws/b/{room}")
        async def via_package(connection, event, data):
            return None

        registered = {r["path"]: r for r in clean_ws_routes}
        assert registered["/ws/a/{room}"]["param_names"] == registered["/ws/b/{room}"]["param_names"] == ["room"]
        assert registered["/ws/a/{room}"]["auth_required"] is False
        assert registered["/ws/b/{room}"]["auth_required"] is False
        assert registered["/ws/b/{room}"]["handler"] is via_package

    def test_still_callable_after_the_submodule_is_imported(self):
        """A re-export would make `import tina4_python.websocket as ws` a function."""
        import importlib

        import tina4_python.websocket as ws_module

        importlib.reload(importlib.import_module("tina4_python.websocket"))
        assert callable(tina4_python.websocket)
        assert callable(ws_module)
        assert isinstance(ws_module, types.ModuleType)
        assert ws_module.WebSocketServer.__name__ == "WebSocketServer"


class TestModuleSurfaceSurvives:
    """Making the module callable must not cost it its exports."""

    def test_documented_names_still_import(self):
        from tina4_python.websocket import (
            WebSocketConnection,
            WebSocketManager,
            WebSocketServer,
            compute_accept_key,
        )

        assert WebSocketServer.__name__ == "WebSocketServer"
        assert WebSocketConnection.__name__ == "WebSocketConnection"
        assert WebSocketManager.__name__ == "WebSocketManager"
        assert callable(compute_accept_key)

    def test_dunder_all_intact(self):
        import tina4_python.websocket as ws

        assert "WebSocketServer" in ws.__all__
        assert "compute_accept_key" in ws.__all__

    def test_it_is_still_a_module(self):
        import tina4_python.websocket as ws

        assert isinstance(ws, types.ModuleType)

    def test_backplane_submodule_still_imports(self):
        from tina4_python.websocket import backplane
        import tina4_python.websocket.backplane as backplane_mod

        assert backplane is backplane_mod
        assert callable(backplane.create_backplane)
