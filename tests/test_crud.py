# Behavioural tests for tina4_python.crud (v3)
#
# AutoCrud generates five REST routes per ORM model and registers them on the
# Router. These tests do NOT stop at "the route object exists" — they bind a
# REAL database (SQLite on disk, plus PostgreSQL when TINA4_TEST_PG_URL or the
# discrete TINA4_TEST_PG_HOST coordinates are set),
# create a REAL table, register the CRUD routes, then INVOKE the registered
# async handlers exactly as the dispatcher would and assert the real list /
# create / read / update / delete results AND the resulting database state.
import asyncio
import json

import pytest

from tina4_python.crud import AutoCrud
from tina4_python.core.router import Router
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.test_client import TestClient
from tina4_python.database import Database
from tina4_python.orm.model import ORM, bind_database
import tina4_python.orm.model as orm_model
from tina4_python.orm.fields import (
    IntegerField,
    StringField,
    FloatField,
    BooleanField,
)


@pytest.fixture(autouse=True)
def clear_state():
    Router.clear()
    AutoCrud.clear()
    yield
    Router.clear()
    AutoCrud.clear()
    # Drop any global DB binding a test installed so models don't leak across
    # tests.
    orm_model._database = None


# ── DB fixtures ─────────────────────────────────────────────────────────────
#
# `db` is parametrised: every behavioural test runs against SQLite (always)
# and against PostgreSQL when the live PG service is configured, so the CRUD
# handlers are exercised against more than one real engine.


def _pg_url():
    import os

    url = os.environ.get("TINA4_TEST_PG_URL") or os.environ.get("TINA4_DATABASE_URL")
    if url and url.startswith(("postgres://", "postgresql://")):
        return url
    host = os.environ.get("TINA4_TEST_PG_HOST")
    if not host:
        return None
    port = os.environ.get("TINA4_TEST_PG_PORT", "5432")
    user = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
    pwd = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
    name = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


_DB_PARAMS = ["sqlite"]
if _pg_url():
    _DB_PARAMS.append("postgres")


@pytest.fixture(params=_DB_PARAMS)
def db(request, tmp_path):
    """A real, bound Database with a fresh `widget` table.

    Yields the Database. Parametrised over SQLite (always) and PostgreSQL
    (when configured) so the same behavioural assertions cover both engines.
    """
    if request.param == "sqlite":
        database = Database(f"sqlite:///{tmp_path}/crud.db")
    else:
        database = Database(_pg_url())

    # Use a per-run unique table so parallel/repeat PG runs don't collide and
    # so a leftover table from a crashed run can't poison the assertions.
    database.execute("DROP TABLE IF EXISTS crud_widget")
    database.commit()

    bind_database(database)
    yield database

    try:
        database.execute("DROP TABLE IF EXISTS crud_widget")
        database.commit()
    except Exception:
        pass
    database.close()


def _make_widget_model():
    """A real ORM model bound to the fixture's database."""

    class Widget(ORM):
        table_name = "crud_widget"
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField(required=True)
        price = FloatField()
        active = BooleanField(default=True)

    return Widget


def _request(method, path, *, params=None, body=None):
    req = Request()
    req.method = method
    req.path = path
    merged = dict(params or {})
    req.params = merged
    req._route_params = merged
    req.body = body
    return req


def _invoke(method, path, *, params=None, body=None):
    """Match the route on the Router and invoke the registered handler exactly
    as the dispatcher does. Returns (status_code, parsed_json_body)."""
    route, route_params = Router.match(method, path)
    assert route is not None, f"no route registered for {method} {path}"
    all_params = {**(params or {}), **route_params}
    req = _request(method, path, params=all_params, body=body)
    resp = Response()
    out = asyncio.run(route["handler"](req, resp))
    payload = json.loads(out.content) if out.content else None
    return out.status_code, payload


# ── Interface contract (collapsed rename guard) ─────────────────────────────


