# Tina4 Store — Complete Framework Demo

A fully functional mini e-commerce platform that demonstrates **every** Tina4 feature through
a real-world use case. Every feature has a natural business reason — nothing is forced.

**What you get:** An online store with a customer storefront (SSR + PWA), an admin panel,
REST/GraphQL/SOAP APIs, real-time order tracking, background job processing, email notifications,
and full test coverage — all in a single self-contained application.

## Quick Start

### macOS / Linux (uv)

```bash
cd example
uv sync
uv run python app.py
```

### macOS / Linux (pip)

```bash
cd example
bash setup.sh
.venv/bin/python app.py
```

### Windows

```cmd
cd example
setup.bat
.venv\Scripts\python app.py
```

### Docker (zero setup)

```bash
cd example
docker build -t tina4-store .
docker run -p 7146:7146 tina4-store
```

Open your browser:

| URL | What |
|-----|------|
| http://localhost:7146 | Customer storefront |
| http://localhost:7146/admin | Admin panel |
| http://localhost:7146/swagger | REST API docs |
| http://localhost:7146/api/soap/orders?wsdl | WSDL definition |
| http://localhost:7146/__dev/ | DevAdmin metrics |

**Demo credentials:**

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@tina4store.com | admin123 |
| Customer | alice@example.com | customer123 |

---

## Architecture

```
Browser ──────────────────────────────────────────── Tina4 Server
  │                                                       │
  ├── Storefront (SSR) ──── Frond Templates ──┐           │
  │     └── tina4-js (PWA overlay)            │           │
  │                                           ├── Router ─┤
  ├── Admin Panel (SSR) ─── Frond Templates ──┘           │
  │     └── SSE (live dashboard)                          │
  │                                                       │
  ├── REST API ──────────── Swagger ──────────────────────┤
  ├── GraphQL ────────────── Auto from ORM ───────────────┤
  ├── SOAP/WSDL ─────────── B2B Integration ──────────────┤
  ├── WebSocket ─────────── Order Tracking ───────────────┤
  └── SSE ───────────────── Sales Feed ───────────────────┤
                                                          │
                                          ORM ────── SQLite
                                          Queue ──── File Backend
                                          Events ─── In-Process
                                          Sessions ─ File Backend
                                          Cache ──── In-Memory
                                          Email ──── DevMailbox
```

---

## Feature Map

Every Tina4 feature, where it's used, and why.

| # | Feature | Where Used | Business Reason | Key File(s) |
|---|---------|-----------|-----------------|-------------|
| 1 | **ORM** | All data access | Product catalog, orders, customers | `src/orm/*.py` |
| 2 | **ForeignKeyField** | Product→Category, Order→Customer | Relationships between entities | `src/orm/product.py` |
| 3 | **Soft Delete** | Customer model | Don't lose customer data on delete | `src/orm/customer.py` |
| 4 | **Migrations** | Database schema | Version-controlled schema changes | `migrations/001_create_tables.sql` |
| 5 | **Seeder** | Demo data | 50 products, 10 customers, sample orders | `src/seeds/seed_store.py` |
| 6 | **Frond Templates** | All HTML pages | Server-rendered storefront + admin | `src/templates/*.twig` |
| 7 | **Template Inheritance** | All pages extend base.twig | Consistent layout, DRY | `src/templates/base.twig` |
| 8 | **Tina4CSS** | All pages | Responsive UI without external CSS | `base.twig` → `/css/tina4.min.css` |
| 9 | **SCSS** | Store brand theme | Custom colors, component styles | `src/scss/store.scss` |
| 10 | **i18n** | Storefront text | English + French support | `src/locales/en.json`, `fr.json` |
| 11 | **Auth (JWT)** | Login/register | Customer and admin authentication | `src/routes/auth.py` |
| 12 | **Password Hashing** | Registration | Secure credential storage | `src/routes/auth.py` |
| 13 | **Sessions** | Shopping cart | Persist cart across requests | `src/routes/cart.py` |
| 14 | **Flash Messages** | Cart/checkout | User feedback after actions | `src/routes/cart.py` |
| 15 | **Middleware** | Request logging | Audit trail for all requests | `src/middleware/request_logger.py` |
| 16 | **Rate Limiter** | Checkout | Prevent checkout abuse | `src/routes/checkout.py` |
| 17 | **Admin Auth Middleware** | Admin panel | Role-based access control | `src/middleware/admin_auth.py` |
| 18 | **REST API** | Product/order CRUD | Mobile app + third-party integration | `src/routes/api/products.py` |
| 19 | **Swagger** | API documentation | Auto-generated OpenAPI docs | `@description`, `@tags` decorators |
| 20 | **Auto-CRUD** | Admin product/category mgmt | Zero-code CRUD endpoints | `app.py` → `AutoCrud.register()` |
| 21 | **Caching** | Product catalog pages | Fast page loads for hot data | `@cached(True, max_age=120)` |
| 22 | **GraphQL** | Flexible product queries | Filter by category, price, stock | `src/routes/api/graphql.py` |
| 23 | **WSDL/SOAP** | B2B order placement | Legacy POS/supplier integration | `src/routes/api/wsdl.py` |
| 24 | **WebSocket** | Order status tracking | Real-time "Preparing→Shipped→Delivered" | `src/routes/api/ws.py` |
| 25 | **SSE** | Admin sales dashboard | Live sales ticker without polling | `src/routes/api/sse.py` |
| 26 | **Queue** | Order processing | Validate→process→notify pipeline | `src/app/services/order_service.py` |
| 27 | **Events** | Decoupled notifications | `order.placed` triggers email + stock | `src/app/services/notification_service.py` |
| 28 | **Messenger** | Order confirmation email | Send confirmation after purchase | `src/app/services/notification_service.py` |
| 29 | **File Upload** | Product images | Admin uploads product photos | `src/routes/api/upload.py` |
| 30 | **Container (DI)** | App-wide singletons | Database, queue, i18n, mailer | `app.py` |
| 31 | **Error Overlay** | Dev mode debugging | Rich error pages during development | Auto when `TINA4_DEBUG=true` |
| 32 | **DevAdmin** | Framework metrics | Built-in dashboard at `/__dev/` | Auto when `TINA4_DEBUG=true` |
| 33 | **tina4-js (PWA)** | Storefront enhancement | Reactive cart, offline browse, install | `src/public/js/store.js` |
| 34 | **tina4-js Signals** | Cart counter, order status | Reactive UI without a framework | `src/public/js/store.js` |
| 35 | **Service Worker** | Offline support | Browse products without network | `pwa.register()` in store.js |

