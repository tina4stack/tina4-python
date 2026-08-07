"""Swagger / OpenAPI CONTRACT suite (Feature 47, ADR-0004) — the ten invariants
of ``plan/v3/fixtures/swagger_contract.json`` proven for the Python reference.

Every invariant is checked against the document a REAL client fetches: the tests
dispatch through the framework's own front controller
(``tina4_python.test_client.TestClient`` -> ``tina4_python.core.server.app``) and
pull the actual bytes served at ``/swagger/openapi.json`` — the same path
Swagger UI reads. No doubles anywhere: real route registration through the real
``@get``/``@post``/``@noauth`` decorators, a real ORM model on a real sqlite
database, the real ``Swagger`` generator the server calls, and — for invariant 1
— a REAL OpenAPI validator (``openapi-spec-validator``, a TEST-ONLY dependency;
the generator itself stays zero-dependency).

The one measured exception is the "unknown token degrades to string" half of
invariant 4: the router REFUSES to register an unknown type token
(``_compile_pattern`` raises ``ValueError``), so that path cannot exist in a
served app. It is therefore proven against the generator's real public API over
a real route dict — the same real, no-mock surface ``test_swagger_parity_3_13_96``
uses — and this is called out where it happens.

Each test's name contains its fixture invariant id (the shared auditor,
``tina4-documentation/scripts/audit-contract-fixtures.py``, normalises names and
substring-matches), and each docstring repeats the invariant id and human stem
verbatim so the fixture can name cases in either idiom.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager

import pytest

from openapi_spec_validator import validate as validate_openapi_document
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

import tina4_python.core.router as router_module
from tina4_python.core.router import get, post, noauth
from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField
import tina4_python.orm.model as orm_model
from tina4_python.orm import bind_database
from tina4_python.swagger import Swagger
from tina4_python.test_client import TestClient


# ── A real ORM model, exactly as AutoCrud hands it to the generator ──────────
# `name` is NOT NULL (required); `id` is the auto-increment PK and is not. A
# distinct name ("Widget") lets the schema-key assertions also prove the tableName
# ("widgets") is NOT used as the key — the Node mis-keying guard from the fixture.
class Widget(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)


# ── Real-server helpers (no mocks) ───────────────────────────────────────────

@contextmanager
def isolated_routes():
    """Swap the global route registry for an empty one, restore on exit.

    ``/swagger/openapi.json`` is generated from ``Router.get_routes()`` (the
    module-level ``_routes`` list), so clearing it makes the served document
    contain EXACTLY the routes a test registers — deterministic, and it cannot
    leak into another suite. The list object identity is preserved (``clear`` +
    slice-assign) because the server captured that very list.
    """
    snapshot = list(router_module._routes)
    router_module._routes.clear()
    try:
        yield
    finally:
        router_module._routes[:] = snapshot


def register_get(path: str):
    """Register a bare public GET through the real decorator; return the handler."""
    async def handler(request, response):
        return response({})
    get(path)(handler)
    return handler


def register_write(path: str, *, public: bool = False, model=None):
    """Register a real POST. ``public`` applies @noauth (outer, as documented);
    ``model`` attaches an ORM model the way AutoCrud does."""
    async def handler(request, response):
        return response({"ok": True}, 201)
    post(path)(handler)          # @post is innermost — registers and sets _route_ref
    if public:
        noauth()(handler)        # @noauth is outer — flips the registered route dict
    if model is not None:
        handler._swagger_model = model
    return handler


def fetch_openapi_document() -> dict:
    """Fetch and parse the document the real server serves at /swagger/openapi.json."""
    response = TestClient().get("/swagger/openapi.json")
    assert response.status == 200, (
        f"/swagger/openapi.json returned {response.status}, expected 200 — swagger "
        "must be enabled for the document to serve"
    )
    assert "application/json" in response.content_type, response.content_type
    document = response.json()
    assert isinstance(document, dict), type(document)
    return document


def clean_swagger_env(monkeypatch):
    """Delete every TINA4_SWAGGER_* / SWAGGER_* var so a test measures a pristine
    baseline instead of whatever the lab happens to have exported."""
    for key in list(os.environ):
        if key.startswith("TINA4_SWAGGER_") or key.startswith("SWAGGER_"):
            monkeypatch.delenv(key, raising=False)


def path_template_names(path_key: str) -> list[str]:
    """The ``{name}`` tokens inside an OpenAPI path key."""
    return re.findall(r"\{([^}]+)\}", path_key)


@pytest.fixture
def sqlite_widget_db(tmp_path):
    """A REAL sqlite database with the Widget table materialised.

    Binds Widget to an actual on-disk sqlite file and runs real CREATE TABLE DDL,
    so the model the document describes is a genuine, persistable app model — not
    a bare class. The previous global binding is saved and restored so the bind
    never leaks into another test.
    """
    previous = orm_model._database
    database = Database(f"sqlite:///{tmp_path / 'swagger_contract.db'}")
    bind_database(database)
    Widget.create_table()
    try:
        yield database
    finally:
        orm_model._database = previous


# ── 1. the-document-validates ────────────────────────────────────────────────

def test_the_document_validates_against_a_real_openapi_validator(monkeypatch, sqlite_widget_db):
    """Invariant: the-document-validates. Human stem: document validates.

    The document fetched from /swagger/openapi.json passes a REAL OpenAPI
    validator for the version it declares, for an app that has routes, a path
    param, an ORM model and a secured route.
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")

    with isolated_routes():
        register_get("/contract/status")                                  # a route
        register_get("/contract/widgets/{id:int}")                        # a path param
        register_write("/contract/widgets", model=Widget)                 # ORM model + secured (POST default)
        document = fetch_openapi_document()

        # The app genuinely exercises all four required shapes.
        assert document["paths"], "the app must publish routes"
        assert "/contract/widgets/{id}" in document["paths"], "path param must be present"
        assert "Widget" in document["components"]["schemas"], "ORM model schema must be present"
        assert "security" in document["paths"]["/contract/widgets"]["post"], "secured route must document security"

        # THE invariant: the version-appropriate real validator accepts it. This
        # is the single rule that would have caught both P1s (php/node shipped
        # structurally invalid documents).
        validate_openapi_document(document)  # raises OpenAPIValidationError if invalid

    # Negative control — prove the validator is a real gate, not a rubber stamp:
    # a document missing the required `info` block MUST be rejected.
    broken = {"openapi": document["openapi"], "paths": {}}
    with pytest.raises(OpenAPIValidationError):
        validate_openapi_document(broken)


