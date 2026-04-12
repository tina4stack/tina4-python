"""Test cart service — demonstrates: Session usage, service layer pattern."""
import pytest
from tests.conftest import FakeSession
from src.app.services.cart_service import get_cart_items, get_cart_total, cart_count


class TestCartService:
    def test_empty_cart(self, db):
        session = FakeSession()
        assert get_cart_items(session) == []
        assert get_cart_total(session) == 0
        assert cart_count(session) == 0

    def test_add_single_item(self, db, sample_product):
        session = FakeSession({"cart": {str(sample_product.id): 2}})
        items = get_cart_items(session)
        assert len(items) == 1
        assert items[0]["quantity"] == 2
        assert items[0]["subtotal"] == sample_product.price * 2

    def test_cart_total(self, db, sample_product):
        session = FakeSession({"cart": {str(sample_product.id): 3}})
        total = get_cart_total(session)
        assert total == pytest.approx(sample_product.price * 3)

    def test_cart_count(self, db, sample_product):
        session = FakeSession({"cart": {str(sample_product.id): 5}})
        assert cart_count(session) == 5

    def test_multiple_items(self, db, sample_category):
        from src.orm.product import Product
        p1 = Product.create(name="A", slug="a", price=10.0, stock=10,
                            category_id=sample_category.id, is_active=True)
        p2 = Product.create(name="B", slug="b", price=20.0, stock=10,
                            category_id=sample_category.id, is_active=True)
        session = FakeSession({"cart": {str(p1.id): 1, str(p2.id): 2}})
        items = get_cart_items(session)
        assert len(items) == 2
        total = get_cart_total(session)
        assert total == pytest.approx(10.0 + 40.0)

    def test_nonexistent_product_ignored(self, db):
        session = FakeSession({"cart": {"9999": 1}})
        items = get_cart_items(session)
        assert len(items) == 0

    def test_add_and_remove_flow(self, db, sample_product):
        session = FakeSession()
        # Add
        cart = session.get("cart") or {}
        cart[str(sample_product.id)] = 3
        session.set("cart", cart)
        assert cart_count(session) == 3

        # Remove
        cart.pop(str(sample_product.id), None)
        session.set("cart", cart)
        assert cart_count(session) == 0
