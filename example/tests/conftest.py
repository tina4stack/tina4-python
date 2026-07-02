"""Shared fixtures for Tina4 Store demo tests.

Demonstrates: Database setup, ORM binding, migrations, seeding — all using
the framework's built-in test infrastructure.
"""
import os
import sys
import pytest

# Put the store root (for `src.*` and this demo's own `tests` package) and the
# tina4-python repo root (for the local `tina4_python` package) on the path.
# ORDER MATTERS: STORE_ROOT must sit AHEAD of REPO_ROOT so `from tests.conftest
# import ...` resolves to THIS demo's example/tests -- not the framework's own
# top-level tests/ dir, which shares the name. REPO_ROOT still supplies the
# checked-out framework source, ahead of any stale pip-installed copy.
STORE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.abspath(os.path.join(STORE_ROOT, ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, STORE_ROOT)

from tina4_python.database import Database
from tina4_python.orm import bind_database
from tina4_python.migration import Migration


@pytest.fixture(scope="session")
def db():
    """Create an in-memory SQLite database with all migrations applied."""
    database = Database("sqlite::memory:")
    bind_database(database)
    # Run migrations from the store's migrations folder
    migration = Migration(database, os.path.join(STORE_ROOT, "migrations"))
    migration.migrate()
    return database


@pytest.fixture(autouse=True)
def clean_tables(db):
    """Clear all data before each test for isolation."""
    for table in ["order_items", "orders", "cart_items", "products", "customers", "categories"]:
        db.execute(f"DELETE FROM {table}")
    db.commit()
    yield


@pytest.fixture
def sample_category(db):
    """Insert a sample category and return its data."""
    from src.orm.category import Category
    return Category.create(name="Electronics", slug="electronics", description="Electronic gadgets")


@pytest.fixture
def sample_product(db, sample_category):
    """Insert a sample product and return its data."""
    from src.orm.product import Product
    return Product.create(
        name="Widget Pro",
        slug="widget-pro",
        description="A professional widget",
        price=29.99,
        stock=100,
        category_id=sample_category.id,
        image_url="/uploads/placeholder-1.svg",
        is_active=True,
    )


@pytest.fixture
def sample_customer(db):
    """Insert a sample customer and return its data."""
    from src.orm.customer import Customer
    from tina4_python.auth import Auth
    return Customer.create(
        name="Alice Test",
        email="alice@example.com",
        password_hash=Auth.hash_password("secret123"),
        role="customer",
    )


@pytest.fixture
def admin_customer(db):
    """Insert an admin customer and return its data."""
    from src.orm.customer import Customer
    from tina4_python.auth import Auth
    return Customer.create(
        name="Admin User",
        email="admin@example.com",
        password_hash=Auth.hash_password("admin123"),
        role="admin",
    )


@pytest.fixture
def sample_order(db, sample_customer, sample_product):
    """Insert a sample order with one item."""
    from src.orm.order import Order
    from src.orm.order_item import OrderItem
    order = Order.create(
        customer_id=sample_customer.id,
        total=29.99,
        status="pending",
        created_at="2026-04-11T12:00:00",
    )
    OrderItem.create(
        order_id=order.id,
        product_id=sample_product.id,
        quantity=1,
        unit_price=29.99,
    )
    return order


class FakeSession:
    """Minimal session mock for testing cart and auth flows."""

    def __init__(self, data=None):
        self._data = data or {}
        self._flash = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def has(self, key):
        return key in self._data

    def delete(self, key):
        self._data.pop(key, None)

    def flash(self, key, value=None):
        if value is not None:
            self._flash[key] = value
        else:
            return self._flash.pop(key, None)

    def get_flash(self, key, default=None):
        return self._flash.pop(key, default)

    def all(self):
        return dict(self._data)
