"""Gallery: Templates — render a Twig template with data."""
from tina4_python.Router import get
from tina4_python.Template import template


@template("gallery_page.twig")
@get("/gallery/page")
async def gallery_page(request, response):
    return {
        "title": "Gallery Demo Page",
        "items": [
            {"name": "Tina4 Python", "description": "Zero-dep web framework", "badge": "v3.0.0"},
            {"name": "Twig Engine", "description": "Built-in template rendering", "badge": "included"},
            {"name": "Auto-Reload", "description": "Templates refresh on save", "badge": "dev mode"},
        ],
    }
