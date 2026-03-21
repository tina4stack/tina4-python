# Database

Tina4 provides a multi-driver database abstraction layer. One API, many backends. The connection URL scheme determines which driver is used. SQLite is built-in (stdlib). All others require installing the driver package.

## Connection Strings

```python
from tina4_python.database.connection import Database

# SQLite (built-in, no install needed)
db = Database("sqlite:///data/app.db")

# PostgreSQL — pip install psycopg2-binary
db = Database("postgresql://user:password@localhost:5432/mydb")

# MySQL — pip install mysql-connector-python
db = Database("mysql://user:password@localhost:3306/mydb")

# MSSQL — pip install pymssql
db = Database("mssql://sa:password@localhost:1433/mydb")

# Firebird — pip install firebird-driver
db = Database("firebird://SYSDBA:masterkey@localhost:3050//path/to/database.fdb")

# ODBC — pip install pyodbc
db = Database("odbc://DSN=MyDSN;UID=user;PWD=pass")

# MongoDB — pip install pymongo
db = Database("mongodb://localhost:27017/mydb")
db = Database("mongodb://user:password@localhost:27017/mydb")

# From environment variable (DATABASE_URL)
db = Database()  # Reads DATABASE_URL, defaults to sqlite:///data/tina4.db
```

## Querying

### Fetch Multiple Rows

```python
result = db.fetch("SELECT * FROM users WHERE active = ?", [1], limit=20, skip=0)

# Result is a DatabaseResult object
for row in result.records:
    print(row["name"], row["email"])

print(result.count)  # Total row count
```

### Fetch One Row

```python
row = db.fetch_one("SELECT * FROM users WHERE id = ?", [42])
if row:
    print(row["name"])  # Dict access, not attribute access
```

### Result Conversion

```python
result = db.fetch("SELECT * FROM products")

result.to_array()     # List of dicts
result.to_json()      # JSON string
result.to_csv()       # CSV string
result.to_paginate()  # {"records": [...], "count": 50, "limit": 20, "skip": 0}
```

## Insert / Update / Delete

```python
# Insert one row
db.insert("users", {"name": "Alice", "email": "alice@example.com"})

# Insert multiple rows
db.insert("users", [
    {"name": "Bob", "email": "bob@example.com"},
    {"name": "Eve", "email": "eve@example.com"},
])

# Update (by primary key — default "id")
db.update("users", {"name": "Alice Updated"}, "id = ?", [1])

# Delete
db.delete("users", "id = ?", [1])
```

## Execute Raw SQL

```python
# DDL and other non-query statements
db.execute("CREATE INDEX idx_email ON users(email)")

# Execute with parameters
db.execute("UPDATE users SET active = ? WHERE last_login < ?", [0, "2024-01-01"])
```

## Transactions

```python
db.start_transaction()
try:
    db.insert("orders", {"user_id": 1, "total": 99.99})
    db.insert("order_items", {"order_id": 1, "product_id": 5, "qty": 2})
    db.commit()
except Exception:
    db.rollback()
```

Never use `db.execute("BEGIN")` or `db.execute("COMMIT")` -- always use the methods above. Raw SQL transaction commands bypass the framework's connection state management.

## Schema Inspection

```python
# Check if a table exists
if db.table_exists("users"):
    print("Table found")

# List all tables
tables = db.get_database_tables()
# ["users", "products", "orders"]

# Get column info for a table
columns = db.get_table_info("users")
# [{"name": "id", "type": "INTEGER", "notnull": 1, "pk": 1}, ...]
```

## MongoDB Specifics

MongoDB uses the same SQL API as all other engines. SQL is translated to MongoDB queries internally by the `SQLToMongo` module.

```python
db = Database("mongodb://localhost:27017/mydb")

# All standard operations work
db.execute("CREATE TABLE users (id INTEGER)")  # Creates collection
db.insert("users", {"id": 1, "name": "Alice"})
result = db.fetch("SELECT * FROM users WHERE name = ?", ["Alice"])
db.execute("UPDATE users SET name = ? WHERE id = ?", ["Bob", 1])
db.execute("DELETE FROM users WHERE id = ?", [1])
```

Supported WHERE operators: `=`, `!=`, `<>`, `>`, `>=`, `<`, `<=`, `LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`, `BETWEEN`, `AND`, `OR`.

Limitation: JOINs are not supported. Use embedded documents or application-level joins.

## Firebird Specifics

- Use generators for auto-increment IDs, not `AUTOINCREMENT`.
- Pagination uses `ROWS {skip+1} TO {skip+per_page}`, not LIMIT/OFFSET.
- No `TEXT` type -- use `VARCHAR(n)` or `BLOB SUB_TYPE TEXT`.
- No `FLOAT` -- use `DOUBLE PRECISION`.
- `fetch_one()` auto-base64-encodes BLOB fields.

## Tips

- Set `DATABASE_URL` in your `.env` file and call `Database()` with no arguments.
- Always use parameterized queries (`?` placeholders) to prevent SQL injection.
- Use `fetch_one()` when you only need one row -- it returns a plain dict (or None), not a DatabaseResult.
- All query results use dict access (`row["column"]`), not attribute access (`row.column`).
