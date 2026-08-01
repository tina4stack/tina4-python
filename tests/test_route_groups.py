# Feature 79 (route groups) — a group must not weaken the auth gate, and its
# prefix and middleware must compose exactly once.
#
# ADR-0019. Attaching middleware to a group used to make every write route
# inside it PUBLIC, and a nested group's prefix was silently dropped. Real
# requests through the REAL front controller (TestClient -> core.server.app),
# which is the only layer where the auth gate actually runs.
import pytest

from tina4_python.core.router import Router
from tina4_python.test_client import TestClient


class CountingMiddleware:
    """An ordinary group middleware. It does NOT do auth."""

    runs = 0

    @staticmethod
    def before_count(request, response):
        CountingMiddleware.runs += 1
        return request, response


@pytest.fixture(autouse=True)
def reset_counter():
    CountingMiddleware.runs = 0
    yield


async def _handler(request, response):
    return response({"ok": True})


class TestRouteGroupAuth:
    """The security pair. Neither case can pass vacuously without the other."""

    def test_ungrouped_write_route_is_secured_by_default(self):
        # The control. If this ever goes public the test below proves nothing.
        Router.add("POST", "/rg/plain", _handler)
        assert TestClient().post("/rg/plain", json={"x": 1}).status == 401

    def test_group_middleware_does_not_open_a_secured_write_route(self):
        # Attaching a logging/audit middleware to a group must not remove the
        # write-secure-by-default gate from every route inside it.
        Router.group(
            "/rg/secured",
            lambda group: group.post("/thing", _handler),
            middleware=[CountingMiddleware],
        )
        response = TestClient().post("/rg/secured/thing", json={"x": 1})
        assert response.status == 401, (
            "group middleware silently opened a secured write route - an "
            f"unauthenticated POST returned {response.status}"
        )

    def test_group_middleware_does_not_open_a_nested_write_route(self):
        Router.group(
            "/rg/outer",
            lambda group: group.group("/inner", lambda inner: inner.post("/thing", _handler)),
            middleware=[CountingMiddleware],
        )
        assert TestClient().post("/rg/outer/inner/thing", json={"x": 1}).status == 401

    def test_group_route_can_still_be_opened_explicitly(self):
        # The positive twin: @noauth is the explicit spelling and must work,
        # or the fix would leave no way to declare a public write route.
        Router.group(
            "/rg/public",
            lambda group: group.post("/thing", _handler, auth_required=False),
            middleware=[CountingMiddleware],
        )
        assert TestClient().post("/rg/public/thing", json={"x": 1}).status == 200


class TestRouteGroupComposition:
    def test_group_middleware_runs_once_per_request(self):
        # It used to be merged twice (once by RouteGroup, once by Router.add),
        # so it ran twice. A counter or a rate-limit bucket double-counted.
        Router.group(
            "/rg/once",
            lambda group: group.get("/thing", _handler),
            middleware=[CountingMiddleware],
        )
        CountingMiddleware.runs = 0
        assert TestClient().get("/rg/once/thing").status == 200
        assert CountingMiddleware.runs == 1, (
            f"group middleware ran {CountingMiddleware.runs} times, expected 1"
        )

    def test_nested_group_prefix_composes(self):
        # The nested prefix was built correctly and then never read, so the
        # route silently landed on the OUTER prefix - a wrong path that can
        # collide with an existing route or sit inside a different gate.
        Router.group(
            "/rg/api",
            lambda group: group.group("/admin", lambda admin: admin.get("/stats", _handler)),
        )
        paths = [route["path"] for route in Router.get_routes()]
        assert "/rg/api/admin/stats" in paths, (
            f"nested group prefix was dropped; registered paths: "
            f"{[p for p in paths if 'stats' in p]}"
        )
        assert "/rg/api/stats" not in paths

    def test_nested_group_middleware_composes(self):
        outer_marker = CountingMiddleware

        class InnerMiddleware:
            runs = 0

            @staticmethod
            def before_inner(request, response):
                InnerMiddleware.runs += 1
                return request, response

        Router.group(
            "/rg/nest",
            lambda group: group.group(
                "/deep",
                lambda inner: inner.get("/thing", _handler),
                middleware=[InnerMiddleware],
            ),
            middleware=[outer_marker],
        )
        outer_marker.runs = 0
        InnerMiddleware.runs = 0
        assert TestClient().get("/rg/nest/deep/thing").status == 200
        assert outer_marker.runs == 1, f"outer ran {outer_marker.runs} times, expected 1"
        assert InnerMiddleware.runs == 1, f"inner ran {InnerMiddleware.runs} times, expected 1"
