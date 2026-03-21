# Seeder

Tina4's `FakeData` class generates realistic test data with deterministic seeding. The `seed_table()` function populates database tables in bulk. No external faker library needed -- it is built from scratch with zero dependencies.

## Fake Data Generator

```python
from tina4_python.seeder import FakeData

fake = FakeData()

fake.name()        # "Alice Johnson"
fake.first_name()  # "Charlie"
fake.last_name()   # "Williams"
fake.email()       # "bob.martinez@example.com"
fake.phone()       # "+1 (415) 234-5678"
fake.address()     # "42 Oak Ave, London"
fake.url()         # "https://demo.net/quick/lorem"
fake.uuid()        # "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
fake.color_hex()   # "#3a7f4c"
```

## Data Types

```python
fake.integer(1, 100)            # Random int between 1 and 100
fake.decimal(0.0, 999.99, 2)    # Random float with 2 decimal places
fake.boolean()                  # True or False
fake.word()                     # "lorem"
fake.sentence(8)                # "The quick brown fox jumps over lazy dog."
fake.paragraph(4)               # 4 sentences
fake.text(3)                    # 3 paragraphs
fake.date()                     # "2023-07-15"
fake.datetime_iso()             # "2024-03-12T14:30:45Z"
fake.alphanumeric(10)           # "aB3xY7mK9p"
```

## Choice and Sample

```python
fake.choice(["red", "green", "blue"])          # Pick one
fake.sample(["a", "b", "c", "d", "e"], 3)     # Pick 3 unique
```

## Deterministic Seeding

Pass a seed for reproducible results -- great for tests.

```python
fake1 = FakeData(seed=42)
fake2 = FakeData(seed=42)

print(fake1.name())  # "Chloe Thomas"
print(fake2.name())  # "Chloe Thomas" — same seed, same output
```

## Seeding a Database Table

`seed_table()` inserts multiple rows using callable generators.

```python
from tina4_python.database.connection import Database
from tina4_python.seeder import FakeData, seed_table

db = Database("sqlite:///data/app.db")
fake = FakeData()

# Seed 50 users
count = seed_table(db, "users", 50, {
    "name": fake.name,
    "email": fake.email,
    "phone": fake.phone,
    "age": lambda: fake.integer(18, 65),
    "role": lambda: fake.choice(["admin", "user", "editor"]),
})
print(f"Inserted {count} users")
```

## Static Overrides

Set fixed values on every row with `overrides`.

```python
seed_table(db, "users", 20,
    field_map={
        "name": fake.name,
        "email": fake.email,
    },
    overrides={
        "active": 1,
        "role": "user",
        "created_at": "2024-01-01",
    }
)
```

## Seeding Multiple Tables

```python
fake = FakeData(seed=42)

# Users
seed_table(db, "users", 100, {
    "name": fake.name,
    "email": fake.email,
})

# Products
seed_table(db, "products", 50, {
    "name": lambda: fake.word().capitalize() + " " + fake.word().capitalize(),
    "price": lambda: fake.decimal(1.0, 999.99),
    "category": lambda: fake.choice(["Electronics", "Books", "Clothing", "Food"]),
})

# Orders (referencing user IDs)
seed_table(db, "orders", 200, {
    "user_id": lambda: fake.integer(1, 100),
    "product_id": lambda: fake.integer(1, 50),
    "quantity": lambda: fake.integer(1, 10),
    "total": lambda: fake.decimal(5.0, 500.0),
    "status": lambda: fake.choice(["pending", "paid", "shipped"]),
})
```

## Seeder Files

Place seeder scripts in `src/seeds/` and run them with the CLI.

```python
# src/seeds/users.py
from tina4_python.seeder import FakeData, seed_table

def run(db):
    fake = FakeData(seed=1)
    seed_table(db, "users", 100, {
        "name": fake.name,
        "email": fake.email,
        "role": lambda: fake.choice(["admin", "user"]),
    })
```

```bash
tina4python seed
```

## Tips

- Use deterministic seeds (`FakeData(seed=42)`) in tests for reproducible data.
- Use `lambda:` wrappers around generators that need arguments (e.g., `lambda: fake.integer(1, 100)`).
- Seed development databases with realistic volumes to test pagination and performance.
- Run seeders after migrations: `tina4python migrate && tina4python seed`.
- The `overrides` parameter is useful for setting default values like `active=1` on every row.
