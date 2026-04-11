"""Test ORM models — demonstrates: ORM CRUD, relationships, soft delete, validation."""
import pytest
from src.orm.category import Category
from src.orm.product import Product
from src.orm.customer import Customer
from src.orm.order import Order
from src.orm.order_item import OrderItem
from src.orm.cart_item import CartItem


class TestCategory:
    def test_create_and_find(self, db):
        cat = Category.create(name="Books", slug="books", description="All books")
        assert cat.id is not None
        found = Category.find(cat.id)
        assert found.name == "Books"
        assert found.slug == "books"

    def test_all_with_order(self, db):
        Category.create(name="Zebra", slug="zebra")
        Category.create(name="Alpha", slug="alpha")
        cats = Category.all(order_by="name")
        assert cats[0].name == "Alpha"
        assert cats[1].name == "Zebra"

    def test_where(self, db):
        Category.create(name="Active", slug="active")
        Category.create(name="Other", slug="other")
        results = Category.where("slug = ?", params=["active"])
        assert len(results) == 1
        assert results[0].name == "Active"

    def test_count(self, db):
        Category.create(name="A", slug="a")
        Category.create(name="B", slug="b")
        assert Category.count() == 2

    def test_update(self, db):
        cat = Category.create(name="Old", slug="old")
        cat.name = "New"
        cat.save()
        found = Category.find(cat.id)
        assert found.name == "New"

    def test_delete(self, db):
        cat = Category.create(name="Temp", slug="temp")
        cat_id = cat.id
        cat.delete()
        assert Category.find(cat_id) is None

    def test_to_dict(self, db):
        cat = Category.create(name="Dict", slug="dict", description="Test")
        d = cat.to_dict()
        assert d["name"] == "Dict"
        assert d["slug"] == "dict"


class TestProduct:
    def test_create_with_category(self, db, sample_category):
        product = Product.create(
            name="Gadget", slug="gadget", price=19.99,
            stock=50, category_id=sample_category.id, is_active=True,
        )
        assert product.id is not None
        assert product.category_id == sample_category.id

    def test_where_active(self, db, sample_category):
        Product.create(name="Active", slug="active", price=10, stock=5,
                       category_id=sample_category.id, is_active=True)
        Product.create(name="Inactive", slug="inactive", price=10, stock=5,
                       category_id=sample_category.id, is_active=False)
        active = Product.where("is_active = 1")
        assert len(active) == 1
        assert active[0].name == "Active"

    def test_find_by_slug(self, db, sample_product):
        results = Product.where("slug = ?", params=["widget-pro"])
        assert len(results) == 1
        assert results[0].price == 29.99

    def test_relationship_category(self, db, sample_product):
        product = Product.find(sample_product.id)
        d = product.to_dict(include=["category"])
        assert "category" in d


class TestCustomer:
    def test_create_customer(self, db):
        from tina4_python.auth import Auth
        customer = Customer.create(
            name="Bob", email="bob@test.com",
            password_hash=Auth.hash_password("pass"), role="customer",
        )
        assert customer.id is not None
        assert customer.role == "customer"

    def test_soft_delete(self, db):
        from tina4_python.auth import Auth
        customer = Customer.create(
            name="Del", email="del@test.com",
            password_hash=Auth.hash_password("pass"), role="customer",
        )
        cid = customer.id
        customer.delete()
        assert Customer.find(cid) is None  # hidden by soft delete
        trashed = Customer.with_trashed(f"id = {cid}")
        assert len(trashed) >= 1

    def test_restore(self, db):
        from tina4_python.auth import Auth
        customer = Customer.create(
            name="Restore", email="restore@test.com",
            password_hash=Auth.hash_password("pass"), role="customer",
        )
        customer.delete()
        customer.restore()
        found = Customer.find(customer.id)
        assert found is not None
        assert found.name == "Restore"


class TestOrder:
    def test_create_order(self, db, sample_customer):
        order = Order.create(
            customer_id=sample_customer.id, total=99.99,
            status="pending", created_at="2026-01-01T00:00:00",
        )
        assert order.id is not None
        assert order.status == "pending"

    def test_order_with_items(self, db, sample_order, sample_product):
        items = OrderItem.where("order_id = ?", params=[sample_order.id])
        assert len(items) == 1
        assert items[0].unit_price == 29.99
        assert items[0].product_id == sample_product.id


class TestCartItem:
    def test_create_cart_item(self, db, sample_product):
        item = CartItem.create(
            session_id="test-session-123",
            product_id=sample_product.id,
            quantity=2,
        )
        assert item.id is not None
        found = CartItem.where("session_id = ?", params=["test-session-123"])
        assert len(found) == 1
        assert found[0].quantity == 2
