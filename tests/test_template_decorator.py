# Tests for the @template() decorator in tina4_python.core.router
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from tina4_python.core.router import template, Router


# ── Helpers ────────────────────────────────────────────────────


class MockRequest:
    """Minimal request stub."""
    def __init__(self):
        self.url = "/test"
        self.method = "GET"
        self.params = {}
        self.headers = {}


class MockResponse:
    """Response stub with a render method that records calls."""

    def __init__(self):
        self.status_code = 200
        self.content = b""
        self.content_type = "text/html; charset=utf-8"
        self._render_calls = []

    def __call__(self, data=None, status_code=200):
        self.content = str(data).encode() if data else b""
        self.status_code = status_code
        return self

    def render(self, template_name, data):
        self._render_calls.append((template_name, data))
        self.content = f"<rendered:{template_name}>".encode()
        self.content_type = "text/html; charset=utf-8"
        return self


# ── Dict return → auto-render ─────────────────────────────────


class TestTemplateDecoratorDictReturn:
    """When the handler returns a dict, @template renders it."""

    @pytest.mark.asyncio
    async def test_dict_is_rendered_through_template(self):
        @template("pages/dashboard.twig")
        async def handler(request, response):
            return {"title": "Hello"}

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert len(resp._render_calls) == 1
        assert resp._render_calls[0] == ("pages/dashboard.twig", {"title": "Hello"})

    @pytest.mark.asyncio
    async def test_rendered_result_is_returned(self):
        @template("page.twig")
        async def handler(request, response):
            return {"key": "value"}

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert result is resp
        assert b"<rendered:page.twig>" in resp.content

    @pytest.mark.asyncio
    async def test_empty_dict_is_rendered(self):
        @template("empty.twig")
        async def handler(request, response):
            return {}

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert resp._render_calls[0] == ("empty.twig", {})


# ── Non-dict return → pass-through ───────────────────────────


class TestTemplateDecoratorPassthrough:
    """Non-dict returns pass through unchanged."""

    @pytest.mark.asyncio
    async def test_response_object_passes_through(self):
        @template("page.twig")
        async def handler(request, response):
            return response("Already handled")

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert result is resp
        assert resp._render_calls == []

    @pytest.mark.asyncio
    async def test_string_passes_through(self):
        @template("page.twig")
        async def handler(request, response):
            return "<h1>Raw HTML</h1>"

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert result == "<h1>Raw HTML</h1>"
        assert resp._render_calls == []

    @pytest.mark.asyncio
    async def test_none_passes_through(self):
        @template("page.twig")
        async def handler(request, response):
            return None

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert result is None
        assert resp._render_calls == []

    @pytest.mark.asyncio
    async def test_list_passes_through(self):
        @template("page.twig")
        async def handler(request, response):
            return [1, 2, 3]

        req = MockRequest()
        resp = MockResponse()
        result = await handler(req, resp)

        assert result == [1, 2, 3]
        assert resp._render_calls == []


# ── Decorator composition ────────────────────────────────────


class TestTemplateDecoratorComposition:
    """@template works with other decorators."""

    @pytest.mark.asyncio
    async def test_functools_wraps_preserves_name(self):
        @template("page.twig")
        async def my_dashboard(request, response):
            return {"x": 1}

        assert my_dashboard.__name__ == "my_dashboard"

    @pytest.mark.asyncio
    async def test_functools_wraps_preserves_docstring(self):
        @template("page.twig")
        async def my_dashboard(request, response):
            """Dashboard handler."""
            return {"x": 1}

        assert my_dashboard.__doc__ == "Dashboard handler."

    @pytest.mark.asyncio
    async def test_stacks_with_route_decorator(self):
        """@template should work above @get — the route registers
        the wrapped function, which intercepts dict returns."""
        Router.clear()

        from tina4_python.core.router import get

        @template("dash.twig")
        @get("/test-template-route")
        async def dash(request, response):
            return {"title": "Test"}

        route, _ = Router.match("GET", "/test-template-route")
        assert route is not None
        # The registered handler should be the wrapper
        assert route["handler"].__name__ == "dash"

        Router.clear()

    @pytest.mark.asyncio
    async def test_template_name_parameterised(self):
        """Different template names are correctly passed."""
        @template("alpha.twig")
        async def handler_a(request, response):
            return {"a": 1}

        @template("beta.twig")
        async def handler_b(request, response):
            return {"b": 2}

        req = MockRequest()

        resp_a = MockResponse()
        await handler_a(req, resp_a)
        assert resp_a._render_calls[0][0] == "alpha.twig"

        resp_b = MockResponse()
        await handler_b(req, resp_b)
        assert resp_b._render_calls[0][0] == "beta.twig"
