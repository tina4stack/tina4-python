"""Test REST API — demonstrates: ORM queries for API responses, Swagger decorators."""
import pytest
from src.orm.product import Product
from src.orm.category import Category
from src.orm.order import Order


class TestProductAPI:
    def test_list_active_products(self, db, sample_category):
        Product.create(name="A", slug="a", price=10, stock=5,
                       category_id=sample_category.id, is_active=True)
        Product.create(name="B", slug="b", price=20, stock=5,
                       category_id=sample_category.id, is_active=True)
        Product.create(name="Hidden", slug="hidden", price=30, stock=5,
                       category_id=sample_category.id, is_active=False)

        active = Product.where("is_active = 1")
        assert len(active) == 2

    def test_product_pagination(self, db, sample_category):
        for i in range(25):
            Product.create(name=f"P{i}", slug=f"p{i}", price=i + 1, stock=10,
                           category_id=sample_category.id, is_active=True)

        page1 = Product.where("is_active = 1", limit=12, offset=0)
        page2 = Product.where("is_active = 1", limit=12, offset=12)
        assert len(page1) == 12
        assert len(page2) == 13  # 25 - 12

    def test_product_by_category(self, db):
        cat1 = Category.create(name="Cat1", slug="cat1")
        cat2 = Category.create(name="Cat2", slug="cat2")
        Product.create(name="In1", slug="in1", price=10, stock=5,
                       category_id=cat1.id, is_active=True)
        Product.create(name="In2", slug="in2", price=20, stock=5,
                       category_id=cat2.id, is_active=True)

        filtered = Product.where(
            "category_id = (select id from categories where slug = ?) and is_active = 1",
            params=["cat1"],
        )
        assert len(filtered) == 1
        assert filtered[0].name == "In1"

    def test_product_detail_with_category(self, db, sample_product):
        product = Product.find(sample_product.id)
        d = product.to_dict(include=["category"])
        assert d["name"] == "Widget Pro"
        assert "category" in d

    def test_product_not_found(self, db):
        product = Product.find(99999)
        assert product is None


class TestCategoryAPI:
    def test_list_categories(self, db):
        Category.create(name="Z", slug="z")
        Category.create(name="A", slug="a")
        cats = Category.all(order_by="name")
        assert len(cats) == 2
        assert cats[0].name == "A"


class TestOrderAPI:
    def test_orders_by_customer(self, db, sample_customer, sample_order):
        orders = Order.where("customer_id = ?", params=[sample_customer.id])
        assert len(orders) == 1
        assert orders[0].total == pytest.approx(29.99)

    def test_order_not_found(self, db, sample_customer):
        orders = Order.where("id = ? and customer_id = ?", params=[99999, sample_customer.id])
        assert len(orders) == 0
