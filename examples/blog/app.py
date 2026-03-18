import sys
import os
# Ensure this example's directory is first on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tina4_python
from tina4_python import run_web_server
from tina4_python.Database import Database
from tina4_python.ORM import ORM, orm
from tina4_python.Migration import migrate
from tina4_python.Template import Template
from tina4_python.Seeder import FakeData, seed_orm

# Database setup
db = Database("sqlite3:app.db")
orm(db)
migrate(db)

# Custom template helpers
Template.add_global("APP_NAME", "Tina4 Blog")

# Import models for seeding
from src.orm.Post import Post
from src.orm.Comment import Comment

# Seed data on first run
if len(Post().select(limit=1).records) == 0:
    fake = FakeData(seed=42)
    seed_orm(Post, count=20, overrides={
        "slug": lambda f: f.name().lower().replace(" ", "-") + "-" + str(f.integer(100, 999)),
        "content": lambda f: " ".join([f.sentence() for _ in range(5)]),
    })
    # Seed comments linked to posts
    for _ in range(50):
        Comment({
            "post_id": fake.integer(1, 20),
            "name": fake.name(),
            "email": fake.email(),
            "body": fake.sentence(words=12),
        }).save()

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
