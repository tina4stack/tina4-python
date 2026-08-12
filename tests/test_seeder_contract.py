"""Seeder + fake-data cross-engine contract - feature 28 (seeder_contract.json).

SEED-DEC-01 (OWNER-DECISIONS.md Batch 4, feature 028-seeder-fake-data.md):
  * SEED-PHP-BACKTICK: PHP's seed_table quoted identifiers with BACKTICKS
    (MySQL/SQLite only) so every INSERT raised a syntax error on PostgreSQL/
    Firebird (double-quote) and MSSQL (brackets) - the dev-admin
    POST /__dev/api/seed endpoint delegates to seed_table, so dashboard
    seeding was BROKEN on those three engines. Fixed by routing PHP's
    seed_table through the parameterized adapter Database::insert() path
    (the same path seed_orm already used), deleting the raw-SQL
    backtick-building code entirely.
  * SEED-TABLE-SEED-INERT: seed_table's `seed` argument was a silent no-op in
    all four (it has no generators of its own to seed - field_map/columns
    callables are opaque). OWNER-DECISIONS.md ratified REMOVAL (same
    principle as the no-op ForeignKeyField `on_delete`) rather than threading
    a seeded FakeData through it: the parameter now RAISES if a non-default
    value is passed, and determinism is achieved by the caller building their
    own seeded FakeData and closing over it in field_map/columns - exactly
    the pattern seed_orm/seed_models already use internally. (Ruby's
    seed_table was, uniquely, NOT fully inert for the plain-type-string
    columns form - it still gets unified for consistency with the ratified
    "remove it" decision; see tina4-ruby's seeder.rb docblock.)

SEED-DEC-02 (low): Node's `forField` always returned a field's declared
default (a dead "sometimes" comment) so every seeded row got an IDENTICAL
value for a defaulted field - fixed to use the default only
PROBABILISTICALLY. Ruby's `FakeData#boolean` returned 0/1 (Integer) instead
of a native boolean, and `seed_orm`'s idempotency short-circuit silently
skipped seeding a table already holding >= count UNRELATED rows - both
fixed (native boolean; the skip is now opt-in via `idempotent:`, off by
default, matching Python/PHP/Node which never silently skip based on
existing row count). SEED-DETERMINISM-PERLANG and SEED-SECRETS-DOC are
documented on the FakeData class docblock in all four. SEED-VOCAB-PARITY
pins one generator vocabulary (idiomatic spelling per language) present in
all four, gated below.

Real engines only, no mocks: SQLite (local, fast) + PostgreSQL :55432 +
MSSQL :1433 + Firebird :3050 (the lab's real service coordinates - same
TINA4_TEST_* convention as pgprovider/mssqlprovider/firebirdprovider
contract). `seed_table_inserts_on_every_engine` is the ONLY case that must
run on all three non-SQLite engines - it is the direct regression guard for
SEED-PHP-BACKTICK. The other cases are seeder-LOGIC properties (RNG
determinism, FK topo-order, failure counting) that are engine-agnostic once
routed through the already adapter-contract-proven db.insert()/ORM.save()
paths, so they run on SQLite + PostgreSQL for a real-engine sanity check
without re-proving the adapter contracts a second time.

Mutation-proof (exercised manually during release verification, restored
after):
  * reinstate PHP's backtick-quoted raw SQL in seed_table ->
    seed_table_inserts_on_every_engine goes RED on PostgreSQL/MSSQL/Firebird
    (a syntax error at or near the backtick/bracket character).
  * make a field_map closure build a FRESH unseeded FakeData per call instead
    of reading the caller-seeded one -> seeded_run_reproduces_identical_rows
    goes RED (two runs diverge).
"""
import os
import socket

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, ForeignKeyField, bind_database
from tina4_python.seeder import FakeData, seed_table, seed_orm, seed_models


