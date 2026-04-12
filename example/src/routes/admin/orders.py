from tina4_python.core.router import get, post, noauth, middleware
from tina4_python.core.events import emit_async
from tina4_python.query_builder import QueryBuilder
from src.orm.order import Order
from src.app.template import render
from src.middleware.admin_auth import AdminAuth


@middleware(AdminAuth)
@get("/admin/orders")
async def admin_order_list(request, response):
    status = request.query.get("status", None)

    qb = QueryBuilder.from_table("orders o") \
        .select("o.*", "c.name as customer_name") \
        .join("customers c", "o.customer_id = c.id") \
        .order_by("o.created_at DESC")

    if status:
        qb = qb.where("o.status = ?", [status])

    orders = qb.get()

    return response(render("admin/orders.twig", {
        "orders": orders,
        "current_status": status,
    }, request))


@middleware(AdminAuth)
@get("/admin/orders/{id:int}")
async def admin_order_detail(id, request, response):
    order = QueryBuilder.from_table("orders o") \
        .select("o.*", "c.name as customer_name", "c.email as customer_email") \
        .join("customers c", "o.customer_id = c.id") \
        .where("o.id = ?", [id]) \
        .first()

    if not order:
        return response(render("admin/orders.twig", {"error": "Order not found"}, request), 404)

    items = QueryBuilder.from_table("order_items oi") \
        .select("oi.*", "p.name", "p.image_url") \
        .join("products p", "oi.product_id = p.id") \
        .where("oi.order_id = ?", [id]) \
        .get()

    return response(render("admin/order_detail.twig", {
        "order": order,
        "items": items.records if items else [],
    }, request))


@noauth()
@middleware(AdminAuth)
@post("/admin/orders/{id:int}/status")
async def admin_update_order_status(id, request, response):
    new_status = request.body.get("status", "")

    order = Order.find_by_id(id)
    if order:
        order.status = new_status
        order.save()

    await emit_async("order.status_changed", {"order_id": id, "status": new_status})

    request.session.flash("success", f"Order status updated to {new_status}")
    return response.redirect(f"/admin/orders/{id}")
