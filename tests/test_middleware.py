#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import pytest
from tina4_python.MiddleWare import MiddleWare


# --- Test middleware classes ---

class SyncMiddleware:
    @staticmethod
    def before_auth(request, response):
        request.headers["X-Before"] = "ran"
        return request, response

    @staticmethod
    def after_log(request, response):
        response.content = response.content + " [logged]"
        return request, response

    @staticmethod
    def check_something(request, response):
        request.headers["X-Any"] = "ran"
        return request, response


class AsyncMiddleware:
    @staticmethod
    async def before_validate(request, response):
        request.headers["X-Async-Before"] = "yes"
        return request, response

    @staticmethod
    async def after_cleanup(request, response):
        response.content = response.content + " [cleaned]"
        return request, response


class EmptyMiddleware:
    pass


class OnlyBeforeMiddleware:
    @staticmethod
    def before_check(request, response):
        request.headers["X-Only-Before"] = "true"
        return request, response


# --- Simple request/response mocks ---

class MockRequest:
    def __init__(self):
        self.headers = {}
        self.body = {}


class MockResponse:
    def __init__(self, content=""):
        self.content = content
        self.http_code = 200


# --- Method categorization ---

def test_before_methods_detected():
    mw = MiddleWare(SyncMiddleware)
    assert "before_auth" in mw.before_methods
    assert "after_log" not in mw.before_methods


def test_after_methods_detected():
    mw = MiddleWare(SyncMiddleware)
    assert "after_log" in mw.after_methods
    assert "before_auth" not in mw.after_methods


def test_any_methods_detected():
    mw = MiddleWare(SyncMiddleware)
    assert "check_something" in mw.any_methods


def test_empty_middleware():
    mw = MiddleWare(EmptyMiddleware)
    assert mw.before_methods == []
    assert mw.after_methods == []
    assert mw.any_methods == []


def test_only_before_middleware():
    mw = MiddleWare(OnlyBeforeMiddleware)
    assert "before_check" in mw.before_methods
    assert mw.after_methods == []
    assert mw.any_methods == []


# --- Sync before/after/any ---

@pytest.mark.asyncio
async def test_call_before_methods_sync():
    mw = MiddleWare(SyncMiddleware)
    req = MockRequest()
    resp = MockResponse()
    req, resp = await mw.call_before_methods(req, resp)
    assert req.headers["X-Before"] == "ran"


@pytest.mark.asyncio
async def test_call_after_methods_sync():
    mw = MiddleWare(SyncMiddleware)
    req = MockRequest()
    resp = MockResponse("response")
    req, resp = await mw.call_after_methods(req, resp)
    assert resp.content == "response [logged]"


@pytest.mark.asyncio
async def test_call_any_methods_sync():
    mw = MiddleWare(SyncMiddleware)
    req = MockRequest()
    resp = MockResponse()
    req, resp = await mw.call_any_methods(req, resp)
    assert req.headers["X-Any"] == "ran"


# --- Async before/after ---

@pytest.mark.asyncio
async def test_call_before_methods_async():
    mw = MiddleWare(AsyncMiddleware)
    req = MockRequest()
    resp = MockResponse()
    req, resp = await mw.call_before_methods(req, resp)
    assert req.headers["X-Async-Before"] == "yes"


@pytest.mark.asyncio
async def test_call_after_methods_async():
    mw = MiddleWare(AsyncMiddleware)
    req = MockRequest()
    resp = MockResponse("data")
    req, resp = await mw.call_after_methods(req, resp)
    assert resp.content == "data [cleaned]"


# --- call_direct_method ---

def test_call_direct_method():
    mw = MiddleWare(SyncMiddleware)
    req = MockRequest()
    resp = MockResponse()
    req, resp = mw.call_direct_method(req, resp, "before_auth")
    assert req.headers["X-Before"] == "ran"


def test_call_direct_method_any():
    mw = MiddleWare(SyncMiddleware)
    req = MockRequest()
    resp = MockResponse()
    req, resp = mw.call_direct_method(req, resp, "check_something")
    assert req.headers["X-Any"] == "ran"


# --- Empty middleware calls ---

@pytest.mark.asyncio
async def test_empty_before():
    mw = MiddleWare(EmptyMiddleware)
    req = MockRequest()
    resp = MockResponse()
    req, resp = await mw.call_before_methods(req, resp)
    assert req.headers == {}


@pytest.mark.asyncio
async def test_empty_after():
    mw = MiddleWare(EmptyMiddleware)
    req = MockRequest()
    resp = MockResponse("unchanged")
    req, resp = await mw.call_after_methods(req, resp)
    assert resp.content == "unchanged"
