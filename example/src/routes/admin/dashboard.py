from tina4_python.core.router import get, middleware
from tina4_python.query_builder import QueryBuilder
from src.orm.product import Product
from src.orm.order import Order
from src.app.template import render
from src.middleware.admin_auth import AdminAuth


@middleware(AdminAuth)
@get("/admin")
async def admin_dashboard(request, response):
    total_orders = Order.count()

    total_sales = QueryBuilder.from_table("orders") \
        .select("coalesce(sum(total), 0) as total") \
        .where("status != ?", ["cancelled"]) \
        .first()["total"]

    low_stock = Product.where("stock <= 5 and is_active = 1")

    recent_orders = QueryBuilder.from_table("orders o") \
        .select("o.*", "c.name as customer_name") \
        .join("customers c", "o.customer_id = c.id") \
        .order_by("o.created_at DESC") \
        .limit(10) \
        .get()

    return response(render("admin/dashboard.twig", {
        "stats": {
            "total_orders": total_orders,
            "total_sales": total_sales,
            "low_stock_count": len(low_stock),
        },
        "low_stock": [p.to_dict() for p in low_stock],
        "recent_orders": recent_orders.records if recent_orders else [],
    }, request))