---

## 1. Project Setup

### Environment Configuration (`.env`)

All Tina4 apps use a `.env` file. Keys are identical across Python, PHP, Ruby, and Node.js:

```env
# Database
TINA4_DATABASE_URL=sqlite:///data/store.db

# Security
SECRET=tina4-store-demo-secret-change-me
TINA4_DEBUG=true
TINA4_DEBUG_LEVEL=DEBUG

# i18n
TINA4_LANGUAGE=en

# Sessions
TINA4_SESSION_HANDLER=file

# Swagger
SWAGGER_TITLE=Tina4 Store API
SWAGGER_DESCRIPTION=Complete e-commerce API demo
SWAGGER_VERSION=1.0.0

# Email (DevMailbox captures all email in dev mode)
TINA4_MAIL_HOST=localhost
TINA4_MAIL_PORT=25
TINA4_MAIL_FROM=store@tina4store.com
TINA4_MAIL_FROM_NAME=Tina4 Store
```

### Dependency Injection Container (`app.py`)

The Container provides app-wide singletons — database, queue, i18n, and mailer are created once
and shared everywhere:

```python
from tina4_python.container import Container
from tina4_python.database import Database
from tina4_python.queue import Queue
from tina4_python.i18n import I18n
from tina4_python.messenger import create_messenger

container = Container()
container.singleton("db", lambda: Database("sqlite:///data/store.db"))
container.singleton("queue", lambda: Queue(topic="orders"))
container.singleton("i18n", lambda: I18n(locale_dir="src/locales", default_locale="en"))
container.singleton("mail", lambda: create_messenger())

db = container.get("db")
```

**Why Container?** Instead of scattering `Database(...)` calls across files, register once and
`container.get("db")` everywhere. Singletons guarantee one connection pool, one queue instance.

### Database & Migrations

Schema is defined in a single SQL migration file:

```sql
-- migrations/001_create_tables.sql
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    price REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    image_url VARCHAR(500),
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL UNIQUE,
    password_hash VARCHAR(500) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'customer',
    is_deleted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total REAL NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR(100) NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
```

Migrations run automatically on startup:

```python
from tina4_python.migration import migrate
migrate(db)
```

---

## 2. Data Models (ORM)

Each model lives in its own file under `src/orm/`. Models are auto-discovered — no manual imports.

### Category (`src/orm/category.py`)

```python
from tina4_python.orm import ORM, IntegerField, StringField

class Category(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    slug = StringField()
    description = StringField()
```

### Product (`src/orm/product.py`)

Demonstrates **ForeignKeyField** — auto-wires `belongs_to` on Product and `has_many` on Category:

```python
from tina4_python.orm import ORM, IntegerField, StringField, FloatField, BooleanField, ForeignKeyField
from src.orm.category import Category

class Product(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    category_id = ForeignKeyField(to=Category, related_name="products")
    name = StringField()
    slug = StringField()
    description = StringField()
    price = FloatField()
    stock = IntegerField()
    image_url = StringField()
    is_active = BooleanField()
```

Now you can:
```python
product = Product.find(1, include=["category"])  # Eager load category
product.category  # → Category instance

category = Category.find(1, include=["products"])
category.products  # → [Product, Product, ...]
```

### Customer (`src/orm/customer.py`)

Demonstrates **soft delete** — customers are never truly removed:

```python
from tina4_python.orm import ORM, IntegerField, StringField

class Customer(ORM):
    soft_delete = True  # Uses is_deleted column (INTEGER 0/1)

    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
    password_hash = StringField()
    role = StringField()  # "customer" or "admin"
```

Soft delete behavior:
```python
customer.delete()                    # Sets is_deleted = 1 (not visible in queries)
customer.force_delete()              # Actually removes the row
customer.restore()                   # Sets is_deleted = 0
Customer.with_trashed()              # Query including soft-deleted
```

### Order (`src/orm/order.py`)

```python
from tina4_python.orm import ORM, IntegerField, StringField, FloatField, ForeignKeyField
from src.orm.customer import Customer

class Order(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    customer_id = ForeignKeyField(to=Customer, related_name="orders")
    status = StringField()      # pending, processing, shipped, delivered, cancelled
    total = FloatField()
    created_at = StringField()
    updated_at = StringField()
```

### OrderItem (`src/orm/order_item.py`)

```python
from tina4_python.orm import ORM, IntegerField, FloatField, ForeignKeyField
from src.orm.order import Order
from src.orm.product import Product

class OrderItem(ORM):
    table_name = "order_items"

    id = IntegerField(primary_key=True, auto_increment=True)
    order_id = ForeignKeyField(to=Order, related_name="items")
    product_id = ForeignKeyField(to=Product)
    quantity = IntegerField()
    unit_price = FloatField()
```

### CartItem (`src/orm/cart_item.py`)

```python
from tina4_python.orm import ORM, IntegerField, StringField, ForeignKeyField
from src.orm.product import Product

class CartItem(ORM):
    table_name = "cart_items"

    id = IntegerField(primary_key=True, auto_increment=True)
    session_id = StringField()
    product_id = ForeignKeyField(to=Product)
    quantity = IntegerField()
```

