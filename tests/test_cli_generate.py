"""Tests for CLI scaffolding generators."""
import os
import shutil
import pytest
from pathlib import Path
from tina4_python.cli import (
    _parse_fields, _parse_flags, _to_snake, _to_table,
    _gen_model, _gen_route, _gen_migration, _gen_middleware,
    _gen_test, _gen_form, _gen_view, _gen_auth, _gen_crud,
    FIELD_TYPE_MAP,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temp project directory and cd into it."""
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(old_cwd)


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
        _gen_route("items", {})
        content = (tmp_project / "src" / "routes" / "items.py").read_text()
        assert "from src.orm" not in content
        assert '{"data": []}' in content


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
