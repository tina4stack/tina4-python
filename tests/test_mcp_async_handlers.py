# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MCP awaits ``async def`` tool and resource handlers.

Before the fix, ``resources/read`` and ``tools/call`` called the handler and
serialised whatever came back, so an async handler answered with the text
``<coroutine object rows at 0x...>`` and the coroutine was never run. Python
sibling of tina4-nodejs#193.

No mocks: a real McpServer, real JSON-RPC messages, and the real ASGI front
controller (TestClient) for the async HTTP routes — both the routes
``McpServer.register_routes`` mounts and the dev-admin ``/__dev/mcp`` endpoint.
"""
import asyncio
import gc
import json
import os
import warnings
from contextlib import contextmanager

import pytest

from tina4_python.core import router
from tina4_python.mcp import McpServer, _get_default_server
from tina4_python.mcp.protocol import INTERNAL_ERROR, encode_response
from tina4_python.test_client import TestClient


async def rows():
    await asyncio.sleep(0)
    return {"rows": [1, 2, 3]}


async def add(a: int, b: int):
    await asyncio.sleep(0)
    return a + b


async def broken_resource():
    await asyncio.sleep(0)
    raise RuntimeError("db down")


async def broken_tool(x: int):
    await asyncio.sleep(0)
    raise RuntimeError(f"tool failed on {x}")


def sync_rows():
    return {"rows": [1, 2, 3]}


def sync_add(a: int, b: int):
    return a + b


def _server(path: str) -> McpServer:
    server = McpServer(path, name="async-handlers")
    server.register_resource("probe://rows", rows, "rows")
    server.register_resource("probe://boom", broken_resource, "fails")
    server.register_resource("probe://sync-rows", sync_rows, "sync rows")
    server.register_tool("add", add, "adds")
    server.register_tool("boom", broken_tool, "fails")
    server.register_tool("sync_add", sync_add, "adds synchronously")
    return server


def _read(uri: str, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": "resources/read", "params": {"uri": uri}}


def _call(name: str, arguments: dict, rid: int = 2) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


# The exact replies a sync handler produced before this change; the async
# handlers returning the same values must now produce the same bytes.
ROWS_REPLY = encode_response(1, {"contents": [{
    "uri": "probe://rows", "mimeType": "application/json",
    "text": json.dumps({"rows": [1, 2, 3]}, indent=2),
}]})
ADD_REPLY = encode_response(2, {"content": [{"type": "text", "text": "5"}]})


@contextmanager
def no_unawaited_coroutines():
    """Fail if any coroutine is garbage-collected without being awaited."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
        gc.collect()
    leaked = [str(w.message) for w in caught
              if issubclass(w.category, RuntimeWarning) and "never awaited" in str(w.message)]
    assert leaked == [], leaked


def _assert_internal_error(raw: str, rid: int, message: str) -> None:
    reply = json.loads(raw)
    assert "result" not in reply, raw
    assert reply["id"] == rid
    assert reply["error"]["code"] == INTERNAL_ERROR == -32603
    assert reply["error"]["message"] == message


# ── handle_message_async (the path the async routes take) ──────────────────

class TestHandleMessageAsync:
    async def test_async_resource_returns_its_value(self):
        server = _server("/__t-async-res")
        raw = await server.handle_message_async(_read("probe://rows"))
        assert "coroutine object" not in raw
        assert raw == ROWS_REPLY

    async def test_async_tool_returns_its_value(self):
        server = _server("/__t-async-tool")
        raw = await server.handle_message_async(_call("add", {"a": 2, "b": 3}))
        assert "coroutine object" not in raw
        assert raw == ADD_REPLY

    async def test_rejecting_async_resource_is_internal_error(self):
        server = _server("/__t-async-res-boom")
        with no_unawaited_coroutines():
            raw = await server.handle_message_async(_read("probe://boom", rid=7))
        _assert_internal_error(raw, 7, "db down")

    async def test_rejecting_async_tool_is_internal_error(self):
        server = _server("/__t-async-tool-boom")
        with no_unawaited_coroutines():
            raw = await server.handle_message_async(_call("boom", {"x": 4}, rid=8))
        _assert_internal_error(raw, 8, "tool failed on 4")

    async def test_sync_handlers_answer_byte_identically_on_both_paths(self):
        server = _server("/__t-sync-both")
        for message, expected in (
            (_read("probe://sync-rows"), encode_response(1, {"contents": [{
                "uri": "probe://sync-rows", "mimeType": "application/json",
                "text": json.dumps({"rows": [1, 2, 3]}, indent=2)}]})),
            (_call("sync_add", {"a": 2, "b": 3}), ADD_REPLY),
        ):
            assert await server.handle_message_async(message) == expected
            # The sync entry point is still usable for sync handlers inside a
            # running loop — nothing about them changed.
            assert server.handle_message(message) == expected

    async def test_async_notification_gets_no_reply(self):
        server = _server("/__t-async-notify")
        message = {"jsonrpc": "2.0", "method": "tools/call",
                   "params": {"name": "add", "arguments": {"a": 1, "b": 1}}}
        assert await server.handle_message_async(message) == ""