### ORM Usage Patterns

```python
# Create
product = Product.create(name="Widget", price=29.99, stock=100, is_active=True, ...)

# Find
product = Product.find(1)
product = Product.find_or_fail(1)  # Raises ValueError if not found

# Query
products = Product.where("is_active = ? AND price < ?", [True, 50], limit=20)
products = Product.all(limit=50, offset=0, include=["category"])

# Update
product.price = 24.99
product.save()

# Count
total = Product.count("is_active = ?", [True])

# Pagination
products = Product.where("category_id = ?", [3], limit=12, offset=24)
```

---

## 3. Storefront — Server Rendering

### Template Inheritance (`base.twig`)

Every page extends a master layout. Tina4CSS and tina4-js are built-in — no CDN or npm:

```twig
{# src/templates/base.twig #}
<!DOCTYPE html>
<html lang="{{ locale|default('en') }}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Tina4 Store{% endblock %}</title>
    <link rel="stylesheet" href="/css/tina4.min.css">
    <link rel="stylesheet" href="/css/store.css">
</head>
<body>
    {% include "partials/nav.twig" %}
    {% include "partials/flash_messages.twig" %}

    <main class="container mt-4">
        {% block content %}{% endblock %}
    </main>

    <footer class="container mt-5 mb-3 text-center text-muted">
        <p>{{ t("footer.powered_by") }} <a href="https://tina4.com">Tina4</a></p>
    </footer>

    <script src="/js/tina4js.min.js"></script>
    <script src="/js/store.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

### Product Listing with Caching

```python
# src/routes/products.py
from tina4_python.core.router import get, cached
from src.orm.product import Product

@cached(True, max_age=120)
@get("/products")
async def product_list(request, response):
    page = int(request.query.get("page", 1))
    per_page = 12
    offset = (page - 1) * per_page

    products = Product.where("is_active = ?", [True], limit=per_page, offset=offset,
                             include=["category"])
    total = Product.count("is_active = ?", [True])

    return response.render("storefront/products.twig", {
        "products": [p.to_dict(include=["category"]) for p in products],
        "page": page,
        "total_pages": (total + per_page - 1) // per_page,
    })
```

### i18n (Internationalization)

Locale files define all user-facing strings:

```json
// src/locales/en.json
{
    "nav": {
        "home": "Home",
        "products": "Products",
        "cart": "Cart",
        "login": "Login",
        "admin": "Admin"
    },
    "store": {
        "add_to_cart": "Add to Cart",
        "checkout": "Checkout",
        "order_placed": "Your order has been placed!",
        "empty_cart": "Your cart is empty"
    },
    "footer": {
        "powered_by": "Powered by"
    }
}
```

```json
// src/locales/fr.json
{
    "nav": {
        "home": "Accueil",
        "products": "Produits",
        "cart": "Panier",
        "login": "Connexion",
        "admin": "Admin"
    },
    "store": {
        "add_to_cart": "Ajouter au panier",
        "checkout": "Commander",
        "order_placed": "Votre commande a été passée !",
        "empty_cart": "Votre panier est vide"
    },
    "footer": {
        "powered_by": "Propulsé par"
    }
}
```

Switch language via API:
```python
@get("/api/locale/{lang}")
async def switch_locale(request, response):
    lang = request.params.get("lang", "en")
    i18n = container.get("i18n")
    i18n.set_locale(lang)
    request.session.set("locale", lang)
    return response({"locale": lang})
```

### SCSS Theming

Custom brand styles override Tina4CSS variables:

```scss
// src/scss/store.scss
:root {
    --primary: #2d6a4f;
    --primary-hover: #1b4332;
    --accent: #d4a373;
    --bg: #fefae0;
    --card-bg: #ffffff;
}

.product-card {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    transition: box-shadow 0.2s;

    &:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    .product-image {
        width: 100%;
        aspect-ratio: 1;
        object-fit: cover;
        border-radius: 4px;
    }

    .product-price {
        color: var(--primary);
        font-weight: bold;
        font-size: 1.25rem;
    }
}

.badge-cart {
    background: var(--accent);
    color: #fff;
    border-radius: 50%;
    padding: 0.15rem 0.5rem;
    font-size: 0.75rem;
}
```

SCSS files in `src/scss/` auto-compile to `src/public/css/` when `TINA4_DEBUG=true`.

---

## 4. Authentication & Sessions

### Customer Registration & Login

```python
# src/routes/auth.py
from tina4_python.core.router import get, post, noauth, template
from tina4_python.auth import Auth, get_token
from tina4_python.core.events import emit
from src.orm.customer import Customer

@noauth()
@template("storefront/login.twig")
@get("/login")
async def login_page(request, response):
    return {}

@noauth()
@post("/login")
async def login(request, response):
    email = request.body.get("email")
    password = request.body.get("password")

    customers = Customer.where("email = ?", [email])
    if not customers or not Auth.check_password(password, customers[0].password_hash):
        request.session.flash("error", "Invalid email or password")
        return response.redirect("/login")

    customer = customers[0]
    token = get_token({"sub": customer.id, "role": customer.role}, expires_in=480)
    request.session.set("token", token)
    request.session.set("customer_id", customer.id)
    request.session.set("customer_name", customer.name)
    request.session.set("role", customer.role)

    return response.redirect("/account" if customer.role == "customer" else "/admin")

@noauth()
@post("/register")
async def register(request, response):
    name = request.body.get("name")
    email = request.body.get("email")
    password = request.body.get("password")

    # Check if email taken
    if Customer.where("email = ?", [email]):
        request.session.flash("error", "Email already registered")
        return response.redirect("/login")

    customer = Customer.create(
        name=name,
        email=email,
        password_hash=Auth.hash_password(password),
        role="customer"
    )

    emit("customer.registered", {"id": customer.id, "name": name, "email": email})

    request.session.flash("success", "Account created! Please log in.")
    return response.redirect("/login")

