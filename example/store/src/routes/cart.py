from tina4_python.core.router import get, post, noauth
from tina4_python.core.events import emit
from src.orm.product import Product
from src.app.services.cart_service import get_cart_items, get_cart_total
from src.app.template import render


@get("/cart")
async def view_cart(request, response):
    items = get_cart_items(request.session)
    total = get_cart_total(request.session)
    return response(render("storefront/cart.twig", {"cart_items": items, "cart_total": total}, request))


# @noauth: anonymous users must add to cart before logging in (session-based cart)
@noauth()
@post("/cart/add")
async def add_to_cart(request, response):
    product_id = str(request.body.get("product_id"))
    quantity = int(request.body.get("quantity", 1))
    cart = request.session.get("cart") or {}
    cart[product_id] = cart.get(product_id, 0) + quantity
    request.session.set("cart", cart)

    # Emit event for SSE admin feed
    product = Product.find_by_id(int(product_id))
    product_name = product.name if product else "Unknown"
    if product:
        customer_name = request.session.get("customer_name", "Guest")
        emit("cart.item_added", {
            "product_name": product.name,
            "price": product.price,
            "quantity": quantity,
            "customer": customer_name,
        })

    # AJAX: return JSON; regular form submit: redirect
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        from src.app.services.cart_service import cart_count
        return response({"ok": True, "count": cart_count(request.session), "product_name": product_name})

    request.session.flash("success", "Item added to cart")
    return response.redirect("/cart")


# @noauth: anonymous users must manage cart before logging in (session-based cart)
@noauth()
@post("/cart/remove")
async def remove_from_cart(request, response):
    product_id = str(request.body.get("product_id"))
    cart = request.session.get("cart") or {}
    cart.pop(product_id, None)
    request.session.set("cart", cart)
    request.session.flash("success", "Item removed from cart")
    return response.redirect("/cart")
