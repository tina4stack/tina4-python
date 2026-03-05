#
# Tina4 - This is not a framework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# Comprehensive test suite for Swagger / OpenAPI 3.0.3 generation
#

import os
import pytest
import tina4_python
from tina4_python import Constant
from tina4_python.Swagger import (
    Swagger, description, summary, secure, noauth,
    tags, example, example_response, params, describe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeRequest:
    """Minimal request stub used by Swagger.get_json()."""
    def __init__(self, host="localhost:7145", scheme="http"):
        self.headers = {"host": host, "x-forwarded-proto": scheme}


def _reset_routes():
    """Clear the global route registry before each test."""
    tina4_python.tina4_routes = {}


def _register_route(callback, routes, methods, swagger_meta=None,
                     noauth_flag=False, secure_flag=False):
    """Simulate registering a route the way Router.add + decorators do."""
    tina4_python.tina4_routes[callback] = {
        "routes": routes if isinstance(routes, list) else [routes],
        "methods": methods if isinstance(methods, list) else [methods],
        "swagger": swagger_meta,
        "noauth": noauth_flag,
        "secure": secure_flag,
        "cached": False,
    }


# ---------------------------------------------------------------------------
# _python_type_to_openapi
# ---------------------------------------------------------------------------

class TestPythonTypeToOpenapi:
    def test_string(self):
        assert Swagger._python_type_to_openapi("hello") == "string"

    def test_integer(self):
        assert Swagger._python_type_to_openapi(42) == "integer"

    def test_float(self):
        assert Swagger._python_type_to_openapi(3.14) == "number"

    def test_boolean(self):
        assert Swagger._python_type_to_openapi(True) == "boolean"

    def test_list(self):
        assert Swagger._python_type_to_openapi([1, 2]) == "array"

    def test_dict(self):
        assert Swagger._python_type_to_openapi({"a": 1}) == "object"

    def test_none_returns_string(self):
        assert Swagger._python_type_to_openapi(None) == "string"

    def test_bool_before_int(self):
        """bool is a subclass of int – ensure we detect boolean first."""
        assert Swagger._python_type_to_openapi(False) == "boolean"


# ---------------------------------------------------------------------------
# _schema_from_example
# ---------------------------------------------------------------------------

class TestSchemaFromExample:
    def test_none_returns_object(self):
        schema = Swagger._schema_from_example(None)
        assert schema == {"type": "object"}

    def test_string_value(self):
        schema = Swagger._schema_from_example("hello")
        assert schema == {"type": "string", "example": "hello"}

    def test_integer_value(self):
        schema = Swagger._schema_from_example(42)
        assert schema == {"type": "integer", "example": 42}

    def test_float_value(self):
        schema = Swagger._schema_from_example(9.99)
        assert schema == {"type": "number", "example": 9.99}

    def test_boolean_value(self):
        schema = Swagger._schema_from_example(True)
        assert schema == {"type": "boolean", "example": True}

    def test_flat_dict(self):
        ex = {"name": "Alice", "age": 30, "active": True}
        schema = Swagger._schema_from_example(ex)
        assert schema["type"] == "object"
        assert schema["example"] == ex
        props = schema["properties"]
        assert props["name"]["type"] == "string"
        assert props["age"]["type"] == "integer"
        assert props["active"]["type"] == "boolean"

    def test_nested_dict(self):
        ex = {"user": {"name": "Bob", "id": 1}}
        schema = Swagger._schema_from_example(ex)
        assert schema["properties"]["user"]["type"] == "object"
        assert schema["properties"]["user"]["properties"]["name"]["type"] == "string"
        assert schema["properties"]["user"]["properties"]["id"]["type"] == "integer"

    def test_list_of_dicts(self):
        ex = [{"id": 1, "title": "Item"}]
        schema = Swagger._schema_from_example(ex)
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "object"
        assert schema["items"]["properties"]["id"]["type"] == "integer"
        assert schema["example"] == ex

    def test_list_of_strings(self):
        ex = ["a", "b", "c"]
        schema = Swagger._schema_from_example(ex)
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "string"

    def test_empty_list(self):
        schema = Swagger._schema_from_example([])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "object"

    def test_dict_with_list_field(self):
        ex = {"tags": ["python", "api"], "count": 2}
        schema = Swagger._schema_from_example(ex)
        assert schema["properties"]["tags"]["type"] == "array"
        assert schema["properties"]["tags"]["items"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"


# ---------------------------------------------------------------------------
# get_path_parameters
# ---------------------------------------------------------------------------

class TestGetPathParameters:
    def test_no_params(self):
        assert Swagger.get_path_parameters("/api/users") == []

    def test_simple_param(self):
        params = Swagger.get_path_parameters("/api/users/{id}")
        assert len(params) == 1
        assert params[0]["name"] == "id"
        assert params[0]["in"] == "path"
        assert params[0]["required"] is True
        assert params[0]["schema"]["type"] == "string"

    def test_typed_int(self):
        params = Swagger.get_path_parameters("/api/users/{id:int}")
        assert params[0]["schema"]["type"] == "integer"

    def test_typed_float(self):
        params = Swagger.get_path_parameters("/api/items/{price:float}")
        assert params[0]["schema"]["type"] == "number"

    def test_typed_path(self):
        params = Swagger.get_path_parameters("/files/{filepath:path}")
        assert params[0]["schema"]["type"] == "string"

    def test_multiple_params(self):
        params = Swagger.get_path_parameters("/api/{org}/users/{uid:int}")
        assert len(params) == 2
        assert params[0]["name"] == "org"
        assert params[0]["schema"]["type"] == "string"
        assert params[1]["name"] == "uid"
        assert params[1]["schema"]["type"] == "integer"

    def test_unknown_type_defaults_string(self):
        params = Swagger.get_path_parameters("/api/{val:custom}")
        assert params[0]["schema"]["type"] == "string"


# ---------------------------------------------------------------------------
# parse_query_params
# ---------------------------------------------------------------------------

class TestParseQueryParams:
    def test_list_with_default(self):
        result = Swagger.parse_query_params(["page=1", "limit=20"])
        assert len(result) == 2
        assert result[0]["name"] == "page"
        assert result[0]["schema"]["default"] == "1"
        assert result[1]["name"] == "limit"
        assert result[1]["schema"]["default"] == "20"

    def test_list_without_default(self):
        result = Swagger.parse_query_params(["search"])
        assert result[0]["name"] == "search"
        assert result[0]["schema"]["default"] is None

    def test_dict_input(self):
        result = Swagger.parse_query_params({"page": "1", "q": ""})
        names = [p["name"] for p in result]
        assert "page" in names
        assert "q" in names

    def test_empty_list(self):
        assert Swagger.parse_query_params([]) == []

    def test_none_input(self):
        assert Swagger.parse_query_params(None) == []

    def test_all_query_params_are_optional(self):
        result = Swagger.parse_query_params(["page=1"])
        assert result[0]["required"] is False
        assert result[0]["in"] == "query"


# ---------------------------------------------------------------------------
# get_operation_id
# ---------------------------------------------------------------------------

class TestGetOperationId:
    def test_simple_route(self):
        assert Swagger.get_operation_id("/api/users", "GET") == "get_api_users"

    def test_route_with_params(self):
        # Braces are stripped
        assert Swagger.get_operation_id("/api/users/{id}", "DELETE") == "delete_api_users_id"

    def test_root_route(self):
        assert Swagger.get_operation_id("/", "GET") == "get_root"

    def test_deep_route(self):
        assert Swagger.get_operation_id("/api/v1/users/{id}/posts", "POST") == "post_api_v1_users_id_posts"


# ---------------------------------------------------------------------------
# get_swagger_entry
# ---------------------------------------------------------------------------

class TestGetSwaggerEntry:
    def test_get_no_request_body(self):
        op = Swagger.get_swagger_entry(
            route="/api/users", method="GET", tags=["Users"],
            summary="List users", description="Get all users",
            secure=False, query_params=["page=1"], example=None,
            example_response=None
        )
        assert "requestBody" not in op
        assert op["tags"] == ["Users"]
        assert op["summary"] == "List users"
        assert op["security"] == []
        assert "200" in op["responses"]
        assert "401" not in op["responses"]  # not secure → no 401

    def test_post_has_request_body(self):
        ex = {"name": "Alice", "age": 30}
        op = Swagger.get_swagger_entry(
            route="/api/users", method="POST", tags=["Users"],
            summary="Create user", description="",
            secure=True, query_params=[], example=ex,
            example_response=None
        )
        assert "requestBody" in op
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert body_schema["type"] == "object"
        assert body_schema["properties"]["name"]["type"] == "string"
        assert body_schema["properties"]["age"]["type"] == "integer"

    def test_put_has_request_body(self):
        op = Swagger.get_swagger_entry(
            route="/api/users/{id}", method="PUT", tags=[],
            summary="", description="", secure=False,
            query_params=[], example={"name": "Bob"},
            example_response=None
        )
        assert "requestBody" in op

    def test_patch_has_request_body(self):
        op = Swagger.get_swagger_entry(
            route="/api/users/{id}", method="PATCH", tags=[],
            summary="", description="", secure=False,
            query_params=[], example=None, example_response=None
        )
        assert "requestBody" in op
        assert op["requestBody"]["content"]["application/json"]["schema"]["type"] == "object"

    def test_delete_no_request_body(self):
        op = Swagger.get_swagger_entry(
            route="/api/users/{id}", method="DELETE", tags=[],
            summary="", description="", secure=True,
            query_params=[], example=None, example_response=None
        )
        assert "requestBody" not in op

    def test_secure_adds_security_and_401(self):
        op = Swagger.get_swagger_entry(
            route="/api/data", method="GET", tags=[],
            summary="", description="", secure=True,
            query_params=[], example=None, example_response=None
        )
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]
        assert "401" in op["responses"]

    def test_not_secure_no_401(self):
        op = Swagger.get_swagger_entry(
            route="/api/data", method="GET", tags=[],
            summary="", description="", secure=False,
            query_params=[], example=None, example_response=None
        )
        assert op["security"] == []
        assert "401" not in op["responses"]

    def test_path_params_and_query_params_combined(self):
        op = Swagger.get_swagger_entry(
            route="/api/users/{id:int}", method="GET", tags=[],
            summary="", description="", secure=False,
            query_params=["fields=name"], example=None,
            example_response=None
        )
        names = [p["name"] for p in op["parameters"]]
        assert "id" in names
        assert "fields" in names
        # Path param should be integer type
        id_param = next(p for p in op["parameters"] if p["name"] == "id")
        assert id_param["schema"]["type"] == "integer"
        assert id_param["in"] == "path"
        assert id_param["required"] is True

    def test_example_response_generates_schema(self):
        resp_ex = {"users": [{"id": 1, "name": "Alice"}], "total": 1}
        op = Swagger.get_swagger_entry(
            route="/api/users", method="GET", tags=[],
            summary="", description="", secure=False,
            query_params=[], example=None, example_response=resp_ex
        )
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert "users" in schema["properties"]
        assert schema["properties"]["users"]["type"] == "array"
        assert schema["properties"]["total"]["type"] == "integer"

    def test_no_example_response_still_has_200(self):
        op = Swagger.get_swagger_entry(
            route="/api/ping", method="GET", tags=[],
            summary="", description="", secure=False,
            query_params=[], example=None, example_response=None
        )
        assert "200" in op["responses"]

    def test_request_body_schema_from_example(self):
        """Request body should use _schema_from_example for full type inference."""
        ex = {"name": "Test", "count": 5, "active": True, "price": 9.99}
        op = Swagger.get_swagger_entry(
            route="/api/items", method="POST", tags=[],
            summary="", description="", secure=False,
            query_params=[], example=ex, example_response=None
        )
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["active"]["type"] == "boolean"
        assert schema["properties"]["price"]["type"] == "number"


# ---------------------------------------------------------------------------
# parse_swagger_metadata
# ---------------------------------------------------------------------------

class TestParseSwaggerMetadata:
    def test_defaults_applied(self):
        meta = Swagger.parse_swagger_metadata({})
        assert meta["tags"] == []
        assert meta["params"] == []
        assert meta["description"] == ""
        assert meta["summary"] == ""
        assert meta["example"] is None
        assert meta["example_response"] is None

    def test_string_tags_converted_to_list(self):
        meta = Swagger.parse_swagger_metadata({"tags": "Users"})
        assert meta["tags"] == ["Users"]

    def test_existing_values_preserved(self):
        meta = Swagger.parse_swagger_metadata({
            "tags": ["Auth"],
            "summary": "Login",
            "description": "Authenticate user",
            "params": ["username"],
            "example": {"user": "test"},
            "example_response": {"token": "abc"},
        })
        assert meta["tags"] == ["Auth"]
        assert meta["summary"] == "Login"
        assert meta["example"]["user"] == "test"
        assert meta["example_response"]["token"] == "abc"


# ---------------------------------------------------------------------------
# Decorators — individual
# ---------------------------------------------------------------------------

class TestDecorators:
    def setup_method(self):
        _reset_routes()

    def test_description_decorator(self):
        @description("Test description")
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["description"] == "Test description"

    def test_summary_decorator(self):
        @summary("Test summary")
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["summary"] == "Test summary"

    def test_secure_decorator(self):
        @secure()
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["secure"] is True

    def test_noauth_decorator(self):
        @noauth()
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["secure"] is False

    def test_tags_decorator_list(self):
        @tags(["Auth", "Users"])
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["tags"] == ["Auth", "Users"]

    def test_tags_decorator_string(self):
        @tags("Auth")
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["tags"] == ["Auth"]

    def test_example_decorator(self):
        @example({"name": "test"})
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["example"] == {"name": "test"}

    def test_example_response_decorator(self):
        @example_response({"id": 1, "name": "test"})
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["example_response"] == {"id": 1, "name": "test"}

    def test_params_decorator_list(self):
        @params(["page=1", "limit=20"])
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["params"] == ["page=1", "limit=20"]

    def test_params_decorator_dict(self):
        @params({"page": "1"})
        def handler(): pass
        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["params"] == {"page": "1"}

    def test_stacked_decorators(self):
        """Multiple decorators on one handler should all apply."""
        @description("Get users")
        @summary("List all users")
        @tags(["Users"])
        @params(["page=1"])
        @example_response([{"id": 1, "name": "Alice"}])
        def handler(): pass

        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["description"] == "Get users"
        assert meta["summary"] == "List all users"
        assert meta["tags"] == ["Users"]
        assert meta["params"] == ["page=1"]
        assert meta["example_response"] == [{"id": 1, "name": "Alice"}]


# ---------------------------------------------------------------------------
# describe() all-in-one decorator
# ---------------------------------------------------------------------------

class TestDescribeDecorator:
    def setup_method(self):
        _reset_routes()

    def test_all_fields(self):
        @describe(
            description="Create a user",
            summary="Create user",
            tags=["Users"],
            params=["notify=true"],
            example={"name": "Alice"},
            example_response={"id": 1, "name": "Alice"},
            secure=True
        )
        def handler(): pass

        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["description"] == "Create a user"
        assert meta["summary"] == "Create user"
        assert meta["tags"] == ["Users"]
        assert meta["params"] == ["notify=true"]
        assert meta["example"] == {"name": "Alice"}
        assert meta["example_response"] == {"id": 1, "name": "Alice"}
        assert meta["secure"] is True

    def test_secure_false_sets_noauth(self):
        """describe(secure=False) should explicitly mark the route as public."""
        @describe(summary="Public POST", secure=False)
        def handler(): pass

        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["secure"] is False

    def test_secure_none_leaves_default(self):
        """describe() without secure= should not set secure at all."""
        @describe(summary="Default auth")
        def handler(): pass

        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert "secure" not in meta

    def test_partial_fields(self):
        @describe(summary="Ping")
        def handler(): pass

        meta = tina4_python.tina4_routes[handler]["swagger"]
        assert meta["summary"] == "Ping"
        assert "description" not in meta
        assert "tags" not in meta


# ---------------------------------------------------------------------------
# get_json — full OpenAPI document generation
# ---------------------------------------------------------------------------

class TestGetJson:
    def setup_method(self):
        _reset_routes()

    def test_empty_routes_produces_valid_document(self):
        doc = Swagger.get_json(_FakeRequest())
        assert doc["openapi"] == "3.0.3"
        assert doc["paths"] == {}
        assert "bearerAuth" in doc["components"]["securitySchemes"]
        assert "basicAuth" in doc["components"]["securitySchemes"]
        assert doc["security"] == []

    def test_server_url_from_request(self):
        doc = Swagger.get_json(_FakeRequest(host="api.example.com", scheme="https"))
        urls = [s["url"] for s in doc["servers"]]
        assert "https://api.example.com" in urls

    def test_info_section(self):
        doc = Swagger.get_json(_FakeRequest())
        assert "title" in doc["info"]
        assert "version" in doc["info"]
        assert "contact" in doc["info"]
        assert "license" in doc["info"]

    def test_get_route_public_by_default(self):
        """GET routes without explicit secure should be public."""
        def handler(): pass
        _register_route(handler, "/api/ping", "GET", swagger_meta={
            "tags": ["Health"], "summary": "Ping"
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/ping"]["get"]
        assert op["security"] == []
        assert "401" not in op["responses"]

    def test_post_route_secured_by_default(self):
        """POST routes without explicit auth should be secured."""
        def handler(): pass
        _register_route(handler, "/api/users", "POST", swagger_meta={
            "tags": ["Users"], "summary": "Create user"
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/users"]["post"]
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]
        assert "401" in op["responses"]

    def test_put_route_secured_by_default(self):
        def handler(): pass
        _register_route(handler, "/api/users/{id}", "PUT", swagger_meta={
            "summary": "Update user"
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/users/{id}"]["put"]
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]

    def test_delete_route_secured_by_default(self):
        def handler(): pass
        _register_route(handler, "/api/users/{id}", "DELETE", swagger_meta={
            "summary": "Delete user"
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/users/{id}"]["delete"]
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]

    def test_noauth_flag_overrides_default(self):
        """route-level noauth=True should make any method public."""
        def handler(): pass
        _register_route(handler, "/api/login", "POST", swagger_meta={
            "summary": "Login"
        }, noauth_flag=True)
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/login"]["post"]
        assert op["security"] == []

    def test_secure_flag_overrides_default(self):
        """route-level secure=True should make GET routes secured."""
        def handler(): pass
        _register_route(handler, "/api/profile", "GET", swagger_meta={
            "summary": "Profile"
        }, secure_flag=True)
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/profile"]["get"]
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]

    def test_swagger_secure_true_overrides(self):
        """swagger metadata secure=True should secure any method."""
        def handler(): pass
        _register_route(handler, "/api/admin", "GET", swagger_meta={
            "summary": "Admin", "secure": True
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/admin"]["get"]
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]

    def test_swagger_secure_false_overrides(self):
        """swagger metadata secure=False should make any method public."""
        def handler(): pass
        _register_route(handler, "/api/register", "POST", swagger_meta={
            "summary": "Register", "secure": False
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/register"]["post"]
        assert op["security"] == []

    def test_route_noauth_trumps_swagger_secure(self):
        """route-level noauth=True should override swagger secure=True."""
        def handler(): pass
        _register_route(handler, "/api/public", "POST", swagger_meta={
            "summary": "Public", "secure": True
        }, noauth_flag=True)
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/public"]["post"]
        assert op["security"] == []

    def test_route_secure_trumps_swagger_noauth(self):
        """route-level secure=True should override swagger secure=False."""
        def handler(): pass
        _register_route(handler, "/api/locked", "GET", swagger_meta={
            "summary": "Locked", "secure": False
        }, secure_flag=True)
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/locked"]["get"]
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]

    def test_routes_without_swagger_are_excluded(self):
        """Routes with swagger=None should not appear in the doc."""
        def handler_a(): pass
        def handler_b(): pass
        _register_route(handler_a, "/api/visible", "GET", swagger_meta={"summary": "Visible"})
        _register_route(handler_b, "/api/hidden", "GET", swagger_meta=None)
        doc = Swagger.get_json(_FakeRequest())
        assert "/api/visible" in doc["paths"]
        assert "/api/hidden" not in doc["paths"]

    def test_multiple_routes_same_callback(self):
        """A callback registered at multiple paths should create entries for each."""
        def handler(): pass
        tina4_python.tina4_routes[handler] = {
            "routes": ["/api/users", "/api/people"],
            "methods": ["GET"],
            "swagger": {"summary": "List"},
            "noauth": False,
            "secure": False,
            "cached": False,
        }
        doc = Swagger.get_json(_FakeRequest())
        assert "/api/users" in doc["paths"]
        assert "/api/people" in doc["paths"]

    def test_multiple_methods_same_route(self):
        """A route supporting both GET and POST should have both operations."""
        def handler(): pass
        tina4_python.tina4_routes[handler] = {
            "routes": ["/api/items"],
            "methods": ["GET", "POST"],
            "swagger": {"summary": "Items", "tags": ["Items"]},
            "noauth": False,
            "secure": False,
            "cached": False,
        }
        doc = Swagger.get_json(_FakeRequest())
        assert "get" in doc["paths"]["/api/items"]
        assert "post" in doc["paths"]["/api/items"]
        # GET should be public, POST should be secured (default behaviour)
        assert doc["paths"]["/api/items"]["get"]["security"] == []
        assert doc["paths"]["/api/items"]["post"]["security"] == [{"bearerAuth": []}, {"basicAuth": []}]

    def test_full_example_with_all_decorators(self):
        """Integration test: register a fully-decorated route and verify output."""
        def create_user(): pass
        tina4_python.tina4_routes[create_user] = {
            "routes": ["/api/users"],
            "methods": ["POST"],
            "swagger": {
                "description": "Create a new user account",
                "summary": "Create user",
                "tags": ["Users"],
                "params": ["notify=true"],
                "example": {"name": "Alice", "email": "alice@example.com", "age": 30},
                "example_response": {"id": 1, "name": "Alice", "email": "alice@example.com"},
                "secure": True,
            },
            "noauth": False,
            "secure": False,
            "cached": False,
        }
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/users"]["post"]

        # Metadata
        assert op["tags"] == ["Users"]
        assert op["summary"] == "Create user"
        assert op["description"] == "Create a new user account"
        assert op["operationId"] == "post_api_users"

        # Security
        assert op["security"] == [{"bearerAuth": []}, {"basicAuth": []}]
        assert "401" in op["responses"]

        # Request body with schema inference
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert body_schema["type"] == "object"
        assert body_schema["properties"]["name"]["type"] == "string"
        assert body_schema["properties"]["email"]["type"] == "string"
        assert body_schema["properties"]["age"]["type"] == "integer"

        # Response schema
        resp_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert resp_schema["type"] == "object"
        assert resp_schema["properties"]["id"]["type"] == "integer"

        # Query params
        query_params = [p for p in op["parameters"] if p["in"] == "query"]
        assert len(query_params) == 1
        assert query_params[0]["name"] == "notify"

    def test_path_params_in_full_document(self):
        """Path parameters should be correctly typed in the full document."""
        def handler(): pass
        _register_route(handler, "/api/users/{id:int}/posts/{post_id}", "GET", swagger_meta={
            "summary": "Get user post"
        })
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/users/{id:int}/posts/{post_id}"]["get"]
        path_params = [p for p in op["parameters"] if p["in"] == "path"]
        assert len(path_params) == 2
        id_param = next(p for p in path_params if p["name"] == "id")
        post_param = next(p for p in path_params if p["name"] == "post_id")
        assert id_param["schema"]["type"] == "integer"
        assert post_param["schema"]["type"] == "string"


# ---------------------------------------------------------------------------
# Security priority chain
# ---------------------------------------------------------------------------

class TestSecurityPriorityChain:
    """Verify the auth resolution priority: route_noauth > route_secure > swagger_secure > method_default"""

    def setup_method(self):
        _reset_routes()

    def test_priority_noauth_wins_over_everything(self):
        """noauth at route level always wins."""
        def handler(): pass
        tina4_python.tina4_routes[handler] = {
            "routes": ["/test"],
            "methods": ["POST"],
            "swagger": {"secure": True},
            "noauth": True,
            "secure": True,
            "cached": False,
        }
        doc = Swagger.get_json(_FakeRequest())
        assert doc["paths"]["/test"]["post"]["security"] == []

    def test_priority_route_secure_over_swagger(self):
        """route secure=True should override swagger secure=False."""
        def handler(): pass
        tina4_python.tina4_routes[handler] = {
            "routes": ["/test"],
            "methods": ["GET"],
            "swagger": {"secure": False},
            "noauth": False,
            "secure": True,
            "cached": False,
        }
        doc = Swagger.get_json(_FakeRequest())
        assert doc["paths"]["/test"]["get"]["security"] != []

    def test_priority_swagger_over_default(self):
        """Swagger-level secure=True overrides method default (GET → public)."""
        def handler(): pass
        tina4_python.tina4_routes[handler] = {
            "routes": ["/test"],
            "methods": ["GET"],
            "swagger": {"secure": True},
            "noauth": False,
            "secure": False,
            "cached": False,
        }
        doc = Swagger.get_json(_FakeRequest())
        assert doc["paths"]["/test"]["get"]["security"] != []


# ---------------------------------------------------------------------------
# OpenAPI structural validity
# ---------------------------------------------------------------------------

class TestOpenApiStructure:
    def setup_method(self):
        _reset_routes()

    def test_required_top_level_keys(self):
        doc = Swagger.get_json(_FakeRequest())
        assert "openapi" in doc
        assert "info" in doc
        assert "paths" in doc
        assert "components" in doc
        assert "servers" in doc

    def test_openapi_version(self):
        doc = Swagger.get_json(_FakeRequest())
        assert doc["openapi"] == "3.0.3"

    def test_info_required_fields(self):
        doc = Swagger.get_json(_FakeRequest())
        assert "title" in doc["info"]
        assert "version" in doc["info"]

    def test_security_schemes_present(self):
        doc = Swagger.get_json(_FakeRequest())
        schemes = doc["components"]["securitySchemes"]
        assert schemes["bearerAuth"]["type"] == "http"
        assert schemes["bearerAuth"]["scheme"] == "bearer"
        assert schemes["basicAuth"]["type"] == "http"
        assert schemes["basicAuth"]["scheme"] == "basic"

    def test_operation_has_required_fields(self):
        """Each operation should have tags, summary, operationId, responses."""
        def handler(): pass
        _register_route(handler, "/api/test", "GET", swagger_meta={"summary": "Test"})
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/test"]["get"]
        assert "tags" in op
        assert "summary" in op
        assert "operationId" in op
        assert "responses" in op
        assert "200" in op["responses"]

    def test_error_responses_have_schema(self):
        """Error responses (400, 404) should have proper error schema."""
        def handler(): pass
        _register_route(handler, "/api/test", "GET", swagger_meta={"summary": "Test"})
        doc = Swagger.get_json(_FakeRequest())
        op = doc["paths"]["/api/test"]["get"]
        for code in ["400", "404"]:
            assert code in op["responses"]
            schema = op["responses"][code]["content"]["application/json"]["schema"]
            assert schema["type"] == "object"
            assert "error" in schema["properties"]
            assert schema["properties"]["error"]["type"] == "string"

    def test_servers_have_url_and_description(self):
        doc = Swagger.get_json(_FakeRequest())
        for server in doc["servers"]:
            assert "url" in server
            assert "description" in server
