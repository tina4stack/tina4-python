"""Simple JSON greeting endpoint."""
from tina4_python.Router import get


@get("/api/hello")
async def hello(request, response):
    return response({"message": "Hello from Tina4!", "version": "3.0.0"})
