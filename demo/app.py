# Tina4 Python Demo Application
# ================================
# Demonstrates every working feature of the Tina4 Python framework.
#
# Usage:
#   cd tina4-python/demo
#   pip install -e ..    # install tina4 from parent
#   python app.py        # run the demo
#
# Then visit http://localhost:7145

import os
import sys

# Ensure the parent directory is on the path so tina4_python can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.dotenv import load_env
from tina4_python.database.connection import Database
from tina4_python.orm import orm_bind
from tina4_python.debug import Log
from tina4_python.core import run

# 1. Load environment variables
load_env()

# 2. Initialize logger
Log.init(level="debug", production=False)

# 3. Set up database (SQLite, file-based so it persists between requests)
os.makedirs("data", exist_ok=True)
db = Database("sqlite:///data/demo.db")
orm_bind(db)

# 4. Routes are auto-discovered from src/routes/ by the server.
#    The demo_routes.py file registers all demo endpoints.

# 5. Start the server
if __name__ == "__main__":
    port = 7145
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    print()
    print("  Tina4 Python Demo")
    print("  ==================")
    print(f"  Visit http://localhost:{port} to see all features.")
    print()

    run("0.0.0.0", port)
