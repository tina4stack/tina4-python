import re
from tina4_python.core.router import get, post, noauth, middleware
from src.orm.product import Product
from src.orm.category import Category
from src.app.template import render
from src.middleware.admin_auth import AdminAuth


@middleware(AdminAuth)
@get("/admin/products")
async def admin_product_list(request, response):
    products = Product.all(limit=500, include=["category"])
    categories = Category.all(order_by="name")
    return response(render("admin/products.twig", {
        "products": [p.to_dict(include=["category"]) for p in products],
        "categories": [c.to_dict() for c in categories],
    }, request))


# @noauth bypasses built-in Bearer check — AdminAuth validates via session token instead
@noauth()
@middleware(AdminAuth)
@post("/admin/products")
async def admin_create_product(request, response):
    name = request.body.get("name", "")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    Product.create(
        name=name,
        slug=slug,
        description=request.body.get("description", ""),
        price=float(request.body.get("price", 0)),
        category_id=int(request.body.get("category_id", 0)),
        stock=int(request.body.get("stock", 0)),
        image_url=request.body.get("image_url", ""),
        is_active=True,
    )
    request.session.flash("success", "Product created")
    return response.redirect("/admin/products")


@middleware(AdminAuth)
@get("/admin/products/{id:int}/edit")
async def admin_edit_product(id, request, response):
    product = Product.find(id)
    if not product:
        request.session.flash("error", "Product not found")
        return response.redirect("/admin/products")
    categories = Category.all(order_by="name")
    return response(render("admin/product_edit.twig", {
        "product": product.to_dict(),
        "categories": [c.to_dict() for c in categories],
    }, request))


@noauth()
@middleware(AdminAuth)
@post("/admin/products/{id:int}/edit")
async def admin_update_product(id, request, response):
    product = Product.find(id)
    if not product:
        request.session.flash("error", "Product not found")
        return response.redirect("/admin/products")

    product.name = request.body.get("name", product.name)
    product.slug = re.sub(r"[^a-z0-9]+", "-", product.name.lower()).strip("-")
    product.description = request.body.get("description", product.description)
    product.price = float(request.body.get("price", product.price))
    product.category_id = int(request.body.get("category_id", product.category_id))
    product.stock = int(request.body.get("stock", product.stock))
    product.image_url = request.body.get("image_url", product.image_url)
    product.save()

    request.session.flash("success", "Product updated")
    return response.redirect("/admin/products")


@noauth()
@middleware(AdminAuth)
@post("/admin/products/{id:int}/delete")
async def admin_delete_product(id, request, response):
    product = Product.find(id)
    if product:
        product.delete()
    request.session.flash("success", "Product deleted")
    return response.redirect("/admin/products")
