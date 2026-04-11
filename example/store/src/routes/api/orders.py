from tina4_python.core.router import get, secured
from tina4_python.swagger import description, tags
from tina4_python.query_builder import QueryBuilder
from src.orm.order import Order


@secured()
@tags("Orders")
@description("Get current customer's orders")
@get("/api/orders")
async def api_order_list(request, response):
    customer_id = request.session.get("customer_id")
    orders = Order.where("customer_id = ?", params=[customer_id])
    return response([o.to_dict() for o in orders], 200)


@secured()
@tags("Orders")
@description("Get a single order with its items")
@get("/api/orders/{id:int}")
async def api_order_detail(request, response):
    customer_id = request.session.get("customer_id")
    order_id = request.params["id"]

    orders = Order.where("id = ? and customer_id = ?", params=[order_id, customer_id])
    if not orders:
        return response({"error": "Order not found"}, 404)

    items = QueryBuilder.from_table("order_items oi") \
        .select("oi.*", "p.name", "p.image_url") \
        .join("products p", "oi.product_id = p.id") \
        .where("oi.order_id = ?", [order_id]) \
        .get()

    order_data = orders[0].to_dict()
    order_data["items"] = items.records if items else []
    return response(order_data, 200)
