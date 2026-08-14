"""Parity Group C — mixins and decorators.

* Test base class with HTTP client mixin (self.get/post/...)
* Frond.add_filter / add_global / add_test callable as classmethods AND
  as instance methods (the dual-call descriptor)
* @GraphQL.resolve("Type", "field") decorator pattern
"""
from __future__ import annotations

import pytest


# ─── Test class HTTP helpers ──────────────────────────────────────────────


class TestTestClassHTTPMixin:
    def test_get_method_returns_test_response(self):
        from tina4_python.test import Test
        from tina4_python.core.router import get

        # Define a route so the test client has something to hit
        @get("/parity-c-health-test")
        async def health(request, response):
            return response({"status": "ok"})

        # Build a Test subclass and exercise the mixed-in HTTP method.
        # We don't actually inherit pytest discovery here — we just want
        # to confirm self.get / self.post call through to TestClient.
        class HealthTest(Test):
            def runTest(self):
                pass

        suite = HealthTest()
        resp = suite.get("/parity-c-health-test")
        assert resp.status == 200
        assert resp.json() == {"status": "ok"}

    def test_post_with_json_body(self):
        from tina4_python.test import Test
        from tina4_python.core.router import post, noauth

        @noauth()
        @post("/parity-c-echo-test")
        async def echo(request, response):
            return response({"received": request.body}, 201)

        class EchoTest(Test):
            def runTest(self):
                pass

        suite = EchoTest()
        resp = suite.post("/parity-c-echo-test", json={"name": "Alice"})
        assert resp.status == 201
        assert resp.json() == {"received": {"name": "Alice"}}

    def test_put_patch_delete_methods_callable(self):
        from tina4_python.test import Test

        class GenericTest(Test):
            def runTest(self):
                pass

        suite = GenericTest()
        # We just verify the methods are bound and callable — return values
        # may be 404 since we haven't registered routes for these specific
        # paths, but they shouldn't raise AttributeError.
        for method in (suite.put, suite.patch):
            resp = method("/parity-c-not-a-route")
            assert hasattr(resp, "status")
        resp = suite.delete("/parity-c-not-a-route")
        assert hasattr(resp, "status")

    def test_client_lazy_initialised_once(self):
        from tina4_python.test import Test

        class LazyTest(Test):
            def runTest(self):
                pass

        suite = LazyTest()
        client_1 = suite._client
        client_2 = suite._client
        assert client_1 is client_2  # cached


# ─── Frond classmethod proxies ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_frond_registry():
    """Clear class-level filters/globals/tests between tests so each test
    sees a clean Frond. Doesn't touch built-in filters."""
    from tina4_python.frond import Frond
    Frond.clear_registry()
    yield
    Frond.clear_registry()


class TestFrondClassmethodProxies:
    def test_class_registration_is_process_global(self):
        from tina4_python.frond import Frond

        Frond.add_filter("class_filter", lambda value: f"class:{value}")
        assert Frond()._filters["class_filter"]("value") == "class:value"

    def test_add_filter_callable_on_class(self):
        from tina4_python.frond import Frond

        Frond.add_filter("upper_x", lambda v: str(v).upper())
        # New instance picks it up
        engine = Frond()
        assert "upper_x" in engine._filters
        assert engine._filters["upper_x"]("hi") == "HI"

    def test_instance_filter_registration_is_instance_local(self):
        from tina4_python.frond import Frond

        engine = Frond()
        engine.add_filter("instance_x", lambda v: f"[{v}]")
        # Instance has it
        assert engine._filters["instance_x"]("y") == "[y]"
        assert "instance_x" not in Frond._class_filters
        engine_2 = Frond()
        assert "instance_x" not in engine_2._filters

    def test_add_global_callable_on_class(self):
        from tina4_python.frond import Frond

        Frond.add_global("APP_NAME", "ParityApp")
        engine = Frond()
        assert engine._globals["APP_NAME"] == "ParityApp"

    def test_instance_global_registration_is_instance_local(self):
        from tina4_python.frond import Frond

        engine = Frond()
        engine.add_global("INST_GLOBAL", 42)
        assert engine._globals["INST_GLOBAL"] == 42
        assert "INST_GLOBAL" not in Frond._class_globals
        assert "INST_GLOBAL" not in Frond()._globals

    def test_add_test_callable_on_class(self):
        from tina4_python.frond import Frond

        Frond.add_test("positive", lambda x: x > 0)
        engine = Frond()
        assert engine._tests["positive"](5) is True
        assert engine._tests["positive"](-1) is False

    def test_instance_test_registration_is_instance_local(self):
        from tina4_python.frond import Frond

        engine = Frond()
        engine.add_test("starts_with_a", lambda s: s.startswith("a"))
        assert "starts_with_a" in engine._tests
        assert "starts_with_a" not in Frond._class_tests
        assert "starts_with_a" not in Frond()._tests


# ─── @GraphQL.resolve decorator ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_gql_registry():
    """Clear class-level resolvers between tests."""
    from tina4_python.graphql import GraphQL
    GraphQL._class_resolvers.clear()
    if hasattr(GraphQL, "_default_instance"):
        GraphQL._default_instance = None
    yield
    GraphQL._class_resolvers.clear()


class TestGraphQLResolveDecorator:
    def test_classmethod_decorator_registers_resolver(self):
        from tina4_python.graphql import GraphQL

        @GraphQL.resolve("Query", "hello")
        def hello_resolver(root, args, ctx):
            return "world"

        assert ("Query", "hello") in GraphQL._class_resolvers

    def test_new_graphql_instance_picks_up_class_registrations(self):
        from tina4_python.graphql import GraphQL

        @GraphQL.resolve("Query", "ping")
        def ping(root, args, ctx):
            return "pong"

        gql = GraphQL()
        assert "ping" in gql.schema.queries
        assert gql.schema.queries["ping"]["resolve"] is ping

    def test_mutation_registration(self):
        from tina4_python.graphql import GraphQL

        @GraphQL.resolve("Mutation", "createWidget")
        def create_widget(root, args, ctx):
            return {"id": 1, "name": args.get("name", "x")}

        gql = GraphQL()
        assert "createWidget" in gql.schema.mutations
        result = gql.schema.mutations["createWidget"]["resolve"](
            None, {"name": "Sprocket"}, {}
        )
        assert result["name"] == "Sprocket"

    def test_field_resolver_on_object_type(self):
        from tina4_python.graphql import GraphQL

        @GraphQL.resolve("Product", "reviews")
        def product_reviews(product, args, ctx):
            return [{"id": 1, "rating": 5}]

        gql = GraphQL()
        # Field resolvers stash on schema.field_resolvers dict
        assert hasattr(gql.schema, "field_resolvers")
        assert ("Product", "reviews") in gql.schema.field_resolvers

    def test_post_instantiation_registration_via_default(self):
        from tina4_python.graphql import GraphQL

        gql = GraphQL()
        GraphQL.set_default(gql)

        @GraphQL.resolve("Query", "lateBound")
        def late(root, args, ctx):
            return "registered after init"

        # The default instance picked it up immediately
        assert "lateBound" in gql.schema.queries
