import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tina4_python
from tina4_python import run_web_server
from tina4_python.Database import Database
from tina4_python.ORM import ORM, orm
from tina4_python.Migration import migrate
from tina4_python.GraphQL import GraphQL
from tina4_python.Seeder import FakeData, seed_orm

# Database setup
db = Database("sqlite3:app.db")
orm(db)
migrate(db)

# Import models
from src.orm.Category import Category
from src.orm.Product import Product

# GraphQL — auto-generate schema from ORM models
gql = GraphQL()
gql.schema.from_orm(Category)
gql.schema.from_orm(Product)
gql.register_route("/graphql")

# Seed data on first run
if len(Category().select(limit=1).records) == 0:
    categories = [
        "Electronics", "Clothing", "Books", "Home & Garden", "Sports",
        "Toys", "Food & Drink", "Automotive", "Health", "Office Supplies",
    ]
    for name in categories:
        Category({"name": name}).save()

    fake = FakeData(seed=42)
    seed_orm(Product, count=100, overrides={
        "category_id": lambda f: f.integer(1, 10),
        "price": lambda f: f.numeric(1.0, 500.0, decimals=2),
        "stock": lambda f: f.integer(0, 200),
    })

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7147)