@get("/logout")
async def logout(request, response):
    request.session.destroy()
    return response.redirect("/")
```

### Session-Based Shopping Cart

```python
# src/routes/cart.py
from tina4_python.core.router import get, post
from src.orm.product import Product

@get("/cart")
async def view_cart(request, response):
    cart = request.session.get("cart", {})
    items = []
    total = 0

    for product_id, qty in cart.items():
        product = Product.find(int(product_id))
        if product:
            subtotal = product.price * qty
            total += subtotal
            items.append({
                "product": product.to_dict(),
                "quantity": qty,
                "subtotal": subtotal
            })

    return response.render("storefront/cart.twig", {
        "items": items,
        "total": total,
        "flash": request.session.get_flash("success")
    })

@post("/cart/add")
async def add_to_cart(request, response):
    product_id = str(request.body.get("product_id"))
    quantity = int(request.body.get("quantity", 1))

    cart = request.session.get("cart", {})
    cart[product_id] = cart.get(product_id, 0) + quantity
    request.session.set("cart", cart)

    request.session.flash("success", "Added to cart!")
    return response.redirect(request.headers.get("Referer", "/products"))

@post("/cart/remove")
async def remove_from_cart(request, response):
    product_id = str(request.body.get("product_id"))
    cart = request.session.get("cart", {})
    cart.pop(product_id, None)
    request.session.set("cart", cart)
    return response.redirect("/cart")
```

---

## 5. REST API

### Swagger-Documented Endpoints

Every API route uses `@description` and `@tags` to auto-generate OpenAPI documentation
at `/swagger`:

```python
# src/routes/api/products.py
from tina4_python.core.router import get, post, put, delete, noauth, secured, cached
from tina4_python.swagger import description, tags, example
from src.orm.product import Product

@noauth()
@cached(True, max_age=120)
@description("List all active products with pagination")
@tags("Products")
@example({"records": [{"id": 1, "name": "Widget", "price": 29.99}], "total": 50})
@get("/api/products")
async def list_products(request, response):
    page = int(request.query.get("page", 1))
    limit = int(request.query.get("limit", 20))
    offset = (page - 1) * limit
    category = request.query.get("category")

    filter_sql = "is_active = ?"
    params = [True]
    if category:
        filter_sql += " AND category_id = ?"
        params.append(int(category))

    products = Product.where(filter_sql, params, limit=limit, offset=offset,
                             include=["category"])
    total = Product.count(filter_sql, params)

    return response({
        "records": [p.to_dict(include=["category"]) for p in products],
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
    })

@noauth()
@description("Get a single product by ID")
@tags("Products")
@get("/api/products/{id:int}")
async def get_product(request, response):
    product = Product.find(request.params["id"], include=["category"])
    if not product:
        return response({"error": "Product not found"}, 404)
    return response(product.to_dict(include=["category"]))
```

### Auto-CRUD

For admin management, Auto-CRUD generates full REST endpoints with zero code:

```python
# In app.py
from tina4_python.crud import AutoCrud
from src.orm.product import Product
from src.orm.category import Category

AutoCrud.register(Product, prefix="/api")
AutoCrud.register(Category, prefix="/api")

# Auto-generates:
# GET    /api/product          — list with pagination
# GET    /api/product/{id}     — get single
# POST   /api/product          — create
# PUT    /api/product/{id}     — update
# DELETE /api/product/{id}     — delete
# (same for /api/category)
```

### Rate Limiting

Checkout is rate-limited to prevent abuse:

```python
# src/routes/checkout.py
from tina4_python.core.router import post, secured, middleware
from tina4_python.core.rate_limiter import RateLimiter

@middleware(RateLimiter)
@secured()
@post("/checkout")
async def checkout(request, response):
    # ... process order (see Section 9: Background Processing)
```

---

## 6. GraphQL

Auto-generated from ORM models — zero schema writing:

```python
# src/routes/api/graphql.py
from tina4_python.core.router import get, post, noauth
from tina4_python.graphql import GraphQL
from src.orm.product import Product
from src.orm.category import Category

gql = GraphQL()
gql.schema.from_orm(Product)    # Auto: product(id), products(limit, offset)
gql.schema.from_orm(Category)   # Auto: category(id), categories(limit, offset)

# Custom resolver: products by price range
gql.schema.add_query(
    "products_by_price",
    {"min_price": "Float!", "max_price": "Float!", "limit": "Int"},
    "[Product]",
    lambda root, args, ctx: [
        p.to_dict() for p in Product.where(
            "price >= ? AND price <= ? AND is_active = ?",
            [args["min_price"], args["max_price"], True],
            limit=args.get("limit", 20)
        )
    ]
)

@noauth()
@post("/api/graphql")
async def graphql_endpoint(request, response):
    query = request.body.get("query", "")
    variables = request.body.get("variables", {})
    result = gql.execute(query, variables)
    return response(result)
```

**Example queries:**

```graphql
# Get product with category
{
  product(id: 1) {
    name
    price
    category {
      name
    }
  }
}

# Filter by price range
{
  products_by_price(min_price: 10, max_price: 50, limit: 5) {
    name
    price
    stock
  }
}
```

---

## 7. SOAP/WSDL (B2B Integration)

Enterprise suppliers place orders via a SOAP endpoint:

```python
# src/routes/api/wsdl.py
from tina4_python.core.router import get, post, noauth
from tina4_python.wsdl import WSDL, wsdl_operation
from src.orm.product import Product
from src.orm.order import Order
from src.orm.order_item import OrderItem

