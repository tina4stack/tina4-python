# Tests for tina4_python.crud (v3)
import pytest
from tina4_python.crud import AutoCrud
from tina4_python.core.router import Router


@pytest.fixture(autouse=True)
def clear_state():
    Router.clear()
    AutoCrud.clear()
    yield
    Router.clear()
    AutoCrud.clear()


class TestAutoCrudClass:

    def test_class_exists(self):
        assert AutoCrud is not None

    def test_register_method_exists(self):
        assert callable(AutoCrud.register)

    def test_discover_method_exists(self):
        assert callable(AutoCrud.discover)

    def test_models_method_exists(self):
        assert callable(AutoCrud.models)

    def test_clear_method_exists(self):
        assert callable(AutoCrud.clear)

    def test_models_returns_dict(self):
        result = AutoCrud.models()
        assert isinstance(result, dict)

    def test_clear_empties_registered(self):
        AutoCrud._registered["test_table"] = object
        AutoCrud.clear()
        assert len(AutoCrud._registered) == 0


class TestAutoCrudRegistration:

    def _make_mock_model(self, table_name="users"):
        """Create a minimal mock ORM model class for testing."""

        class MockField:
            def __init__(self, pk=False, auto=False, ft=str):
                self.primary_key = pk
                self.auto_increment = auto
                self.field_type = ft

            def validate(self, value):
                return value

        class MockModel:
            _fields = {
                "id": MockField(pk=True, auto=True, ft=int),
                "name": MockField(ft=str),
                "email": MockField(ft=str),
            }

            def __init__(self, data=None):
                self._data = data or {}

            @classmethod
            def _get_table(cls):
                return table_name

            @classmethod
            def _get_pk(cls):
                return "id"

            @classmethod
            def all(cls, limit=10, skip=0):
                return [], 0

            @classmethod
            def find(cls, pk):
                return None

            def to_dict(self):
                return self._data

            def validate(self):
                return []

            def save(self):
                pass

            def delete(self):
                pass

        MockModel.__name__ = "MockModel"
        return MockModel

    def test_register_creates_five_routes(self):
        model = self._make_mock_model("test_items")
        routes = AutoCrud.register(model)
        assert len(routes) == 5

    def test_register_creates_get_list_route(self):
        model = self._make_mock_model("products")
        AutoCrud.register(model)
        route, _ = Router.match("GET", "/api/products")
        assert route is not None

    def test_register_creates_get_single_route(self):
        model = self._make_mock_model("products")
        AutoCrud.register(model)
        route, params = Router.match("GET", "/api/products/42")
        assert route is not None
        assert params.get("id") == "42"

    def test_register_creates_post_route(self):
        model = self._make_mock_model("products")
        AutoCrud.register(model)
        route, _ = Router.match("POST", "/api/products")
        assert route is not None

    def test_register_creates_put_route(self):
        model = self._make_mock_model("products")
        AutoCrud.register(model)
        route, params = Router.match("PUT", "/api/products/1")
        assert route is not None
        assert params.get("id") == "1"

    def test_register_creates_delete_route(self):
        model = self._make_mock_model("products")
        AutoCrud.register(model)
        route, params = Router.match("DELETE", "/api/products/1")
        assert route is not None

    def test_register_custom_prefix(self):
        model = self._make_mock_model("widgets")
        AutoCrud.register(model, prefix="/api/v2")
        route, _ = Router.match("GET", "/api/v2/widgets")
        assert route is not None

    def test_register_tracks_model(self):
        model = self._make_mock_model("orders")
        AutoCrud.register(model)
        assert "orders" in AutoCrud.models()

    def test_register_no_table_raises_error(self):
        class BadModel:
            @classmethod
            def _get_table(cls):
                return ""
        BadModel.__name__ = "BadModel"
        with pytest.raises(ValueError, match="no table_name"):
            AutoCrud.register(BadModel)

    def test_register_route_methods_correct(self):
        model = self._make_mock_model("tasks")
        routes = AutoCrud.register(model)
        methods = [r["method"] for r in routes]
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods


class TestBuildExample:

    def test_build_example_skips_auto_pk(self):

        class MockField:
            def __init__(self, pk=False, auto=False, ft=str):
                self.primary_key = pk
                self.auto_increment = auto
                self.field_type = ft

        class Model:
            _fields = {
                "id": MockField(pk=True, auto=True, ft=int),
                "name": MockField(ft=str),
                "age": MockField(ft=int),
            }

        example = AutoCrud._build_example(Model)
        assert "id" not in example
        assert example["name"] == "string"
        assert example["age"] == 0

    def test_build_example_float_field(self):

        class MockField:
            def __init__(self, pk=False, auto=False, ft=str):
                self.primary_key = pk
                self.auto_increment = auto
                self.field_type = ft

        class Model:
            _fields = {
                "price": MockField(ft=float),
            }

        example = AutoCrud._build_example(Model)
        assert example["price"] == 0.0

    def test_build_example_bool_field(self):

        class MockField:
            def __init__(self, pk=False, auto=False, ft=str):
                self.primary_key = pk
                self.auto_increment = auto
                self.field_type = ft

        class Model:
            _fields = {
                "active": MockField(ft=bool),
            }

        example = AutoCrud._build_example(Model)
        assert example["active"] is True
