# Shared contract suite for feature 27 -- AutoCrud (REST from ORM models).
#
# Fixture: tina4-documentation/plan/v3/fixtures/autocrud_contract.json
# Decisions: CRUD-DEC-01 (a consistent 422 with field errors on an invalid
# create/update, plus PUT partial-update validation) + CRUD-DEC-02 (allow-list
# writable columns -- guard is_deleted, strip the PK on create -- and add wire
# tests).
#
# NO MOCKS. Every case boots a REAL server (uvicorn -- the production ASGI
# server tina4 ships, not a dev shortcut -- in a child process), with a REAL
# AutoCrud-registered model on a REAL SQLite database, driven over REAL HTTP
# (urllib, a genuine TCP socket) with a REAL JWT minted by
# ``tina4_python.auth.get_token``. One server is booted ONCE per module and
# shared by every case below; DB state is asserted by reading the SQLite file
# directly, independent of the ORM.
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SECRET = "autocrud-contract-test-secret"


def _free_port() -> int:
    """A port free right now -- the child binds it a moment later (small race, fine for a test)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# The child app: a real AutoCrud-registered model (soft-delete enabled, so
# is_deleted is a genuine declared column -- the worst case for
# CRUD-MASS-ASSIGNMENT) served by real uvicorn. Secure-by-default (no
# public=True), so every write route requires the minted token.
_CHILD_APP = '''\
import os

from tina4_python.database import Database
from tina4_python.orm.model import ORM, bind_database
from tina4_python.orm.fields import IntegerField, StringField
from tina4_python.crud import AutoCrud
from tina4_python.auth import get_token

db = Database(f"sqlite:///{os.environ['CRUD_DB_PATH']}")
bind_database(db)


class CrudItem(ORM):
    table_name = "crud_item"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True, max_length=20)
    is_deleted = IntegerField(default=0)


CrudItem.create_table()
AutoCrud.register(CrudItem)  # public=False -- secure-by-default

with open(os.environ["CRUD_TOKEN_FILE"], "w") as fh:
    fh.write(get_token({"sub": "autocrud-contract-tester"}, expires_in=60))

from tina4_python.core.server import app
import uvicorn

uvicorn.run(app, host="127.0.0.1", port=int(os.environ["CRUD_PORT"]), log_level="warning")
'''


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """One real server for the whole module -- real uvicorn, real SQLite, a
    real AutoCrud-registered model, a real minted JWT -- shared by every wire
    case below (no mocks anywhere in this chain)."""
    tmp_path = tmp_path_factory.mktemp("autocrud_contract")
    db_path = tmp_path / "autocrud.db"
    token_file = tmp_path / "token.txt"
    script = tmp_path / "child_app.py"
    script.write_text(_CHILD_APP)
    port = _free_port()

    env = {
        **os.environ,
        "CRUD_DB_PATH": str(db_path),
        "CRUD_TOKEN_FILE": str(token_file),
        "CRUD_PORT": str(port),
        "TINA4_SECRET": _SECRET,
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_DEBUG": "false",
    }
    proc = subprocess.Popen([sys.executable, str(script)], cwd=REPO_ROOT, env=env)
    try:
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            if token_file.exists():
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        ready = True
                        break
                except OSError:
                    pass
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert ready, (
            f"autocrud contract child server never became ready "
            f"(exit={proc.poll()})"
        )
        token = token_file.read_text().strip()
        yield {"base": f"http://127.0.0.1:{port}", "token": token, "db_path": str(db_path)}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _request(server, method, path, *, body=None, token=None):
    """A REAL HTTP round trip over a genuine TCP socket -- no in-process shortcut."""
    url = server["base"] + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def _row_count(db_path, *, where=None):
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        sql = "SELECT COUNT(*) FROM crud_item"
        if where:
            sql += f" WHERE {where}"
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def _fetch_row(db_path, item_id):
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM crud_item WHERE id = ?", (item_id,)).fetchone()
    finally:
        conn.close()


def test_tokenless_write_returns_401(server):
    """A POST/PUT/DELETE with NO token -> 401 (secure-by-default)."""
    status, _ = _request(server, "POST", "/api/crud_item", body={"name": "no-token"})
    assert status == 401

    status, _ = _request(server, "PUT", "/api/crud_item/1", body={"name": "no-token"})
    assert status == 401

    status, _ = _request(server, "DELETE", "/api/crud_item/1")
    assert status == 401


def test_valid_authenticated_post_returns_201(server):
    """A valid authenticated POST creates + returns 201."""
    status, body = _request(
        server, "POST", "/api/crud_item", body={"name": "widget-1"}, token=server["token"]
    )
    assert status == 201
    assert body["name"] == "widget-1"
    assert body["id"] is not None
    assert _fetch_row(server["db_path"], body["id"])["name"] == "widget-1"


def test_invalid_post_returns_422_with_field_errors(server):
    """An invalid body -> 422 with the field errors (CRUD-VALIDATION-STATUS)."""
    before = _row_count(server["db_path"])
    status, body = _request(server, "POST", "/api/crud_item", body={}, token=server["token"])
    assert status == 422
    assert body["error"] == "Validation failed"
    assert any("name" in d for d in body["detail"])
    assert _row_count(server["db_path"]) == before


def test_invalid_put_is_rejected(server):
    """A PUT with length-violating data -> 422 (CRUD-PUT-NOVALIDATE)."""
    status, created = _request(
        server, "POST", "/api/crud_item", body={"name": "put-target"}, token=server["token"]
    )
    assert status == 201
    item_id = created["id"]

    status, body = _request(
        server,
        "PUT",
        f"/api/crud_item/{item_id}",
        body={"name": "x" * 100},  # exceeds max_length=20
        token=server["token"],
    )
    assert status == 422
    assert body["error"] == "Validation failed"

    # Unchanged in the DB -- the invalid PUT never wrote through.
    assert _fetch_row(server["db_path"], item_id)["name"] == "put-target"


def test_mass_assignment_is_blocked(server):
    """A POST/PUT body carrying is_deleted (and a client-supplied PK on
    create) is rejected/stripped -- the guarded column is never written."""
    status, created = _request(
        server,
        "POST",
        "/api/crud_item",
        body={"name": "mass-assign", "is_deleted": 1, "id": 999999},
        token=server["token"],
    )
    assert status == 201
    # The client-supplied PK never won -- a fresh id was assigned, not an
    # overwrite of (or a no-op update reported as success for) row 999999.
    assert created["id"] != 999999
    item_id = created["id"]

    row = _fetch_row(server["db_path"], item_id)
    assert row is not None
    assert int(row["is_deleted"]) == 0

    status, body = _request(
        server,
        "PUT",
        f"/api/crud_item/{item_id}",
        body={"is_deleted": 1},
        token=server["token"],
    )
    assert status == 200

    row = _fetch_row(server["db_path"], item_id)
    assert int(row["is_deleted"]) == 0


def test_list_is_the_seven_key_envelope(server):
    """The list route returns the ADR-0043 7-key envelope with a true COUNT."""
    status, body = _request(server, "GET", "/api/crud_item")
    assert status == 200
    assert set(body) == {
        "records", "total", "page", "per_page", "total_pages", "limit", "offset",
    }
    assert body["total"] == _row_count(server["db_path"])
