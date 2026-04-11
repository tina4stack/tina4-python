from tina4_python.core.router import get, post, secured
from tina4_python.core.events import emit
from tina4_python.queue import Queue
from tina4_python.orm import ORM
from src.orm.order import Order
from src.orm.order_item import OrderItem
from src.app.services.cart_service import get_cart_items, get_cart_total
from src.app.template import render
from datetime import datetime


@get("/checkout")
async def checkout_page(request, response):
    items = get_cart_items(request.session)
    total = get_cart_total(request.session)
    return response(render("storefront/checkout.twig", {
        "cart_items": items,
        "cart_total": total,
    }, request))


@post("/checkout")
async def checkout(request, response):
    cart = request.session.get("cart") or {}
    if not cart:
        request.session.flash("error", "Cart is empty")
        return response.redirect("/cart")

    customer_id = request.session.get("customer_id")
    if not customer_id:
        request.session.flash("error", "Please login to checkout")
        return response.redirect("/login")

    items = get_cart_items(request.session)
    total = get_cart_total(request.session)

    order = Order.create(
        customer_id=customer_id,
        total=total,
        status="pending",
        created_at=datetime.now().isoformat(),
    )

    for item in items:
        OrderItem.create(
            order_id=order.id,
            product_id=item["product_id"],
            quantity=item["quantity"],
            unit_price=item["price"],
        )

    # Process order via queue
    queue = Queue("orders")
    queue.push({"order_id": order.id, "customer_id": customer_id})

    emit("order.placed", {"order_id": order.id, "total": total, "customer_id": customer_id})

    request.session.set("cart", {})
    request.session.flash("success", "Order placed successfully!")
    return response.redirect("/account")
