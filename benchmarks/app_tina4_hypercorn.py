"""tina4-python benchmark app -- run with standalone Hypercorn.

Usage (from benchmarks/ dir):
    hypercorn app_tina4_hypercorn:app --bind 0.0.0.0:8101
"""
import sys
import os

# Set root path to benchmarks dir so tina4 doesn't try to load ../src/
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Create required dirs so tina4 init doesn't fail
os.makedirs("migrations", exist_ok=True)
os.makedirs("src/routes", exist_ok=True)

# Prevent tina4 from importing parent project's src/
if "src" in sys.modules:
    del sys.modules["src"]

from tina4_python.Router import get

@get("/api/hello")
async def hello(request, response):
    return response({"message": "Hello, World!"})

# Import the ASGI callable that Hypercorn needs
from tina4_python import app
