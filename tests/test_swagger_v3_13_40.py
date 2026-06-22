"""Swagger v3.13.40 sweep — new-behaviour contract tests.

Locks the generator features added in the 3.13.40 Swagger sweep:
multi-status responses, in:query params, @description detail, ORM ->
components.schemas + $ref, enums, wildcard/splat -> valid templating,
operationId de-dup, typed-param formats, top-level tags[], multi-server,
multipart bodies, and the wired production enable-gate.
"""
import os
import pytest

from tina4_python.swagger import (
    Swagger, description, tags, example, example_response, is_enabled,
)
from tina4_python.orm import ORM
from tina4_python.orm.fields import Field


class Widget(ORM):
    table_name = "widgets"
    id = Field(int, primary_key=True, auto_increment=True)
    name = Field(str, required=True, max_length=50, min_length=2)
    role = Field(str, choices=["admin", "user", "guest"])
    score = Field(int, min_value=0, max_value=100)


def _route(method, path, handler=None, auth=False):
    return {"method": method, "path": path, "handler": handler, "auth_required": auth}


@pytest.fixture
def swagger():
    return Swagger(title="T", version="1.0.0")


# ── Multi-status responses ─────────────────────────────────────

def test_multi_status_responses_do_not_collapse(swagger):
    @example_response(201, {"id": 1})
    @example_response(404, {"error": "nope"})
    def handler(request, response):
        return response

    spec = swagger.generate([_route("POST", "/widgets", handler)])
    responses = spec["paths"]["/widgets"]["post"]["responses"]
    assert "201" in responses
    assert "404" in responses
    assert responses["201"]["content"]["application/json"]["example"] == {"id": 1}
    assert responses["404"]["content"]["application/json"]["example"] == {"error": "nope"}


def test_single_example_response_still_keys_200(swagger):
    @example_response({"id": 1})
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/widgets", handler)])
    assert "200" in spec["paths"]["/widgets"]["get"]["responses"]


# ── Query params + detail ──────────────────────────────────────

def test_query_params_emitted(swagger):
    @description("List", query={"active": "bool — only active"})
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/widgets", handler)])
    params = spec["paths"]["/widgets"]["get"]["parameters"]
    q = [p for p in params if p["in"] == "query"]
    assert len(q) == 1
    assert q[0]["name"] == "active"
    assert q[0]["required"] is False


def test_description_detail_appended(swagger):
    @description("Create", detail="Validates email first.")
    def handler(request, response):
        return response

    spec = swagger.generate([_route("POST", "/widgets", handler)])
    assert "Validates email first." in spec["paths"]["/widgets"]["post"]["description"]


# ── ORM -> components.schemas + $ref ───────────────────────────

