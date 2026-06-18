# Lock-in regression tests for the SEEDING FULL OVERHAUL (P1-P4).
#
# Engine-agnostic SQLite, no server. These guard the unified
# visible-but-resilient behaviour: never silent (PHP/Ruby's old bug),
# never fragile (Python/Node's old crash).
import pytest

from tina4_python.seeder import (
    FakeData, SeedSummary, seed_table, seed_orm, seed_models,
)
from tina4_python.database import Database
from tina4_python.orm import (
    ORM, IntegerField, StringField, ForeignKeyField, bind_database,
)


# ── P1: error handling (visible but resilient) ──────────────────────────

class TestErrorHandling:
    def _db_with_unique(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'err.db'}")
        # name is UNIQUE → a duplicate row violates the constraint.
        db.execute(
            "CREATE TABLE u (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)"
        )
        db.commit()
        return db

    def test_summary_shape(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'shape.db'}")
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        db.commit()
        summary = seed_table(db, "t", 3, {"name": FakeData(seed=1).name})
        # SeedSummary is an int (== seeded) AND exposes the struct.
        assert summary == 3
        assert summary.seeded == 3
        assert summary.failed == 0
        assert summary.errors == []
        assert summary["seeded"] == 3
        assert dict(summary) == {"seeded": 3, "failed": 0, "errors": []}
        db.close()

    def test_constraint_violation_does_not_crash_and_is_not_silent(self, tmp_path):
        db = self._db_with_unique(tmp_path)
        # Every row generates the SAME name → first inserts, rest violate UNIQUE.
        summary = seed_table(db, "u", 5, {"name": lambda: "dup"})
        assert summary.failed >= 1               # NOT silently all-success
        assert summary.seeded == 1               # only the first landed
        assert summary.seeded + summary.failed == 5
        assert len(summary.errors) == summary.failed
        assert "row" in summary.errors[0] and "message" in summary.errors[0]
        # And it did NOT raise.
        result = db.fetch("SELECT * FROM u", limit=100)
        assert result.count == 1
        db.close()

    def test_strict_reraises_on_first_failure(self, tmp_path):
        db = self._db_with_unique(tmp_path)
        with pytest.raises(Exception):
            seed_table(db, "u", 5, {"name": lambda: "dup"}, strict=True)
        db.close()

    def test_partial_success_counts(self, tmp_path):
        db = self._db_with_unique(tmp_path)
        # First two unique, then a repeat that violates.
        names = iter(["a", "b", "a", "c", "a"])
        summary = seed_table(db, "u", 5, {"name": lambda: next(names)})
        # a, b inserted; a fails; c inserted; a fails → seeded 3, failed 2
        assert summary.seeded == 3
        assert summary.failed == 2
        db.close()


# ── P2: idempotency (clear/truncate) ────────────────────────────────────

