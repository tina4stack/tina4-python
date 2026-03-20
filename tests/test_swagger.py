# Tests for tina4_python.swagger
import json
import pytest
from tina4_python.swagger import (
    Swagger, description, summary, tags,
    example, example_response, deprecated,
)


@pytest.fixture
def swagger():
    return Swagger(title="Test API", version="1.0.0")


def _handler():
    """Dummy route handler."""
    pass


# ── Spec Generation Tests ─────────────────────────────────────


class TestSwaggerGeneration:
    def test_empty_spec(self, swagger):
        spec = swagger.generate([])
        assert spec["openapi"] == "3.0.3"
        assert spec["info"]["title"] == "Test API"
        assert spec["paths"] == {}

    def test_simple_route(self, swagger):
        routes = [{"method": "GET", "path": "/api/users", "handler": _handler}]
        spec = swagger.generate(routes)
        assert "/api/users" in spec["paths"]
        assert "get" in spec["paths"]["/api/users"]

    def test_multiple_methods(self, swagger):
        routes = [
            {"method": "GET", "path": "/api/items", "handler": _handler},
            {"method": "POST", "path": "/api/items", "handler": _handler},
        ]
        spec = swagger.generate(routes)
        assert "get" in spec["paths"]["/api/items"]
        assert "post" in spec["paths"]["/api/items"]

    def test_path_params(self, swagger):
        routes = [{"method": "GET", "path": "/api/users/{id:int}", "handler": _handler}]
        spec = swagger.generate(routes)
        assert "/api/users/{id}" in spec["paths"]
        params = spec["paths"]["/api/users/{id}"]["get"]["parameters"]
        assert params[0]["name"] == "id"
        assert params[0]["schema"]["type"] == "integer"

    def test_auth_required(self, swagger):
        routes = [{"method": "POST", "path": "/api/secure", "handler": _handler, "auth_required": True}]
        spec = swagger.generate(routes)
        assert "security" in spec["paths"]["/api/secure"]["post"]

    def test_operation_id(self, swagger):
        routes = [{"method": "GET", "path": "/api/users/{id}", "handler": _handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/api/users/{id}"]["get"]["operationId"] == "get_api_users_id"


# ── Decorator Tests ────────────────────────────────────────────


class TestSwaggerDecorators:
    def test_description_decorator(self, swagger):
        @description("List all users")
        def handler():
            pass

        routes = [{"method": "GET", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/users"]["get"]["description"] == "List all users"

    def test_summary_decorator(self, swagger):
        @summary("Get users")
        def handler():
            pass

        routes = [{"method": "GET", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/users"]["get"]["summary"] == "Get users"

    def test_tags_decorator(self, swagger):
        @tags(["users", "admin"])
        def handler():
            pass

        routes = [{"method": "GET", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/users"]["get"]["tags"] == ["users", "admin"]

    def test_example_decorator(self, swagger):
        @example({"name": "Alice", "email": "alice@test.com"})
        def handler():
            pass

        routes = [{"method": "POST", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        body = spec["paths"]["/users"]["post"]["requestBody"]
        assert body["content"]["application/json"]["example"]["name"] == "Alice"

    def test_example_response_decorator(self, swagger):
        @example_response({"id": 1, "name": "Alice"})
        def handler():
            pass

        routes = [{"method": "GET", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        resp = spec["paths"]["/users"]["get"]["responses"]["200"]
        assert resp["content"]["application/json"]["example"]["id"] == 1

    def test_deprecated_decorator(self, swagger):
        @deprecated()
        def handler():
            pass

        routes = [{"method": "GET", "path": "/old", "handler": handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/old"]["get"]["deprecated"] is True

    def test_stacked_decorators(self, swagger):
        @description("Create user")
        @tags(["users"])
        @example({"name": "Bob"})
        def handler():
            pass

        routes = [{"method": "POST", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        op = spec["paths"]["/users"]["post"]
        assert op["description"] == "Create user"
        assert op["tags"] == ["users"]
        assert "requestBody" in op


# ── Schema Inference Tests ─────────────────────────────────────


class TestSchemaInference:
    def test_infer_string(self):
        assert Swagger._infer_schema("hello") == {"type": "string"}

    def test_infer_integer(self):
        assert Swagger._infer_schema(42) == {"type": "integer"}

    def test_infer_float(self):
        assert Swagger._infer_schema(3.14) == {"type": "number"}

    def test_infer_boolean(self):
        assert Swagger._infer_schema(True) == {"type": "boolean"}

    def test_infer_object(self):
        schema = Swagger._infer_schema({"name": "Alice", "age": 30})
        assert schema["type"] == "object"
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"

    def test_infer_array(self):
        schema = Swagger._infer_schema([1, 2, 3])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "integer"

    def test_infer_nested(self):
        schema = Swagger._infer_schema({"user": {"name": "Alice"}})
        assert schema["properties"]["user"]["type"] == "object"

    def test_generate_json(self, swagger):
        spec_json = swagger.generate_json([])
        parsed = json.loads(spec_json)
        assert parsed["openapi"] == "3.0.3"
