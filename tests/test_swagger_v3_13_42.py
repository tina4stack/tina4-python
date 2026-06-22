"""Swagger v3.13.42 configurability — new-behaviour contract tests.

Locks the four gaps closed in 3.13.42:
    1. Configurable security schemes (bearerFormat, apiKey) + per-route @security + scopes
    2. Path include/exclude filtering (framework internals always excluded)
    3. OpenAPI 3.1 opt-in (default 3.0.3)
    4. Reusable custom component schemas via add_schema + @request_schema/@response_schema
"""
import pytest

from tina4_python.swagger import (
    Swagger, security, request_schema, response_schema,
)


@pytest.fixture(autouse=True)
def _clean_registry_and_env(monkeypatch):
    # Isolate each test from registry + env leakage.
    Swagger.reset_registry()
    for k in (
        "TINA4_SWAGGER_OPENAPI", "TINA4_SWAGGER_BEARER_FORMAT",
        "TINA4_SWAGGER_API_KEY_NAME", "TINA4_SWAGGER_API_KEY_IN",
        "TINA4_SWAGGER_DEFAULT_SCHEME", "TINA4_SWAGGER_INCLUDE", "TINA4_SWAGGER_EXCLUDE",
    ):
        monkeypatch.delenv(k, raising=False)
    yield
    Swagger.reset_registry()


def _route(method, path, handler=None, auth_required=False):
    return {"method": method, "path": path, "handler": handler, "auth_required": auth_required}


# ── OpenAPI version ───────────────────────────────────────────────

class TestOpenAPIVersion:
    def test_default_is_3_0_3(self):
        assert Swagger().generate([])["openapi"] == "3.0.3"

    def test_opt_in_3_1(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_OPENAPI", "3.1")
        assert Swagger().generate([])["openapi"] == "3.1.0"


# ── Configurable security schemes ─────────────────────────────────

class TestSecuritySchemes:
    def test_bearer_format_configurable(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_BEARER_FORMAT", "opaque")
        spec = Swagger().generate([])
        assert spec["components"]["securitySchemes"]["bearerAuth"]["bearerFormat"] == "opaque"

    def test_api_key_scheme_from_env(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_API_KEY_NAME", "X-Api-Key")
        schemes = Swagger().generate([])["components"]["securitySchemes"]
        assert schemes["apiKeyAuth"] == {"type": "apiKey", "name": "X-Api-Key", "in": "header"}

    def test_default_scheme_drives_secured_routes(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_API_KEY_NAME", "X-Api-Key")
        monkeypatch.setenv("TINA4_SWAGGER_DEFAULT_SCHEME", "apiKeyAuth")
        spec = Swagger().generate([_route("post", "/api/v1/things", auth_required=True)])
        op = spec["paths"]["/api/v1/things"]["post"]
        assert op["security"] == [{"apiKeyAuth": []}]

    def test_registered_scheme_appears(self):
        Swagger.add_security_scheme("oauth2", {
            "type": "oauth2",
            "flows": {"clientCredentials": {"tokenUrl": "https://x/token",
                                            "scopes": {"read:users": "Read"}}},
        })
        schemes = Swagger().generate([])["components"]["securitySchemes"]
        assert schemes["oauth2"]["type"] == "oauth2"


# ── Per-route @security + scopes ──────────────────────────────────

class TestPerRouteSecurity:
    def test_explicit_security_overrides_default(self):
        @security("bearerAuth")
        def h(req, resp):
            return resp
        spec = Swagger().generate([_route("get", "/api/v1/me", h, auth_required=False)])
        assert spec["paths"]["/api/v1/me"]["get"]["security"] == [{"bearerAuth": []}]

    def test_public_marks_no_security(self):
        @security("public")
        def h(req, resp):
            return resp
        # auth_required True, but @security("public") wins -> explicitly open.
        spec = Swagger().generate([_route("post", "/api/v1/webhook", h, auth_required=True)])
        assert spec["paths"]["/api/v1/webhook"]["post"]["security"] == []

    def test_oauth2_scopes_preserved(self):
        Swagger.add_security_scheme("oauth2", {
            "type": "oauth2",
            "flows": {"clientCredentials": {"tokenUrl": "https://x/token",
                                            "scopes": {"read:users": "Read", "write:users": "Write"}}},
        })
        @security("oauth2", scopes=["read:users", "write:users"])
        def h(req, resp):
            return resp
        op = Swagger().generate([_route("get", "/api/v1/users", h)])["paths"]["/api/v1/users"]["get"]
        assert op["security"] == [{"oauth2": ["read:users", "write:users"]}]

    def test_scopes_dropped_on_non_oauth2_scheme(self):
        # Scopes on an http/bearer scheme are invalid OpenAPI -> sanitized to [].
        @security("bearerAuth", scopes=["read:users"])
        def h(req, resp):
            return resp
        op = Swagger().generate([_route("get", "/api/v1/users", h)])["paths"]["/api/v1/users"]["get"]
        assert op["security"] == [{"bearerAuth": []}]

    def test_or_requirements(self):
        Swagger.add_security_scheme("oauth2", {"type": "oauth2", "flows": {}})
        @security([{"oauth2": ["read"]}, {"bearerAuth": []}])
        def h(req, resp):
            return resp
        op = Swagger().generate([_route("get", "/api/v1/x", h)])["paths"]["/api/v1/x"]["get"]
        assert op["security"] == [{"oauth2": ["read"]}, {"bearerAuth": []}]


# ── Path filtering ────────────────────────────────────────────────

class TestPathFiltering:
    def _routes(self):
        return [
            _route("get", "/api/v1/users"),
            _route("get", "/dashboard"),
            _route("get", "/__dev/api/reload"),
            _route("get", "/swagger"),
        ]

    def test_framework_internals_always_excluded(self):
        paths = Swagger().generate(self._routes())["paths"]
        assert "/__dev/api/reload" not in paths
        assert "/swagger" not in paths
        assert "/api/v1/users" in paths

    def test_include_allow_list(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_INCLUDE", "/api/v1")
        paths = Swagger().generate(self._routes())["paths"]
        assert set(paths) == {"/api/v1/users"}

    def test_exclude_prefix(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_EXCLUDE", "/dashboard")
        paths = Swagger().generate(self._routes())["paths"]
        assert "/dashboard" not in paths and "/api/v1/users" in paths


# ── Reusable custom schemas ───────────────────────────────────────

class TestCustomSchemas:
    def test_request_schema_ref(self):
        Swagger.add_schema("CreateUser", {
            "type": "object",
            "properties": {"email": {"type": "string"}, "name": {"type": "string"}},
            "required": ["email"],
        })
        @request_schema("CreateUser")
        def h(req, resp):
            return resp
        spec = Swagger().generate([_route("post", "/api/v1/users", h)])
        body = spec["paths"]["/api/v1/users"]["post"]["requestBody"]
        assert body["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/CreateUser"}
        assert "CreateUser" in spec["components"]["schemas"]

    def test_response_schema_ref_and_list(self):
        Swagger.add_schema("User", {"type": "object", "properties": {"id": {"type": "integer"}}})
        @response_schema("User", status=200)
        @response_schema("User", status=201, is_list=True)
        def h(req, resp):
            return resp
        resps = Swagger().generate([_route("get", "/api/v1/users", h)])["paths"]["/api/v1/users"]["get"]["responses"]
        assert resps["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/User"}
        assert resps["201"]["content"]["application/json"]["schema"] == {
            "type": "array", "items": {"$ref": "#/components/schemas/User"}
        }
