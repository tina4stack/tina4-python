from tina4_python.Router import get, post, put, delete
from tina4_python.Swagger import description, tags, example
from src.orm.Product import Product


@description("List products with pagination")
@tags(["products"])
@get("/api/products")
async def list_products(request, response):
    limit = int(request.params.get("limit", 10))
    skip = int(request.params.get("skip", 0))
    result = Product().select("*", order_by="id", limit=limit, skip=skip)
    return response(result.to_paginate())


@description("Get a single product by ID")
@tags(["products"])
@get("/api/products/{id:int}")
async def get_product(id, request, response):
    product = Product()
    if not product.load("id = ?", [id]):
        return response({"error": "Product not found"}, 404)
    return response(product.to_dict())


@description("Create a new product")
@tags(["products"])
@example({"name": "Widget", "description": "A useful widget", "price": 9.99, "category_id": 1, "stock": 100})
@post("/api/products")
async def create_product(request, response):
    product = Product(request.body)
    product.save()
    return response(product.to_dict(), 201)


@description("Update a product")
@tags(["products"])
@put("/api/products/{id:int}")
async def update_product(id, request, response):
    product = Product()
    if not product.load("id = ?", [id]):
        return response({"error": "Product not found"}, 404)
    for key, value in request.body.items():
        if hasattr(product, key):
            setattr(product, key, value)
    product.save()
    return response(product.to_dict())


@description("Delete a product")
@tags(["products"])
@delete("/api/products/{id:int}")
async def delete_product(id, request, response):
    product = Product()
    if not product.load("id = ?", [id]):
        return response({"error": "Product not found"}, 404)
    product.delete()
    return response({"deleted": True})