# ── handle_message (sync, public API) ──────────────────────────────────────

class TestHandleMessageSync:
    def test_async_resource_without_running_loop(self):
        server = _server("/__t-sync-res")
        with no_unawaited_coroutines():
            assert server.handle_message(_read("probe://rows")) == ROWS_REPLY

    def test_async_tool_without_running_loop(self):
        server = _server("/__t-sync-tool")
        with no_unawaited_coroutines():
            assert server.handle_message(json.dumps(_call("add", {"a": 2, "b": 3}))) == ADD_REPLY

    def test_rejecting_async_handlers_without_running_loop(self):
        server = _server("/__t-sync-boom")
        with no_unawaited_coroutines():
            _assert_internal_error(server.handle_message(_read("probe://boom", rid=3)), 3, "db down")
            _assert_internal_error(server.handle_message(_call("boom", {"x": 1}, rid=4)), 4,
                                   "tool failed on 1")

    def test_leaves_the_threads_event_loop_setting_alone(self):
        # The private loop handle_message drives must not become (or clear)
        # this thread's current loop for code that runs afterwards.
        server = _server("/__t-sync-loop")
        own = asyncio.new_event_loop()
        asyncio.set_event_loop(own)
        try:
            assert server.handle_message(_read("probe://rows")) == ROWS_REPLY
            assert asyncio.get_event_loop() is own
        finally:
            asyncio.set_event_loop(None)
            own.close()

    async def test_async_handler_inside_running_loop_is_clear_error(self):
        server = _server("/__t-sync-in-loop")
        message = ("async MCP handler cannot be awaited by the synchronous handle_message() "
                   "inside a running event loop; await handle_message_async() instead")
        with no_unawaited_coroutines():
            _assert_internal_error(server.handle_message(_read("probe://rows", rid=5)), 5, message)
            _assert_internal_error(server.handle_message(_call("add", {"a": 1, "b": 2}, rid=6)), 6,
                                   message)


# ── The real async HTTP routes ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    server = _server("/__t-async-route")
    server.register_routes(router)
    return TestClient()


class TestRegisteredRoutes:
    """POST through the real ASGI app to the routes register_routes mounts."""

    def test_streamable_resource(self, client):
        res = client.post("/__t-async-route", json=_read("probe://rows"))
        assert res.status == 200
        assert res.json() == json.loads(ROWS_REPLY)

    def test_streamable_tool(self, client):
        res = client.post("/__t-async-route", json=_call("add", {"a": 2, "b": 3}))
        assert res.status == 200
        assert res.json() == json.loads(ADD_REPLY)

    def test_streamable_rejections(self, client):
        res = client.post("/__t-async-route", json=_read("probe://boom", rid=9))
        _assert_internal_error(json.dumps(res.json()), 9, "db down")
        res = client.post("/__t-async-route", json=_call("boom", {"x": 2}, rid=10))
        _assert_internal_error(json.dumps(res.json()), 10, "tool failed on 2")

    def test_sync_handlers_unchanged_over_http(self, client):
        res = client.post("/__t-async-route", json=_call("sync_add", {"a": 2, "b": 3}))
        assert res.status == 200
        assert res.json() == json.loads(ADD_REPLY)

    def test_legacy_message_path(self, client):
        res = client.post("/__t-async-route/message", json=_read("probe://rows"))
        assert res.status == 200
        assert res.json() == json.loads(ROWS_REPLY)
        res = client.post("/__t-async-route/message", json=_call("add", {"a": 2, "b": 3}))
        assert res.json() == json.loads(ADD_REPLY)


@pytest.fixture
def dev_mcp():
    """Turn the dev MCP endpoint on for a loopback caller and put an async tool
    and resource on the real default server; restore everything after."""
    keys = ("TINA4_DEBUG", "TINA4_MCP", "TINA4_MCP_REMOTE", "TINA4_MCP_TOKEN", "TINA4_HOST")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    os.environ["TINA4_DEBUG"] = "true"
    server = _get_default_server()
    server.register_tool("__t_async_add", add, "adds")
    server.register_resource("probe://dev-rows", rows, "rows")
    try:
        yield TestClient()
    finally:
        server._tools.pop("__t_async_add", None)
        server._resources.pop("probe://dev-rows", None)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestDevAdminEndpoint:
    """The dev-admin /__dev/mcp routes, through the real ASGI app."""

    def test_async_tool_and_resource(self, dev_mcp):
        res = dev_mcp.post("/__dev/mcp", json=_call("__t_async_add", {"a": 2, "b": 3}))
        assert res.status == 200
        assert res.json() == json.loads(ADD_REPLY)
        res = dev_mcp.post("/__dev/mcp/message", json=_read("probe://dev-rows"))
        assert res.status == 200
        assert res.json()["result"]["contents"][0]["text"] == json.dumps({"rows": [1, 2, 3]}, indent=2)
