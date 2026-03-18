from tina4_python.Router import get
from tina4_python.Swagger import description, tags
from src.orm.Category import Category


@description("List all categories")
@tags(["categories"])
@get("/api/categories")
async def list_categories(request, response):
    result = Category().select("*", order_by="name", limit=100)
    return response(result.to_array())


@description("Get a single category by ID")
@tags(["categories"])
@get("/api/categories/{id:int}")
async def get_category(id, request, response):
    cat = Category()
    if not cat.load("id = ?", [id]):
        return response({"error": "Category not found"}, 404)
    return response(cat.to_dict())
