"""Cart service -- session-based cart with ORM product lookups.

Demonstrates: ORM lookups, session helpers, inline @tests.
"""
from tina4_python.Testing import tests, expect_equal, expect_true
from src.orm.product import Product


# -- Test helpers (lightweight session stubs) --
# Must be defined before @tests decorators that reference them.
class _EmptySession:
    def get(self, key, default=None):
        return default


class _CartSession:
    def __init__(self, cart):
        self._cart = cart

    def get(self, key, default=None):
        if key == "cart":
            return self._cart
        return default


def get_cart_items(session):
    """Return list of cart items with product details and quantities."""
    cart = session.get("cart") or {}
    if not cart:
        return []
    items = []
    for product_id, quantity in cart.items():
        try:
            pid = int(product_id)
        except (ValueError, TypeError):
            continue
        product = Product.find_by_id(pid)
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


@tests(
    expect_equal((_EmptySession(),), 0),
    expect_equal((_CartSession({"1": 2, "3": 5}),), 7),
    expect_equal((_CartSession({}),), 0),
)
def cart_count(session):
    """Return total number of items in cart."""
    cart = session.get("cart") or {}
    return sum(cart.values())


@tests(
    expect_equal((10.0, 1.0), 10.0),
    expect_equal((25.50, 0.85), 21.68),
    expect_equal((100.0, 0.0), 0.0),
)
def convert_price(price, rate):
    """Convert a price using a forex rate."""
    return round(price * rate, 2)
