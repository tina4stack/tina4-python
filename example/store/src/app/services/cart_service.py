"""Cart service — session-based cart with ORM product lookups."""
from src.orm.product import Product


def get_cart_items(session):
    """Return list of cart items with product details and quantities."""
    cart = session.get("cart") or {}
    if not cart:
        return []
    items = []
    for product_id, quantity in cart.items():
        product = Product.find(int(product_id))
        if product:
            item = product.to_dict()
            item["product_id"] = product.id
            item["quantity"] = quantity
            item["subtotal"] = product.price * quantity
            items.append(item)
    return items


def get_cart_total(session):
    """Return total price of all items in cart."""
    items = get_cart_items(session)
    return sum(item["subtotal"] for item in items)


def cart_count(session):
    """Return total number of items in cart."""
    cart = session.get("cart") or {}
    return sum(cart.values())
