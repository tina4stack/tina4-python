# ORM

Tina4's ORM is SQL-first Active Record. You define models with typed fields, and the ORM handles CRUD, type coercion, validation, and serialization. Models live in `src/orm/` -- one class per file.

## Defining a Model

```python
# src/orm/User.py
from tina4_python.orm import ORM, Field

class User(ORM):
    table_name = "users"  # Optional — defaults to lowercase class name + "s"
    id    = Field(int, primary_key=True, auto_increment=True)
    name  = Field(str, required=True, min_length=1, max_length=100)
    email = Field(str, regex=r'^[^@]+@[^@]+\.[^@]+$')
    age   = Field(int, min_value=0, max_value=150)
    role  = Field(str, choices=["admin", "user", "guest"], default="user")
    active = Field(bool, default=True)
```

## Verbose Field Types

Tina4 provides named field classes for clarity. Both short and verbose names are available.

```python
from tina4_python.orm import (
    ORM,
    IntegerField, StringField, BooleanField, FloatField,
    DateTimeField, TextField, BlobField,
    IntField, StrField, BoolField,  # Short aliases
)

class Product(ORM):
    id          = IntegerField(primary_key=True, auto_increment=True)
    name        = StringField(required=True)
    description = TextField()
    price       = FloatField(min_value=0)
    in_stock    = BooleanField(default=True)
    created_at  = DateTimeField()
    image       = BlobField()
```

All verbose types (`IntegerField`, `StringField`, etc.) are wrappers around `Field` with the type preset.

## Binding the Database

In your `app.py`, bind a database to all ORM models before using them.

```python
# app.py
from tina4_python.database import Database
from tina4_python.orm import orm_bind

db = Database("sqlite:///data/app.db")
orm_bind(db)
```

## CRUD Operations

### Create

```python
user = User({"name": "Alice", "email": "alice@example.com"})
user.save()
print(user.id)  # Auto-populated after insert
```

### Read

```python
# Find by primary key
user = User.find(1)
if user:
    print(user.name)

# Find or raise
user = User.find_or_fail(1)  # Raises ValueError if not found

# Fetch all
users, count = User.all(limit=50)

# WHERE clause
admins, count = User.where("role = ?", ["admin"], limit=10)

# Full SQL query
results, count = User.select(
    "SELECT * FROM users WHERE age > ? ORDER BY name",
    [18], limit=20, skip=0
)
```

### Update

```python
user = User.find(1)
user.name = "Alice Wonder"
user.save()  # UPDATE since id already has a value
```

### Delete

```python
user = User.find(1)
user.delete()
```

## Serialization

```python
user = User.find(1)

# To dict (field values only)
data = user.to_dict()
# {"id": 1, "name": "Alice", "email": "alice@example.com", ...}

# To JSON string
json_str = user.to_json()
```

## Create Table from Model

For prototyping, generate and run DDL from your model definition.

```python
Product().create_table()
```

For production, always use migration files instead.

## Field Validation

Fields support built-in constraints. Validation runs on `.save()` or explicitly.

```python
class Order(ORM):
    id     = IntegerField(primary_key=True, auto_increment=True)
    amount = FloatField(required=True, min_value=0.01, max_value=999999.99)
    status = StringField(choices=["pending", "paid", "shipped", "cancelled"])
    code   = StringField(regex=r'^ORD-\d{6}$')
    notes  = StringField(max_length=500)

# Validate without saving
order = Order({"amount": -5, "status": "invalid"})
errors = order.validate()
# ["Field 'amount': minimum value is 0.01, got -5", "Field 'status': value must be one of ..."]
```

### Custom Validator

```python
def validate_even(value):
    if value % 2 != 0:
        raise ValueError("Must be an even number")

class Widget(ORM):
    count = Field(int, validator=validate_even)
```

## Named Database Connections

Models can use different databases via named connections.

```python
# app.py
from tina4_python.orm import orm_bind

orm_bind(main_db)                    # Default for all models
orm_bind(audit_db, name="audit")     # Named connection

# src/orm/AuditLog.py
class AuditLog(ORM):
    _db = "audit"  # Uses the named "audit" connection
    id = IntegerField(primary_key=True, auto_increment=True)
    action = StringField()
```

## Tips

- One model per file in `src/orm/`, filename matching the class name.
- Always create a migration for the table schema -- `create_table()` is for prototyping only.
- Use `to_dict()` when returning data from routes: `return response(user.to_dict())`.
- Field column names default to the Python attribute name. Use `column="db_col_name"` to override.
