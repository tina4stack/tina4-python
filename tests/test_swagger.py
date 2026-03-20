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


# ── Spec Structure Tests ─────────────────────────────────────


class TestSwaggerSpecStructure:
    def test_spec_has_info(self, swagger):
        spec = swagger.generate([])
        assert "info" in spec
        assert spec["info"]["title"] == "Test API"
        assert spec["info"]["version"] == "1.0.0"

    def test_spec_has_servers(self, swagger):
        spec = swagger.generate([])
        assert "servers" in spec
        assert len(spec["servers"]) > 0

    def test_spec_has_components(self, swagger):
        spec = swagger.generate([])
        assert "components" in spec
        assert "securitySchemes" in spec["components"]

    def test_bearer_auth_scheme(self, swagger):
        spec = swagger.generate([])
        scheme = spec["components"]["securitySchemes"]["bearerAuth"]
        assert scheme["type"] == "http"
        assert scheme["scheme"] == "bearer"
        assert scheme["bearerFormat"] == "JWT"


# ── Path Tests ────────────────────────────────────────────────


class TestSwaggerPaths:
    def test_delete_method(self, swagger):
        routes = [{"method": "DELETE", "path": "/api/users/{id}", "handler": _handler}]
        spec = swagger.generate(routes)
        assert "delete" in spec["paths"]["/api/users/{id}"]

    def test_put_method(self, swagger):
        routes = [{"method": "PUT", "path": "/api/users/{id}", "handler": _handler}]
        spec = swagger.generate(routes)
        assert "put" in spec["paths"]["/api/users/{id}"]

    def test_patch_method(self, swagger):
        routes = [{"method": "PATCH", "path": "/api/users/{id}", "handler": _handler}]
        spec = swagger.generate(routes)
        assert "patch" in spec["paths"]["/api/users/{id}"]

    def test_multiple_paths(self, swagger):
        routes = [
            {"method": "GET", "path": "/api/users", "handler": _handler},
            {"method": "GET", "path": "/api/products", "handler": _handler},
            {"method": "GET", "path": "/api/orders", "handler": _handler},
        ]
        spec = swagger.generate(routes)
        assert len(spec["paths"]) == 3

    def test_empty_routes_empty_paths(self, swagger):
        spec = swagger.generate([])
        assert spec["paths"] == {}


# ── Path Parameter Tests ─────────────────────────────────────


class TestSwaggerPathParams:
    def test_string_param(self, swagger):
        routes = [{"method": "GET", "path": "/api/users/{name}", "handler": _handler}]
        spec = swagger.generate(routes)
        params = spec["paths"]["/api/users/{name}"]["get"]["parameters"]
        assert params[0]["name"] == "name"
        assert params[0]["schema"]["type"] == "string"
        assert params[0]["in"] == "path"
        assert params[0]["required"] is True

    def test_float_param(self, swagger):
        routes = [{"method": "GET", "path": "/api/items/{price:float}", "handler": _handler}]
        spec = swagger.generate(routes)
        params = spec["paths"]["/api/items/{price}"]["get"]["parameters"]
        assert params[0]["schema"]["type"] == "number"

    def test_multiple_params(self, swagger):
        routes = [{"method": "GET", "path": "/api/users/{user_id:int}/posts/{post_id:int}", "handler": _handler}]
        spec = swagger.generate(routes)
        params = spec["paths"]["/api/users/{user_id}/posts/{post_id}"]["get"]["parameters"]
        assert len(params) == 2
        assert params[0]["name"] == "user_id"
        assert params[1]["name"] == "post_id"

    def test_no_params(self, swagger):
        routes = [{"method": "GET", "path": "/api/users", "handler": _handler}]
        spec = swagger.generate(routes)
        assert "parameters" not in spec["paths"]["/api/users"]["get"]


# ── Operation ID Tests ────────────────────────────────────────


