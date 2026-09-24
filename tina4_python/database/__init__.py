# Tina4 Database — Multi-driver abstraction with a clean adapter interface.
"""
SQL-first database layer. One interface, many drivers.

    from tina4_python.database import Database

    db = Database("sqlite:///data/app.db")
    db = Database("postgresql://user:pass@localhost:5432/mydb")

    rows = db.fetch("SELECT * FROM users WHERE active = ?", [1])
    row = db.fetch_one("SELECT * FROM users WHERE id = ?", [42])
    db.execute("INSERT INTO users (name) VALUES (?)", ["Alice"])

In an ``async def`` route use the awaitable twins (ADR-0074):

    row = await db.fetch_one_async("SELECT * FROM users WHERE id = ?", [42])
"""
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult
from tina4_python.database.sql_translator import SQLTranslator, SpatialNotSupportedError
from tina4_python.database.connection import Database
from tina4_python.database.pool import DatabasePoolExhausted

__all__ = [
    "Database", "DatabaseAdapter", "DatabaseResult", "DatabasePoolExhausted",
    "SQLTranslator", "SpatialNotSupportedError",
]
