from tina4_python.core.router import get, noauth
from tina4_python.swagger import description, tags, example
from src.orm.category import Category


@noauth()
@tags("Categories")
@description("List all product categories")
@example([{"id": 1, "name": "Electronics", "slug": "electronics"}])
@get("/api/categories")
async def api_category_list(request, response):
    categories = Category.all(order_by="name")
    return response([c.to_dict() for c in categories], 200)
