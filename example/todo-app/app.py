from tina4_python import run_web_server, orm
from tina4_python.Database import Database

db = Database("sqlite3:todos.db")
orm(db)

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