# ── 2. every-template-expression-has-a-parameter ─────────────────────────────

def test_every_template_expression_has_a_parameter(monkeypatch):
    """Invariant: every-template-expression-has-a-parameter.
    Human stem: every path template has a parameter.

    Every {name} in a path key has a matching in:path required:true parameter,
    and the path key itself carries NO framework type token (no ':').
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")

    with isolated_routes():
        register_get("/contract/a/{id:int}")                              # typed
        register_get("/contract/b/{slug:slug}")                           # typed
        register_get("/contract/c/{name}")                                # bare
        register_get("/contract/d/{user_id:int}/items/{item_id:int}")     # two typed
        register_get("/contract/files/*")                                 # splat -> {wildcard}
        document = fetch_openapi_document()

        assert document["paths"], "expected the registered templated routes"
        for path_key, methods in document["paths"].items():
            names = path_template_names(path_key)
            for name in names:
                assert ":" not in name, (
                    f"path key {path_key!r} leaked a framework type token into the "
                    f"template {{{name}}}"
                )
            for operation in methods.values():
                parameters = operation.get("parameters", [])
                path_params = {
                    p["name"]: p for p in parameters if p.get("in") == "path"
                }
                # Exactly one in:path parameter per {name} — none missing, none extra.
                assert set(path_params) == set(names), (
                    f"{path_key}: path params {sorted(path_params)} do not match "
                    f"template names {sorted(names)}"
                )
                for name in names:
                    parameter = path_params[name]
                    assert parameter["in"] == "path"
                    assert parameter["required"] is True, (
                        f"{path_key}: {name} must be required:true"
                    )
                    assert "schema" in parameter


# ── 3. security-mirrors-the-runtime-gate ─────────────────────────────────────

def test_security_mirrors_the_runtime_gate(monkeypatch):
    """Invariant: security-mirrors-the-runtime-gate.
    Human stem: security mirrors the runtime gate.

    POSITIVE: a secured write documents security AND the server answers 401 for
    it with no token. NEGATIVE: an explicitly-public (@noauth) write documents
    NO security AND the server lets a tokenless request through. Both derive from
    the same auth_required flag dispatch enforces.
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")
    # No token is minted anywhere: the runtime gate is proven by the 401 itself.
    monkeypatch.delenv("TINA4_API_KEY", raising=False)

    with isolated_routes():
        register_write("/contract/secure-write")                # POST default -> auth required
        register_write("/contract/public-write", public=True)   # @noauth -> public
        document = fetch_openapi_document()
        client = TestClient()

        secure_operation = document["paths"]["/contract/secure-write"]["post"]
        public_operation = document["paths"]["/contract/public-write"]["post"]

        # Document side.
        assert "security" in secure_operation, "a secured write must document security"
        assert secure_operation["security"] == [{"bearerAuth": []}]
        assert "security" not in public_operation, "an explicitly-public write must document none"

        # Runtime side — the SAME flag, proven by the live server's answer.
        assert client.post("/contract/secure-write", json={}).status == 401, (
            "the secured write the document marks protected must 401 without a token"
        )
        assert client.post("/contract/public-write", json={}).status == 201, (
            "the @noauth write the document marks public must serve without a token"
        )