class OrderService(WSDL):
    """B2B order placement for enterprise integrations."""

    @wsdl_operation({"OrderId": int, "Status": str, "Total": float})
    def PlaceOrder(self, ProductId: int, Quantity: int, CustomerEmail: str):
        product = Product.find(ProductId)
        if not product:
            return {"OrderId": 0, "Status": "error", "Total": 0.0}

        if product.stock < Quantity:
            return {"OrderId": 0, "Status": "insufficient_stock", "Total": 0.0}

        total = product.price * Quantity
        order = Order.create(customer_id=1, status="pending", total=total)
        OrderItem.create(order_id=order.id, product_id=ProductId,
                        quantity=Quantity, unit_price=product.price)

        product.stock -= Quantity
        product.save()

        return {"OrderId": order.id, "Status": "pending", "Total": total}

    @wsdl_operation({"OrderId": int, "Status": str})
    def GetOrderStatus(self, OrderId: int):
        order = Order.find(OrderId)
        if not order:
            return {"OrderId": OrderId, "Status": "not_found"}
        return {"OrderId": order.id, "Status": order.status}

@noauth()
@get("/api/soap/orders")
@post("/api/soap/orders")
async def soap_orders(request, response):
    service = OrderService(request, service_url="/api/soap/orders")
    return response(service.handle())
```

- **GET `/api/soap/orders?wsdl`** → Returns WSDL definition
- **POST `/api/soap/orders`** → Accepts SOAP XML envelope, invokes operation

---

## 8. Real-Time

### WebSocket — Order Tracking

Customers track their order status in real time. Each order gets its own WebSocket room:

```python
# src/routes/api/ws.py
from tina4_python.websocket import WebSocketServer

ws_server = WebSocketServer("0.0.0.0", 7146)

@ws_server.on_connect("/ws/orders")
async def on_connect(ws):
    # Client sends order ID to join the room
    pass

@ws_server.route("/ws/orders")
async def order_tracking(ws):
    async for message in ws:
        data = message if isinstance(message, dict) else {"action": message}
        if data.get("action") == "track":
            order_id = data.get("order_id")
            ws.join_room(f"order_{order_id}")
            await ws.send_json({"event": "joined", "order_id": order_id})

@ws_server.on_disconnect("/ws/orders")
async def on_disconnect(ws):
    pass
```

When the order status changes (from the queue worker), broadcast to the room:

```python
# In order_service.py
await ws_server.manager.broadcast_to_room(
    f"order_{order_id}",
    json.dumps({"event": "status_changed", "order_id": order_id, "status": new_status})
)
```

### SSE — Admin Sales Dashboard

Live sales feed pushed to the admin dashboard:

```python
# src/routes/api/sse.py
import asyncio
import json
from tina4_python.core.router import get, secured

# Global sales queue — events pushed here from order processing
sales_events = asyncio.Queue()

