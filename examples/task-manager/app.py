import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tina4_python
from tina4_python import run_web_server
from tina4_python.Database import Database
from tina4_python.ORM import ORM, orm
from tina4_python.Migration import migrate

db = Database("sqlite3:app.db")
orm(db)
migrate(db)

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7146)
