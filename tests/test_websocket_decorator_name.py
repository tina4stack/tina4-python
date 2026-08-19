"""`from tina4_python import websocket` must give the decorator, not the module.

`tina4_python.websocket` is two things at once: the RFC 6455 subpackage, and —
to every reader of the docs — the route decorator that sits beside @get/@post
in ``core.router``. Python binds a submodule onto its parent package the moment
the submodule is imported, so the name resolved to the module and the
documented usage died at import time::

    from tina4_python import websocket

    @websocket("/ws")            # TypeError: 'module' object is not callable
    async def chat(connection, event, data): ...

which takes the whole route file with it. Reproduced on 3.13.105:
``type(tina4_python.websocket).__name__ == "module"``, ``callable(...) is False``.

Re-exporting the decorator from ``tina4_python/__init__.py`` cannot fix this —
importing the subpackage rebinds the attribute over the re-export afterwards,
so the failure would come and go with import order. The module is callable
instead, which is why `test_still_callable_after_the_submodule_is_imported`
matters: it is the case a re-export would lose.
"""
from __future__ import annotations

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
        """Both spellings must land the same route."""
        from tina4_python.core.router import websocket as router_websocket

        @router_websocket("/ws/a")
        async def via_router(connection, event, data):
            return None

        @tina4_python.websocket("/ws/b")
        async def via_package(connection, event, data):
            return None

        registered = {r["path"]: r for r in clean_ws_routes}
        assert registered["/ws/a"].keys() == registered["/ws/b"].keys()
        assert registered["/ws/b"]["handler"] is via_package

    def test_still_callable_after_the_submodule_is_imported(self):
        """The case a plain re-export in __init__.py would lose."""
        import importlib

        import tina4_python.websocket as ws_module

        importlib.reload(importlib.import_module("tina4_python.websocket"))
        assert callable(tina4_python.websocket)
        assert callable(ws_module)


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
        import types

        import tina4_python.websocket as ws

        assert isinstance(ws, types.ModuleType)
