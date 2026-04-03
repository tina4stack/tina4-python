# Tests for bugs reported in GitHub issue #106.
import os
import pytest
from tina4_python.core.router import Router, get, _routes
from tina4_python.core.request import Request
from tina4_python.database import Database
from tina4_python.database.adapter import DatabaseResult


@pytest.fixture(autouse=True)
def clean_routes():
    """Clear route registry before and after each test."""
    Router.clear()
    yield
    Router.clear()


# ── 1. Wildcard param key is "*" ─────────────────────────────────

class TestWildcardParamKey:
    def test_wildcard_param_uses_star_key(self):
        """Route '/docs/*' should capture remaining path under params['*']."""
        async def handler(request, response):
            pass

        Router.get("/docs/*", handler)
        route, params = Router.match("GET", "/docs/hello/world")

        assert route is not None, "Route should match /docs/hello/world"
        assert "*" in params, "Params should contain '*' key for wildcard"
        assert params["*"] == "hello/world"

    def test_wildcard_no_named_wildcard_key(self):
        """Wildcard should NOT produce a 'wildcard' key in params."""
        async def handler(request, response):
            pass

        Router.get("/api/files/*", handler)
        _, params = Router.match("GET", "/api/files/a/b/c")

        assert "wildcard" not in params
        assert params["*"] == "a/b/c"


# ── 2. Router.group accessible ───────────────────────────────────

class TestRouterGroup:
    def test_group_is_callable(self):
        assert callable(Router.group)

    def test_group_registers_routes_with_prefix(self):
        async def users_handler(request, response):
            pass

        async def items_handler(request, response):
            pass

        Router.group("/api", lambda group: [
            group.get("/users", users_handler),
            group.post("/items", items_handler),
        ])

        route, _ = Router.match("GET", "/api/users")
        assert route is not None, "GET /api/users should be registered"

        route, _ = Router.match("POST", "/api/items")
        assert route is not None, "POST /api/items should be registered"

    def test_group_does_not_register_without_prefix(self):
        async def handler(request, response):
            pass

        Router.group("/v2", lambda group: [
            group.get("/health", handler),
        ])

        route, _ = Router.match("GET", "/health")
        assert route is None, "/health without prefix should not match"


# ── 3. Global exports ────────────────────────────────────────────

class TestGlobalExports:
    def test_route_decorators(self):
        from tina4_python import get, post, put, delete
        assert callable(get)
        assert callable(post)
        assert callable(put)
        assert callable(delete)

    def test_core_classes(self):
        from tina4_python import Database, Auth, Queue, Frond, Router, ORM
        assert Database is not None
        assert Auth is not None
        assert Queue is not None
        assert Frond is not None
        assert Router is not None
        assert ORM is not None

    def test_run_import(self):
        from tina4_python import run
        assert callable(run)


# ── 4. request.files populated for multipart ─────────────────────

class TestMultipartFiles:
    def _build_multipart_body(self, boundary, fields, files):
        """Build a multipart/form-data body from fields and files."""
        parts = []
        for name, value in fields.items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"\r\n"
                f"{value}\r\n"
            )
        for name, file_info in files.items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{file_info["filename"]}"\r\n'
                f'Content-Type: {file_info["type"]}\r\n'
                f"\r\n"
            )
            parts.append(None)  # placeholder for binary content
            parts.append(f"\r\n")
        parts.append(f"--{boundary}--\r\n")

        # Build bytes
        body = b""
        file_iter = iter(files.values())
        for part in parts:
            if part is None:
                body += next(file_iter)["content"]
            else:
                body += part.encode()
        return body

    def test_files_separated_from_body(self):
        boundary = "----TestBoundary123"
        fields = {"title": "My Document"}
        files = {
            "upload": {
                "filename": "test.txt",
                "type": "text/plain",
                "content": b"hello world",
            }
        }
        body = self._build_multipart_body(boundary, fields, files)
        content_type = f"multipart/form-data; boundary={boundary}"

        scope = {
            "method": "POST",
            "path": "/upload",
            "query_string": b"",
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
        req = Request.from_scope(scope, body)

        # Files should be in request.files
        assert "upload" in req.files
        assert req.files["upload"]["filename"] == "test.txt"
        assert req.files["upload"]["type"] == "text/plain"
        assert "content" in req.files["upload"]

        # Form fields should be in request.body, NOT the file
        assert isinstance(req.body, dict)
        assert req.body.get("title") == "My Document"
        assert "upload" not in req.body


# ── 5. to_paginate() slices correctly ────────────────────────────

class TestToPaginate:
    def test_page_2_of_50_records(self):
        records = [{"id": i, "name": f"item_{i}"} for i in range(50)]
        result = DatabaseResult(records=records, count=50)

        page = result.to_paginate(page=2, per_page=10)

        assert len(page["data"]) == 10
        assert page["data"][0]["id"] == 10
        assert page["data"][-1]["id"] == 19
        assert page["total"] == 50
        assert page["page"] == 2

    def test_last_page(self):
        records = [{"id": i} for i in range(50)]
        result = DatabaseResult(records=records, count=50)

        page = result.to_paginate(page=5, per_page=10)

        assert len(page["data"]) == 10

    def test_first_page(self):
        records = [{"id": i} for i in range(50)]
        result = DatabaseResult(records=records, count=50)

        page = result.to_paginate(page=1, per_page=10)

        assert page["page"] == 1


# ── 6. column_info() infers types ────────────────────────────────

class TestColumnInfoInference:
    def test_infers_integer_real_text(self):
        records = [
            {"id": 1, "price": 9.99, "name": "Widget", "extra": None},
        ]
        result = DatabaseResult(records=records, count=1)
        cols = result.column_info()

        col_map = {c["name"]: c for c in cols}

        assert col_map["id"]["type"] == "INTEGER"
        assert col_map["price"]["type"] == "REAL"
        assert col_map["name"]["type"] == "TEXT"
        # None falls back to TEXT, not UNKNOWN
        assert col_map["extra"]["type"] == "TEXT"

    def test_id_column_is_primary_key(self):
        records = [{"id": 1, "name": "test"}]
        result = DatabaseResult(records=records, count=1)
        cols = result.column_info()

        col_map = {c["name"]: c for c in cols}
        assert col_map["id"]["primary_key"] is True
        assert col_map["name"]["primary_key"] is False


# ── 7. Default fetch limit is 100 ────────────────────────────────

class TestDefaultFetchLimit:
    def test_fetch_default_limit_100(self, tmp_path):
        db_path = tmp_path / "limit_test.db"
        db = Database(f"sqlite:///{db_path}")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
        for i in range(150):
            db.execute("INSERT INTO items (id, val) VALUES (?, ?)", [i, f"v{i}"])
        db.commit()

        result = db.fetch("SELECT * FROM items")
        assert len(result.records) == 100, (
            f"Default fetch should return 100 rows, got {len(result.records)}"
        )

        db.close()


# ── 8. tina4.css served from framework public ────────────────────

class TestTina4CssExists:
    def test_tina4_css_exists(self):
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "tina4_python", "public", "css", "tina4.css",
        )
        assert os.path.isfile(css_path), f"tina4.css not found at {css_path}"

    def test_tina4_min_css_exists(self):
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "tina4_python", "public", "css", "tina4.min.css",
        )
        assert os.path.isfile(css_path), f"tina4.min.css not found at {css_path}"
