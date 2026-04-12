"""
Simulates a new order every 60 seconds for demo purposes.
Picks a random customer and 1-3 random products, creates an order,
pushes it to the queue, and emits events — so the admin dashboard
SSE feed shows live activity.
"""
import random
import time
import datetime
from tina4_python.orm import ORM
from tina4_python.queue import Queue
from tina4_python.core.events import emit


def run_order_simulator(interval=60):
    """Long-running loop — run in a daemon thread (legacy, use simulate_order() with background())."""
    time.sleep(5)  # wait for server to finish startup

    while True:
        simulate_order()
        time.sleep(interval)


def simulate_order():
    """Create a single simulated order. Called by background() or the legacy loop."""
    try:
        db = ORM.get_db()

        # Pick a random customer
        customers = db.fetch("select id from customers", limit=100)
        if not customers or not customers.records:
            return
        customer_id = random.choice(customers.records)["id"]

        # Pick 1-3 random in-stock products
        products = db.fetch(
            "select id, price, stock from products where is_active = 1 and stock > 0",
            limit=100,
        )
        if not products or not products.records:
            return

        picks = random.sample(
            products.records,
            min(random.randint(1, 3), len(products.records)),
        )

        # Create the order
        now = datetime.datetime.now().isoformat()
        total = 0
        for p in picks:
            qty = random.randint(1, min(3, p["stock"]))
            total += p["price"] * qty

        order = db.fetch_one(
            "insert into orders (customer_id, total, status, created_at) "
            "values (?, ?, 'pending', ?) returning id",
            [customer_id, round(total, 2), now],
        )
        if not order:
            return

        order_id = order["id"]

        # Create order items
        for p in picks:
            qty = random.randint(1, min(3, p["stock"]))
            db.execute(
                "insert into order_items (order_id, product_id, quantity, unit_price) "
                "values (?, ?, ?, ?)",
                [order_id, p["id"], qty, p["price"]],
            )

        db.commit()

        # Emit event → triggers SSE push to admin dashboard
        emit("order.placed", {
            "order_id": order_id,
            "total": round(total, 2),
            "customer_id": customer_id,
        })

        # Push to queue for processing
        queue = Queue(topic="orders")
        queue.push({"order_id": order_id, "customer_id": customer_id})

    except Exception:
        pass  # don't crash the background task
