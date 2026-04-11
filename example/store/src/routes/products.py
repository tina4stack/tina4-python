from tina4_python.core.router import get, noauth, cached
from tina4_python.orm import ORM
from src.orm.product import Product
from src.orm.category import Category
from src.app.template import render


@noauth()
@cached(max_age=120)
@get("/products")
async def product_list(request, response):
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

    categories = Category.all(order_by="name")
    total_pages = (total + per_page - 1) // per_page

    return response(render("storefront/products.twig", {
        "products": [p.to_dict() for p in products],
        "categories": [c.to_dict() for c in categories],
        "current_category": category,
        "page": page,
        "total_pages": total_pages,
    }, request))


@noauth()
@get("/products/{slug}")
async def product_detail(request, response):
    products = Product.where("slug = ?", params=[request.params["slug"]], include=["category"])
    if not products:
        return response(render("storefront/home.twig", {"error": "Product not found"}, request), 404)

    product = products[0]
    product_data = product.to_dict(include=["category"])
    return response(render("storefront/product_detail.twig", {"product": product_data}, request))
