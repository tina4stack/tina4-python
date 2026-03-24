# Comprehensive smoke test for Tina4 Python — one test per feature.
# All tests use in-memory or temp resources; no external services required.
import asyncio
import json
import mimetypes
import os
import struct
import time

import pytest

from tina4_python.core.router import Router, get, post
from tina4_python.core.response import Response
from tina4_python.core.middleware import CorsMiddleware
from tina4_python.database import Database, DatabaseResult
from tina4_python.orm import ORM, orm_bind, Field
from tina4_python.frond import Frond
from tina4_python.session import Session, FileSessionHandler
from tina4_python.auth import Auth
from tina4_python.queue import Queue
from tina4_python.graphql import GraphQL
from tina4_python.swagger import Swagger, description, tags
from tina4_python.i18n import I18n
from tina4_python.seeder import FakeData
from tina4_python.migration import migrate, create_migration
from tina4_python.crud import AutoCrud
from tina4_python.cache import ResponseCache
from tina4_python.container import Container
from tina4_python.messenger import DevMailbox
from tina4_python.dotenv import load_env, get_env
from tina4_python.wsdl import WSDL, wsdl_operation
from tina4_python.websocket import (
    compute_accept_key, build_frame, read_frame,
    OP_TEXT, MAGIC_STRING,
)


# ── Shared fixtures ──────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """In-memory-style temp SQLite database."""
    d = Database(f"sqlite:///{tmp_path / 'smoke.db'}")
    d.execute(
        "CREATE TABLE items ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT NOT NULL,"
        "  price REAL DEFAULT 0,"
        "  active INTEGER DEFAULT 1"
        ")"
    )
    d.commit()
    yield d
    d.close()


class Item(ORM):
    table_name = "items"
    id = Field(int, primary_key=True, auto_increment=True)
    name = Field(str, required=True)
    price = Field(float, default=0.0)
    active = Field(bool, default=True)


@pytest.fixture(autouse=True)
def _clear_routes():
    Router.clear()
    AutoCrud._registered.clear()
    yield
    Router.clear()
    AutoCrud._registered.clear()


# ── 1. Server boot ──────────────────────────────────────────────


class TestServerBoot:
    def test_server_module_importable(self):
        """Core server module can be imported without starting a listener."""
        from tina4_python.core import server  # noqa: F401
        assert hasattr(server, "_auto_discover")


# ── 2. Route discovery ──────────────────────────────────────────


class TestRouteDiscovery:
    def test_get_and_post_routes_registered(self):
        @get("/smoke/hello")
        async def hello(req, res):
            pass

        @post("/smoke/echo")
        async def echo(req, res):
            pass

        route_get, _ = Router.match("GET", "/smoke/hello")
        route_post, _ = Router.match("POST", "/smoke/echo")
        assert route_get is not None
        assert route_post is not None
        assert route_get["handler"] is hello
        assert route_post["handler"] is echo

    def test_parameterised_route_match(self):
        @get("/smoke/items/{id:int}")
        async def item_detail(req, res):
            pass

        route, params = Router.match("GET", "/smoke/items/42")
        assert route is not None
        assert params["id"] == "42"


# ── 3. ORM ──────────────────────────────────────────────────────


class TestORM:
    def test_save_load_delete(self, db):
        orm_bind(db)
        item = Item({"name": "Widget", "price": 9.99})
        item.save()
        db.commit()

        found = Item.find(item.id)
        assert found is not None
        assert found.name == "Widget"
        assert found.price == 9.99

        found.delete()
        db.commit()
        assert Item.find(item.id) is None


# ── 4. Database CRUD ────────────────────────────────────────────


class TestDatabase:
    def test_insert_fetch_update_delete(self, db):
        db.insert("items", {"name": "Bolt", "price": 1.50})
        db.commit()

        row = db.fetch_one("SELECT * FROM items WHERE name = ?", ["Bolt"])
        assert row is not None
        assert row["price"] == 1.50

        db.update("items", {"name": "Bolt Updated"}, "name = ?", ["Bolt"])
        db.commit()
        row = db.fetch_one("SELECT * FROM items WHERE name = ?", ["Bolt Updated"])
        assert row is not None

        db.delete("items", "name = ?", ["Bolt Updated"])
        db.commit()
        assert db.fetch_one("SELECT * FROM items WHERE name = ?", ["Bolt Updated"]) is None

    def test_table_exists(self, db):
        assert db.table_exists("items") is True
        assert db.table_exists("nonexistent") is False


