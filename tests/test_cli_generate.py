"""Tests for CLI scaffolding generators."""
import ast
import asyncio
import importlib.util
import os
import shutil
import subprocess
import sys
import pytest
from pathlib import Path
from tina4_python.cli import (
    _parse_fields, _parse_flags, _to_snake, _to_table,
    _gen_model, _gen_route, _gen_migration, _gen_middleware,
    _gen_test, _gen_form, _gen_view, _gen_auth, _gen_crud,
    _gen_service, _gen_queue, _gen_validator, _gen_seeder,
    _gen_websocket, _gen_listener, _ai_fill, _extend, _parse_every,
    FIELD_TYPE_MAP, DEFAULT_FIELDS,
)
import tina4_python.cli as cli_module


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temp project directory, cd into it, and put it on sys.path so a
    generated file's `from src.orm.X import X` resolves to THIS project."""
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    sys.path.insert(0, str(tmp_path))
    yield tmp_path
    os.chdir(old_cwd)
    try:
        sys.path.remove(str(tmp_path))
    except ValueError:
        pass
    # Drop any `src.*` modules this test imported so the name can't resolve to a
    # previous tmp project on the next test.
    for mod in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
        del sys.modules[mod]


def _load_generated(path: Path, modname: str):
    """Import a generated file for real (no mocks) and return the module.

    Executes the module top-to-bottom, so decorator-based wiring (@websocket,
    @on) actually registers on the real Router / event bus, and a bad import
    raises ImportError here — proving the scaffold's imports resolve.
    """
    assert path.exists(), f"expected generated file at {path}"
    # Fresh-resolve any `src.*` imports (avoid a stale tmp binding).
    for mod in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
        del sys.modules[mod]
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_registry():
    """Clear the global Router / event bus / DB binding around a behavioural
    test so registrations and bindings never leak between tests."""
    from tina4_python.core.router import Router
    # core.events re-exports an `events()` fn that shadows the submodule attr, so
    # `import ... as ev` yields the function — import_module returns the module.
    ev = importlib.import_module("tina4_python.core.events")
    import tina4_python.orm.model as orm_model

    Router.clear()
    ev.clear()
    _prev_db = getattr(orm_model, "_database", None)
    yield
    Router.clear()
    ev.clear()
    orm_model._database = _prev_db


# ── Helper tests ──────────────────────────────────────────────────────

class TestHelpers:
    def test_parse_fields_basic(self):
        result = _parse_fields("name:string,price:float")
        assert result == [("name", "string"), ("price", "float")]

    def test_parse_fields_default_type(self):
        result = _parse_fields("name")
        assert result == [("name", "string")]

    def test_parse_fields_empty(self):
        assert _parse_fields("") == []
        assert _parse_fields(None) == []

    def test_parse_fields_multiple_types(self):
        result = _parse_fields("name:string,age:int,active:bool,price:float,bio:text")
        assert len(result) == 5
        assert result[3] == ("price", "float")

    def test_parse_flags(self):
        flags, pos = _parse_flags(["--fields", "name:string", "--model", "Product", "--no-migration"])
        assert flags["fields"] == "name:string"
        assert flags["model"] == "Product"
        assert flags["no-migration"] is True
        assert pos == []

    def test_parse_flags_positional(self):
        flags, pos = _parse_flags(["Product", "--fields", "name:string"])
        assert flags["fields"] == "name:string"
        assert pos == ["Product"]

    def test_to_snake(self):
        assert _to_snake("Product") == "product"
        assert _to_snake("ProductCategory") == "product_category"
        assert _to_snake("HTMLParser") == "html_parser"
        assert _to_snake("simple") == "simple"

    def test_to_table(self):
        assert _to_table("Product") == "product"
        assert _to_table("OrderItem") == "order_item"

    def test_field_type_map_coverage(self):
        """Every field type should have orm and sql keys."""
        for key, info in FIELD_TYPE_MAP.items():
            assert "orm" in info, f"Missing orm for {key}"
            assert "sql" in info, f"Missing sql for {key}"
            assert "default" in info, f"Missing default for {key}"


# ── Model generator ──────────────────────────────────────────────────

