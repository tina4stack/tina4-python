from tina4_python.core.router import get, noauth, cached
from src.orm.product import Product
from src.orm.category import Category
from src.app.template import render


CATEGORY_STYLES = [
    {"icon": "📚", "gradient": "linear-gradient(135deg, #667eea, #764ba2)"},
    {"icon": "👕", "gradient": "linear-gradient(135deg, #f093fb, #f5576c)"},
    {"icon": "📱", "gradient": "linear-gradient(135deg, #4facfe, #00f2fe)"},
    {"icon": "🌿", "gradient": "linear-gradient(135deg, #43e97b, #38f9d7)"},
    {"icon": "🏋️", "gradient": "linear-gradient(135deg, #fa709a, #fee140)"},
    {"icon": "🎮", "gradient": "linear-gradient(135deg, #a18cd1, #fbc2eb)"},
    {"icon": "🍳", "gradient": "linear-gradient(135deg, #fccb90, #d57eeb)"},
    {"icon": "🎨", "gradient": "linear-gradient(135deg, #e0c3fc, #8ec5fc)"},
    {"icon": "🎵", "gradient": "linear-gradient(135deg, #f5576c, #ff6a88)"},
    {"icon": "🛋️", "gradient": "linear-gradient(135deg, #667eea, #00f2fe)"},
]


@noauth()
@cached(max_age=120)
@get("/")
async def home(request, response):
    products = Product.where("is_active = 1", limit=8)
    categories = Category.all(order_by="name")
    cat_list = []
    for i, c in enumerate(categories):
        d = c.to_dict()
        style = CATEGORY_STYLES[i % len(CATEGORY_STYLES)]
        d["icon"] = style["icon"]
        d["gradient"] = style["gradient"]
        cat_list.append(d)
    return response(render("storefront/home.twig", {
        "featured_products": [p.to_dict() for p in products],
        "categories": cat_list,
    }, request))
