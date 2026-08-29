"""Product-name seeding — a `name` column on a product-ish table gets product
names ("Wireless Keyboard"), not person names ("John Smith").

No mocks: the integration tests seed a REAL SQLite table/model and read the rows
back. The heuristic tests call the real seeder functions over real strings (pure,
no dependency). Product and person vocabularies are disjoint, so the first word of
a generated value tells which generator ran.
"""
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, bind_database
from tina4_python.seeder import (
    FakeData,
    seed_orm,
    seed_table,
    auto_field_map,
    _generator_for_column,
    _generate_for_field,
    _is_product_table,
    _PRODUCT_ADJECTIVES,
    _FIRST_NAMES,
)

PRODUCT_ADJ = set(_PRODUCT_ADJECTIVES)
PERSON_FIRST = set(_FIRST_NAMES)


def _first(value: str) -> str:
    return str(value).split(" ", 1)[0]


class TestProductGenerator:
    def test_shape_and_vocab(self):
        fake = FakeData(seed=1)
        p = fake.product()
        assert _first(p) in PRODUCT_ADJ          # adjective + noun
        assert " " in p and len(p.split()) >= 2

    def test_deterministic_under_seed(self):
        a = [FakeData(seed=7).product() for _ in range(3)]
        b = [FakeData(seed=7).product() for _ in range(3)]
        assert a == b
        # ...and it varies across draws, not one constant string.
        fake = FakeData(seed=3)
        assert len({fake.product() for _ in range(30)}) > 1

    def test_disjoint_from_person_names(self):
        # A product's first word is never a person first-name and vice versa,
        # which is what makes the table-aware assertions below unambiguous.
        assert PRODUCT_ADJ.isdisjoint(PERSON_FIRST)


class TestIsProductTable:
    @pytest.mark.parametrize("t", ["products", "Product", "order_items", "catalog",
                                   "inventory", "sku_table", "listings"])
    def test_product_ish_true(self, t):
        assert _is_product_table(t) is True

    @pytest.mark.parametrize("t", ["users", "people", "customers", "employees",
                                   None, "", "orders"])
    def test_non_product_false(self, t):
        assert _is_product_table(t) is False


class TestHeuristicIsTableAware:
    """The three name->generator sites all honour the table, and default to a
    person name with no table context (back-compat)."""

    def test_generator_for_column(self):
        fake = FakeData(seed=1)
        # Returns the generator CALLABLE (== by func+instance; a fresh bound
        # method is a distinct object each access, so `is` would not hold).
        assert _generator_for_column(fake, "name", "TEXT", "products") == fake.product
        assert _generator_for_column(fake, "name", "TEXT", "users") == fake.name
        assert _generator_for_column(fake, "name", "TEXT", None) == fake.name  # back-compat

    def test_generate_for_field(self):
        fake = FakeData(seed=1)
        meta = {"type": "string"}
        assert _first(_generate_for_field(fake, meta, "name", "products")) in PRODUCT_ADJ
        assert _first(_generate_for_field(fake, meta, "name", "users")) in PERSON_FIRST
        assert _first(_generate_for_field(fake, meta, "name", None)) in PERSON_FIRST

    def test_for_field_method(self):
        fake = FakeData(seed=1)
        assert _first(fake.for_field({"type": "string"}, "name", "products")) in PRODUCT_ADJ
        assert _first(fake.for_field({"type": "string"}, "name", "users")) in PERSON_FIRST
        assert _first(fake.for_field({"type": "string"}, "name")) in PERSON_FIRST


class TestRealSeeding:
    """Seed real SQLite rows and read them back."""

    def test_seed_orm_product_model_gets_product_names(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'p.db'}")
        bind_database(db)

        class Product(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        Product.create_table()
        seed_orm(Product, count=8, seed=42)
        rows = db.fetch("SELECT name FROM product", limit=100).records
        assert len(rows) == 8
        assert all(_first(r["name"]) in PRODUCT_ADJ for r in rows), [r["name"] for r in rows]
        db.close()

    def test_seed_orm_user_model_gets_person_names(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'u.db'}")
        bind_database(db)

        class User(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        User.create_table()
        seed_orm(User, count=8, seed=42)
        rows = db.fetch("SELECT name FROM user", limit=100).records
        assert len(rows) == 8
        assert all(_first(r["name"]) in PERSON_FIRST for r in rows), [r["name"] for r in rows]
        db.close()

    def test_auto_field_map_seeds_products_table_with_product_names(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'pt.db'}")
        db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL)")
        db.commit()
        fake = FakeData(seed=5)
        seed_table(db, "products", 8, auto_field_map(db, "products", fake))
        rows = db.fetch("SELECT name FROM products", limit=100).records
        assert len(rows) == 8
        assert all(_first(r["name"]) in PRODUCT_ADJ for r in rows), [r["name"] for r in rows]
        db.close()

    def test_seed_orm_reproducible(self, tmp_path):
        # Same seed -> same product names.
        def run(path):
            db = Database(f"sqlite:///{path}")
            bind_database(db)

            class Item(ORM):
                id = IntegerField(primary_key=True, auto_increment=True)
                name = StringField()

            Item.create_table()
            seed_orm(Item, count=6, seed=99)
            names = [r["name"] for r in db.fetch("SELECT name FROM item ORDER BY id", limit=100).records]
            db.close()
            return names

        assert run(tmp_path / "a.db") == run(tmp_path / "b.db")
