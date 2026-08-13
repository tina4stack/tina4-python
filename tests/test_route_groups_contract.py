# Feature 32 (route groups) — the prefix+path JOIN grammar (RG-DEC-01).
#
# The audit found the join grammar diverges and is UNGATED: PHP fully
# normalizes (Tina4/Router.php addRoute — the reference: one separator, no
# double slash, a single leading slash); Python bare-concatenated
# (cls._group_prefix + path), so group("/api") + get("users") silently
# mis-registered at "/apiusers" instead of "/api/users". This converges
# Python onto PHP's grammar (core/router.py:_join_group_path, ported
# verbatim from Router.php).
#
# Real registration through the real Router, real dispatch through
# TestClient -> core.server.app (the SAME front controller a live request
# hits) — no mocks. Positive AND negative: the OLD mis-registered path must
# 404 once the fix is in place.
#
# Same case names in all four:
#   tina4-php/tests/RouteGroupsContractTest.php
#   tina4-ruby/spec/route_groups_contract_spec.rb
#   tina4-nodejs/test/routeGroupsContract.test.ts
#
# See tina4-documentation/plan/v3/fixtures/route_groups_contract.json.
from tina4_python.core.router import Router
from tina4_python.test_client import TestClient


async def _ok(request, response):
    return response({"ok": True})


class _CountingMiddleware:
    """An ordinary group middleware. It does NOT do auth."""

    runs = 0

    @staticmethod
    def before_count(request, response):
        _CountingMiddleware.runs += 1
        return request, response


class TestRouteGroupsSlashNormalization:
    def test_group_prefix_joins_to_a_single_slash_path(self):
        # group("/api") + get("users") — the route's own path has NO leading
        # slash. The old bare concatenation silently produced "/apiusers".
        Router.group("/__rg32/c1", lambda group: group.get("users", _ok))

        client = TestClient()
        assert client.get("/__rg32/c1/users").status == 200, (
            "the normalized join must resolve at /__rg32/c1/users"
        )
        # Negative: the OLD mis-registered path (missing separator) must not
        # exist as a route.
        assert client.get("/__rg32/c1users").status == 404, (
            "the bare-concat mis-registration (/__rg32/c1users) must not resolve"
        )

    def test_leading_slash_on_the_route_is_normalized(self):
        # group("/api") + get("/users") — the route's own path ALREADY
        # carries its leading slash. Must land on the SAME single-slash
        # canonical path as the no-leading-slash form above, never a double
        # slash.
        Router.group("/__rg32/c2", lambda group: group.get("/users", _ok))

        client = TestClient()
        assert client.get("/__rg32/c2/users").status == 200

        paths = [route["path"] for route in Router.get_routes()]
        assert "/__rg32/c2/users" in paths
        assert "/__rg32/c2//users" not in paths, (
            "a route path must never carry a doubled separator"
        )

    def test_trailing_slash_on_the_prefix_is_normalized(self):
        # group("/api/") + get("/users") — the GROUP prefix carries a
        # trailing slash. Must ALSO land on the same canonical path.
        Router.group("/__rg32/c3/", lambda group: group.get("/users", _ok))

        client = TestClient()
        assert client.get("/__rg32/c3/users").status == 200

        paths = [route["path"] for route in Router.get_routes()]
        assert "/__rg32/c3/users" in paths
        assert "/__rg32/c3//users" not in paths, (
            "a trailing slash on the group prefix must not leave a doubled separator"
        )

    def test_nested_groups_concatenate_the_prefix(self):
        # group("/api") > group("/v1") + get("users") -> "/api/v1/users".
        # Nesting composes the prefix AND the final join must still insert
        # exactly one separator before the innermost route's own path.
        Router.group(
            "/__rg32/c4",
            lambda group: group.group("/v1", lambda inner: inner.get("users", _ok)),
        )

        client = TestClient()
        assert client.get("/__rg32/c4/v1/users").status == 200, (
            "nested groups must concatenate to /__rg32/c4/v1/users"
        )
        # Negative: the OLD missing-separator mis-registration must not exist.
        assert client.get("/__rg32/c4/v1users").status == 404, (
            "the nested bare-concat mis-registration (/__rg32/c4/v1users) must not resolve"
        )


class TestRouteGroupsWriteAuthGate:
    def test_group_middleware_never_opens_the_write_auth_gate(self):
        # LOCK: group middleware must never disable the secure-by-default
        # write-auth gate — including under the newly-normalized prefix
        # join. An ordinary (non-auth) group middleware attached to a POST
        # route inside a group must still 401 a tokenless request.
        _CountingMiddleware.runs = 0
        Router.group(
            "/__rg32/c5",
            lambda group: group.post("/thing", _ok),
            middleware=[_CountingMiddleware],
        )

        response = TestClient().post("/__rg32/c5/thing", json={"x": 1})
        assert response.status == 401, (
            "group middleware silently opened a secured write route under "
            f"the normalized join - got {response.status}"
        )
