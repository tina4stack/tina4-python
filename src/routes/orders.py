from tina4_python.core.router import get, post, noauth
from src.orm.Order import Order

@noauth()
@get("/api/orders")
async def list_orders(request, response):
    return response({"orders": []})

@noauth()
@post("/api/orders")
async def create_order(request, response):
    data = request.body or {}
    items = data.get("items", [])
    customer_id = data.get("customer_id")
    
    if not customer_id:
        return response({"error": "Customer required"}, 400)
    if not items:
        return response({"error": "No items"}, 400)
    
    total = 0
    for item in items:
        qty = item.get("qty", 1)
        price = item.get("price", 0)
        discount = item.get("discount", 0)
        tax_rate = item.get("tax_rate", 0.15)
        
        if qty <= 0:
            return response({"error": f"Invalid qty for {item.get('name')}"}, 400)
        if price < 0:
            return response({"error": f"Invalid price for {item.get('name')}"}, 400)
        if discount < 0 or discount > 100:
            return response({"error": "Discount must be 0-100"}, 400)
        
        line_total = qty * price
        if discount > 0:
            line_total -= line_total * (discount / 100)
        
        tax = line_total * tax_rate
        line_total += tax
        total += line_total
    
    return response({"order_id": 1, "total": round(total, 2), "items": len(items)}, 201)