class TestIdempotency:
    def test_clear_avoids_duplicates_on_rerun(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'idem.db'}")
        db.execute("CREATE TABLE c (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        db.commit()

        fm = {"name": FakeData(seed=7).name}
        seed_table(db, "c", 10, fm, clear=True)
        first = db.fetch("SELECT * FROM c", limit=1000).count
        seed_table(db, "c", 10, fm, clear=True)
        second = db.fetch("SELECT * FROM c", limit=1000).count

        assert first == 10
        assert second == 10            # not 20 — clear truncated before re-seeding
        db.close()

    def test_clear_prevents_unique_pk_violation(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'idempk.db'}")
        db.execute("CREATE TABLE k (id INTEGER PRIMARY KEY, label TEXT)")
        db.commit()

        # Static PK would collide on a naive re-run; clear=True makes it safe.
        ids = None

        def gen_id():
            nonlocal ids
            ids = (ids or 0) + 1
            return ids

        seed_table(db, "k", 5, {"id": gen_id, "label": lambda: "x"}, clear=True)
        ids = 0
        summary = seed_table(db, "k", 5, {"id": gen_id, "label": lambda: "x"}, clear=True)
        assert summary.failed == 0
        assert db.fetch("SELECT * FROM k", limit=1000).count == 5
        db.close()


# ── P3: reproducibility (seeded RNG) ────────────────────────────────────

class TestReproducibility:
    def test_same_seed_identical_data(self, tmp_path):
        def run(path):
            db = Database(f"sqlite:///{path}")
            db.execute("CREATE TABLE r (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT)")
            db.commit()
            fake = FakeData(seed=999)
            seed_table(db, "r", 8, {"name": fake.name, "email": fake.email})
            rows = [(row["name"], row["email"])
                    for row in db.fetch("SELECT * FROM r ORDER BY id", limit=1000)]
            db.close()
            return rows

        a = run(tmp_path / "rep_a.db")
        b = run(tmp_path / "rep_b.db")
        assert a == b
        assert len(a) == 8

    def test_seed_orm_seed_param_reproducible(self, tmp_path):
        def run(path):
            db = Database(f"sqlite:///{path}")
            bind_database(db)
            db.execute("CREATE TABLE seedperson (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT)")
            db.commit()

            class SeedPerson(ORM):
                id = IntegerField(primary_key=True, auto_increment=True)
                name = StringField()
                email = StringField()

            seed_orm(SeedPerson, count=6, seed=4242)
            rows = [(row["name"], row["email"])
                    for row in db.fetch("SELECT * FROM seedperson ORDER BY id", limit=1000)]
            db.close()
            return rows

        a = run(tmp_path / "orm_a.db")
        b = run(tmp_path / "orm_b.db")
        assert a == b
        assert len(a) == 6


# ── P4a: FK ordering (topological sort over ForeignKeyField graph) ──────

class TestForeignKeyOrdering:
    def test_wrong_declared_order_still_seeds_parents_first(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'fk.db'}")
        bind_database(db)
        # Real FK constraint — SQLite enforces it (PRAGMA foreign_keys=ON).
        db.execute(
            "CREATE TABLE author (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        )
        db.execute(
            "CREATE TABLE book (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
            "author_id INTEGER NOT NULL REFERENCES author(id))"
        )
        db.commit()

        class Author(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        class Book(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            title = StringField()
            author_id = ForeignKeyField(to=Author)

        # Pass children BEFORE parents on purpose — topo-sort must fix it.
        results = seed_models([Book, Author], count=4)

        assert results["Author"].failed == 0
        assert results["Author"].seeded == 4
        assert results["Book"].failed == 0      # no FK violation
        assert results["Book"].seeded == 4

        assert db.fetch("SELECT * FROM author", limit=100).count == 4
        assert db.fetch("SELECT * FROM book", limit=100).count == 4
        # Every book points at an existing author.
        orphans = db.fetch(
            "SELECT * FROM book WHERE author_id NOT IN (SELECT id FROM author)",
            limit=100,
        )
        assert orphans.count == 0
        db.close()

    def test_clear_runs_in_reverse_topo_order(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'fkclear.db'}")
        bind_database(db)
        db.execute(
            "CREATE TABLE maker (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        )
        db.execute(
            "CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, "
            "maker_id INTEGER NOT NULL REFERENCES maker(id))"
        )
        db.commit()

        class Maker(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        class Widget(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            label = StringField()
            maker_id = ForeignKeyField(to=Maker)

        seed_models([Maker, Widget], count=3)
        # Re-run with clear=True — clearing parents before children would trip
        # the FK; reverse-topo clear (children first) must keep it clean.
        results = seed_models([Maker, Widget], count=3, clear=True)
        assert results["Maker"].failed == 0
        assert results["Widget"].failed == 0
        assert db.fetch("SELECT * FROM maker", limit=100).count == 3
        assert db.fetch("SELECT * FROM widget", limit=100).count == 3
        db.close()
