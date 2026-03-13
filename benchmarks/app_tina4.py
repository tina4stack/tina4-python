"""tina4-python benchmark app -- uses tina4's built-in server (Hypercorn).

Must be run from the benchmarks/ directory.
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
from tina4_python import run_web_server

@get("/api/hello")
async def hello(request, response):
    return response({"message": "Hello, World!"})

if __name__ == "__main__":
    run_web_server("0.0.0.0", 8100)