def test_orm_model_becomes_component_schema(swagger):
    def create(request, response):
        return response
    create._swagger_model = Widget

    spec = swagger.generate([_route("POST", "/widgets", create)])
    schemas = spec["components"]["schemas"]
    assert "Widget" in schemas
    props = schemas["Widget"]["properties"]
    assert props["name"]["type"] == "string"
    assert props["name"]["maxLength"] == 50
    assert props["score"]["type"] == "integer"
    # required list comes from required fields
    assert "name" in schemas["Widget"]["required"]
    # request body $refs the component
    body_schema = spec["paths"]["/widgets"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema == {"$ref": "#/components/schemas/Widget"}


def test_orm_enum_from_choices(swagger):
    def create(request, response):
        return response
    create._swagger_model = Widget

    spec = swagger.generate([_route("POST", "/widgets", create)])
    assert spec["components"]["schemas"]["Widget"]["properties"]["role"]["enum"] == ["admin", "user", "guest"]


def test_orm_numeric_min_max_and_readonly_pk(swagger):
    def create(request, response):
        return response
    create._swagger_model = Widget

    props = swagger.generate([_route("POST", "/widgets", create)])["components"]["schemas"]["Widget"]["properties"]
    assert props["score"]["minimum"] == 0
    assert props["score"]["maximum"] == 100
    assert props["id"]["readOnly"] is True


def test_list_handler_response_is_array_of_ref(swagger):
    def list_h(request, response):
        return response
    list_h._swagger_model = Widget
    list_h._swagger_model_list = True

    spec = swagger.generate([_route("GET", "/widgets", list_h)])
    schema = spec["paths"]["/widgets"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"type": "array", "items": {"$ref": "#/components/schemas/Widget"}}


# ── Spec validity: wildcard / splat ────────────────────────────

def test_wildcard_path_becomes_valid_template(swagger):
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/api/files/*", handler)])
    assert "/api/files/{wildcard}" in spec["paths"]
    assert "*" not in str(list(spec["paths"].keys()))
    params = spec["paths"]["/api/files/{wildcard}"]["get"]["parameters"]
    assert params[0]["name"] == "wildcard"
    assert params[0]["in"] == "path"


def test_greedy_path_param_emits_matching_template(swagger):
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/files/{rest:path}", handler)])
    assert "/files/{rest}" in spec["paths"]
    params = spec["paths"]["/files/{rest}"]["get"]["parameters"]
    assert params[0]["name"] == "rest"


# ── operationId de-dup ─────────────────────────────────────────

def test_operation_id_dedup(swagger):
    def a(request, response):
        return response

    def b(request, response):
        return response

    # /users/{id} and literal /users/id both sanitize to get_users_id
    spec = swagger.generate([
        _route("GET", "/users/{id}", a),
        _route("GET", "/users/id", b),
    ])
    ids = [
        spec["paths"]["/users/{id}"]["get"]["operationId"],
        spec["paths"]["/users/id"]["get"]["operationId"],
    ]
    assert len(set(ids)) == 2, ids


# ── Typed path param formats ───────────────────────────────────

def test_uuid_param_gets_format(swagger):
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/items/{id:uuid}", handler)])
    p = spec["paths"]["/items/{id}"]["get"]["parameters"][0]
    assert p["schema"] == {"type": "string", "format": "uuid"}


def test_slug_param_gets_pattern(swagger):
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/posts/{slug:slug}", handler)])
    p = spec["paths"]["/posts/{slug}"]["get"]["parameters"][0]
    assert p["schema"]["type"] == "string"
    assert "pattern" in p["schema"]


# ── Top-level tags[] + multi-server + multipart ────────────────

def test_top_level_tags_array(swagger):
    @tags(["users", "admin"])
    def handler(request, response):
        return response

    spec = swagger.generate([_route("GET", "/x", handler)])
    names = [t["name"] for t in spec["tags"]]
    assert names == ["users", "admin"]


def test_multi_server_from_env(monkeypatch):
    monkeypatch.setenv("TINA4_SWAGGER_SERVERS", "https://a.test, https://b.test")
    spec = Swagger().generate([])
    urls = [s["url"] for s in spec["servers"]]
    assert urls == ["https://a.test", "https://b.test"]


def test_multipart_request_body(swagger):
    @example({"avatar": b"", "name": "Alice"}, content_type="multipart/form-data")
    def handler(request, response):
        return response

    spec = swagger.generate([_route("POST", "/upload", handler)])
    content = spec["paths"]["/upload"]["post"]["requestBody"]["content"]
    assert "multipart/form-data" in content
    avatar = content["multipart/form-data"]["schema"]["properties"]["avatar"]
    assert avatar == {"type": "string", "format": "binary"}


# ── Production enable-gate is wired (not dead) ─────────────────

class _FakeReq:
    def __init__(self, path):
        self.path = path
        self.method = "GET"
        self.headers = {}


def test_handle_swagger_gated_on_is_enabled(monkeypatch):
    from tina4_python.core import server as srv
    from tina4_python.core.response import Response

    monkeypatch.delenv("TINA4_SWAGGER_ENABLED", raising=False)
    monkeypatch.setenv("TINA4_DEBUG", "false")
    assert is_enabled() is False
    # Disabled -> handler must refuse to serve (returns None) even for /swagger.
    assert srv._handle_swagger(_FakeReq("/swagger"), Response()) is None

    # Explicit prod-enable -> served despite TINA4_DEBUG=false.
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")
    assert is_enabled() is True
    out = srv._handle_swagger(_FakeReq("/swagger"), Response())
    assert out is not None


class TestConfigurableUiCdn:
    def test_default_cdn(self, monkeypatch):
        from tina4_python.core import server as srv
        from tina4_python.core.response import Response
        monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")
        monkeypatch.delenv("TINA4_SWAGGER_UI_CDN", raising=False)
        out = srv._handle_swagger(_FakeReq("/swagger"), Response())
        assert b"swagger-ui-dist@5/swagger-ui.css" in out.content

    def test_custom_cdn_for_airgapped(self, monkeypatch):
        from tina4_python.core import server as srv
        from tina4_python.core.response import Response
        monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")
        monkeypatch.setenv("TINA4_SWAGGER_UI_CDN", "https://mirror.internal/swagger")
        out = srv._handle_swagger(_FakeReq("/swagger"), Response())
        assert b"https://mirror.internal/swagger/swagger-ui.css" in out.content
        assert b"https://mirror.internal/swagger/swagger-ui-bundle.js" in out.content


class TestContactBlock:
    def test_contact_name_url_email(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_CONTACT_TEAM", "Platform Team")
        monkeypatch.setenv("TINA4_SWAGGER_CONTACT_URL", "https://tina4.com/support")
        monkeypatch.setenv("TINA4_SWAGGER_CONTACT_EMAIL", "team@tina4.com")
        contact = Swagger().generate([])["info"]["contact"]
        assert contact == {
            "name": "Platform Team",
            "url": "https://tina4.com/support",
            "email": "team@tina4.com",
        }

    def test_legacy_swagger_contact_team_fallback(self, monkeypatch):
        monkeypatch.delenv("TINA4_SWAGGER_CONTACT_TEAM", raising=False)
        monkeypatch.setenv("SWAGGER_CONTACT_TEAM", "Legacy Team")
        contact = Swagger().generate([])["info"]["contact"]
        assert contact["name"] == "Legacy Team"
