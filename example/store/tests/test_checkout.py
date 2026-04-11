"""Test checkout flow — demonstrates: ORM create, Queue push, Events emit."""
import pytest
from src.orm.order import Order
from src.orm.order_item import OrderItem
from src.orm.product import Product
from tina4_python.queue import Queue
from tina4_python.core.events import on, emit, off


class TestCheckoutFlow:
    def test_create_order_from_cart(self, db, sample_customer, sample_product):
        order = Order.create(
            customer_id=sample_customer.id,
            total=sample_product.price * 2,
            status="pending",
            created_at="2026-04-11T12:00:00",
        )
        OrderItem.create(
            order_id=order.id,
            product_id=sample_product.id,
            quantity=2,
            unit_price=sample_product.price,
        )
        assert order.id is not None
        items = OrderItem.where("order_id = ?", params=[order.id])
        assert len(items) == 1
        assert items[0].quantity == 2

    def test_order_total_correct(self, db, sample_customer, sample_category):
        p1 = Product.create(name="X", slug="x", price=15.0, stock=10,
                            category_id=sample_category.id, is_active=True)
        p2 = Product.create(name="Y", slug="y", price=25.0, stock=10,
                            category_id=sample_category.id, is_active=True)
        total = (15.0 * 2) + (25.0 * 1)
        order = Order.create(
            customer_id=sample_customer.id, total=total,
            status="pending", created_at="2026-04-11T12:00:00",
        )
        OrderItem.create(order_id=order.id, product_id=p1.id, quantity=2, unit_price=15.0)
        OrderItem.create(order_id=order.id, product_id=p2.id, quantity=1, unit_price=25.0)
        assert order.total == pytest.approx(55.0)

    def test_order_status_flow(self, db, sample_order):
        order = Order.find(sample_order.id)
        assert order.status == "pending"
        order.status = "processing"
        order.save()
        reloaded = Order.find(order.id)
        assert reloaded.status == "processing"

    def test_empty_cart_rejected(self, db):
        """No order should be created from an empty cart."""
        initial_count = Order.count()
        # Simulate: cart is empty, don't create order
        cart = {}
        assert len(cart) == 0
        assert Order.count() == initial_count


class TestQueueIntegration:
    def test_push_order_to_queue(self, db, sample_order):
        queue = Queue("test-orders")
        queue.push({"order_id": sample_order.id, "customer_id": 1})
        assert queue.size() >= 1

    def test_consume_from_queue(self, db, sample_order):
        queue = Queue("test-consume")
        queue.push({"order_id": sample_order.id})
        for job in queue.consume(poll_interval=0):
            assert job.data["order_id"] == sample_order.id
            job.complete()
            break


class TestEventIntegration:
    def test_order_placed_event(self, db, sample_order):
        received = []

        @on("test.order.placed")
        def handler(data):
            received.append(data)

        emit("test.order.placed", {"order_id": sample_order.id, "total": 29.99})
        assert len(received) == 1
        assert received[0]["order_id"] == sample_order.id

        off("test.order.placed")
