from tina4_python.core.router import get, post, noauth
from src.app.services.cart_service import get_cart_items, get_cart_total, cart_count


@noauth()
@get("/api/cart")
async def api_get_cart(request, response):
    items = get_cart_items(request.session)
    total = get_cart_total(request.session)
    return response({"items": items, "total": total}, 200)


@noauth()
@post("/api/cart")
async def api_add_to_cart(request, response):
    product_id = str(request.body.get("product_id"))
    quantity = int(request.body.get("quantity", 1))
    cart = request.session.get("cart") or {}
    cart[product_id] = cart.get(product_id, 0) + quantity
    request.session.set("cart", cart)
    return response({"message": "Added to cart", "cart_count": cart_count(request.session)}, 200)


@noauth()
@get("/api/cart/count")
async def api_cart_count(request, response):
    return response({"count": cart_count(request.session)}, 200)
