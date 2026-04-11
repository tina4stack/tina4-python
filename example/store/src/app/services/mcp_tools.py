"""Custom MCP tools for the Tina4 Store — queryable by AI assistants.

Demonstrates: McpServer, @mcp_tool, @mcp_resource for AI integration.
"""
from tina4_python.mcp import McpServer, mcp_tool, mcp_resource
from src.orm.product import Product
from src.orm.category import Category

# Register a custom MCP server at /mcp/store
mcp = McpServer("/mcp/store", name="Tina4 Store Tools")


@mcp_tool("check_stock", description="Check stock level for a product by name or ID")
def check_stock(query: str):
    """Look up product stock by name (partial match) or numeric ID."""
    try:
        product_id = int(query)
        product = Product.find_by_id(product_id)
        if product:
            return {
                "id": product.id,
                "name": product.name,
                "stock": product.stock,
                "price": product.price,
                "in_stock": product.stock > 0,
                "low_stock": product.stock < 10,
            }
        return {"error": f"No product with ID {product_id}"}
    except (ValueError, TypeError):
        pass

    # Search by name
    products = Product.where(
        "name like ? and is_active = 1",
        params=[f"%{query}%"],
        limit=10,
    )
    if not products:
        return {"error": f"No products matching '{query}'"}

    return [
        {
            "id": p.id,
            "name": p.name,
            "stock": p.stock,
            "price": p.price,
            "in_stock": p.stock > 0,
            "low_stock": p.stock < 10,
        }
        for p in products
    ]


@mcp_tool("low_stock_report", description="List all products with stock below a threshold")
def low_stock_report(threshold: int = 10):
    """Return products with stock below the given threshold."""
    products = Product.where(
        "stock < ? and is_active = 1",
        params=[threshold],
        limit=50,
    )
    return [
        {"id": p.id, "name": p.name, "stock": p.stock, "price": p.price}
        for p in products
    ]


@mcp_tool("search_products", description="Search products by keyword")
def search_products(term: str, limit: int = 10):
    """Full-text search across product name and description."""
    like = f"%{term}%"
    products = Product.where(
        "(name like ? or description like ?) and is_active = 1",
        params=[like, like],
        limit=limit,
    )
    return [p.to_dict() for p in products]


@mcp_resource("store://categories", description="All product categories")
def get_categories():
    """Return all categories in the store."""
    return [c.to_dict() for c in Category.all(limit=100)]


@mcp_resource("store://inventory-summary", description="Stock summary by category")
def inventory_summary():
    """Aggregate stock counts per category."""
    from tina4_python.query_builder import QueryBuilder
    result = QueryBuilder.from_table("products p") \
        .select("c.name as category", "count(*) as product_count",
                "sum(p.stock) as total_stock",
                "sum(case when p.stock < 10 then 1 else 0 end) as low_stock_count") \
        .join("categories c", "p.category_id = c.id") \
        .where("p.is_active = 1") \
        .group_by("c.name") \
        .get()
    return result.records if result else []