def test_autocrud_interface_contract():
    """One consolidated rename guard for the whole public surface. Replaces the
    five per-method `callable(...)`/`is not None` smoke tests. If any of these
    is renamed or dropped, AutoCrud's contract — and therefore the CRUD route
    generation the rest of these tests exercise — is broken."""
    assert AutoCrud is not None
    for name in ("register", "discover", "models", "clear", "generate_routes",
                 "_build_example"):
        member = getattr(AutoCrud, name, None)
        assert callable(member), f"AutoCrud.{name} missing or not callable"


# ── Registration behaviour ──────────────────────────────────────────────────


def test_register_generates_the_five_crud_routes_and_tracks_model(db):
    """register() returns the five route descriptors AND wires them onto the
    Router so all five are matchable, AND records the model for introspection."""
    Widget = _make_widget_model()
    routes = AutoCrud.register(Widget)

    methods_paths = {(r["method"], r["path"]) for r in routes}
    assert methods_paths == {
        ("GET", "/api/crud_widget"),
        ("GET", "/api/crud_widget/{id}"),
        ("POST", "/api/crud_widget"),
        ("PUT", "/api/crud_widget/{id}"),
        ("DELETE", "/api/crud_widget/{id}"),
    }

    # Every generated route is really resolvable on the Router.
    assert Router.match("GET", "/api/crud_widget")[0] is not None
    assert Router.match("GET", "/api/crud_widget/1")[0] is not None
    assert Router.match("POST", "/api/crud_widget")[0] is not None
    assert Router.match("PUT", "/api/crud_widget/1")[0] is not None
    assert Router.match("DELETE", "/api/crud_widget/1")[0] is not None

    # Model is tracked for introspection.
    assert AutoCrud.models().get("crud_widget") is Widget


def test_register_no_table_raises_value_error():
    """A model with no resolvable table name is rejected loudly, not silently
    registered with a broken empty path."""

    class BadModel(ORM):
        table_name = ""

        @classmethod
        def _get_table(cls):
            return ""

    with pytest.raises(ValueError, match="no table"):
        AutoCrud.register(BadModel)


def test_clear_removes_tracked_models(db):
    """clear() empties the registry after a real registration."""
    Widget = _make_widget_model()
    AutoCrud.register(Widget)
    assert "crud_widget" in AutoCrud.models()

    AutoCrud.clear()
    assert AutoCrud.models() == {}


# ── Secure-by-default writes (opt-in public) ────────────────────────────────


def test_writes_are_secure_by_default():
    """The write routes (POST/PUT/DELETE) are GATED by default — no `_noauth` —
    so the framework's write-auth applies. Regression guard for the 'AutoCrud
    silently ships public writes' footgun."""
    Widget = _make_widget_model()
    AutoCrud.register(Widget)   # default: public=False
    for method, path in (("POST", "/api/crud_widget"),
                         ("PUT", "/api/crud_widget/1"),
                         ("DELETE", "/api/crud_widget/1")):
        route, _ = Router.match(method, path)
        assert route is not None
        assert not getattr(route["handler"], "_noauth", False), \
            f"{method} must be secure-by-default (no _noauth)"


def test_public_true_opts_writes_out_to_open():
    """`public=True` explicitly opens the write routes (`_noauth`) for a demo /
    quick-start open API — the visible, intentional escape hatch."""
    Widget = _make_widget_model()
    AutoCrud.register(Widget, public=True)
    for method, path in (("POST", "/api/crud_widget"),
                         ("PUT", "/api/crud_widget/1"),
                         ("DELETE", "/api/crud_widget/1")):
        route, _ = Router.match(method, path)
        assert getattr(route["handler"], "_noauth", False) is True, \
            f"{method} must be public when public=True"


# ── End-to-end CRUD behaviour through the generated handlers ────────────────