@secured()
@get("/api/events/sales")
async def sales_stream(request, response):
    async def generate():
        while True:
            try:
                event = await asyncio.wait_for(sales_events.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield f": keepalive\n\n"  # Prevent connection timeout

    return response.stream(generate())
```

The admin dashboard template connects via JavaScript:

```javascript
// In admin/dashboard.twig
const source = new EventSource("/api/events/sales");
source.onmessage = (e) => {
    const sale = JSON.parse(e.data);
    addSaleToTicker(sale);  // Update UI
};
```

---

## 9. Background Processing

### Queue — Order Pipeline

When a customer checks out, the order is pushed to a queue. A background worker processes it
in stages:

```python
# src/routes/checkout.py
from tina4_python.core.router import post, secured, middleware
from tina4_python.core.rate_limiter import RateLimiter
from tina4_python.core.events import emit
from tina4_python.queue import Queue

@middleware(RateLimiter)
@secured()
@post("/checkout")
async def checkout(request, response):
    cart = request.session.get("cart", {})
    if not cart:
        return response({"error": "Cart is empty"}, 400)

    customer_id = request.session.get("customer_id")

    # Create order
    order = Order.create(customer_id=customer_id, status="pending", total=0)
    total = 0
    for product_id, qty in cart.items():
        product = Product.find(int(product_id))
        OrderItem.create(order_id=order.id, product_id=product.id,
                        quantity=qty, unit_price=product.price)
        total += product.price * qty

    order.total = total
    order.save()

    # Push to queue for async processing
    queue = container.get("queue")
    queue.push({
        "order_id": order.id,
        "customer_id": customer_id,
        "action": "process"
    })

    # Fire event (handled by notification service)
    emit("order.placed", {"order_id": order.id, "total": total, "customer_id": customer_id})

    # Clear cart
    request.session.set("cart", {})
    request.session.flash("success", f"Order #{order.id} placed!")

    return response.redirect(f"/account/orders/{order.id}")
```

### Queue Worker (`src/app/services/order_service.py`)

```python
from tina4_python.queue import Queue

def process_orders(container):
    queue = container.get("queue")

    for job in queue.consume("orders", poll_interval=2.0):
        data = job.data
        order_id = data["order_id"]

        try:
            order = Order.find(order_id)
            if not order:
                job.fail("Order not found")
                continue

            # Step 1: Validate stock
            items = OrderItem.where("order_id = ?", [order_id])
            for item in items:
                product = Product.find(item.product_id)
                if product.stock < item.quantity:
                    order.status = "cancelled"
                    order.save()
                    job.fail(f"Insufficient stock for product {product.id}")
                    continue

            # Step 2: Deduct stock
            for item in items:
                product = Product.find(item.product_id)
                product.stock -= item.quantity
                product.save()
                if product.stock < 5:
                    emit("stock.low", {"product_id": product.id, "stock": product.stock})

            # Step 3: Update status
            order.status = "processing"
            order.save()

            # Step 4: Notify (triggers email + WebSocket)
            emit("order.processing", {"order_id": order_id})

            job.complete()

        except Exception as e:
            job.fail(str(e))
```

### Events — Decoupled Notifications (`src/app/services/notification_service.py`)

```python
from tina4_python.core.events import on
from tina4_python.messenger import create_messenger

@on("order.placed")
def on_order_placed(data):
    """Push to SSE sales feed + send confirmation email."""
    # Push to admin SSE
    from src.routes.api.sse import sales_events
    sales_events.put_nowait({
        "type": "new_order",
        "order_id": data["order_id"],
        "total": data["total"]
    })

    # Send confirmation email
    mail = create_messenger()
    customer = Customer.find(data["customer_id"])
    if customer:
        mail.send_template(
            to=customer.email,
            subject=f"Order #{data['order_id']} Confirmed",
            template="email/order_confirmation.twig",
            data={"order_id": data["order_id"], "total": data["total"], "name": customer.name}
        )

@on("order.processing")
async def on_order_processing(data):
    """Broadcast status update via WebSocket."""
    from src.routes.api.ws import ws_server
    import json
    await ws_server.manager.broadcast_to_room(
        f"order_{data['order_id']}",
        json.dumps({"event": "status_changed", "status": "processing"})
    )

@on("stock.low")
def on_stock_low(data):
    """Alert admin via SSE."""
    from src.routes.api.sse import sales_events
    sales_events.put_nowait({
        "type": "low_stock",
        "product_id": data["product_id"],
        "stock": data["stock"]
    })
```

---

## 10. File Uploads

Admin uploads product images:

```python
# src/routes/api/upload.py
import os
from tina4_python.core.router import post, secured
from tina4_python.swagger import description, tags

@secured()
@description("Upload a product image")
@tags("Products")
@post("/api/upload/product-image")
async def upload_product_image(request, response):
    file = request.files.get("image")
    if not file:
        return response({"error": "No image provided"}, 400)

    # Validate type
    allowed = ["image/jpeg", "image/png", "image/webp"]
    if file["type"] not in allowed:
        return response({"error": f"Invalid type: {file['type']}"}, 422)

    # Save to uploads
    filename = f"{file['filename']}"
    path = os.path.join("src", "public", "uploads", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "wb") as f:
        f.write(file["content"])  # Raw bytes — NOT base64

    url = f"/uploads/{filename}"
    return response({"url": url, "filename": filename})
```

---

## 11. Email (Messenger)

Order confirmation emails use Frond templates:

```twig
{# src/templates/email/order_confirmation.twig #}
<h1>Order Confirmed!</h1>
<p>Hi {{ name }},</p>
<p>Your order <strong>#{{ order_id }}</strong> has been received.</p>
<p>Total: <strong>${{ "%.2f"|format(total) }}</strong></p>
<p>We'll notify you when it ships.</p>
<hr>
<p style="color: #666; font-size: 12px;">Tina4 Store — tina4.com</p>
```

In dev mode (`TINA4_DEBUG=true`), all emails are captured by DevMailbox instead of being sent.
View them at `/__dev/mailbox`.

---

## 12. PWA (tina4-js)

The storefront has a progressive enhancement layer using tina4-js — the sub-3KB reactive
frontend framework bundled with Tina4:

```javascript
// src/public/js/store.js
const { signal, computed, html, api, ws, sse, pwa, Tina4Element } = Tina4;

// ── PWA Registration ──────────────────────────────────────────
pwa.register({
    name: "Tina4 Store",
    shortName: "T4Store",
    themeColor: "#2d6a4f",
    backgroundColor: "#fefae0",
    display: "standalone",
    cacheStrategy: "network-first",
    precache: ["/", "/products", "/css/tina4.min.css", "/css/store.css"],
    offlineRoute: "/offline"
});

// ── Reactive Cart Badge ───────────────────────────────────────
const cartCount = signal(0);

// Fetch initial count from session
api.get("/api/cart/count").then(r => { cartCount.value = r.body.count; });

// Cart badge component — updates reactively
class CartBadge extends Tina4Element {
    render() {
        return html`<span class="badge-cart">${cartCount}</span>`;
    }
}
customElements.define("cart-badge", CartBadge);

// ── Add to Cart (AJAX) ───────────────────────────────────────
document.querySelectorAll("[data-add-to-cart]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
        e.preventDefault();
        const productId = btn.dataset.addToCart;
        await api.post("/api/cart", { product_id: productId, quantity: 1 });
        cartCount.value++;
    });
});

// ── WebSocket Order Tracking ──────────────────────────────────
const orderStatus = signal("pending");

function trackOrder(orderId) {
    const socket = ws.connect(`ws://localhost:7146/ws/orders`);
    socket.onopen = () => {
        socket.send(JSON.stringify({ action: "track", order_id: orderId }));
    };
    socket.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.event === "status_changed") {
            orderStatus.value = data.status;
        }
    };
}

// Order tracking component
class OrderTracker extends Tina4Element {
    render() {
        const statuses = ["pending", "processing", "shipped", "delivered"];
        const current = statuses.indexOf(orderStatus.value);
        return html`
            <div class="order-tracker">
                ${statuses.map((s, i) => html`
                    <div class="step ${i <= current ? 'active' : ''}">
                        <div class="dot"></div>
                        <span>${s}</span>
                    </div>
                `)}
            </div>
        `;
    }
}
customElements.define("order-tracker", OrderTracker);

