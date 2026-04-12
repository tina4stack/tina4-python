"""Test middleware patterns — demonstrates: request logger middleware timing,
admin auth middleware role checking.

These are thin tests since middleware normally runs inside the HTTP server.
We test the before/after methods directly with mock request/response objects.
"""
import time
import pytest
from tina4_python.auth import Auth, get_token, valid_token, get_payload


class FakeRequest:
    """Minimal request mock for middleware tests."""

    def __init__(self, method="GET", url="/test", headers=None, session=None):
        self.method = method
        self.url = url
        self.headers = headers or {}
        self.session = session or FakeSession()


class FakeSession:
    """Minimal session mock."""

    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class FakeResponse:
    """Minimal response mock that captures status codes and redirect targets."""

    def __init__(self):
        self.status_code = 200
        self._body = None
        self._redirect_url = None

    def __call__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        return self

    def redirect(self, url):
        self._redirect_url = url
        self.status_code = 302
        return self


class TestRequestLoggerMiddleware:
    def test_before_sets_start_time(self):
        from src.middleware.request_logger import RequestLogger

        request = FakeRequest(method="GET", url="/api/products")
        response = FakeResponse()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            RequestLogger.before(request, response)
        )

        req, resp = result
        assert hasattr(req, "_start_time")
        assert isinstance(req._start_time, float)

    def test_after_calculates_duration(self):
        from src.middleware.request_logger import RequestLogger

        request = FakeRequest(method="GET", url="/api/products")
        response = FakeResponse()
        request._start_time = time.time() - 0.05  # 50ms ago

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            RequestLogger.after(request, response)
        )

        req, resp = result
        # Should not raise and should return request/response pair
        assert req is request
        assert resp is response

    def test_before_and_after_round_trip(self):
        from src.middleware.request_logger import RequestLogger

        request = FakeRequest(method="POST", url="/api/orders")
        response = FakeResponse()

        import asyncio
        loop = asyncio.get_event_loop()

        req, resp = loop.run_until_complete(RequestLogger.before(request, response))
        assert hasattr(req, "_start_time")

        req, resp = loop.run_until_complete(RequestLogger.after(req, resp))
        assert req.method == "POST"


class TestAdminAuthMiddleware:
    def test_no_token_redirects_to_login(self):
        from src.middleware.admin_auth import AdminAuth

        session = FakeSession({})
        request = FakeRequest(session=session)
        response = FakeResponse()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            AdminAuth.before(request, response)
        )

        # Should redirect to login
        assert result._redirect_url == "/login" or result.status_code == 302

    def test_invalid_token_redirects_to_login(self):
        from src.middleware.admin_auth import AdminAuth

        session = FakeSession({"token": "invalid.jwt.token"})
        request = FakeRequest(session=session)
        response = FakeResponse()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            AdminAuth.before(request, response)
        )

        assert result._redirect_url == "/login" or result.status_code == 302

    def test_valid_admin_token_passes(self):
        from src.middleware.admin_auth import AdminAuth

        token = get_token({"user_id": 1, "role": "admin"})
        session = FakeSession({"token": token})
        request = FakeRequest(session=session)
        response = FakeResponse()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            AdminAuth.before(request, response)
        )

        # Admin passes through: returns (request, response) tuple
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_customer_role_returns_forbidden(self):
        from src.middleware.admin_auth import AdminAuth

        token = get_token({"user_id": 2, "role": "customer"})
        session = FakeSession({"token": token})
        request = FakeRequest(session=session)
        response = FakeResponse()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            AdminAuth.before(request, response)
        )

        # Non-admin gets 403
        assert result.status_code == 403
        assert result._body["error"] == "Forbidden: admin access required"