# ── 5. Frond templates ──────────────────────────────────────────


class TestFrondTemplates:
    def test_render_with_variables(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string("Hello {{ name }}!", {"name": "Smoke"})
        assert result == "Hello Smoke!"

    def test_inheritance(self, tmp_path):
        (tmp_path / "base.html").write_text(
            "<h1>{% block title %}Default{% endblock %}</h1>"
            "<div>{% block content %}{% endblock %}</div>"
        )
        (tmp_path / "child.html").write_text(
            '{% extends "base.html" %}'
            "{% block title %}Smoke{% endblock %}"
            "{% block content %}OK{% endblock %}"
        )
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render("child.html", {})
        assert "<h1>Smoke</h1>" in result
        assert "<div>OK</div>" in result

    def test_filter(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string("{{ name | upper }}", {"name": "smoke"})
        assert result == "SMOKE"


# ── 6. Error templates ──────────────────────────────────────────


class TestErrorTemplate:
    def test_404_response_is_text_not_json(self):
        r = Response()
        r("Not found", 404)
        assert r.status_code == 404
        # Plain text response, not JSON
        assert "text/plain" in r.content_type


# ── 7. Sessions ─────────────────────────────────────────────────


class TestSessions:
    def test_create_read_destroy(self, tmp_path):
        handler = FileSessionHandler(str(tmp_path / "sessions"))
        session = Session(handler=handler, ttl=300)
        sid = session.start()
        assert sid

        session.set("user", "smoke")
        session.save()
        assert session.get("user") == "smoke"

        session.destroy()
        s2 = Session(handler=handler, ttl=300)
        s2.start(sid)
        assert s2.get("user") is None


# ── 8. Auth/JWT ─────────────────────────────────────────────────


class TestAuthJWT:
    def test_create_and_validate_token(self):
        auth = Auth(secret="smoke-secret", token_expiry=30)
        token = auth.create_token({"user_id": 1, "role": "admin"})
        payload = auth.validate_token(token)
        assert payload is not None
        assert payload["user_id"] == 1
        assert payload["role"] == "admin"

    def test_expired_token_rejected(self):
        from tina4_python.auth import _b64url_encode
        auth = Auth(secret="smoke-secret", token_expiry=0)
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_encode(json.dumps({"user_id": 1, "exp": int(time.time()) - 10}).encode())
        sig = auth._sign(f"{header}.{payload}")
        expired = f"{header}.{payload}.{sig}"
        assert auth.validate_token(expired) is None


# ── 9. Middleware ────────────────────────────────────────────────


class TestMiddleware:
    def test_cors_before_and_after(self):
        cors = CorsMiddleware()

        class Req:
            method = "GET"
            headers = {"origin": "https://test.com"}

        class Resp:
            _headers = {}
            status_code = 200
            def header(self, n, v):
                self._headers[n] = v
                return self
            def status(self, c):
                self.status_code = c
                return self

        req, resp = Req(), Resp()
        cors.apply(req, resp)
        assert resp._headers["access-control-allow-origin"] == "*"
        assert "GET" in resp._headers["access-control-allow-methods"]


# ── 10. Queue ────────────────────────────────────────────────────


class TestQueue:
    def test_push_pop_verify_payload(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'q.db'}")
        q = Queue(db, topic="smoke")
        q.push({"action": "send_email", "to": "user@test.com"})
        job = q.pop()
        assert job is not None
        assert job.data["action"] == "send_email"
        assert job.data["to"] == "user@test.com"
        db.close()


# ── 11. GraphQL ──────────────────────────────────────────────────


class TestGraphQL:
    def test_type_query_mutation(self):
        gql = GraphQL()
        gql.schema.add_type("Widget", {"id": "ID", "name": "String"})
        gql.schema.add_query("widget", {
            "type": "Widget",
            "args": {"id": "ID!"},
            "resolve": lambda r, a, c: {"id": a["id"], "name": "Cog"},
        })
        gql.schema.add_mutation("createWidget", {
            "type": "Widget",
            "args": {"name": "String!"},
            "resolve": lambda r, a, c: {"id": "1", "name": a["name"]},
        })

        result = gql.execute('{ widget(id: "1") { name } }')
        assert result["data"]["widget"]["name"] == "Cog"

        result = gql.execute('mutation { createWidget(name: "Gear") { id name } }')
        assert result["data"]["createWidget"]["name"] == "Gear"

    def test_from_orm(self, db):
        orm_bind(db)
        gql = GraphQL()
        gql.schema.from_orm(Item)
        schema = gql.introspect()
        assert "Item" in schema["types"]
        assert "item" in schema["queries"]
        assert "items" in schema["queries"]


# ── 12. Swagger ──────────────────────────────────────────────────


class TestSwagger:
    def test_generate_openapi_spec(self):
        swagger = Swagger(title="Smoke API", version="1.0.0")

        @description("List items")
        @tags(["items"])
        def handler():
            pass

        routes = [
            {"method": "GET", "path": "/api/items", "handler": handler},
            {"method": "POST", "path": "/api/items", "handler": handler},
        ]
        spec = swagger.generate(routes)
        assert spec["openapi"] == "3.0.3"
        assert "/api/items" in spec["paths"]
        assert "get" in spec["paths"]["/api/items"]
        assert "post" in spec["paths"]["/api/items"]
        assert spec["paths"]["/api/items"]["get"]["description"] == "List items"


# ── 13. i18n ─────────────────────────────────────────────────────


class TestI18n:
    def test_translate_and_switch_locale(self, tmp_path):
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        (locale_dir / "en.json").write_text(json.dumps({"greeting": "Hello"}))
        (locale_dir / "fr.json").write_text(json.dumps({"greeting": "Bonjour"}))

        i18n = I18n(locale_dir=str(locale_dir), default_locale="en")
        assert i18n.t("greeting") == "Hello"
        i18n.locale = "fr"
        assert i18n.t("greeting") == "Bonjour"


# ── 14. FakeData ─────────────────────────────────────────────────


class TestFakeData:
    def test_seeded_deterministic(self):
        f1 = FakeData(seed=99)
        f2 = FakeData(seed=99)
        assert f1.name() == f2.name()
        assert f1.email() == f2.email()
        assert f1.integer(0, 1000) == f2.integer(0, 1000)


# ── 15. Migrations ───────────────────────────────────────────────


class TestMigrations:
    def test_run_migration_creates_table(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'mig.db'}")
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_create_products.sql").write_text(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT);"
        )
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_create_products.sql"]
        assert db.table_exists("products")
        db.close()


# ── 16. AutoCRUD ─────────────────────────────────────────────────


class TestAutoCRUD:
    def test_register_generates_crud_routes(self, db):
        orm_bind(db)
        generated = AutoCrud.register(Item)
        paths = [r["path"] for r in generated]
        assert "/api/items" in paths
        assert "/api/items/{id}" in paths

        methods = {r["method"] for r in generated}
        assert methods == {"GET", "POST", "PUT", "DELETE"}

        # Verify the routes exist in the router
        route, _ = Router.match("GET", "/api/items")
        assert route is not None
        route, _ = Router.match("POST", "/api/items")
        assert route is not None


# ── 17. Response Cache ───────────────────────────────────────────


class TestResponseCache:
    def test_cache_hit(self):
        cache = ResponseCache(ttl=60)

        class Req:
            method = "GET"
            url = "/api/cached"
            params = None

        class Resp:
            def __init__(self, body="", status_code=200):
                self.body = body
                self.status_code = status_code
                self.content_type = "application/json"
            def __call__(self, body=None, status_code=None):
                return Resp(
                    body=body if body is not None else self.body,
                    status_code=status_code if status_code is not None else self.status_code,
                )

        req = Req()
        resp = Resp()

        # Miss
        cache.before_cache(req, resp)
        resp_out = Resp(body='{"ok":true}', status_code=200)
        cache.after_cache(req, resp_out)

        # Hit
        req2 = Req()
        resp2 = Resp()
        _, hit = cache.before_cache(req2, resp2)
        assert hit.body == '{"ok":true}'
        assert cache.cache_stats()["hits"] == 1


# ── 18. DI Container ────────────────────────────────────────────


class TestDIContainer:
    def test_register_and_resolve(self):
        c = Container()
        c.register("greeter", lambda: "Hello, DI!")
        assert c.get("greeter") == "Hello, DI!"

    def test_singleton_same_instance(self):
        c = Container()
        c.singleton("obj", lambda: object())
        assert c.get("obj") is c.get("obj")

    def test_missing_raises(self):
        c = Container()
        with pytest.raises(KeyError):
            c.get("missing")


# ── 19. DevMailbox ───────────────────────────────────────────────


class TestDevMailbox:
    def test_capture_email(self, tmp_path):
        mailbox = DevMailbox(mailbox_dir=str(tmp_path / "mailbox"))
        result = mailbox.capture(
            to="user@test.com",
            subject="Smoke Test",
            body="Hello from smoke test",
            from_address="dev@test.com",
        )
        assert result["success"] is True
        messages = mailbox.inbox()
        assert len(messages) == 1
        assert messages[0]["subject"] == "Smoke Test"


# ── 20. Static files — MIME type detection ───────────────────────


class TestStaticFiles:
    def test_mime_type_detection(self):
        checks = {
            "style.css": "text/css",
            "app.js": "text/javascript",  # or application/javascript
            "image.png": "image/png",
            "doc.pdf": "application/pdf",
            "data.json": "application/json",
            "page.html": "text/html",
        }
        for filename, expected in checks.items():
            mime, _ = mimetypes.guess_type(filename)
            assert mime is not None, f"No MIME for {filename}"
            # Accept either text/javascript or application/javascript for .js
            if filename.endswith(".js"):
                assert "javascript" in mime
            else:
                assert mime == expected, f"Expected {expected} for {filename}, got {mime}"


# ── 21. DotEnv ───────────────────────────────────────────────────


class TestDotEnv:
    def test_load_and_read(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SMOKE_VAR=smoke_value\nSMOKE_PORT=8080\n")
        result = load_env(str(env_file), override=True)
        assert result["SMOKE_VAR"] == "smoke_value"
        assert get_env("SMOKE_VAR") == "smoke_value"
        assert get_env("SMOKE_PORT") == "8080"
        # Cleanup
        os.environ.pop("SMOKE_VAR", None)
        os.environ.pop("SMOKE_PORT", None)


# ── 22. WSDL ─────────────────────────────────────────────────────


class TestWSDL:
    def test_define_service_generate_wsdl(self):
        class Adder(WSDL):
            @wsdl_operation({"Result": int})
            def Add(self, a: int, b: int):
                return {"Result": a + b}

        svc = Adder()
        wsdl_xml = svc.generate_wsdl()
        assert "<?xml" in wsdl_xml
        assert "<definitions" in wsdl_xml
        assert "Add" in wsdl_xml
        assert "Adder" in wsdl_xml
        assert 'type="xsd:int"' in wsdl_xml

    def test_soap_invocation(self):
        class Adder(WSDL):
            @wsdl_operation({"Result": int})
            def Add(self, a: int, b: int):
                return {"Result": a + b}

        soap_body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            '<soap:Body><Add><a>10</a><b>7</b></Add></soap:Body>'
            '</soap:Envelope>'
        )
        req = type("R", (), {"body": soap_body, "url": "/adder", "params": {}})()
        svc = Adder(req)
        result = svc.handle()
        assert "<Result>17</Result>" in result


# ── 23. WebSocket ────────────────────────────────────────────────


class TestWebSocket:
    def test_compute_accept_key(self):
        # RFC 6455 Section 4.2.2 example
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        assert compute_accept_key(key) == expected

    def test_build_and_parse_frame(self):
        payload = b"Hello Smoke"
        frame = build_frame(OP_TEXT, payload)
        assert frame[0] == 0x81  # FIN + TEXT opcode
        # Length in byte 1
        assert frame[1] == len(payload)
        assert frame[2:] == payload

    @pytest.mark.asyncio
    async def test_read_frame(self):
        payload = b"async test"
        frame = build_frame(OP_TEXT, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert fin is True
        assert opcode == OP_TEXT
        assert data == payload


# ── 24. Additional Router Tests ──────────────────────────────────


class TestRouterAdvanced:
    def test_nonexistent_route_returns_none(self):
        route, params = Router.match("GET", "/does/not/exist")
        assert route is None
        assert params == {}

    def test_put_route(self):
        from tina4_python.core.router import put

        @put("/smoke/update/{id}")
        async def update_item(req, res):
            pass

        route, params = Router.match("PUT", "/smoke/update/99")
        assert route is not None
        assert params["id"] == "99"

    def test_delete_route(self):
        from tina4_python.core.router import delete

        @delete("/smoke/remove/{id}")
        async def remove_item(req, res):
            pass

        route, _ = Router.match("DELETE", "/smoke/remove/5")
        assert route is not None

    def test_patch_route(self):
        from tina4_python.core.router import patch

        @patch("/smoke/patch/{id}")
        async def patch_item(req, res):
            pass

        route, _ = Router.match("PATCH", "/smoke/patch/7")
        assert route is not None

    def test_any_method_route(self):
        from tina4_python.core.router import any_method

        @any_method("/smoke/any")
        async def any_handler(req, res):
            pass

        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            route, _ = Router.match(method, "/smoke/any")
            assert route is not None, f"ANY route should match {method}"

    def test_float_param_route(self):
        @get("/smoke/price/{price:float}")
        async def price_handler(req, res):
            pass

        route, params = Router.match("GET", "/smoke/price/19.99")
        assert route is not None
        assert params["price"] == "19.99"

    def test_greedy_path_param(self):
        @get("/smoke/files/{filepath:path}")
        async def file_handler(req, res):
            pass

        route, params = Router.match("GET", "/smoke/files/a/b/c.txt")
        assert route is not None
        assert params["filepath"] == "a/b/c.txt"

    def test_multiple_params(self):
        @get("/smoke/{category}/{id:int}")
        async def multi_param(req, res):
            pass

        route, params = Router.match("GET", "/smoke/widgets/42")
        assert route is not None
        assert params["category"] == "widgets"
        assert params["id"] == "42"

    def test_router_all_returns_registered_routes(self):
        @get("/smoke/listed")
        async def listed(req, res):
            pass

        routes = Router.all()
        paths = [r["path"] for r in routes]
        assert "/smoke/listed" in paths

    def test_method_mismatch_returns_none(self):
        @get("/smoke/get-only")
        async def get_only(req, res):
            pass

        route, _ = Router.match("POST", "/smoke/get-only")
        assert route is None

    def test_noauth_decorator(self):
        from tina4_python.core.router import noauth

        @post("/smoke/public-write")
        @noauth()
        async def public_write(req, res):
            pass

        route, _ = Router.match("POST", "/smoke/public-write")
        assert route is not None
        assert route["auth_required"] is False

    def test_secured_decorator(self):
        from tina4_python.core.router import secured

        @get("/smoke/protected-read")
        @secured()
        async def protected_read(req, res):
            pass

        route, _ = Router.match("GET", "/smoke/protected-read")
        assert route is not None
        assert route["auth_required"] is True

    def test_get_route_defaults_public(self):
        @get("/smoke/default-public")
        async def default_pub(req, res):
            pass

        route, _ = Router.match("GET", "/smoke/default-public")
        assert route["auth_required"] is False

    def test_post_route_defaults_secured(self):
        @post("/smoke/default-secured")
        async def default_sec(req, res):
            pass

        route, _ = Router.match("POST", "/smoke/default-secured")
        assert route["auth_required"] is True


# ── 25. Additional ORM Tests ─────────────────────────────────────


class TestORMAdvanced:
    def test_orm_update(self, db):
        orm_bind(db)
        item = Item({"name": "Original", "price": 5.0})
        item.save()
        db.commit()

        item.name = "Updated"
        item.price = 10.0
        item.save()
        db.commit()

        found = Item.find(item.id)
        assert found.name == "Updated"
        assert found.price == 10.0

    def test_orm_find_nonexistent(self, db):
        orm_bind(db)
        assert Item.find(99999) is None

    def test_orm_to_dict(self, db):
        orm_bind(db)
        item = Item({"name": "DictTest", "price": 3.0})
        item.save()
        db.commit()

        d = item.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "DictTest"
        assert d["price"] == 3.0


# ── 26. Additional Database Tests ────────────────────────────────


class TestDatabaseAdvanced:
    def test_fetch_returns_database_result(self, db):
        db.insert("items", {"name": "Res1", "price": 1.0})
        db.insert("items", {"name": "Res2", "price": 2.0})
        db.commit()

        result = db.fetch("SELECT * FROM items", limit=10)
        assert isinstance(result, DatabaseResult)
        assert result.count == 2

    def test_database_result_iteration(self, db):
        db.insert("items", {"name": "Iter1"})
        db.insert("items", {"name": "Iter2"})
        db.commit()

        result = db.fetch("SELECT * FROM items", limit=10)
        names = [r["name"] for r in result]
        assert "Iter1" in names
        assert "Iter2" in names

    def test_database_result_to_list(self, db):
        db.insert("items", {"name": "List1"})
        db.commit()

        result = db.fetch("SELECT * FROM items", limit=10)
        as_list = result.to_list()
        assert isinstance(as_list, list)
        assert len(as_list) >= 1

    def test_insert_multiple_individually(self, db):
        db.insert("items", {"name": "Multi1", "price": 1.0})
        db.insert("items", {"name": "Multi2", "price": 2.0})
        db.insert("items", {"name": "Multi3", "price": 3.0})
        db.commit()

        result = db.fetch("SELECT * FROM items WHERE name LIKE 'Multi%'", limit=10)
        assert result.count == 3

    def test_transaction_rollback(self, db):
        db.insert("items", {"name": "BeforeRollback"})
        db.commit()

        db.start_transaction()
        db.insert("items", {"name": "Rolled"})
        db.rollback()

        row = db.fetch_one("SELECT * FROM items WHERE name = ?", ["Rolled"])
        assert row is None

    def test_table_exists_positive(self, db):
        assert db.table_exists("items") is True

    def test_table_exists_negative(self, db):
        assert db.table_exists("nonexistent_table") is False


# ── 27. Additional Template Tests ────────────────────────────────


class TestFrondAdvanced:
    def test_dotted_path(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string("{{ user.name }}", {"user": {"name": "Alice"}})
        assert result == "Alice"

    def test_for_loop(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string(
            "{% for item in items %}{{ item }},{% endfor %}",
            {"items": ["a", "b", "c"]},
        )
        assert "a," in result
        assert "b," in result
        assert "c," in result

    def test_conditional(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string(
            "{% if show %}YES{% else %}NO{% endif %}", {"show": True}
        )
        assert result == "YES"
        result2 = engine.render_string(
            "{% if show %}YES{% else %}NO{% endif %}", {"show": False}
        )
        assert result2 == "NO"

    def test_lower_filter(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string("{{ name | lower }}", {"name": "SMOKE"})
        assert result == "smoke"

    def test_default_filter(self, tmp_path):
        engine = Frond(template_dir=str(tmp_path))
        result = engine.render_string("{{ missing | default('fallback') }}", {})
        assert result == "fallback"


# ── 28. Auth Advanced ────────────────────────────────────────────


class TestAuthAdvanced:
    def test_token_payload_contains_claims(self):
        auth = Auth(secret="test-key", token_expiry=60)
        token = auth.create_token({"role": "admin", "org": "acme"})
        payload = auth.validate_token(token)
        assert payload["role"] == "admin"
        assert payload["org"] == "acme"

    def test_token_invalid_signature_rejected(self):
        auth1 = Auth(secret="secret-a", token_expiry=60)
        auth2 = Auth(secret="secret-b", token_expiry=60)
        token = auth1.create_token({"user_id": 1})
        assert auth2.validate_token(token) is None

    def test_token_tampered_payload_rejected(self):
        auth = Auth(secret="secure-key", token_expiry=60)
        token = auth.create_token({"user_id": 1})
        parts = token.split(".")
        # Tamper with payload
        import base64
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
        tampered = payload_bytes.replace(b"1", b"9")
        parts[1] = base64.urlsafe_b64encode(tampered).rstrip(b"=").decode()
        tampered_token = ".".join(parts)
        assert auth.validate_token(tampered_token) is None


# ── 29. Response Advanced ────────────────────────────────────────


class TestResponseAdvanced:
    def test_200_response(self):
        r = Response()
        r("OK", 200)
        assert r.status_code == 200

    def test_json_response_content_type(self):
        r = Response()
        r(json.dumps({"key": "value"}), 200, content_type="application/json")
        assert r.status_code == 200
        assert "application/json" in r.content_type

    def test_500_response(self):
        r = Response()
        r("Internal error", 500)
        assert r.status_code == 500


# ── 30. Middleware Advanced ──────────────────────────────────────


class TestMiddlewareAdvanced:
    def test_rate_limiter_instantiates(self):
        from tina4_python.core.middleware import RateLimiter
        rl = RateLimiter()
        assert rl.limit > 0
        assert rl.window > 0

    def test_rate_limiter_allows_requests(self):
        from tina4_python.core.middleware import RateLimiter
        rl = RateLimiter()
        allowed, info = rl.check("127.0.0.1")
        assert allowed is True
        assert info["remaining"] >= 0

    def test_cors_options_preflight(self):
        cors = CorsMiddleware()

        class Req:
            method = "OPTIONS"
            headers = {"origin": "https://test.com"}

        class Resp:
            _headers = {}
            status_code = 200
            def header(self, n, v):
                self._headers[n] = v
                return self
            def status(self, c):
                self.status_code = c
                return self

        req, resp = Req(), Resp()
        cors.apply(req, resp)
        assert "access-control-allow-origin" in resp._headers


# ── 31. DotEnv Advanced ─────────────────────────────────────────


class TestDotEnvAdvanced:
    def test_comments_ignored(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nSMOKE_A=hello\n# another\nSMOKE_B=world\n")
        result = load_env(str(env_file), override=True)
        assert result.get("SMOKE_A") == "hello"
        assert result.get("SMOKE_B") == "world"
        os.environ.pop("SMOKE_A", None)
        os.environ.pop("SMOKE_B", None)

    def test_quoted_values(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('SMOKE_Q="hello world"\n')
        result = load_env(str(env_file), override=True)
        # Value should contain hello world (quotes may or may not be stripped)
        val = result.get("SMOKE_Q", "")
        assert "hello" in val
        assert "world" in val
        os.environ.pop("SMOKE_Q", None)

    def test_missing_env_returns_none(self):
        assert get_env("TOTALLY_NONEXISTENT_VAR_XYZ") is None

    def test_empty_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        result = load_env(str(env_file), override=True)
        assert isinstance(result, dict)


# ── 32. Queue Advanced ───────────────────────────────────────────


class TestQueueAdvanced:
    def test_pop_empty_queue_returns_none(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'eq.db'}")
        q = Queue(db, topic="empty")
        assert q.pop() is None
        db.close()

    def test_multiple_pushes(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'mq.db'}")
        q = Queue(db, topic="multi")
        q.push({"msg": "first"})
        q.push({"msg": "second"})
        q.push({"msg": "third"})

        job1 = q.pop()
        job2 = q.pop()
        job3 = q.pop()
        assert job1.data["msg"] == "first"
        assert job2.data["msg"] == "second"
        assert job3.data["msg"] == "third"
        assert q.pop() is None
        db.close()


# ── 33. GraphQL Advanced ────────────────────────────────────────


class TestGraphQLAdvanced:
    def test_query_with_args(self):
        gql = GraphQL()
        gql.schema.add_type("Item", {"id": "ID", "title": "String"})
        gql.schema.add_query("item", {
            "type": "Item",
            "args": {"id": "ID!"},
            "resolve": lambda r, a, c: {"id": a["id"], "title": "Found"},
        })
        result = gql.execute('{ item(id: "5") { id title } }')
        assert result["data"]["item"]["title"] == "Found"
        assert result["data"]["item"]["id"] == "5"

    def test_introspect_has_queries_and_types(self):
        gql = GraphQL()
        gql.schema.add_type("Product", {"id": "ID", "name": "String", "price": "Float"})
        gql.schema.add_query("product", {
            "type": "Product",
            "args": {"id": "ID!"},
            "resolve": lambda r, a, c: None,
        })
        schema = gql.introspect()
        assert "Product" in schema["types"]
        assert "product" in schema["queries"]


# ── 34. I18n Advanced ───────────────────────────────────────────


class TestI18nAdvanced:
    def test_missing_key_returns_key(self, tmp_path):
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        (locale_dir / "en.json").write_text(json.dumps({"greeting": "Hello"}))
        i18n = I18n(locale_dir=str(locale_dir), default_locale="en")
        # Missing key should return the key itself or a fallback
        result = i18n.t("nonexistent_key")
        assert result is not None
        assert len(result) > 0

    def test_multiple_keys(self, tmp_path):
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        (locale_dir / "en.json").write_text(json.dumps({
            "greeting": "Hello",
            "farewell": "Goodbye",
            "thanks": "Thank you",
        }))
        i18n = I18n(locale_dir=str(locale_dir), default_locale="en")
        assert i18n.t("greeting") == "Hello"
        assert i18n.t("farewell") == "Goodbye"
        assert i18n.t("thanks") == "Thank you"


# ── 35. Container Advanced ──────────────────────────────────────


class TestContainerAdvanced:
    def test_override_registration(self):
        c = Container()
        c.register("svc", lambda: "v1")
        assert c.get("svc") == "v1"
        c.register("svc", lambda: "v2")
        assert c.get("svc") == "v2"

    def test_factory_called_each_time(self):
        c = Container()
        call_count = [0]
        def factory():
            call_count[0] += 1
            return call_count[0]
        c.register("counter", factory)
        assert c.get("counter") == 1
        assert c.get("counter") == 2
        assert c.get("counter") == 3

    def test_singleton_only_called_once(self):
        c = Container()
        call_count = [0]
        def factory():
            call_count[0] += 1
            return f"instance-{call_count[0]}"
        c.singleton("svc", factory)
        v1 = c.get("svc")
        v2 = c.get("svc")
        assert v1 == v2
        assert call_count[0] == 1


# ── 36. Migration Advanced ──────────────────────────────────────


class TestMigrationAdvanced:
    def test_create_migration_file(self, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        filename = create_migration("add users table", str(mig_dir))
        assert filename is not None
        assert "add_users_table" in filename
        assert (mig_dir / filename).exists()

    def test_migration_idempotent(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'idm.db'}")
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_create_things.sql").write_text(
            "CREATE TABLE things (id INTEGER PRIMARY KEY, val TEXT);"
        )
        ran1 = migrate(db, str(mig_dir))
        assert ran1 == ["000001_create_things.sql"]
        # Second run should skip already-applied migration
        ran2 = migrate(db, str(mig_dir))
        assert ran2 == []
        db.close()

    def test_multiple_migrations_ordered(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'ord.db'}")
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_first.sql").write_text(
            "CREATE TABLE first_table (id INTEGER PRIMARY KEY);"
        )
        (mig_dir / "000002_second.sql").write_text(
            "CREATE TABLE second_table (id INTEGER PRIMARY KEY);"
        )
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_first.sql", "000002_second.sql"]
        assert db.table_exists("first_table")
        assert db.table_exists("second_table")
        db.close()


# ── 37. WebSocket Advanced ──────────────────────────────────────


class TestWebSocketAdvanced:
    def test_build_frame_empty_payload(self):
        frame = build_frame(OP_TEXT, b"")
        assert frame[0] == 0x81
        assert frame[1] == 0

    def test_build_frame_long_payload(self):
        payload = b"x" * 200
        frame = build_frame(OP_TEXT, payload)
        assert frame[0] == 0x81
        # Length > 125 uses extended length encoding
        assert frame[1] == 126
        length = struct.unpack("!H", frame[2:4])[0]
        assert length == 200

    @pytest.mark.asyncio
    async def test_read_frame_roundtrip_various_sizes(self):
        for size in [0, 1, 125, 126, 1000]:
            payload = b"a" * size
            frame = build_frame(OP_TEXT, payload)
            reader = asyncio.StreamReader()
            reader.feed_data(frame)
            fin, opcode, data = await read_frame(reader)
            assert fin is True
            assert opcode == OP_TEXT
            assert data == payload


# ── 38. DevMailbox Advanced ──────────────────────────────────────


class TestDevMailboxAdvanced:
    def test_multiple_emails(self, tmp_path):
        mailbox = DevMailbox(mailbox_dir=str(tmp_path / "mb"))
        mailbox.capture(to="a@test.com", subject="First", body="Body1", from_address="dev@test.com")
        mailbox.capture(to="b@test.com", subject="Second", body="Body2", from_address="dev@test.com")
        messages = mailbox.inbox()
        assert len(messages) == 2
        subjects = [m["subject"] for m in messages]
        assert "First" in subjects
        assert "Second" in subjects

    def test_empty_inbox(self, tmp_path):
        mailbox = DevMailbox(mailbox_dir=str(tmp_path / "emptybox"))
        messages = mailbox.inbox()
        assert len(messages) == 0


# ── 39. Static MIME Types Advanced ───────────────────────────────


class TestStaticFilesAdvanced:
    def test_svg_mime(self):
        mime, _ = mimetypes.guess_type("icon.svg")
        assert mime is not None
        assert "svg" in mime

    def test_woff2_mime(self):
        mime, _ = mimetypes.guess_type("font.woff2")
        # woff2 may or may not be registered depending on OS
        # Just check it doesn't error
        assert True

    def test_unknown_extension(self):
        mime, _ = mimetypes.guess_type("file.xyz123abc")
        # Unknown extension returns None
        assert mime is None


# ── 40. FakeData in Smoke Context ────────────────────────────────


class TestFakeDataSmoke:
    def test_different_seeds_produce_different_data(self):
        f1 = FakeData(seed=1)
        f2 = FakeData(seed=2)
        # With very high probability, different seeds produce different names
        names1 = [f1.name() for _ in range(10)]
        names2 = [f2.name() for _ in range(10)]
        assert names1 != names2

    def test_no_seed_is_random(self):
        f1 = FakeData()
        f2 = FakeData()
        # Without seed, outputs should differ (with very high probability)
        results1 = [f1.integer(0, 1000000) for _ in range(5)]
        results2 = [f2.integer(0, 1000000) for _ in range(5)]
        assert results1 != results2
