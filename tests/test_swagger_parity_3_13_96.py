# Swagger parity locks for 3.13.96 — decisions S2, S3, S6.
"""
These pin the three Swagger invariants the cross-framework decision
(plan/v3/parity-3.13.96-decisions.md) settled for 3.13.96:

  S2  components.schemas is keyed by the MODEL CLASS NAME and carries `required`.
  S3  servers[0].url defaults to "/" (not a hard-coded host:port); info.description
      defaults to "". TINA4_SWAGGER_SERVERS still overrides.
  S6  operationId preserves leading underscores from the path, so /__health and
      /health produce two DISTINCT ids (never a collapse-then-suffix).

No doubles: a real Swagger generator over real route dicts and a real ORM model.
"""
import pytest

from tina4_python.swagger import Swagger
from tina4_python.orm import ORM, IntegerField, StringField


def _handler():
    pass


# A real ORM model, exactly as AutoCrud would hand it to the generator. `name`
# is required; `id` is the auto-increment PK and is not.
class Item(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)


@pytest.fixture(autouse=True)
def _clean_swagger_env(monkeypatch):
    # The servers[] / version / description defaults must be measured with a
    # pristine environment, or a stray TINA4_SWAGGER_* / SWAGGER_DEV_URL leaks in.
    for var in (
        "TINA4_SWAGGER_SERVERS", "SWAGGER_DEV_URL", "TINA4_SWAGGER_VERSION",
        "TINA4_SWAGGER_DESCRIPTION",
    ):
        monkeypatch.delenv(var, raising=False)


# ── S2. components.schemas keyed by class name, with `required` ──────────────


class TestS2SchemaKeyedByClassName:
    def test_schema_key_is_the_class_name_not_the_table(self):
        handler = _handler
        handler._swagger_model = Item
        routes = [{"method": "GET", "path": "/api/items", "handler": handler}]
        spec = Swagger(title="T", version="1.0.0").generate(routes)

        schemas = spec["components"]["schemas"]
        # Keyed by the MODEL CLASS NAME ("Item"), never by tableName ("items").
        assert "Item" in schemas
        assert "items" not in schemas
        assert list(schemas.keys()) == [Item.__name__]

    def test_schema_carries_properties_and_required(self):
        handler = _handler
        handler._swagger_model = Item
        routes = [{"method": "GET", "path": "/api/items", "handler": handler}]
        spec = Swagger(title="T", version="1.0.0").generate(routes)

        schema = spec["components"]["schemas"]["Item"]
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "id" in schema["properties"]
        # `required` is what makes the schema worth having; `name` is required,
        # the auto-increment PK is not.
        assert schema["required"] == ["name"]


# ── S3. servers[0].url defaults to "/", info.description defaults to "" ───────


class TestS3ServersAndDescriptionDefaults:
    def test_servers_default_is_root_slash(self):
        # A server bound to any host/port must advertise "/", which resolves
        # correctly under any port or reverse proxy — never a hard-coded 7145.
        spec = Swagger(title="T", version="1.0.0").generate([])
        assert spec["servers"] == [{"url": "/"}]

    def test_no_hardcoded_localhost_7145(self):
        spec = Swagger(title="T", version="1.0.0").generate([])
        assert "localhost:7145" not in spec["servers"][0]["url"]

    def test_info_description_defaults_to_empty_string(self):
        spec = Swagger(title="T", version="1.0.0").generate([])
        assert spec["info"]["description"] == ""

    def test_info_version_defaults_to_1_0_0(self):
        # The app's version, not the framework's (guards against a 3.13.x leak).
        spec = Swagger(title="T").generate([])
        assert spec["info"]["version"] == "1.0.0"

    def test_swagger_servers_env_still_overrides(self, monkeypatch):
        monkeypatch.setenv("TINA4_SWAGGER_SERVERS", "https://api.example.com")
        spec = Swagger(title="T", version="1.0.0").generate([])
        assert spec["servers"] == [{"url": "https://api.example.com"}]

    def test_swagger_servers_env_multi_value(self, monkeypatch):
        monkeypatch.setenv(
            "TINA4_SWAGGER_SERVERS", "https://a.example.com, https://b.example.com"
        )
        spec = Swagger(title="T", version="1.0.0").generate([])
        assert spec["servers"] == [
            {"url": "https://a.example.com"},
            {"url": "https://b.example.com"},
        ]

    def test_explicit_server_url_constructor_beats_default(self):
        # ADR-0041: explicit constructor arg wins over the "/" default.
        spec = Swagger(title="T", server_url="https://explicit.example.com").generate([])
        assert spec["servers"] == [{"url": "https://explicit.example.com"}]


# ── S6. operationId never collides (leading underscores preserved) ───────────


class TestS6OperationIdNoCollision:
    def test_internal_and_public_health_get_distinct_ids(self):
        routes = [
            {"method": "GET", "path": "/__health", "handler": _handler},
            {"method": "GET", "path": "/health", "handler": _handler},
        ]
        spec = Swagger(title="T", version="1.0.0").generate(routes)

        internal = spec["paths"]["/__health"]["get"]["operationId"]
        public = spec["paths"]["/health"]["get"]["operationId"]

        # Leading underscores are preserved, so the two paths yield two distinct
        # ids — never a collapse to the same base with a registration-order _2.
        assert internal == "get___health"
        assert public == "get_health"
        assert internal != public

    def test_no_order_dependent_suffix(self):
        # Reversing registration order must NOT change which id each path gets
        # (the collapse-then-suffix bug is order-dependent; preserving the
        # underscores is not).
        routes = [
            {"method": "GET", "path": "/health", "handler": _handler},
            {"method": "GET", "path": "/__health", "handler": _handler},
        ]
        spec = Swagger(title="T", version="1.0.0").generate(routes)
        assert spec["paths"]["/__health"]["get"]["operationId"] == "get___health"
        assert spec["paths"]["/health"]["get"]["operationId"] == "get_health"