// ── Language Switcher ─────────────────────────────────────────
document.querySelectorAll("[data-lang]").forEach(btn => {
    btn.addEventListener("click", async () => {
        await api.get(`/api/locale/${btn.dataset.lang}`);
        location.reload();
    });
});
```

**What this gives you:**
- **Offline support** — Products page works without network (service worker caches it)
- **Add to homescreen** — Mobile users get an app-like experience
- **Reactive cart** — Badge updates instantly without page reload
- **Live order tracking** — Status changes appear in real time via WebSocket
- **Zero build step** — No webpack, no npm. Just a `<script>` tag.

---

## 13. Developer Tools

### Error Overlay

When `TINA4_DEBUG=true`, any unhandled exception renders a rich HTML error page with:
- Exception type and message
- Full stack trace with source code context
- Request details (headers, body, params)
- Environment info

### DevAdmin

Built-in dashboard at `/__dev/` showing:
- Request metrics (count, latency, status codes)
- Active WebSocket connections
- Queue status (pending, processing, failed)
- Database query log
- Email captures (DevMailbox)

### Seeder

Load demo data for development:

```python
# src/seeds/seed_store.py
from tina4_python.seeder import FakeData, seed_orm
from tina4_python.auth import Auth
from src.orm.category import Category
from src.orm.product import Product
from src.orm.customer import Customer

def seed(db):
    fake = FakeData(seed=42)  # Deterministic for reproducible demos

    # Categories
    categories = ["Electronics", "Clothing", "Books", "Home & Garden", "Sports"]
    for name in categories:
        Category.create(name=name, slug=name.lower().replace(" & ", "-").replace(" ", "-"),
                       description=fake.sentence())

    # Products (50)
    for i in range(50):
        cat = Category.find(fake.integer(1, len(categories)))
        Product.create(
            category_id=cat.id,
            name=f"{fake.word().title()} {fake.word().title()}",
            slug=f"product-{i+1}",
            description=fake.paragraph(),
            price=fake.decimal(5, 200),
            stock=fake.integer(0, 100),
            image_url=f"/uploads/placeholder-{(i % 5) + 1}.webp",
            is_active=True
        )

    # Admin user
    Customer.create(
        name="Admin",
        email="admin@tina4store.com",
        password_hash=Auth.hash_password("admin123"),
        role="admin"
    )

    # Demo customers (10)
    Customer.create(
        name="Alice Smith",
        email="alice@example.com",
        password_hash=Auth.hash_password("customer123"),
        role="customer"
    )
    for _ in range(9):
        Customer.create(
            name=fake.name(),
            email=fake.email(),
            password_hash=Auth.hash_password("customer123"),
            role="customer"
        )
```

---

## 14. Middleware

### Request Logger

Logs every incoming request — demonstrates custom middleware:

```python
# src/middleware/request_logger.py
import time
from tina4_python.debug import Log

class RequestLogger:
    @staticmethod
    def before(request, response):
        request._start_time = time.time()
        return True  # Continue to route handler

    @staticmethod
    def after(request, response):
        duration = (time.time() - request._start_time) * 1000
        Log.info(f"{request.method} {request.url} → {response.status_code} ({duration:.1f}ms)")
```

### Admin Auth Guard

Protects admin routes — checks JWT role:

```python
# src/middleware/admin_auth.py
from tina4_python.auth import valid_token

class AdminAuth:
    @staticmethod
    def before(request, response):
        token = request.session.get("token") if hasattr(request, "session") else None
        if not token:
            return response.redirect("/login")

        payload = valid_token(token)
        if not payload or payload.get("role") != "admin":
            return response({"error": "Admin access required"}, 403)

        return True  # Continue
```

Usage:
```python
@middleware(AdminAuth)
@get("/admin")
async def admin_dashboard(request, response):
    ...