# ── 4. path-param-types-map-identically ──────────────────────────────────────

def test_typed_path_param_types_map_identically(monkeypatch):
    """Invariant: path-param-types-map-identically.
    Human stem: typed path token maps identically.

    int/integer->integer, float/number->number, uuid->string+format uuid,
    slug/alpha/alnum->string+pattern, bare->string. An unknown token degrades to
    string rather than dropping the parameter.
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")

    slug_pattern = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    alpha_pattern = r"^[A-Za-z]+$"
    alnum_pattern = r"^[A-Za-z0-9]+$"

    expected = {
        "/contract/t/int/{id}": {"type": "integer"},
        "/contract/t/integer/{id}": {"type": "integer"},
        "/contract/t/float/{v}": {"type": "number"},
        "/contract/t/number/{v}": {"type": "number"},
        "/contract/t/uuid/{u}": {"type": "string", "format": "uuid"},
        "/contract/t/slug/{s}": {"type": "string", "pattern": slug_pattern},
        "/contract/t/alpha/{a}": {"type": "string", "pattern": alpha_pattern},
        "/contract/t/alnum/{a}": {"type": "string", "pattern": alnum_pattern},
        "/contract/t/bare/{name}": {"type": "string"},
    }

    with isolated_routes():
        register_get("/contract/t/int/{id:int}")
        register_get("/contract/t/integer/{id:integer}")
        register_get("/contract/t/float/{v:float}")
        register_get("/contract/t/number/{v:number}")
        register_get("/contract/t/uuid/{u:uuid}")
        register_get("/contract/t/slug/{s:slug}")
        register_get("/contract/t/alpha/{a:alpha}")
        register_get("/contract/t/alnum/{a:alnum}")
        register_get("/contract/t/bare/{name}")
        document = fetch_openapi_document()

        for path_key, want in expected.items():
            parameters = document["paths"][path_key]["get"]["parameters"]
            assert len(parameters) == 1, path_key
            assert parameters[0]["schema"] == want, (
                f"{path_key}: got {parameters[0]['schema']}, want {want}"
            )

    # Unknown-token degradation. The router REFUSES an unknown type token
    # (_compile_pattern raises ValueError), so it can never reach a served
    # document; the generator's defensive fallback is proven against its real
    # public API over a real route dict (no mock — same surface the parity suite
    # uses). The parameter must degrade to string, NOT be dropped.
    unknown_spec = Swagger(version="1.0.0").generate(
        [{"method": "GET", "path": "/contract/t/unknown/{x:bogus}", "handler": None}]
    )
    unknown_params = unknown_spec["paths"]["/contract/t/unknown/{x}"]["get"]["parameters"]
    assert unknown_params == [
        {"name": "x", "in": "path", "required": True, "schema": {"type": "string"}}
    ]


# ── 5. model-schemas-are-referenced-not-inlined ──────────────────────────────

def test_model_schemas_are_referenced_not_inlined(monkeypatch, sqlite_widget_db):
    """Invariant: model-schemas-are-referenced-not-inlined.
    Human stem: model schema keyed by class name.

    An ORM model becomes ONE components.schemas entry keyed by the model CLASS
    name, `required` derived from nullability, referenced by $ref (not inlined).
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")

    with isolated_routes():
        register_write("/contract/widgets", model=Widget)
        document = fetch_openapi_document()

        schemas = document["components"]["schemas"]
        # Keyed by the CLASS name, never the tableName.
        assert Widget.__name__ == "Widget"
        assert "Widget" in schemas
        assert "widgets" not in schemas, "keyed by tableName is the Node mis-keying bug"

        schema = schemas["Widget"]
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {"id", "name"}
        # `required` derives from nullability: NOT NULL `name` is required, the
        # auto-increment PK is not.
        assert schema["required"] == ["name"]

        # Referenced by $ref, not inlined into the operation body.
        request_body = document["paths"]["/contract/widgets"]["post"]["requestBody"]
        media = request_body["content"]["application/json"]
        assert media["schema"] == {"$ref": "#/components/schemas/Widget"}
        assert "properties" not in media["schema"], "the body must $ref the schema, not inline it"