class TestGenerateModel:
    def test_creates_model_file(self, tmp_project):
        _gen_model("Product", {})
        path = tmp_project / "src" / "orm" / "Product.py"
        assert path.exists()
        content = path.read_text()
        assert "class Product(ORM):" in content
        assert 'table_name = "product"' in content

    def test_creates_model_with_fields(self, tmp_project):
        _gen_model("Product", {"fields": "name:string,price:float,active:bool"})
        content = (tmp_project / "src" / "orm" / "Product.py").read_text()
        assert "StringField" in content
        assert "NumericField" in content
        assert "BooleanField" in content
        assert "name = StringField()" in content
        assert "price = NumericField()" in content

    def test_creates_migration(self, tmp_project):
        _gen_model("Product", {"fields": "name:string"})
        migrations = list((tmp_project / "migrations").glob("*.sql"))
        assert len(migrations) == 2  # .sql + .down.sql
        up = [m for m in migrations if not m.name.endswith(".down.sql")][0]
        content = up.read_text()
        assert "CREATE TABLE" in content
        assert "product" in content

    def test_no_migration_flag(self, tmp_project):
        _gen_model("Product", {"fields": "name:string", "no-migration": True})
        assert (tmp_project / "src" / "orm" / "Product.py").exists()
        migrations = list((tmp_project / "migrations").glob("*.sql"))
        assert len(migrations) == 0

    def test_refuses_overwrite(self, tmp_project):
        _gen_model("Product", {})
        # Second call should not crash (prints message, doesn't overwrite)
        _gen_model("Product", {})
        # File should still exist with original content
        assert (tmp_project / "src" / "orm" / "Product.py").exists()


# ── Route generator ──────────────────────────────────────────────────

class TestGenerateRoute:
    def test_creates_route_file(self, tmp_project):
        _gen_route("products", {})
        path = tmp_project / "src" / "routes" / "products.py"
        assert path.exists()
        content = path.read_text()
        assert "list_products" in content
        assert "get_product" in content
        assert "create_product" in content
        assert "update_product" in content
        assert "delete_product" in content

    def test_route_has_swagger(self, tmp_project):
        _gen_route("products", {})
        content = (tmp_project / "src" / "routes" / "products.py").read_text()
        assert "@description" in content
        assert "@tags" in content

    def test_route_with_model(self, tmp_project):
        _gen_route("products", {"model": "Product"})
        content = (tmp_project / "src" / "routes" / "products.py").read_text()
        assert "from src.orm.Product import Product" in content
        assert "Product.find_by_id" in content
        assert "Product.create" in content

    def test_route_without_model(self, tmp_project):
        # No --model → a custom route: every handler body is an AI-FILL stub
        # (raise NotImplementedError), not working code and not a public write.
        _gen_route("items", {})
        content = (tmp_project / "src" / "routes" / "items.py").read_text()
        assert "from src.orm.Item import" not in content  # no real model import
        assert "AI-FILL" in content
        assert "raise NotImplementedError" in content
        assert "@noauth" not in content  # secure by default


# ── Migration generator ──────────────────────────────────────────────

class TestGenerateMigration:
    def test_creates_migration_with_up_down(self, tmp_project):
        _gen_migration("create_product", {"fields": "name:string,price:float"})
        files = list((tmp_project / "migrations").glob("*.sql"))
        assert len(files) == 2
        up = [f for f in files if not f.name.endswith(".down.sql")][0]
        content = up.read_text()
        assert "name TEXT" in content
        assert "price REAL" in content

    def test_creates_down_file(self, tmp_project):
        _gen_migration("create_product", {})
        down = list((tmp_project / "migrations").glob("*.down.sql"))
        assert len(down) == 1
        assert "DROP TABLE" in down[0].read_text()

    def test_non_create_migration(self, tmp_project):
        _gen_migration("add_email_to_product", {})
        files = list((tmp_project / "migrations").glob("*add_email*.sql"))
        up = [f for f in files if not f.name.endswith(".down.sql")][0]
        content = up.read_text()
        assert "ALTER TABLE" in content or "add_email" in up.name  # migration exists

    def test_singular_table_name(self, tmp_project):
        _gen_migration("create_product", {"fields": "name:string"})
        up = [f for f in (tmp_project / "migrations").glob("*.sql") if not f.name.endswith(".down.sql")][0]
        content = up.read_text()
        assert "product" in content
        assert "products" not in content


# ── Middleware generator ──────────────────────────────────────────────

class TestGenerateMiddleware:
    def test_creates_middleware(self, tmp_project):
        _gen_middleware("AuthLog", {})
        path = tmp_project / "src" / "middleware" / "auth_log.py"
        assert path.exists()
        content = path.read_text()
        assert "class AuthLog:" in content
        assert "before_auth_log" in content
        assert "after_auth_log" in content

    def test_middleware_has_usage_doc(self, tmp_project):
        _gen_middleware("RateLimit", {})
        content = (tmp_project / "src" / "middleware" / "rate_limit.py").read_text()
        assert "@middleware" in content


# ── Test generator ────────────────────────────────────────────────────