```

---

## 15. Testing

Run all store tests:

```bash
cd /path/to/tina4-python
.venv/bin/python -m pytest example/store/tests/ -v
```

### Test Coverage Map

| Test File | What It Tests | Features Covered |
|-----------|--------------|-----------------|
| `test_models.py` | CRUD for all 6 models | ORM, ForeignKeyField, soft delete |
| `test_auth.py` | Login, register, JWT, roles | Auth, password hashing, sessions |
| `test_cart.py` | Add/remove/view cart | Sessions, flash messages |
| `test_checkout.py` | End-to-end order flow | Queue, events, middleware |
| `test_api.py` | REST endpoints | Swagger, caching, pagination |
| `test_graphql.py` | GraphQL queries | GraphQL, ORM auto-generation |
| `test_wsdl.py` | SOAP requests | WSDL, XML parsing |
| `test_websocket.py` | WS connection + messages | WebSocket, rooms |
| `test_sse.py` | SSE stream | Streaming response |
| `test_queue.py` | Push/consume/retry | Queue, job lifecycle |
| `test_events.py` | Emit/on/once | Event system |
| `test_i18n.py` | Locale switching | i18n |
| `test_middleware.py` | Rate limiter, admin guard | Middleware |

---

## 16. Porting to Other Languages

This store is designed for cross-framework parity. The same app structure, routes, templates,
and business logic apply to all four Tina4 implementations:

| Component | Python | PHP | Ruby | Node.js |
|-----------|--------|-----|------|---------|
| Entry point | `app.py` | `index.php` | `app.rb` | `app.ts` |
| ORM fields | `IntegerField()` | `$id` (type hints) | `integer_field` | `IntegerField()` |
| Route decorator | `@get("/path")` | `Router::get("/path", ...)` | `Tina4::Router.get("/path")` | `Router.get("/path", ...)` |
| Template | `response.render("t.twig", data)` | `$response->render("t.twig", $data)` | `response.render("t.twig", data)` | `res.html("t.twig", data)` |
| JWT | `get_token(payload)` | `Auth::getToken($payload)` | `Auth.get_token(payload)` | `Auth.getToken(payload)` |
| Queue | `queue.push(data)` | `$queue->push($data)` | `queue.push(data)` | `queue.push(data)` |
| WebSocket | `ws.send(msg)` | `$ws->send($msg)` | `ws.send(msg)` | `ws.send(msg)` |

The templates (`.twig` files), locales (`.json`), migrations (`.sql`), and SCSS are **identical**
across all four frameworks — copy them directly.

---

## Appendix A: Complete Route Table

| Method | Path | Auth | Cache | Middleware | Handler |
|--------|------|------|-------|-----------|---------|
| GET | `/` | Public | Yes | Logger | `routes/index.py` |
| GET | `/products` | Public | Yes | Logger | `routes/products.py` |
| GET | `/products/{slug}` | Public | Yes | Logger | `routes/products.py` |
| GET | `/cart` | Public | No | Logger | `routes/cart.py` |
| POST | `/cart/add` | Public | No | Logger | `routes/cart.py` |
| POST | `/cart/remove` | Public | No | Logger | `routes/cart.py` |
| POST | `/checkout` | JWT | No | RateLimiter, Logger | `routes/checkout.py` |
| GET | `/login` | Public | No | Logger | `routes/auth.py` |
| POST | `/login` | Public | No | Logger | `routes/auth.py` |
| POST | `/register` | Public | No | Logger | `routes/auth.py` |
| GET | `/logout` | Public | No | Logger | `routes/auth.py` |
| GET | `/account` | JWT | No | Logger | `routes/account.py` |
| GET | `/account/orders/{id}` | JWT | No | Logger | `routes/account.py` |
| GET | `/admin` | Admin | No | AdminAuth, Logger | `routes/admin/dashboard.py` |
| GET | `/admin/products` | Admin | No | AdminAuth | `routes/admin/products.py` |
| GET | `/admin/categories` | Admin | No | AdminAuth | `routes/admin/categories.py` |
| GET | `/admin/orders` | Admin | No | AdminAuth | `routes/admin/orders.py` |
| GET | `/api/products` | Public | Yes | Logger | `routes/api/products.py` |
| GET | `/api/products/{id}` | Public | Yes | Logger | `routes/api/products.py` |
| GET | `/api/categories` | Public | Yes | — | Auto-CRUD |
| POST | `/api/cart` | Public | No | — | `routes/api/cart.py` |
| GET | `/api/cart/count` | Public | No | — | `routes/api/cart.py` |
| GET | `/api/orders` | JWT | No | — | `routes/api/orders.py` |
| POST | `/api/graphql` | Public | No | — | `routes/api/graphql.py` |
| GET/POST | `/api/soap/orders` | Public | No | — | `routes/api/wsdl.py` |
| GET | `/api/events/sales` | JWT | No | — | `routes/api/sse.py` |
| WS | `/ws/orders` | — | — | — | `routes/api/ws.py` |
| POST | `/api/upload/product-image` | JWT | No | — | `routes/api/upload.py` |
| GET | `/api/locale/{lang}` | Public | No | — | `routes/api/i18n.py` |

## Appendix B: Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TINA4_DATABASE_URL` | `sqlite:///data/store.db` | Database connection string |
| `SECRET` | — | JWT signing secret (required) |
| `TINA4_DEBUG` | `false` | Enable debug mode, error overlay, DevAdmin |
| `TINA4_DEBUG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `TINA4_LANGUAGE` | `en` | Default locale |
| `TINA4_SESSION_HANDLER` | `file` | Session backend (file, redis, database) |
| `SWAGGER_TITLE` | — | Swagger UI title |
| `SWAGGER_DESCRIPTION` | — | Swagger UI description |
| `TINA4_MAIL_HOST` | — | SMTP host |
| `TINA4_MAIL_PORT` | — | SMTP port |
| `TINA4_MAIL_FROM` | — | Sender email |
| `TINA4_MAIL_FROM_NAME` | — | Sender name |
| `TINA4_CACHE_TTL` | `60` | Default cache TTL (seconds) |
| `TINA4_CACHE_MAX_ENTRIES` | `1000` | Max cached entries |

## Appendix C: Feature Cross-Reference

Quick lookup: which Tina4 module powers each feature.

| Feature | Python Module | Key Class/Function |
|---------|--------------|-------------------|
| Routing | `tina4_python.core.router` | `@get`, `@post`, `@secured`, `@cached` |
| ORM | `tina4_python.orm` | `ORM`, `IntegerField`, `ForeignKeyField` |
| Database | `tina4_python.database` | `Database` |
| Auth | `tina4_python.auth` | `Auth`, `get_token`, `valid_token` |
| Sessions | `tina4_python.session` | `Session` |
| Templates | `tina4_python.frond` | `Frond.render()` |
| Queue | `tina4_python.queue` | `Queue`, `Job` |
| Events | `tina4_python.core.events` | `@on`, `emit`, `emit_async` |
| GraphQL | `tina4_python.graphql` | `GraphQL`, `Schema` |
| WSDL | `tina4_python.wsdl` | `WSDL`, `@wsdl_operation` |
| WebSocket | `tina4_python.websocket` | `WebSocketServer`, `WebSocketConnection` |
| Caching | `tina4_python.cache` | `ResponseCache`, `@cached` |
| i18n | `tina4_python.i18n` | `I18n` |
| SCSS | Auto-compile | Files in `src/scss/` |
| Seeder | `tina4_python.seeder` | `FakeData`, `seed_table` |
| Migration | `tina4_python.migration` | `migrate`, `create_migration` |
| Swagger | `tina4_python.swagger` | `@description`, `@tags`, `@example` |
| Auto-CRUD | `tina4_python.crud` | `AutoCrud.register()` |
| File Upload | `request.files` | Dict with `filename`, `content`, `type` |
| Email | `tina4_python.messenger` | `Messenger`, `create_messenger` |
| Container | `tina4_python.container` | `Container` |
| Rate Limiter | `tina4_python.core.rate_limiter` | `RateLimiter` |
| Error Overlay | `tina4_python.debug.error_overlay` | `render_error_overlay` |
| SSE | `response.stream()` | Async generator |
| PWA | tina4-js (bundled) | `pwa.register()` |
| Signals | tina4-js (bundled) | `signal()`, `computed()` |
