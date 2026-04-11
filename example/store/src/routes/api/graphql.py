from tina4_python.core.router import post, noauth
from tina4_python.graphql import GraphQL
from tina4_python.orm import ORM
from src.orm.product import Product
from src.orm.category import Category


graphql = GraphQL()
graphql.schema.from_orm(Product)
graphql.schema.from_orm(Category)


def products_by_price(min_price=0, max_price=99999, **kwargs):
    return [p.to_dict() for p in Product.where(
        "price between ? and ? and is_active = 1",
        params=[min_price, max_price],
        limit=50,
    )]


def search_products(term="", limit=10, **kwargs):
    """Search products by name or description — powers the frontend search bar."""
    if not term or len(term) < 2:
        return []
    like = f"%{term}%"
    return [p.to_dict() for p in Product.where(
        "(name like ? or description like ?) and is_active = 1",
        params=[like, like],
        limit=limit,
    )]


graphql.schema.add_query(
    "products_by_price",
    {"min_price": "Float", "max_price": "Float"},
    "[Product]",
    products_by_price,
)

graphql.schema.add_query(
    "search_products",
    {"term": "String", "limit": "Int"},
    "[Product]",
    search_products,
)


@noauth()
@post("/api/graphql")
async def graphql_endpoint(request, response):
    query = request.body.get("query", "")
    variables = request.body.get("variables", {})
    result = graphql.execute(query, variables)
    return response(result, 200)
