from tina4_python.seeder import FakeData
from tina4_python.auth import Auth
from src.orm.category import Category
from src.orm.product import Product
from src.orm.customer import Customer
from src.orm.order import Order
from src.orm.order_item import OrderItem


def seed(db):
    """Seed demo data — deterministic (seed=42) for reproducible demos."""
    # Skip if already seeded
    if Category.count() > 0:
        return

    fake = FakeData(seed=42)

    # Categories
    categories_data = [
        ("Electronics", "electronics", "Gadgets, devices, and tech accessories"),
        ("Clothing", "clothing", "Apparel for all seasons"),
        ("Books", "books", "Fiction, non-fiction, and technical reads"),
        ("Home & Garden", "home-garden", "Everything for your living space"),
        ("Sports", "sports", "Gear and equipment for active living"),
    ]
    for name, slug, desc in categories_data:
        Category.create(name=name, slug=slug, description=desc)

    # Products (50)
    adjectives = ["Premium", "Classic", "Ultra", "Pro", "Essential", "Deluxe", "Smart", "Eco",
                  "Compact", "Vintage"]
    nouns = ["Widget", "Gadget", "Tool", "Kit", "Set", "Pack", "Bundle", "Device", "Gear", "Item"]

    for i in range(50):
        cat_id = (i % 5) + 1
        adj = adjectives[i % len(adjectives)]
        noun = nouns[(i // len(adjectives)) % len(nouns)]
        Product.create(
            category_id=cat_id,
            name=f"{adj} {noun} {i + 1}",
            slug=f"product-{i + 1}",
            description=fake.paragraph(),
            price=round(fake.decimal(5, 200), 2),
            stock=fake.integer(0, 100),
            image_url=f"/uploads/placeholder-{(i % 5) + 1}.svg",
            is_active=True,
        )

    # Admin user
    Customer.create(
        name="Admin",
        email="admin@tina4store.com",
        password_hash=Auth.hash_password("admin123"),
        role="admin",
    )

    # Named demo customer
    Customer.create(
        name="Alice Smith",
        email="alice@example.com",
        password_hash=Auth.hash_password("customer123"),
        role="customer",
    )

    # Additional customers
    for _ in range(9):
        Customer.create(
            name=fake.name(),
            email=fake.email(),
            password_hash=Auth.hash_password("customer123"),
            role="customer",
        )

    # Sample orders for Alice (customer_id=2)
    for i in range(3):
        order = Order.create(
            customer_id=2,
            status=["delivered", "shipped", "pending"][i],
            total=0,
        )
        total = 0
        for j in range(fake.integer(1, 4)):
            product = Product.find_by_id(fake.integer(1, 50))
            qty = fake.integer(1, 3)
            OrderItem.create(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                unit_price=product.price,
            )
            total += product.price * qty
        order.total = round(total, 2)
        order.save()
