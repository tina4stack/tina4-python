from tina4_python.core.router import get, secured
from tina4_python.query_builder import QueryBuilder
from src.orm.order import Order
from src.app.template import render


@secured()
@get("/account")
async def account_page(request, response):
    customer_id = request.session.get("customer_id")
    orders = Order.where("customer_id = ?", params=[customer_id])
    return response(render("storefront/account.twig", {
        "customer_name": request.session.get("customer_name"),
        "orders": [o.to_dict() for o in orders],
    }, request))


@secured()
@get("/account/orders/{id:int}")
async def account_order_detail(id, request, response):
    customer_id = request.session.get("customer_id")

    orders = Order.where("id = ? and customer_id = ?", params=[id, customer_id])
    if not orders:
        return response(render("storefront/account.twig", {"error": "Order not found"}, request), 404)

    items = QueryBuilder.from_table("order_items oi") \
        .select("oi.*", "p.name as product_name", "p.image_url") \
        .join("products p", "oi.product_id = p.id") \
        .where("oi.order_id = ?", [id]) \
        .get()

    return response(render("storefront/order_detail.twig", {
        "order": orders[0].to_dict(),
        "items": items.records if items else [],
    }, request))