# ── 6. info-and-servers-defaults-are-one-value ───────────────────────────────

def test_info_and_servers_defaults_are_one_value(monkeypatch):
    """Invariant: info-and-servers-defaults-are-one-value.
    Human stem: info and servers defaults identical.

    With no TINA4_SWAGGER_* set: info.version == "1.0.0", info.description == "",
    servers[0].url == "/".
    """
    clean_swagger_env(monkeypatch)
    # Enable via TINA4_DEBUG so that NO TINA4_SWAGGER_* variable is set — the
    # defaults must be measured in a pristine swagger environment.
    monkeypatch.setenv("TINA4_DEBUG", "true")
    assert not any(k.startswith("TINA4_SWAGGER_") for k in os.environ)
    assert not any(k.startswith("SWAGGER_") for k in os.environ)

    with isolated_routes():
        register_get("/contract/anything")
        document = fetch_openapi_document()

        assert document["info"]["version"] == "1.0.0"
        assert document["info"]["description"] == ""
        assert document["servers"] == [{"url": "/"}]
        # The hard-coded host:port that was measurably wrong off 7145 must be gone.
        assert "localhost:7145" not in document["servers"][0]["url"]


# ── 7. env-surface-is-identical ──────────────────────────────────────────────

def test_swagger_env_surface_is_identical(monkeypatch):
    """Invariant: env-surface-is-identical. Human stem: swagger env surface identical.

    The documented TINA4_SWAGGER_* variables are read — spot-checking several,
    including CONTACT_TEAM -> info.contact.name and CONTACT_URL -> info.contact.url
    (the two PHP alone ignored).
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")
    monkeypatch.setenv("TINA4_SWAGGER_TITLE", "Contract Surface API")
    monkeypatch.setenv("TINA4_SWAGGER_VERSION", "9.9.9")
    monkeypatch.setenv("TINA4_SWAGGER_DESCRIPTION", "surface under contract")
    monkeypatch.setenv("TINA4_SWAGGER_CONTACT_TEAM", "Platform Team")
    monkeypatch.setenv("TINA4_SWAGGER_CONTACT_URL", "https://contact.example.com")
    monkeypatch.setenv("TINA4_SWAGGER_CONTACT_EMAIL", "team@example.com")
    monkeypatch.setenv("TINA4_SWAGGER_LICENSE", "MIT")

    with isolated_routes():
        register_get("/contract/anything")
        document = fetch_openapi_document()

    info = document["info"]
    assert info["title"] == "Contract Surface API"
    assert info["version"] == "9.9.9"
    assert info["description"] == "surface under contract"
    # The spot-check the fixture names explicitly.
    assert info["contact"]["name"] == "Platform Team"      # CONTACT_TEAM
    assert info["contact"]["url"] == "https://contact.example.com"  # CONTACT_URL
    assert info["contact"]["email"] == "team@example.com"
    assert info["license"] == {"name": "MIT"}


# ── 8. disabled-means-nothing-is-served ──────────────────────────────────────

DISABLED_GATED_PATHS = (
    "/swagger",
    "/swagger/",
    "/swagger/openapi.json",
    "/swagger/index.html",
    "/swagger/oauth2-redirect.html",
)


def test_disabled_means_nothing_is_served(monkeypatch):
    """Invariant: disabled-means-nothing-is-served. Human stem: disabled serves nothing.

    With TINA4_SWAGGER_ENABLED=false the UI path, its trailing-slash form, the
    spec endpoint AND the bundled UI assets all 404. Positive control: with it
    true, those same paths serve — so the 404s are the gate, not a broken route.
    """
    clean_swagger_env(monkeypatch)

    # POSITIVE control — enabled: every path serves (not 404).
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")
    with isolated_routes():
        register_get("/contract/anything")
        client = TestClient()
        for path in DISABLED_GATED_PATHS:
            assert client.get(path).status != 404, f"{path} should serve when swagger is enabled"

    # NEGATIVE — disabled: every path 404s, static assets included.
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "false")
    with isolated_routes():
        register_get("/contract/anything")
        client = TestClient()
        for path in DISABLED_GATED_PATHS:
            assert client.get(path).status == 404, (
                f"{path} was served with TINA4_SWAGGER_ENABLED=false"
            )


# ── 9. only-the-application-is-documented ────────────────────────────────────

def test_only_the_application_is_documented(monkeypatch):
    """Invariant: only-the-application-is-documented.
    Human stem: only the application is documented.

    Framework-internal routes are excluded from the published document by the one
    shared rule (the /swagger and /__dev prefixes), never a per-framework list.
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")

    with isolated_routes():
        register_get("/contract/widgets")           # application route
        register_get("/__dev/api/probe")            # framework-internal prefix
        register_get("/swagger/custom")             # framework-internal prefix
        document = fetch_openapi_document()

        paths = document["paths"]
        assert "/contract/widgets" in paths, "the application route must be documented"
        assert "/__dev/api/probe" not in paths, "/__dev internals must be excluded"
        assert "/swagger/custom" not in paths, "/swagger internals must be excluded"
        # No published path may sit under either internal prefix.
        for path_key in paths:
            assert not path_key.startswith("/__dev"), path_key
            assert not path_key.startswith("/swagger"), path_key


# ── 10. operation-ids-are-stable-and-distinct ────────────────────────────────

def test_operation_ids_are_stable_and_distinct(monkeypatch):
    """Invariant: operation-ids-are-stable-and-distinct.
    Human stem: operation ids stable and distinct.

    Two distinct paths never collapse to one operationId; /__health and /health
    stay distinct, and which id each path gets does not depend on registration
    order.
    """
    clean_swagger_env(monkeypatch)
    monkeypatch.setenv("TINA4_SWAGGER_ENABLED", "true")

    with isolated_routes():
        register_get("/__health")
        register_get("/health")
        document = fetch_openapi_document()
        internal_id = document["paths"]["/__health"]["get"]["operationId"]
        public_id = document["paths"]["/health"]["get"]["operationId"]
        assert internal_id == "get___health"
        assert public_id == "get_health"
        assert internal_id != public_id

    # Order-independence: reversing registration yields the SAME two ids (the
    # collapse-then-suffix bug is order-dependent; preserving underscores is not).
    with isolated_routes():
        register_get("/health")
        register_get("/__health")
        document = fetch_openapi_document()
        assert document["paths"]["/__health"]["get"]["operationId"] == "get___health"
        assert document["paths"]["/health"]["get"]["operationId"] == "get_health"