class TestGenerateTest:
    def test_creates_test_file(self, tmp_project):
        _gen_test("products", {})
        path = tmp_project / "tests" / "test_products.py"
        assert path.exists()
        content = path.read_text()
        assert "class Test" in content
        assert "def test_example" in content

    def test_creates_test_with_model(self, tmp_project):
        _gen_test("products", {"model": "Product"})
        content = (tmp_project / "tests" / "test_products.py").read_text()
        assert "TestProduct" in content
        assert "test_list_products" in content
        assert "test_create_product" in content


# ── Form generator ────────────────────────────────────────────────────

class TestGenerateForm:
    def test_creates_form_template(self, tmp_project):
        _gen_form("Product", {"fields": "name:string,price:float,active:bool"})
        path = tmp_project / "src" / "templates" / "forms" / "product.twig"
        assert path.exists()
        content = path.read_text()
        assert "form_token()" in content
        assert 'type="text"' in content
        assert 'type="number"' in content
        assert 'type="checkbox"' in content
        assert 'step="0.01"' in content  # float gets step

    def test_form_has_edit_mode(self, tmp_project):
        _gen_form("Product", {"fields": "name:string"})
        content = (tmp_project / "src" / "templates" / "forms" / "product.twig").read_text()
        assert "item.id" in content  # edit/create detection

    def test_form_without_fields_uses_the_shared_default(self, tmp_project):
        """No --fields: the form's inputs must come from DEFAULT_FIELDS.

        _gen_form was the one generator the #101 fix missed: it kept its own
        inline [("name", "string")] fallback instead of routing through
        _fields_or_default. Same output today, but change DEFAULT_FIELDS and the
        form would render an input the model has no column for -> the POST 500s.
        """
        _gen_form("Todo", {})
        content = (tmp_project / "src" / "templates" / "forms" / "todo.twig").read_text()
        for fname, _ftype in DEFAULT_FIELDS:
            assert f'name="{fname}"' in content, \
                f"form omits the default field {fname!r}:\n{content}"

    def test_form_matches_the_models_own_fields(self, tmp_project):
        """The form and the model must agree — both derive from one default."""
        _gen_model("Todo", {})
        _gen_form("Todo", {})
        model_src = (tmp_project / "src" / "orm" / "Todo.py").read_text()
        form_src = (tmp_project / "src" / "templates" / "forms" / "todo.twig").read_text()
        tree = ast.parse(model_src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Todo")
        declared = {t.id for stmt in cls.body if isinstance(stmt, ast.Assign)
                    for t in stmt.targets
                    if isinstance(t, ast.Name) and not t.id.startswith("_")
                    and t.id not in ("table_name", "id", "created_at")}
        for field in declared:
            assert f'name="{field}"' in form_src, \
                f"model declares {field!r} but the form has no input for it:\n{form_src}"

    def test_the_default_field_literal_is_defined_exactly_once(self):
        """Source invariant: ONE definition of the default, no restatements.

        This is the test that actually catches the regression. The behaviour is
        identical while the default happens to be `name`, so only a
        single-definition check proves a generator is not carrying its own copy.
        Before the fix this file held two: DEFAULT_FIELDS and _gen_form's inline
        fallback.
        """
        src = Path(cli_module.__file__).read_text()
        occurrences = src.count('("name", "string")')
        assert occurrences == 1, (
            f"the default field literal appears {occurrences} times; it must be "
            "defined once in DEFAULT_FIELDS and referenced everywhere else"
        )


# ── View generator ────────────────────────────────────────────────────

class TestGenerateView:
    def test_creates_list_and_detail(self, tmp_project):
        _gen_view("Product", {"fields": "name:string,price:float"})
        list_path = tmp_project / "src" / "templates" / "pages" / "products.twig"
        detail_path = tmp_project / "src" / "templates" / "pages" / "product.twig"
        assert list_path.exists()
        assert detail_path.exists()

    def test_list_has_columns(self, tmp_project):
        _gen_view("Product", {"fields": "name:string,price:float"})
        content = (tmp_project / "src" / "templates" / "pages" / "products.twig").read_text()
        assert "item.name" in content
        assert "item.price" in content

    def test_detail_has_fields(self, tmp_project):
        _gen_view("Product", {"fields": "name:string,price:float"})
        content = (tmp_project / "src" / "templates" / "pages" / "product.twig").read_text()
        assert "item.name" in content
        assert "Detail" in content


# ── Auth generator ────────────────────────────────────────────────────

class TestGenerateAuth:
    def test_creates_all_auth_files(self, tmp_project):
        _gen_auth()
        assert (tmp_project / "src" / "orm" / "User.py").exists()
        assert (tmp_project / "src" / "routes" / "auth.py").exists()
        assert (tmp_project / "src" / "templates" / "forms" / "login.twig").exists()
        assert (tmp_project / "src" / "templates" / "forms" / "register.twig").exists()
        assert (tmp_project / "tests" / "test_auth.py").exists()
        migrations = list((tmp_project / "migrations").glob("*create_user*"))
        assert len(migrations) >= 1

    def test_user_model_has_fields(self, tmp_project):
        _gen_auth()
        content = (tmp_project / "src" / "orm" / "User.py").read_text()
        assert "email" in content
        assert "password" in content
        assert "role" in content

    def test_auth_routes_have_endpoints(self, tmp_project):
        _gen_auth()
        content = (tmp_project / "src" / "routes" / "auth.py").read_text()
        assert "/api/auth/register" in content
        assert "/api/auth/login" in content
        assert "/api/auth/me" in content
        assert "Auth.hash_password" in content
        assert "Auth.check_password" in content


# ── CRUD generator ────────────────────────────────────────────────────

class TestGenerateCrud:
    def test_creates_all_crud_files(self, tmp_project):
        _gen_crud("Product", {"fields": "name:string,price:float"})
        assert (tmp_project / "src" / "orm" / "Product.py").exists()
        assert (tmp_project / "src" / "routes" / "products.py").exists()
        assert (tmp_project / "src" / "templates" / "forms" / "product.twig").exists()
        assert (tmp_project / "tests" / "test_products.py").exists()
        migrations = list((tmp_project / "migrations").glob("*create_product*"))
        assert len(migrations) >= 1

    def test_crud_route_imports_model(self, tmp_project):
        _gen_crud("Product", {"fields": "name:string"})
        content = (tmp_project / "src" / "routes" / "products.py").read_text()
        assert "from src.orm.Product import Product" in content


# ══════════════════════════════════════════════════════════════════════
# Scaffolding-first acceptance matrix — real temp project, real test
# client, NO mocks. Compile + import + boot behaviour, not string-grep.
# ══════════════════════════════════════════════════════════════════════

def _compiles(path: Path):
    """B2 — the generated source COMPILES (stricter than ast.parse)."""
    src = path.read_text()
    compile(src, str(path), "exec")   # raises SyntaxError if not


# ── Placeholder / helper unit tests ───────────────────────────────────

class TestPlaceholderHelpers:
    def test_ai_fill_is_a_grounded_fill_spec(self):
        block = _ai_fill(
            "create_widget", "persist a widget", "Widget.create(request.body)",
            "create_widget: persist and return",
            given="request.body -> dict", ret="response(item.to_dict(), 201)",
            ground='tina4_context("create ORM record", "python")',
        )
        assert "AI-FILL: create_widget" in block
        assert "# Intent:" in block and "# Use:" in block and "# Ground:" in block
        assert 'raise NotImplementedError("create_widget: persist and return")' in block

    def test_extend_marks_without_notimplemented(self):
        block = _extend("validate before persist", "e.g. reject invalid input")
        assert "EXTEND: validate before persist" in block
        assert "NotImplementedError" not in block

    def test_parse_every_durations(self):
        assert _parse_every("5m") == 300
        assert _parse_every("30s") == 30
        assert _parse_every("2h") == 7200
        assert _parse_every("1d") == 86400
        assert _parse_every("45") == 45
        assert _parse_every("") == 60          # default
        assert _parse_every("garbage") == 60   # unparseable → default


# ── Route: secure-by-default BEHAVIOUR (R1–R4) ────────────────────────

def _boot_model_route(tmp_project, model, route, *, public=False, fields="name:string"):
    """Generate model + route, bind a REAL sqlite DB, create the table, import
    the route (registers the 5 handlers). Returns the imported route module."""
    from tina4_python.database import Database
    from tina4_python.orm.model import bind_database

    _gen_model(model, {"fields": fields, "no-migration": True})
    flags = {"model": model}
    if public:
        flags["public"] = True
    _gen_route(route, flags)

    bind_database(Database(f"sqlite:///{tmp_project}/app.db"))
    mod = _load_generated(tmp_project / "src" / "routes" / f"{route}.py", f"genroute_{route}")
    getattr(mod, model).create_table()
    return mod


class TestRouteSecureByDefaultBehaviour:
    def test_model_route_boot_gate(self, tmp_project, clean_registry):
        from tina4_python.core.router import Router
        from tina4_python.test_client import TestClient
        from tina4_python.auth import get_token
        os.environ["TINA4_SECRET"] = "scaffold-test-secret"
        os.environ.pop("TINA4_API_KEY", None)

        _boot_model_route(tmp_project, "Sprocket", "sprockets")

        # R1 — all five routes registered.
        paths = {(r["method"], r["path"]) for r in Router.get_routes()}
        assert ("GET", "/api/sprockets") in paths
        assert ("GET", "/api/sprockets/{id:int}") in paths
        assert ("POST", "/api/sprockets") in paths
        assert ("PUT", "/api/sprockets/{id:int}") in paths
        assert ("DELETE", "/api/sprockets/{id:int}") in paths

        client = TestClient()
        # R2 — secure by default, proven by behaviour.
        assert client.get("/api/sprockets").status == 200                       # read public
        assert client.get("/api/sprockets/1").status in (200, 404)              # read public
        assert client.post("/api/sprockets", json={"name": "a"}).status == 401  # write gated
        token = get_token({"user_id": 1})
        created = client.post("/api/sprockets", json={"name": "a"},
                              headers={"Authorization": f"Bearer {token}"})
        assert created.status == 201                                            # token → 201

    def test_model_route_source_has_no_noauth_by_default(self, tmp_project):
        # R4 — no @noauth, no noauth import, secure by default.
        _gen_model("Cog", {"fields": "name:string", "no-migration": True})
        _gen_route("cogs", {"model": "Cog"})
        src = (tmp_project / "src" / "routes" / "cogs.py").read_text()
        assert "@noauth" not in src
        assert "noauth" not in src.splitlines()[0]  # not imported


class TestRoutePublicOptOut:
    def test_public_route_boot_gate(self, tmp_project, clean_registry):
        from tina4_python.test_client import TestClient
        os.environ["TINA4_SECRET"] = "scaffold-test-secret"
        os.environ.pop("TINA4_API_KEY", None)

        _boot_model_route(tmp_project, "Widget", "widgets", public=True)
        client = TestClient()
        # R3 — --public opened the writes: anonymous POST creates.
        assert client.post("/api/widgets", json={"name": "a"}).status == 201
        # DELETE is open too (gate passed → handler runs → 404 for the missing row).
        assert client.delete("/api/widgets/999").status in (204, 404)

    def test_public_route_source_has_noauth_on_writes_only(self, tmp_project):
        # R4 (--public) — @noauth on the 3 writes, noauth imported, never on GETs.
        _gen_model("Gadget", {"fields": "name:string", "no-migration": True})
        _gen_route("gadgets", {"model": "Gadget", "public": True})
        src = (tmp_project / "src" / "routes" / "gadgets.py").read_text()
        assert src.count("@noauth()") == 3            # create + update + delete
        assert "get, post, put, delete, noauth" in src
        # @noauth sits directly above each WRITE handler, and neither READ.
        assert '@noauth()\n@description("Create a new gadget")' in src
        assert '@noauth()\n@description("Update a gadget")' in src
        assert '@noauth()\n@description("Delete a gadget")' in src
        assert '@noauth()\n@description("List all gadgets")' not in src
        assert '@noauth()\n@description("Get a gadget by ID")' not in src


class TestRouteNoModelStub:
    def test_no_model_route_is_a_live_stub(self, tmp_project, clean_registry):
        from tina4_python.core.router import Router
        from tina4_python.test_client import TestClient
        os.environ["TINA4_SECRET"] = "scaffold-test-secret"
        os.environ.pop("TINA4_API_KEY", None)

        _gen_route("notes", {})
        path = tmp_project / "src" / "routes" / "notes.py"
        _compiles(path)                                        # B2
        mod = _load_generated(path, "genroute_notes")          # B3 imports clean
        # R1 — five routes registered.
        assert len([r for r in Router.get_routes() if "/api/notes" in r["path"]]) == 5
        # S2 — AI-FILL banner + Ground line present.
        src = path.read_text()
        assert "AI-FILL" in src and "# Ground:" in src
        # Secure gate holds even though the handler is a stub (gate runs first).
        assert TestClient().post("/api/notes", json={}).status == 401
        # S1 — calling a handler raises NotImplementedError (placeholder is live).
        from tina4_python.core.request import Request
        from tina4_python.core.response import Response
        req = Request.from_scope({"type": "http", "method": "GET", "path": "/api/notes",
                                  "query_string": b"", "headers": [], "client": ("127.0.0.1", 0)}, b"")
        with pytest.raises(NotImplementedError):
            asyncio.run(mod.list_notes(req, Response()))


# ── CRUD: generated test file itself PASSES (R5) ──────────────────────

class TestCrudGeneratedTestPasses:
    def test_generated_crud_test_runs_green(self, tmp_project):
        _gen_crud("Trinket", {"fields": "name:string,qty:int"})
        # R5 — the emitted test file executes green in a real pytest subprocess.
        test_file = tmp_project / "tests" / "test_trinkets.py"
        assert test_file.exists()
        env = {**os.environ, "PYTHONPATH": str(tmp_project)}
        env.pop("TINA4_API_KEY", None)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q"],
            cwd=str(tmp_project), env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + "\n" + result.stderr

    def test_crud_default_routes_secure(self, tmp_project):
        _gen_crud("Doohickey", {"fields": "name:string"})
        src = (tmp_project / "src" / "routes" / "doohickeys.py").read_text()
        assert "@noauth" not in src

    def test_crud_public_routes_open_writes(self, tmp_project):
        _gen_crud("Contraption", {"fields": "name:string", "public": True})
        src = (tmp_project / "src" / "routes" / "contraptions.py").read_text()
        assert src.count("@noauth()") == 3


# ── The six new logic-shaped generators (B1–B4 + S1–S3) ───────────────

class TestServiceGenerator:
    def test_interval_service(self, tmp_project, capsys):
        _gen_service("Reaper", {"every": "5m"})
        path = tmp_project / "src" / "services" / "reaper.py"
        assert path.exists()                       # B1
        _compiles(path)                            # B2
        mod = _load_generated(path, "gen_reaper")  # B3
        # B4 — second run refuses to overwrite.
        _gen_service("Reaper", {"every": "5m"})
        assert "already exists" in capsys.readouterr().out
        # S2 — AI-FILL + Ground.
        src = path.read_text()
        assert "AI-FILL" in src and "# Ground:" in src
        # S1 — the task body raises until filled.
        with pytest.raises(NotImplementedError):
            mod.reaper_task(None)
        # S3 — the service is registrable / discoverable on a REAL ServiceRunner.
        from tina4_python.service import ServiceRunner
        assert mod.service["name"] == "reaper" and mod.service["interval"] == 300
        runner = ServiceRunner()
        mod.register(runner)
        assert any(s["name"] == "reaper" for s in runner.list())
        assert "reaper" in ServiceRunner().discover("src/services")

    def test_cron_service(self, tmp_project):
        _gen_service("Nightly", {"cron": "0 3 * * *"})
        mod = _load_generated(tmp_project / "src" / "services" / "nightly.py", "gen_nightly")
        assert mod.service["cron"] == "0 3 * * *"


class TestQueueGenerator:
    def test_queue_consumer_and_producer(self, tmp_project):
        _gen_queue("order-emails", {})
        path = tmp_project / "src" / "services" / "order_emails_consumer.py"
        assert path.exists()                              # B1
        _compiles(path)                                   # B2
        mod = _load_generated(path, "gen_queue_orders")   # B3
        src = path.read_text()
        assert "AI-FILL" in src and "# Ground:" in src    # S2
        # S1 — the consume body raises until filled.
        with pytest.raises(NotImplementedError):
            mod.handle_order_emails({})
        # S3 — consumer wired as a daemon service; producer is callable + real.
        assert mod.service["daemon"] is True
        assert mod.service["handler"].__name__ == "consume_order_emails"
        job_id = mod.publish_order_emails({"to": "a@b.c"})  # real file-backend push
        assert job_id
        assert "order-emails-consumer" in ServiceRunnerNames(tmp_project)

    def test_idempotent(self, tmp_project, capsys):
        _gen_queue("invoices", {})
        _gen_queue("invoices", {})
        assert "already exists" in capsys.readouterr().out


def ServiceRunnerNames(tmp_project):
    from tina4_python.service import ServiceRunner
    return ServiceRunner().discover("src/services")


class TestValidatorGenerator:
    def test_validator(self, tmp_project, capsys):
        _gen_validator("CreateUser", {})
        path = tmp_project / "src" / "validators" / "create_user.py"
        assert path.exists()                                # B1
        _compiles(path)                                     # B2
        mod = _load_generated(path, "gen_validator")        # B3
        _gen_validator("CreateUser", {})                    # B4
        assert "already exists" in capsys.readouterr().out
        src = path.read_text()
        # Working default (not a loud stub): a starter rule + an EXTEND marker.
        assert "EXTEND" in src                              # S2
        assert "from tina4_python.validator import Validator" in src  # S3 wiring
        assert 'validator.required("name")' in src
        # S1 — runs against valid + invalid real input (the starter rule works).
        assert mod.validate_create_user({"name": "Ada"}).is_valid()
        assert not mod.validate_create_user({}).is_valid()
        # Co-emitted real valid/invalid test lands next to the code.
        assert (tmp_project / "tests" / "test_create_user.py").exists()


class TestSeederGenerator:
    def test_seeder(self, tmp_project, capsys):
        from tina4_python.seeder import FakeData
        _gen_model("Sprocket", {"fields": "name:string", "no-migration": True})
        _gen_seeder("Sprocket", {})
        path = tmp_project / "src" / "seeds" / "sprocket_seeder.py"
        assert path.exists()                                # B1
        _compiles(path)                                     # B2
        mod = _load_generated(path, "gen_seeder")           # B3 (resolves src.orm.Sprocket)
        _gen_seeder("Sprocket", {})                         # B4
        assert "already exists" in capsys.readouterr().out
        src = path.read_text()
        # Working default (not a loud stub): zero-override seeder auto-fills.
        assert "EXTEND" in src                              # S2
        assert "seed_orm" in src and "run" in src           # S3 wiring (run() for `tina4 seed`)
        # S1 — field_overrides returns a real dict (auto-fill), not a raise.
        assert mod.field_overrides(FakeData()) == {}
        # Co-emitted real seeding test lands next to the code.
        assert (tmp_project / "tests" / "test_sprocket_seeder.py").exists()


class TestWebsocketGenerator:
    def test_websocket(self, tmp_project, capsys, clean_registry):
        from tina4_python.core.router import Router
        _gen_websocket("chat", {})
        path = tmp_project / "src" / "routes" / "ws_chat.py"
        assert path.exists()                                # B1
        _compiles(path)                                     # B2
        mod = _load_generated(path, "gen_ws")               # B3
        _gen_websocket("chat", {})                          # B4
        assert "already exists" in capsys.readouterr().out
        src = path.read_text()
        assert "AI-FILL" in src and "# Ground:" in src      # S2
        # S3 — the ws handler registered on the real Router.
        assert any(r["path"] == "/ws/chat" for r in Router.get_web_socket_routes())
        # S1 — the message body raises until filled.
        with pytest.raises(NotImplementedError):
            asyncio.run(mod.chat_ws(None, "message", None))


class TestListenerGenerator:
    def test_listener(self, tmp_project, capsys, clean_registry):
        events = importlib.import_module("tina4_python.core.events")
        _gen_listener("user.created", {})
        path = tmp_project / "src" / "listeners" / "user_created.py"
        assert path.exists()                                # B1
        _compiles(path)                                     # B2
        mod = _load_generated(path, "gen_listener")         # B3
        _gen_listener("user.created", {})                   # B4
        assert "already exists" in capsys.readouterr().out
        src = path.read_text()
        assert "AI-FILL" in src and "# Ground:" in src      # S2
        # S3 — the listener bound on the real event bus.
        assert "user.created" in events.events()
        assert len(events.listeners("user.created")) >= 1
        # S1 — the reaction body raises until filled.
        with pytest.raises(NotImplementedError):
            mod.on_user_created({"id": 1})


# ── Regression guard (A1) + robustness (N1) ───────────────────────────

class TestAuthNotOverSwept:
    def test_auth_routes_still_public(self, tmp_project):
        # A1 — the CRUD secure-by-default fix must NOT strip @noauth from the
        # genuinely-public auth routes (login/register).
        _gen_auth()
        src = (tmp_project / "src" / "routes" / "auth.py").read_text()
        assert src.count("@noauth()") >= 2   # register + login are public


class TestRobustness:
    def test_invalid_fields_no_stacktrace(self, tmp_project):
        # N1 — a malformed --fields value must not raise.
        _gen_model("Junk", {"fields": ":::,,,bad"})
        assert (tmp_project / "src" / "orm" / "Junk.py").exists()

    def test_existing_file_not_clobbered(self, tmp_project, capsys):
        _gen_validator("Once", {})
        original = (tmp_project / "src" / "validators" / "once.py").read_text()
        _gen_validator("Once", {})
        assert (tmp_project / "src" / "validators" / "once.py").read_text() == original
        assert "already exists" in capsys.readouterr().out


# ── SQL reserved words must never become table names ──────────────────

class TestReservedTableNames:
    """`CREATE TABLE order (...)` is a syntax error on every engine, and the
    ORM interpolates table names unquoted, so a resource called Order used to
    generate a table that could never be created."""

    def test_reserved_name_is_pluralised(self):
        assert _to_table("Order") == "orders"
        assert _to_table("Group") == "groups"
        assert _to_table("User") == "users"
        assert _to_table("Index") == "indexes"
        # Non-reserved names stay singular — no behaviour change.
        assert _to_table("Product") == "product"
        assert _to_table("Customer") == "customer"

    def test_model_and_migration_agree_on_the_escaped_name(self, tmp_project):
        _gen_model("Order", {"fields": "total:float,status:string"})
        model_src = (tmp_project / "src" / "orm" / "Order.py").read_text()
        assert 'table_name = "orders"' in model_src

        migration = next((tmp_project / "migrations").glob("*create_orders.sql"))
        ddl = migration.read_text()
        assert "orders" in ddl
        # The bare reserved word must not appear as the CREATE TABLE target.
        assert "CREATE TABLE IF NOT EXISTS order " not in ddl

    def test_generated_ddl_actually_executes(self, tmp_project):
        """The real regression: run the emitted DDL against SQLite."""
        import sqlite3
        _gen_model("Order", {"fields": "total:float,status:string"})
        migration = next((tmp_project / "migrations").glob("*create_orders.sql"))
        conn = sqlite3.connect(":memory:")
        for stmt in migration.read_text().split(";"):
            if stmt.strip():
                conn.execute(stmt)          # raised "near \"order\": syntax error" before
        cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
        assert {"id", "total", "status"} <= cols
        conn.close()


class TestGeneratedMigrationMatchesModel:
    """Regression: `generate model/crud` WITHOUT --fields used to write a model
    declaring `name` while its migration created only id + created_at, so the
    first write died with "table x has no column named name" (a 500 surfacing as
    an unrelated AttributeError, because the route did not check create()).

    The default field set now lives in one place (_fields_or_default) and flows
    into the model, the migration, the template and the test alike.
    """

    def _up_sql(self, project: Path) -> str:
        ups = [m for m in (project / "migrations").glob("*.sql")
               if not m.name.endswith(".down.sql")]
        assert ups, "no UP migration was generated"
        return ups[0].read_text()

    def _model_fields(self, project: Path, model: str) -> set[str]:
        """Field names declared on the generated ORM model, via a real AST parse."""
        tree = ast.parse((project / "src" / "orm" / f"{model}.py").read_text())
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == model)
        return {t.id for stmt in cls.body if isinstance(stmt, ast.Assign)
                for t in stmt.targets
                if isinstance(t, ast.Name) and not t.id.startswith("_")
                and t.id != "table_name"}

    def test_model_without_fields_migration_has_every_declared_column(self, tmp_project):
        """No --fields: the default `name` column must reach the migration."""
        _gen_model("Todo", {})
        declared = self._model_fields(tmp_project, "Todo")
        up = self._up_sql(tmp_project)
        assert "name" in declared, "model should declare the default name field"
        for field in declared:
            assert field in up, f"model declares {field!r} but the migration omits it:\n{up}"

    def test_crud_without_fields_migration_has_every_declared_column(self, tmp_project):
        """Same contract through `generate crud`, the path llms.txt recommends."""
        _gen_crud("Todo", {})
        declared = self._model_fields(tmp_project, "Todo")
        up = self._up_sql(tmp_project)
        for field in declared:
            assert field in up, f"model declares {field!r} but the migration omits it:\n{up}"

    def test_explicit_fields_still_all_reach_the_migration(self, tmp_project):
        """Positive control: the --fields path must not regress."""
        _gen_model("Product", {"fields": "title:string,price:float,in_stock:bool"})
        up = self._up_sql(tmp_project)
        for field in ("title", "price", "in_stock"):
            assert field in up, f"{field!r} missing from migration:\n{up}"

    def test_generated_schema_accepts_a_row_using_the_models_fields(self, tmp_project):
        """End-to-end against REAL sqlite: run the generated DDL, then insert a
        row using the model's own field names. This is what actually broke."""
        import sqlite3
        _gen_model("Todo", {})
        declared = self._model_fields(tmp_project, "Todo") - {"id", "created_at"}
        conn = sqlite3.connect(":memory:")
        conn.executescript(self._up_sql(tmp_project))
        cols = ", ".join(sorted(declared))
        placeholders = ", ".join("?" for _ in declared)
        conn.execute(f"INSERT INTO todo ({cols}) VALUES ({placeholders})",
                     ["x" for _ in declared])
        assert conn.execute("SELECT COUNT(*) FROM todo").fetchone()[0] == 1
        conn.close()

    def test_create_route_checks_result_before_to_dict(self, tmp_project):
        """The 500 was masked as AttributeError because the generated route did
        item.to_dict() without checking create() (which returns False, never raises)."""
        _gen_crud("Todo", {})
        route = (tmp_project / "src" / "routes" / "todos.py").read_text()
        assert "is False" in route, "generated route must check create()/save() result"
        assert route.index("is False") < route.index("to_dict(), 201"), \
            "the guard must come before to_dict()"
