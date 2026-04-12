from tina4_python.queue import Queue
from tina4_python.core.events import emit
from tina4_python.orm import ORM


def process_orders(queue):
    """Consume from 'orders' topic and process each order."""
    for job in queue.consume("orders"):
        db = ORM.get_db()
        data = job.data if hasattr(job, 'data') else job
        order_id = data.get("order_id") if isinstance(data, dict) else data

        items = db.fetch(
            "select oi.product_id, oi.quantity, p.stock "
            "from order_items oi join products p on oi.product_id = p.id "
            "where oi.order_id = ?",
            [order_id],
        )

        out_of_stock = False
        if items and items.records:
            for item in items.records:
                if item["stock"] < item["quantity"]:
                    out_of_stock = True
                    break

        if out_of_stock:
            db.execute("update orders set status = 'failed' where id = ?", [order_id])
            db.commit()
            emit("order.failed", {"order_id": order_id, "reason": "insufficient stock"})
            if hasattr(job, 'complete'):
                job.complete()
            continue

        if items and items.records:
            for item in items.records:
                db.execute(
                    "update products set stock = stock - ? where id = ?",
                    [item["quantity"], item["product_id"]],
                )
                if item["stock"] - item["quantity"] <= 5:
                    emit("stock.low", {"product_id": item["product_id"], "remaining": item["stock"] - item["quantity"]})

        db.execute("update orders set status = 'processing' where id = ?", [order_id])
        db.commit()
        emit("order.processing", {"order_id": order_id})
        if hasattr(job, 'complete'):
            job.complete()
