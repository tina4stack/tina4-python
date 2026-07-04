"""Frond {% live %} endpoint - /__frond/live/{name}.

Real dispatch through the router + real Request/Response + real Frond engine.
No doubles: Request/Response/Frond are the actual framework collaborators.
"""
import pytest

from tina4_python.core.router import Router
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.frond import Frond, live_source, live_endpoint


def _register_route_module():
    import tina4_python.core.server  # noqa: F401  (registers /__frond/live/{name} at import)


def _fresh():
    Frond.clear_registry()


def test_endpoint_is_registered_with_name_param():
    _register_route_module()
    route, params = Router.match("GET", "/__frond/live/notifications")
    assert route is not None
    assert params.get("name") == "notifications"


async def test_endpoint_reregisters_fragment_with_provider_data():
    _fresh()
    engine = Frond()
    engine.render_string(
        '{% live "cart" poll 5 %}<b>{{ count }}</b> items{% endlive %}', {"count": 1})

    @live_source("cart")
    def _cart(request):
        return {"count": 7}

    resp = await live_endpoint("cart", Request(), Response())
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "<b>7</b> items" == body.strip() or "<b>7</b> items" in body


async def test_endpoint_unknown_name_404():
    _fresh()
    resp = await live_endpoint("nope", Request(), Response())
    assert resp.status_code == 404


async def test_endpoint_fragment_not_rendered_yet_404():
    _fresh()

    @live_source("later")
    def _later(request):
        return {"x": 1}

    resp = await live_endpoint("later", Request(), Response())
    assert resp.status_code == 404


async def test_endpoint_async_provider_awaited():
    _fresh()
    Frond().render_string('{% live "async" poll 5 %}<i>{{ v }}</i>{% endlive %}', {"v": 0})

    @live_source("async")
    async def _prov(request):
        return {"v": 42}

    resp = await live_endpoint("async", Request(), Response())
    assert "<i>42</i>" in resp.content.decode()


async def test_endpoint_reapplies_auth_scoping_per_request():
    """The IDOR contract: the provider re-runs with the LIVE request every
    refresh, so an unauthenticated caller can never receive another user's
    scoped fragment."""
    _fresh()
    Frond().render_string('{% live "me" poll 5 %}<span>{{ who }}</span>{% endlive %}', {"who": ""})

    @live_source("me")
    def _me(request):
        user = request.headers.get("x-user") if hasattr(request, "headers") else None
        return {"who": user or "guest"}

    anon = Request()
    anon.headers = {}
    r1 = await live_endpoint("me", anon, Response())
    assert "<span>guest</span>" in r1.content.decode()

    authed = Request()
    authed.headers = {"x-user": "alice"}
    r2 = await live_endpoint("me", authed, Response())
    assert "<span>alice</span>" in r2.content.decode()
    assert "alice" not in r1.content.decode()


async def test_endpoint_provider_none_but_fragment_exists_renders_empty_context():
    _fresh()
    Frond().render_string('{% live "static" poll 5 %}<p>hello</p>{% endlive %}', {})
    resp = await live_endpoint("static", Request(), Response())
    assert resp.status_code == 200
    assert "<p>hello</p>" in resp.content.decode()