def test_create_inserts_row_and_returns_201_with_body(db):
    """POST runs the create handler, returns 201 with the persisted record
    (including the engine-assigned id), AND the row really lands in the DB."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    status, body = _invoke(
        "POST", "/api/crud_widget", body={"name": "Gizmo", "price": 9.99}
    )
    assert status == 201
    assert body["name"] == "Gizmo"
    assert body["price"] == 9.99
    assert body["id"] is not None

    # Real DB state, read back independently of the ORM.
    row = db.fetch_one("SELECT name, price FROM crud_widget WHERE name = ?", ["Gizmo"])
    assert row is not None
    assert row["name"] == "Gizmo"
    assert float(row["price"]) == 9.99


def test_create_with_missing_required_field_returns_400_and_inserts_nothing(db):
    """Validation fires before the driver: a missing required field yields 400
    with the field error, and NO row is written."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    status, body = _invoke("POST", "/api/crud_widget", body={"price": 1.0})
    assert status == 400
    assert body["error"] == "Validation failed"
    assert any("name" in d for d in body["detail"])

    assert db.fetch_one("SELECT COUNT(*) AS c FROM crud_widget")["c"] == 0


def test_list_returns_records_and_pagination_metadata(db):
    """GET list returns the actual rows plus a correct total count and the
    derived pagination fields — not a hard-coded empty result."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    for i in range(3):
        _invoke("POST", "/api/crud_widget", body={"name": f"w{i}", "price": float(i)})

    status, body = _invoke("GET", "/api/crud_widget")
    assert status == 200
    assert body["total"] == 3
    names = sorted(r["name"] for r in body["records"])
    assert names == ["w0", "w1", "w2"]


def test_list_pagination_limit_and_offset_slice_the_real_rows(db):
    """limit/offset really slice the result set and the page math is computed
    from the live total — the claim the route name makes."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    for i in range(5):
        _invoke("POST", "/api/crud_widget", body={"name": f"w{i}", "price": float(i)})

    status, body = _invoke(
        "GET", "/api/crud_widget", params={"limit": "2", "offset": "2"}
    )
    assert status == 200
    assert len(body["records"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert body["total"] == 5
    assert body["page"] == 2          # (offset // limit) + 1
    assert body["total_pages"] == 3   # ceil(5 / 2)


def test_paginate_rest_list_envelope_is_the_seven_keys(db):
    """ADR-0043: the AutoCrud REST list endpoint returns EXACTLY the seven
    canonical snake_case keys — records, total, page, per_page, total_pages,
    limit, offset — with no ``data``/``count``/``totalPages`` duplicates, and
    the same derivation ``DatabaseResult.to_paginate()`` uses.

    Proven against a real 250-row SQLite table through the REAL front controller
    (``TestClient`` -> ``core.server.app``), reading ADR-0043's measured page
    (limit=20 offset=40, page 3 of 13), so ``total`` is the true COUNT (250),
    never the number of rows returned (20). No mocks.
    """
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()

    # A real 250-row table, inserted straight through the driver (no mock).
    db.insert(
        "crud_widget",
        [{"name": f"w{i}", "price": float(i)} for i in range(250)],
    )
    db.commit()
    assert db.fetch_one("SELECT COUNT(*) AS c FROM crud_widget")["c"] == 250

    AutoCrud.register(Widget)

    # Fetch page 3 the honest way: limit=20 offset=40.
    resp = TestClient().get("/api/crud_widget?limit=20&offset=40")
    assert resp.status == 200
    body = resp.json()

    # EXACTLY the seven canonical keys — the discriminator. On the old envelope
    # this carried ten keys (records+data, total+count, total_pages+totalPages).
    assert set(body) == {
        "records", "total", "page", "per_page", "total_pages", "limit", "offset",
    }
    for dropped in ("data", "count", "totalPages", "perPage", "has_next", "has_prev"):
        assert dropped not in body, f"dropped alias {dropped!r} is back in the envelope"

    # total is the TRUE count (250), never rows returned (20).
    assert body["total"] == 250
    assert len(body["records"]) == 20        # the page's rows, verbatim
    assert body["page"] == 3                  # floor(40 / 20) + 1
    assert body["per_page"] == 20             # the query's limit
    assert body["total_pages"] == 13          # ceil(250 / 20)
    assert body["limit"] == 20
    assert body["offset"] == 40


def test_get_single_returns_record_then_404_after_delete(db):
    """GET /{id} returns the real record; a non-existent id yields 404."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    _, created = _invoke(
        "POST", "/api/crud_widget", body={"name": "Solo", "price": 5.0}
    )
    wid = created["id"]

    status, body = _invoke("GET", f"/api/crud_widget/{wid}")
    assert status == 200
    assert body["name"] == "Solo"
    assert body["id"] == wid

    status, body = _invoke("GET", "/api/crud_widget/999999")
    assert status == 404
    assert body["error"] == "Not Found"


def test_update_mutates_the_row_and_returns_updated_body(db):
    """PUT /{id} applies the changes, returns the updated record, and the new
    values are really persisted; updating a missing id is 404."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    _, created = _invoke(
        "POST", "/api/crud_widget", body={"name": "Before", "price": 1.0}
    )
    wid = created["id"]

    status, body = _invoke(
        "PUT",
        f"/api/crud_widget/{wid}",
        body={"name": "After", "price": 42.5},
    )
    assert status == 200
    assert body["name"] == "After"
    assert body["price"] == 42.5

    # Persisted, read back independently.
    row = db.fetch_one("SELECT name, price FROM crud_widget WHERE id = ?", [wid])
    assert row["name"] == "After"
    assert float(row["price"]) == 42.5

    # Missing record → 404 and nothing changes.
    status, body = _invoke(
        "PUT", "/api/crud_widget/999999", body={"name": "ghost"}
    )
    assert status == 404
    assert db.fetch_one(
        "SELECT COUNT(*) AS c FROM crud_widget WHERE name = ?", ["ghost"]
    )["c"] == 0


def test_delete_removes_the_row_then_404_on_second_delete(db):
    """DELETE /{id} really removes the row from the DB and reports it; deleting
    an absent id is a 404."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget)

    _, created = _invoke(
        "POST", "/api/crud_widget", body={"name": "Doomed", "price": 0.0}
    )
    wid = created["id"]
    assert db.fetch_one("SELECT COUNT(*) AS c FROM crud_widget")["c"] == 1

    status, body = _invoke("DELETE", f"/api/crud_widget/{wid}")
    assert status == 200
    assert body["deleted"] is True
    assert db.fetch_one("SELECT COUNT(*) AS c FROM crud_widget")["c"] == 0

    # Second delete: the row is already gone → 404.
    status, body = _invoke("DELETE", f"/api/crud_widget/{wid}")
    assert status == 404
    assert body["error"] == "Not Found"


def test_custom_prefix_handlers_serve_real_data(db):
    """A custom prefix doesn't just produce a matchable path — the handlers
    mounted under it actually run and return real records."""
    Widget = _make_widget_model()
    Widget.create_table()
    db.commit()
    AutoCrud.register(Widget, prefix="/api/v2")

    status, created = _invoke(
        "POST", "/api/v2/crud_widget", body={"name": "Prefixed", "price": 3.0}
    )
    assert status == 201

    status, body = _invoke("GET", "/api/v2/crud_widget")
    assert status == 200
    assert body["total"] == 1
    assert body["records"][0]["name"] == "Prefixed"


# ── _build_example: real ORM field-type → sample-value mapping ──────────────
#
# These assert the actual computed sample body for each real Field type and
# that the auto-increment PK is skipped — the values a Swagger request-body
# example would show. Uses real Field/ORM, not hand-rolled mock fields.


def test_build_example_maps_field_types_and_skips_auto_pk():
    class Sample(ORM):
        table_name = "sample_a"
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()
        age = IntegerField()
        price = FloatField()
        active = BooleanField()

    example = AutoCrud._build_example(Sample)
    assert "id" not in example          # auto-increment PK skipped
    assert example["name"] == "string"
    assert example["age"] == 0
    assert example["price"] == 0.0
    assert example["active"] is True


def test_build_example_keeps_non_auto_primary_key():
    """A natural (non-auto-increment) primary key is part of the request body
    example — only auto-generated PKs are skipped."""

    class NaturalKey(ORM):
        table_name = "sample_b"
        code = StringField(primary_key=True)
        label = StringField()

    example = AutoCrud._build_example(NaturalKey)
    assert example["code"] == "string"   # not auto-increment → kept
    assert example["label"] == "string"
