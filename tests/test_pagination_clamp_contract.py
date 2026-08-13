# PAGE-DEC-01 pagination clamp + cap - feature 24 (pagination_contract.json).
#
# The audit's PAGE-NEGATIVE-OFFSET finding: `page < 1` was NOT clamped in the
# AutoCrud list handler, so `offset = (page - 1) * per_page` handed the driver a
# NEGATIVE offset - a hard ERROR on PostgreSQL ("OFFSET must not be negative")
# and a silent 0-offset on SQLite (still wrong: the envelope reported page:0).
# PAGE-NO-MAX-LIMIT: an oversized ?limit=/?per_page= was honoured verbatim - a
# client could request the whole table in one query.
#
# PAGE-DEC-01 (OWNER-DECISIONS.md Batch 4): clamp page >= 1 (so offset is never
# negative) and cap the per-page size at MAX_PER_PAGE (100 - the same row cap
# ORM.all()/db.fetch() already default to, and Node's own DEFAULT_ROW_CAP).
#
# Real SQLite (always) + real PostgreSQL :55432 tina4/tina4 (when reachable,
# TINA4_TEST_PG_* to relocate) through the REAL AutoCrud list handler via
# TestClient -> the real ASGI front controller. No mocks. The page=0 case is
# the one that matters on PostgreSQL: before the fix it is a genuine driver
# ERROR, not just a wrong number.
#
# Mutation-proof (manual): revert the `page = max(1, page)` clamp in
# tina4_python/crud/__init__.py and `test_page_zero_clamps_to_page_one`'s
# postgres parametrisation goes RED with "OFFSET must not be negative" surfaced
# through the response; restore the clamp and it is GREEN again.
import os
import socket

import pytest

from tina4_python.crud import AutoCrud
from tina4_python.core.router import Router
from tina4_python.database import Database
from tina4_python.orm.model import ORM, bind_database
import tina4_python.orm.model as orm_model
from tina4_python.orm.fields import IntegerField, StringField
from tina4_python.test_client import TestClient


def _pg_url() -> str:
    host = os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1")
    port = os.environ.get("TINA4_TEST_PG_PORT", "55432")
    user = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
    pwd = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
    name = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


def _pg_reachable() -> bool:
    host = os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1")
    port = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


_DB_PARAMS = ["sqlite"]
if _pg_reachable():
    _DB_PARAMS.append("postgres")


@pytest.fixture(autouse=True)
def clear_state():
    Router.clear()
    AutoCrud.clear()
    yield
    Router.clear()
    AutoCrud.clear()
    orm_model._database = None


@pytest.fixture(params=_DB_PARAMS)
def db(request, tmp_path):
    """A real, bound Database with a fresh `page_clamp_widget` table.

    Parametrised over SQLite (always) and PostgreSQL (when TINA4_TEST_PG_HOST
    is reachable) so the negative-offset proof runs against the engine that
    actually rejects it.
    """
    if request.param == "sqlite":
        database = Database(f"sqlite:///{tmp_path}/pageclamp.db")
    else:
        database = Database(_pg_url())

    database.execute("DROP TABLE IF EXISTS page_clamp_widget")
    database.commit()
    bind_database(database)
    yield database

    try:
        database.execute("DROP TABLE IF EXISTS page_clamp_widget")
        database.commit()
    except Exception:
        pass
    database.close()


def _make_model():
    class PageClampWidget(ORM):
        table_name = "page_clamp_widget"
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField(required=True)

    return PageClampWidget


def test_page_zero_clamps_to_page_one(db):
    """page=0 (or negative) never produces a negative offset to the driver.

    Before PAGE-DEC-01 this was a hard error on PostgreSQL and a silent-wrong
    envelope (page:0) on SQLite. After the fix, both engines return 200 with
    page:1, offset:0 - the full row set, never truncated.
    """
    Widget = _make_model()
    Widget.create_table()
    db.commit()
    db.insert("page_clamp_widget", [{"name": f"w{i}"} for i in range(5)])
    db.commit()
    AutoCrud.register(Widget)

    for bad_page in ("0", "-3"):
        resp = TestClient().get(f"/api/page_clamp_widget?page={bad_page}&per_page=10")
        assert resp.status == 200, (
            f"page={bad_page} must not error (got {resp.status}): {resp.text()}"
        )
        body = resp.json()
        assert body["page"] == 1, f"page={bad_page} -> envelope page {body['page']}, want 1"
        assert body["offset"] == 0, f"page={bad_page} -> envelope offset {body['offset']}, want 0"
        assert len(body["records"]) == 5


def test_oversized_per_page_is_capped(db):
    """An oversized ?per_page=/?limit= is capped at MAX_PER_PAGE (100) - the
    envelope's per_page/limit report the CAP, never the requested huge value."""
    Widget = _make_model()
    Widget.create_table()
    db.commit()
    db.insert("page_clamp_widget", [{"name": f"w{i}"} for i in range(5)])
    db.commit()
    AutoCrud.register(Widget)

    resp = TestClient().get("/api/page_clamp_widget?per_page=1000000")
    assert resp.status == 200
    body = resp.json()
    assert body["per_page"] == 100, f"got per_page={body['per_page']}"
    assert body["limit"] == 100, f"got limit={body['limit']}"

    # The alternate ?limit= spelling (no ?page=) takes the same cap.
    resp2 = TestClient().get("/api/page_clamp_widget?limit=999999")
    assert resp2.status == 200
    body2 = resp2.json()
    assert body2["limit"] == 100, f"got limit={body2['limit']}"
    assert body2["per_page"] == 100, f"got per_page={body2['per_page']}"
