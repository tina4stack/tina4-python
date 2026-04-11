from tina4_python.core.router import get, noauth, cached
from tina4_python.swagger import description, tags, example
from src.orm.product import Product


@noauth()
@cached(max_age=120)
@tags("Products")
@description("List products with optional category filter and pagination")
@example({"products": [{"id": 1, "name": "Widget", "price": 9.99}], "page": 1, "total_pages": 5})
@get("/api/products")
async def api_product_list(request, response):
    page = int(request.query.get("page", 1))
    category = request.query.get("category", None)
    per_page = 12
    offset = (page - 1) * per_page

    if category:
        products = Product.where(
            "category_id = (select id from categories where slug = ?) and is_active = 1",
            params=[category], limit=per_page, offset=offset,
        )
        total = Product.count(
            "category_id = (select id from categories where slug = ?) and is_active = 1",
            params=[category],
        )
    else:
        products = Product.where("is_active = 1", limit=per_page, offset=offset)
        total = Product.count("is_active = 1")

    return response({
        "products": [p.to_dict() for p in products],
        "page": page,
        "total_pages": (total + per_page - 1) // per_page,
    }, 200)


@noauth()
@tags("Products")
@description("Get a single product by ID")
@example({"id": 1, "name": "Widget", "price": 9.99, "description": "A fine widget"})
@get("/api/products/{id:int}")
async def api_product_detail(request, response):
    product = Product.find(request.params["id"])
    if not product:
        return response({"error": "Product not found"}, 404)
    return response(product.to_dict(include=["category"]), 200)