# ── real-service coordinates (the canonical TINA4_TEST_* convention - same
#    as pgprovider/mssqlprovider/firebirdprovider_contract) ─────────────────
_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)
_MSSQL = dict(
    host=os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433")),
    user=os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa"),
    pwd=os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "TinaSQL123!Secure"),
    db=os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test"),
)
FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


needs_pg = pytest.mark.skipif(
    not _reachable(_PG["host"], _PG["port"]),
    reason=f"no reachable postgres at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)",
)
needs_mssql = pytest.mark.skipif(
    not _reachable(_MSSQL["host"], _MSSQL["port"]),
    reason=f"no reachable mssql at {_MSSQL['host']}:{_MSSQL['port']} (set TINA4_TEST_MSSQL_*)",
)
needs_firebird = pytest.mark.skipif(
    not FIREBIRD_URL, reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)"
)


def _pg_db() -> Database:
    return Database(f"postgresql://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])


def _mssql_db() -> Database:
    return Database(f"mssql://{_MSSQL['host']}:{_MSSQL['port']}/{_MSSQL['db']}", _MSSQL["user"], _MSSQL["pwd"])


def _firebird_db() -> Database:
    return Database(FIREBIRD_URL)


def _sqlite_db(path) -> Database:
    return Database(f"sqlite:///{path}")


def _drop(db: Database, *statements: str) -> None:
    """Best-effort cleanup - tolerant of "does not exist" on a fresh DB."""
    for stmt in statements:
        try:
            db.execute(stmt)
        except Exception:
            pass


def _close(db: Database) -> None:
    try:
        db.close()
    except Exception:
        pass


# ── seed_table_inserts_on_every_engine ───────────────────────────────────
# Catches SEED-PHP-BACKTICK: creates the table with each engine's real DDL,
# seeds 5 rows through seed_table (no ORM involved - this is the raw-SQL
# INSERT path specifically), and reads every row back on the SAME engine.

def _seed_table_roundtrip(db: Database, table: str, setup_statements: list, drop_statements: list) -> None:
    _drop(db, *drop_statements)
    try:
        for stmt in setup_statements:
            db.execute(stmt)
        fake = FakeData(seed=1)
        summary = seed_table(db, table, 5, field_map={
            "name": fake.name,
            "score": lambda: fake.integer(1, 100),
        })
        assert summary.seeded == 5, f"{table}: seeded={summary.seeded} errors={summary.errors}"
        assert summary.failed == 0
        rows = db.fetch(f"SELECT name, score FROM {table}", limit=100).records
        assert len(rows) == 5
        for row in rows:
            assert row["name"]
            assert 1 <= int(row["score"]) <= 100
    finally:
        _drop(db, *drop_statements)
        _close(db)


class TestSeedTableInsertsOnEveryEngine:
    def test_seed_table_inserts_on_every_engine_sqlite(self, tmp_path):
        table = "contract_sqlite"
        db = _sqlite_db(tmp_path / "seed_contract.db")
        _seed_table_roundtrip(
            db, table,
            setup_statements=[
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                f"name TEXT, score INTEGER)",
            ],
            drop_statements=[f"DROP TABLE {table}"],
        )

    @needs_pg
    def test_seed_table_inserts_on_every_engine_postgresql(self):
        table = "contract_pg"
        _seed_table_roundtrip(
            _pg_db(), table,
            setup_statements=[
                f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, name VARCHAR(100), score INTEGER)",
            ],
            drop_statements=[f"DROP TABLE {table}"],
        )

    @needs_mssql
    def test_seed_table_inserts_on_every_engine_mssql(self):
        table = "contract_mssql"
        _seed_table_roundtrip(
            _mssql_db(), table,
            setup_statements=[
                f"CREATE TABLE {table} (id INTEGER IDENTITY(1,1) PRIMARY KEY, "
                f"name VARCHAR(100), score INTEGER)",
            ],
            drop_statements=[f"DROP TABLE {table}"],
        )

    @needs_firebird
    def test_seed_table_inserts_on_every_engine_firebird(self):
        # Firebird has no AUTOINCREMENT - the real idiom is a generator +
        # BEFORE INSERT trigger (same pattern firebirdprovider_contract.py
        # uses), so `id` is assigned without seed_table needing to know it.
        table = "contract_fb"
        _seed_table_roundtrip(
            _firebird_db(), table,
            setup_statements=[
                f"CREATE TABLE {table} (id INTEGER NOT NULL PRIMARY KEY, "
                f"name VARCHAR(100), score INTEGER)",
                f"CREATE GENERATOR gen_{table}_id",
                f"CREATE TRIGGER {table}_bi FOR {table} ACTIVE BEFORE INSERT POSITION 0 "
                f"AS BEGIN IF (NEW.id IS NULL) THEN NEW.id = GEN_ID(gen_{table}_id, 1); END",
            ],
            drop_statements=[
                f"DROP TRIGGER {table}_bi",
                f"DROP TABLE {table}",
                f"DROP GENERATOR gen_{table}_id",
            ],
        )


