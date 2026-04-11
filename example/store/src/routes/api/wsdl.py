from tina4_python.core.router import get, post, noauth
from tina4_python.wsdl import WSDL, wsdl_operation
from tina4_python.orm import ORM
from datetime import datetime


class OrderService:
    """SOAP service for B2B order operations."""

    @wsdl_operation({"order_id": "int", "status": "string"})
    def place_order(self, customer_id: int, product_ids: str, quantities: str):
        db = ORM.get_db()
        pids = [int(x) for x in product_ids.split(",")]
        qtys = [int(x) for x in quantities.split(",")]

        db.execute(
            "insert into orders (customer_id, total, status, created_at) values (?, 0, 'pending', ?)",
            [customer_id, datetime.now().isoformat()],
        )
        order_id = db.get_last_id()
        total = 0

        for pid, qty in zip(pids, qtys):
            product = db.fetch_one("select price from products where id = ?", [pid])
            price = product["price"] if product else 0
            total += price * qty
            db.execute(
                "insert into order_items (order_id, product_id, quantity, unit_price) values (?, ?, ?, ?)",
                [order_id, pid, qty, price],
            )

        db.execute("update orders set total = ? where id = ?", [total, order_id])
        db.commit()
        return {"order_id": order_id, "status": "pending"}

    @wsdl_operation({"order_id": "int", "status": "string", "total": "float"})
    def get_order_status(self, order_id: int):
        db = ORM.get_db()
        order = db.fetch_one("select id, status, total from orders where id = ?", [order_id])
        if not order:
            return {"order_id": order_id, "status": "not_found", "total": 0}
        return {"order_id": order["id"], "status": order["status"], "total": order["total"]}


@noauth()
@get("/api/soap/orders")
async def wsdl_definition(request, response):
    wsdl = WSDL(request, service_url="/api/soap/orders")
    return response(wsdl.generate_wsdl(), 200)


@noauth()
@post("/api/soap/orders")
async def soap_handler(request, response):
    wsdl = WSDL(request, service_url="/api/soap/orders")
    result = wsdl.handle()
    return response(result, 200)
