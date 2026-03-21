"""Gallery: ORM — Product CRUD endpoints."""
from tina4_python.Router import get, post, noauth


@get("/api/gallery/products")
async def gallery_list_products(request, response):
    from src.orm.Product import Product
    result = Product().select(limit=50)
    return response(result.to_array())


@get("/api/gallery/products/{id:int}")
async def gallery_get_product(id, request, response):
    from src.orm.Product import Product
    p = Product()
    if p.load("id = ?", [id]):
        return response(p.to_dict())
    return response({"error": "Not found"}, 404)


@noauth()
@post("/api/gallery/products")
async def gallery_create_product(request, response):
    from src.orm.Product import Product
    p = Product(request.body)
    if p.save():
        return response(p.to_dict(), 201)
    return response({"error": "Failed to save"}, 400)
