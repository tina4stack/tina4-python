# Tina4 Database — Multi-driver abstraction with a clean adapter interface.
"""
SQL-first database layer. One interface, many drivers.

    from tina4_python.database import Database

    db = Database("sqlite:///data/app.db")
    db = Database("postgresql://user:pass@localhost:5432/mydb")

    rows = db.fetch("SELECT * FROM users WHERE active = ?", [1])
    row = db.fetch_one("SELECT * FROM users WHERE id = ?", [42])
    db.execute("INSERT INTO users (name) VALUES (?)", ["Alice"])
"""
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator
from tina4_python.database.connection import Database

__all__ = ["Database", "DatabaseAdapter", "DatabaseResult", "SQLTranslator"]