class TestSwaggerOperationId:
    def test_simple_path(self, swagger):
        routes = [{"method": "GET", "path": "/api/users", "handler": _handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/api/users"]["get"]["operationId"] == "get_api_users"

    def test_root_path(self, swagger):
        routes = [{"method": "GET", "path": "/", "handler": _handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/"]["get"]["operationId"] == "get"

    def test_post_operation_id(self, swagger):
        routes = [{"method": "POST", "path": "/api/users", "handler": _handler}]
        spec = swagger.generate(routes)
        assert spec["paths"]["/api/users"]["post"]["operationId"] == "post_api_users"


# ── Response Tests ────────────────────────────────────────────


class TestSwaggerResponses:
    def test_default_200_response(self, swagger):
        routes = [{"method": "GET", "path": "/api/users", "handler": _handler}]
        spec = swagger.generate(routes)
        resp = spec["paths"]["/api/users"]["get"]["responses"]
        assert "200" in resp
        assert resp["200"]["description"] == "Successful response"


# ── Example Decorator for PUT/PATCH ──────────────────────────


class TestSwaggerExampleMethods:
    def test_example_on_put(self, swagger):
        @example({"name": "Updated"})
        def handler():
            pass

        routes = [{"method": "PUT", "path": "/users/{id}", "handler": handler}]
        spec = swagger.generate(routes)
        body = spec["paths"]["/users/{id}"]["put"]["requestBody"]
        assert body["content"]["application/json"]["example"]["name"] == "Updated"

    def test_example_on_patch(self, swagger):
        @example({"status": "active"})
        def handler():
            pass

        routes = [{"method": "PATCH", "path": "/users/{id}", "handler": handler}]
        spec = swagger.generate(routes)
        body = spec["paths"]["/users/{id}"]["patch"]["requestBody"]
        assert body["content"]["application/json"]["example"]["status"] == "active"

    def test_example_not_on_get(self, swagger):
        @example({"name": "Alice"})
        def handler():
            pass

        routes = [{"method": "GET", "path": "/users", "handler": handler}]
        spec = swagger.generate(routes)
        assert "requestBody" not in spec["paths"]["/users"]["get"]


# ── Schema Inference Extra ───────────────────────────────────


class TestSchemaInferenceExtra:
    def test_infer_empty_array(self):
        schema = Swagger._infer_schema([])
        assert schema["type"] == "array"
        assert schema["items"] == {}

    def test_infer_array_of_strings(self):
        schema = Swagger._infer_schema(["a", "b", "c"])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "string"

    def test_infer_array_of_objects(self):
        schema = Swagger._infer_schema([{"id": 1}])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "object"

    def test_infer_nested_object(self):
        schema = Swagger._infer_schema({"user": {"address": {"city": "NYC"}}})
        assert schema["properties"]["user"]["properties"]["address"]["properties"]["city"]["type"] == "string"

    def test_infer_none_as_string(self):
        schema = Swagger._infer_schema(None)
        assert schema["type"] == "string"

    def test_infer_boolean_false(self):
        schema = Swagger._infer_schema(False)
        assert schema["type"] == "boolean"


# ── OpenAPI Path Conversion ──────────────────────────────────


class TestOpenAPIPath:
    def test_removes_type_annotation(self):
        assert Swagger._openapi_path("/api/users/{id:int}") == "/api/users/{id}"

    def test_multiple_typed_params(self):
        result = Swagger._openapi_path("/api/{user_id:int}/items/{item_id:int}")
        assert result == "/api/{user_id}/items/{item_id}"

    def test_untyped_param_unchanged(self):
        assert Swagger._openapi_path("/api/users/{id}") == "/api/users/{id}"

    def test_no_params(self):
        assert Swagger._openapi_path("/api/users") == "/api/users"


# ── JSON Generation ──────────────────────────────────────────


class TestSwaggerJSON:
    def test_json_has_all_routes(self, swagger):
        routes = [
            {"method": "GET", "path": "/api/a", "handler": _handler},
            {"method": "POST", "path": "/api/b", "handler": _handler},
        ]
        spec_json = swagger.generate_json(routes)
        parsed = json.loads(spec_json)
        assert "/api/a" in parsed["paths"]
        assert "/api/b" in parsed["paths"]

    def test_json_is_valid(self, swagger):
        routes = [{"method": "GET", "path": "/api/test", "handler": _handler}]
        spec_json = swagger.generate_json(routes)
        parsed = json.loads(spec_json)
        assert isinstance(parsed, dict)


# ── Swagger Constructor ──────────────────────────────────────


class TestSwaggerConstructor:
    def test_default_title(self):
        s = Swagger()
        assert s.title == "Tina4 API"

    def test_custom_title(self):
        s = Swagger(title="Custom API")
        assert s.title == "Custom API"

    def test_custom_description(self):
        s = Swagger(description="My API description")
        assert s.description == "My API description"

    def test_custom_server_url(self):
        s = Swagger(server_url="https://api.example.com")
        spec = s.generate([])
        assert spec["servers"][0]["url"] == "https://api.example.com"