# ── seeded_run_reproduces_identical_rows ─────────────────────────────────
# seed_orm/seed_models: their OWN `seed=` is deterministic (unchanged).
# seed_table: no longer HAS a `seed=` (removed) - the documented replacement
# is a caller-seeded FakeData closed over in field_map, proven here.

class TestSeededRunReproducesIdenticalRows:
    def test_seeded_run_reproduces_identical_rows_seed_orm(self, tmp_path):
        def run(path):
            db = _sqlite_db(path)
            bind_database(db)
            # Table name matches the ORM's derived name (lowercased class
            # name, no underscores) - contractseedormperson.
            db.execute(
                "CREATE TABLE contractseedormperson (id INTEGER PRIMARY KEY "
                "AUTOINCREMENT, name TEXT, email TEXT, age INTEGER)"
            )
            db.commit()

            class ContractSeedOrmPerson(ORM):
                id = IntegerField(primary_key=True, auto_increment=True)
                name = StringField()
                email = StringField()
                age = IntegerField()

            seed_orm(ContractSeedOrmPerson, count=6, seed=4242)
            rows = [
                (row["name"], row["email"], row["age"])
                for row in db.fetch(
                    "SELECT * FROM contractseedormperson ORDER BY id", limit=1000
                )
            ]
            db.close()
            return rows

        a = run(tmp_path / "seedorm_a.db")
        b = run(tmp_path / "seedorm_b.db")
        assert a == b
        assert len(a) == 6

    def test_seeded_run_reproduces_identical_rows_seed_table(self, tmp_path):
        # Replacement pattern for the removed seed_table(seed=): the caller
        # builds its OWN seeded FakeData and closes over it in field_map.
        def run(path):
            db = _sqlite_db(path)
            db.execute(
                "CREATE TABLE contract_seedtable_raw (id INTEGER PRIMARY KEY "
                "AUTOINCREMENT, name TEXT, score INTEGER)"
            )
            db.commit()
            fake = FakeData(seed=777)
            seed_table(db, "contract_seedtable_raw", 6, field_map={
                "name": fake.name,
                "score": lambda: fake.integer(1, 1000),
            })
            rows = [
                (row["name"], row["score"])
                for row in db.fetch(
                    "SELECT * FROM contract_seedtable_raw ORDER BY id", limit=1000
                )
            ]
            db.close()
            return rows

        a = run(tmp_path / "seedtable_a.db")
        b = run(tmp_path / "seedtable_b.db")
        assert a == b
        assert len(a) == 6

    def test_seeded_run_reproduces_identical_rows_seed_table_seed_param_raises(self, tmp_path):
        # SEED-TABLE-SEED-INERT fix, mutation witness: seed_table's OWN
        # seed= is gone - passing a real value now RAISES instead of
        # silently doing nothing.
        db = _sqlite_db(tmp_path / "raises.db")
        db.execute("CREATE TABLE contract_seedtable_raises (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        db.commit()
        with pytest.raises(ValueError):
            seed_table(db, "contract_seedtable_raises", 1, field_map={"name": lambda: "x"}, seed=99)
        db.close()

    @needs_pg
    def test_seeded_run_reproduces_identical_rows_postgresql(self):
        def run(table):
            db = _pg_db()
            _drop(db, f"DROP TABLE {table}")
            db.execute(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, name VARCHAR(100), score INTEGER)")
            fake = FakeData(seed=555)
            seed_table(db, table, 5, field_map={
                "name": fake.name,
                "score": lambda: fake.integer(1, 100),
            })
            rows = [(r["name"], r["score"]) for r in db.fetch(f"SELECT * FROM {table} ORDER BY id", limit=100).records]
            _drop(db, f"DROP TABLE {table}")
            _close(db)
            return rows

        a = run("contract_repro_pg_a")
        b = run("contract_repro_pg_b")
        assert a == b
        assert len(a) == 5


# ── seed_models_orders_parents_before_children ───────────────────────────

class TestSeedModelsOrdersParentsBeforeChildren:
    def test_seed_models_orders_parents_before_children_sqlite(self, tmp_path):
        db = _sqlite_db(tmp_path / "fk_contract.db")
        bind_database(db)
        db.execute(
            "CREATE TABLE seedercontractauthor (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        )
        db.execute(
            "CREATE TABLE seedercontractbook (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
            "author_id INTEGER NOT NULL REFERENCES seedercontractauthor(id))"
        )
        db.commit()

        class SeederContractAuthor(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        class SeederContractBook(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            title = StringField()
            author_id = ForeignKeyField(to=SeederContractAuthor)

        # Children declared BEFORE parents on purpose - topo-sort must fix it.
        results = seed_models([SeederContractBook, SeederContractAuthor], count=5, seed=3)

        assert results["SeederContractAuthor"].seeded == 5
        assert results["SeederContractAuthor"].failed == 0
        assert results["SeederContractBook"].seeded == 5
        assert results["SeederContractBook"].failed == 0  # real parent PKs, no FK violation

        orphans = db.fetch(
            "SELECT * FROM seedercontractbook WHERE author_id NOT IN "
            "(SELECT id FROM seedercontractauthor)",
            limit=100,
        )
        assert orphans.count == 0
        db.close()

    @needs_pg
    def test_seed_models_orders_parents_before_children_postgresql(self):
        db = _pg_db()
        bind_database(db)
        _drop(db, "DROP TABLE seedercontractpgbook", "DROP TABLE seedercontractpgauthor")
        db.execute("CREATE TABLE seedercontractpgauthor (id SERIAL PRIMARY KEY, name VARCHAR(100))")
        db.execute(
            "CREATE TABLE seedercontractpgbook (id SERIAL PRIMARY KEY, title VARCHAR(100), "
            "author_id INTEGER NOT NULL REFERENCES seedercontractpgauthor(id))"
        )

        class SeederContractPgAuthor(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        class SeederContractPgBook(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            title = StringField()
            author_id = ForeignKeyField(to=SeederContractPgAuthor)

        try:
            results = seed_models([SeederContractPgBook, SeederContractPgAuthor], count=5, seed=9)

            assert results["SeederContractPgAuthor"].seeded == 5
            assert results["SeederContractPgAuthor"].failed == 0
            assert results["SeederContractPgBook"].seeded == 5
            assert results["SeederContractPgBook"].failed == 0

            orphans = db.fetch(
                "SELECT * FROM seedercontractpgbook WHERE author_id NOT IN "
                "(SELECT id FROM seedercontractpgauthor)",
                limit=100,
            )
            assert orphans.count == 0
        finally:
            _drop(db, "DROP TABLE seedercontractpgbook", "DROP TABLE seedercontractpgauthor")
            _close(db)


# ── failures_are_counted_not_silent ──────────────────────────────────────

class TestFailuresAreCountedNotSilent:
    def test_failures_are_counted_not_silent_sqlite(self, tmp_path):
        db = _sqlite_db(tmp_path / "fail_contract.db")
        db.execute(
            "CREATE TABLE contract_fail (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT, email TEXT NOT NULL)"
        )
        db.commit()
        # email is NOT NULL but every generated value is None -> every INSERT
        # violates the constraint - never silent, never a crash.
        summary = seed_table(db, "contract_fail", 4, field_map={
            "name": lambda: "someone",
            "email": None,
        })
        assert summary.seeded == 0
        assert summary.failed == 4
        assert len(summary.errors) == 4
        assert summary.errors[0]["row"] == 0
        assert db.fetch("SELECT * FROM contract_fail", limit=100).count == 0
        db.close()

    def test_failures_are_counted_not_silent_strict_reraises(self, tmp_path):
        db = _sqlite_db(tmp_path / "fail_strict.db")
        db.execute(
            "CREATE TABLE contract_fail_strict (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, email TEXT NOT NULL)"
        )
        db.commit()
        with pytest.raises(Exception):
            seed_table(db, "contract_fail_strict", 3, field_map={"email": None}, strict=True)
        db.close()

    @needs_pg
    def test_failures_are_counted_not_silent_postgresql(self):
        db = _pg_db()
        table = "contract_fail_pg"
        _drop(db, f"DROP TABLE {table}")
        db.execute(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, email VARCHAR(100) NOT NULL)")
        try:
            summary = seed_table(db, table, 4, field_map={"email": None})
            assert summary.seeded == 0
            assert summary.failed == 4
            assert db.fetch(f"SELECT * FROM {table}", limit=100).count == 0
        finally:
            _drop(db, f"DROP TABLE {table}")
            _close(db)


# ── generator_vocabulary_present ─────────────────────────────────────────
# SEED-VOCAB-PARITY: this exact generator set (idiomatic spelling per
# language) exists in all four - Python/PHP/Ruby/Node.

GENERATOR_VOCABULARY = [
    "name", "first_name", "last_name", "email", "phone", "address", "city",
    "country", "zip_code", "company", "job_title", "sentence", "paragraph",
    "text", "word", "integer", "numeric", "boolean", "date", "datetime",
    "uuid", "url", "color_hex", "currency", "ip_address", "credit_card",
    "choice", "for_field",
]


class TestGeneratorVocabularyPresent:
    def test_generator_vocabulary_present(self):
        fake = FakeData(seed=1)
        for generator_name in GENERATOR_VOCABULARY:
            assert hasattr(fake, generator_name), f"FakeData missing generator: {generator_name}"

        assert isinstance(fake.name(), str) and fake.name()
        assert isinstance(fake.first_name(), str) and fake.first_name()
        assert isinstance(fake.last_name(), str) and fake.last_name()
        assert "@" in fake.email()
        assert fake.phone()
        assert fake.address()
        assert fake.city()
        assert fake.country()
        assert fake.zip_code()
        assert fake.company()
        assert fake.job_title()
        assert fake.sentence()
        assert fake.paragraph()
        assert fake.text()
        assert fake.word()
        assert isinstance(fake.integer(1, 10), int)
        assert isinstance(fake.numeric(0, 10), float)
        assert isinstance(fake.boolean(), bool)
        assert fake.date()
        assert fake.datetime()
        assert fake.uuid()
        assert fake.url().startswith("https://")
        assert fake.color_hex().startswith("#")
        assert len(fake.currency()) == 3
        assert fake.ip_address().count(".") == 3
        assert fake.credit_card()
        assert fake.choice([1, 2, 3]) in (1, 2, 3)
        assert fake.for_field({"type": "string"}) is not None
