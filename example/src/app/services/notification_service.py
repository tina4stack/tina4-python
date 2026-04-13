"""Event listeners for SSE dashboard and email notifications.

Demonstrates: Events (@on decorator), SSE queue, Messenger (email).
"""
import json
from tina4_python.core.events import on
from tina4_python.messenger import create_messenger
from tina4_python.frond import Frond
from tina4_python.debug import Log
from src.routes.api.sse import sales_queue

# Messenger for email — reads SMTP config from .env
messenger = create_messenger()
frond = Frond()


@on("order.placed")
def on_order_placed(data):
    """Push to SSE feed + send confirmation email."""
    sales_queue.put({
        "type": "order_placed",
        "order_id": data["order_id"],
        "total": data["total"],
    })

    # Send order confirmation email via Messenger
    # Templates expect order.id / order.total (object), so fetch from ORM
    try:
        from src.orm.order import Order
        from src.orm.customer import Customer
        order = Order.find_by_id(data["order_id"])
        customer = Customer.find_by_id(data.get("customer_id")) if data.get("customer_id") else None
        html = frond.render("email/order_confirmation.twig", {
            "order": order.to_dict() if order else {"id": data["order_id"], "total": data["total"]},
            "customer_name": customer.name if customer else "Customer",
        })
        messenger.send(
            to=data.get("email", ""),
            subject=f"Order #{data['order_id']} Confirmed",
            body=html,
        )
    except Exception as e:
        Log.info(f"Email skipped (no SMTP configured): {e}")


@on("order.processing")
def on_order_processing(data):
    sales_queue.put({
        "type": "order_processing",
        "order_id": data["order_id"],
    })


@on("order.status_changed")
def on_order_status_changed(data):
    """Push status update to SSE + send shipping email if shipped."""
    sales_queue.put({
        "type": "status_changed",
        "order_id": data["order_id"],
        "status": data["status"],
    })

    if data["status"] == "shipped":
        try:
            from src.orm.order import Order
            from src.orm.customer import Customer
            order = Order.find_by_id(data["order_id"])
            customer = Customer.find_by_id(order.customer_id) if order else None
            html = frond.render("email/shipping_notification.twig", {
                "order": order.to_dict() if order else {"id": data["order_id"]},
                "customer_name": customer.name if customer else "Customer",
            })
            messenger.send(
                to=data.get("email", ""),
                subject=f"Order #{data['order_id']} Shipped!",
                body=html,
            )
        except Exception as e:
            Log.info(f"Email skipped (no SMTP configured): {e}")


@on("stock.low")
def on_stock_low(data):
    sales_queue.put({
        "type": "stock_low",
        "product_id": data["product_id"],
        "remaining": data["remaining"],
    })


@on("cart.item_added")
def on_cart_item_added(data):
    sales_queue.put({
        "type": "cart_add",
        "product": data["product_name"],
        "price": data["price"],
        "quantity": data["quantity"],
        "customer": data["customer"],
    })


@on("customer.registered")
def on_customer_registered(data):
    """Send welcome email to new customer."""
    try:
        messenger.send(
            to=data.get("email", ""),
            subject="Welcome to Tina4 Store!",
            body=f"Hi {data['name']}, welcome to our store!",
        )
    except Exception as e:
        Log.info(f"Welcome email skipped (no SMTP configured): {e}")
