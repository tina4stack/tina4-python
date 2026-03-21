"""Root route — renders the welcome page."""
from tina4_python.Router import get
from tina4_python.Template import template


@template("index.twig")
@get("/")
async def index(request, response):
    return {
        "title": "Welcome to Tina4",
        "message": "This is not a framework.",
    }
