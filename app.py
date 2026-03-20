"""Demo app for Tina4 Dev Admin dashboard."""
import os
os.environ["TINA4_DEBUG_LEVEL"] = "DEBUG"
os.environ["TINA4_DEBUG"] = "true"

from tina4_python.core.router import get
from tina4_python.core.server import run


@get("/")
async def home(request, response):
    return response.html("<html><body><h1>Tina4 v3 Demo</h1><p>Visit <a href='/__dev/'>Dev Admin</a></p></body></html>")


@get("/api/hello")
async def hello(request, response):
    return response.json({"message": "Hello from Tina4!"})


@get("/api/error")
async def error_demo(request, response):
    raise ValueError("This is a demo error for testing the error tracker")


if __name__ == "__main__":
    run("localhost", 7145)
