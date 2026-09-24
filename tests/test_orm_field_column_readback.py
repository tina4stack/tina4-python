"""ORM field column read-back: a Field(column=...) round-trips on every read path.

Bug (tina4-python origin/v3): ``name = StringField(column="full_name")`` was
WRITTEN to ``full_name`` (the write path honoured ``Field.column``) but the read
path did not reverse it. The hydrator only reversed ``field_mapping``, so a row
``{"id": 1, "full_name": "Ada"}`` came back with ``name = None`` and a stray
``full_name`` attribute. ``_get_db_column`` also ignored ``Field.column``, and
the ``find({...})`` filter, the soft-delete column and the relationship foreign
key did the same.

The fix is ONE resolver, ``ORM.get_db_column(attribute)``:
``field_mapping[attribute]``, else the Field's own ``column``, else the
attribute name. Every read and write path uses it, and hydration reverses the
same resolution.

Real databases, no mocks. Every case runs on SQLite, PostgreSQL, MySQL, MSSQL
and Firebird (Firebird folds unquoted identifiers to upper case, so it is the
engine most likely to disagree about a column name).
"""
from __future__ import annotations

import contextlib
import os
import socket
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, ForeignKeyField, IntegerField, StringField, bind_database
from tina4_python.orm.fields import has_one


_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)
_MYSQL = dict(
    host=os.environ.get("TINA4_TEST_MYSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306")),
    user=os.environ.get("TINA4_TEST_MYSQL_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test"),
)
_MSSQL = dict(
    host=os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433")),
    user=os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa"),
    pwd=os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "TinaSQL123!Secure"),
    db=os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test"),
)
_FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")

_ENGINES = ["sqlite", "postgres", "mysql", "mssql", "firebird"]

_TABLES = (
    "colrb_person", "colrb_mixed", "colrb_plain", "colrb_pet", "colrb_owner", "colrb_soft", "colrb_keyed",
    "colrb_named_key", "colrb_keyed_child",
)


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _open(engine, tmp_path) -> Database:
    if engine == "sqlite":
        return Database(f"sqlite:///{tmp_path / 'colrb.db'}")
    if engine == "firebird":
        if not _FIREBIRD_URL:
            pytest.skip("firebird not set: TINA4_TEST_FIREBIRD_URL (needs a live Firebird)")
        return Database(_FIREBIRD_URL)
    coordinates, scheme = {
        "postgres": (_PG, "postgresql"),
        "mysql": (_MYSQL, "mysql"),
        "mssql": (_MSSQL, "mssql"),
    }[engine]
    if not _reachable(coordinates["host"], coordinates["port"]):
        pytest.skip(f"{engine} unreachable at {coordinates['host']}:{coordinates['port']}")
    return Database(
        f"{scheme}://{coordinates['host']}:{coordinates['port']}/{coordinates['db']}",
        coordinates["user"], coordinates["pwd"],
    )


def _is_firebird(db) -> bool:
    return (db.get_database_type() or "").lower() == "firebird"


def _drop_tables(db):
    # A failed test can leave a transaction open; end it first so this
    # connection's locks never block the next test's DDL.
    with contextlib.suppress(Exception):
        db.rollback()
    for table in _TABLES:
        statements = [f"DROP TABLE {table}"]
        if _is_firebird(db):
            statements = [f"DROP TRIGGER {table}_bi", *statements, f"DROP GENERATOR gen_{table}_id"]
        for statement in statements:
            with contextlib.suppress(Exception):
                if _is_firebird(db) or db.table_exists(table):
                    db.execute(statement)
                    db.commit()


@pytest.fixture(params=_ENGINES)
def db(request, tmp_path):
    database = _open(request.param, tmp_path)
    bind_database(database)
    _drop_tables(database)
    try:
        yield database
    finally:
        _drop_tables(database)
        with contextlib.suppress(Exception):
            database.close()


# ── Models ──────────────────────────────────────────────────────────────────


class ColumnPerson(ORM):
    """A field that names its own column (no field_mapping)."""

    table_name = "colrb_person"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(column="full_name")


class ColumnMixed(ORM):
    """field_mapping on one field, Field(column=) on another."""

    table_name = "colrb_mixed"
    field_mapping = {"email": "email_address"}
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(column="full_name")
    email = StringField()


class ColumnPlain(ORM):
    """Neither is set: the attribute name IS the column (the negative case)."""

    table_name = "colrb_plain"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


class ColumnOwner(ORM):
    table_name = "colrb_owner"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(column="owner_name")
    pet = has_one("ColumnPet", foreign_key="owner_id")


class ColumnPet(ORM):
    """A foreign key whose column differs from its attribute."""

    table_name = "colrb_pet"
    id = IntegerField(primary_key=True, auto_increment=True, column="pet_id")
    name = StringField(column="pet_name")
    owner_id = ForeignKeyField(ColumnOwner, column="owner_ref", related_name="pets")


class ColumnSoft(ORM):
    """Soft delete whose flag column is named by Field(column=)."""

    table_name = "colrb_soft"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(column="full_name")
    is_deleted = IntegerField(default=0, column="deleted_flag")


class ColumnKeyed(ORM):
    """The primary key itself names its own column."""

    table_name = "colrb_keyed"
    id = IntegerField(primary_key=True, auto_increment=True, column="person_id")
    name = StringField(column="full_name")


class NamedKey(ORM):
    """An auto-increment key column that is simply not called "id"."""

    table_name = "colrb_named_key"
    person_id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


class ColumnKeyedChild(ORM):
    """A child whose foreign key points at a parent with a mapped key column."""

    table_name = "colrb_keyed_child"
    id = IntegerField(primary_key=True, auto_increment=True)
    keyed_id = ForeignKeyField(ColumnKeyed, related_name="children")
    label = StringField()


def _create(db, *models):
    for model in models:
        bind_database(db)
        assert model.create_table() is True, f"create_table({model.__name__}) failed: {db.get_error()}"
        if _is_firebird(db):
            # Firebird has no AUTOINCREMENT keyword: the adapter reads the new key
            # from a GEN_<TABLE>_ID generator, fed by a BEFORE INSERT trigger (the
            # real Firebird auto-key idiom, as in test_firebirdprovider_contract).
            table = model.table_name
            key = model.get_db_column(model._get_pk())
            db.execute(f"CREATE GENERATOR gen_{table}_id")
            db.execute(
                f"CREATE TRIGGER {table}_bi FOR {table} ACTIVE BEFORE INSERT POSITION 0 "
                f"AS BEGIN IF (NEW.{key} IS NULL) THEN NEW.{key} = GEN_ID(gen_{table}_id, 1); END"
            )
            db.commit()


def _raw_row(db, sql, params=None) -> dict:
    """Read a row straight from the table and lower-case its keys (Firebird
    folds unquoted identifiers to upper case) so the assertion is about WHERE
    the value landed, not about the driver's key casing."""
    row = db.fetch_one(sql, params or [])
    assert row is not None, f"no row for: {sql}"
    return {str(key).lower(): value for key, value in dict(row).items()}


def _assert_no_stray_column_attribute(instance, column):
    assert column not in vars(instance), (
        f"hydration left a stray '{column}' attribute on {type(instance).__name__}: "
        f"the DB column must map back onto its declared field"
    )


# ── Field(column=) round-trips on every read path ───────────────────────────


def test_field_column_write_lands_in_the_declared_column(db):
    _create(db, ColumnPerson)
    ColumnPerson.create(name="Ada")
    row = _raw_row(db, "SELECT full_name FROM colrb_person")
    assert row["full_name"] == "Ada"


def test_field_column_reads_back_through_find_by_primary_key(db):
    _create(db, ColumnPerson)
    saved = ColumnPerson.create(name="Ada")
    found = ColumnPerson.find(saved.id)
    assert found is not None
    assert found.name == "Ada"
    _assert_no_stray_column_attribute(found, "full_name")


def test_field_column_reads_back_through_all(db):
    _create(db, ColumnPerson)
    ColumnPerson.create(name="Ada")
    ColumnPerson.create(name="Grace")
    names = sorted(person.name for person in ColumnPerson.all())
    assert names == ["Ada", "Grace"]
    for person in ColumnPerson.all():
        _assert_no_stray_column_attribute(person, "full_name")


def test_field_column_reads_back_through_where(db):
    _create(db, ColumnPerson)
    ColumnPerson.create(name="Ada")
    ColumnPerson.create(name="Grace")
    rows = ColumnPerson.where("full_name = ?", ["Grace"])
    assert [person.name for person in rows] == ["Grace"]
    _assert_no_stray_column_attribute(rows[0], "full_name")


def test_field_column_filters_through_find_by_attribute_name(db):
    _create(db, ColumnPerson)
    ColumnPerson.create(name="Ada")
    ColumnPerson.create(name="Grace")
    rows = ColumnPerson.find({"name": "Ada"})
    assert [person.name for person in rows] == ["Ada"]


def test_field_column_sorts_and_reads_back_in_order(db):
    _create(db, ColumnPerson)
    for name in ("Grace", "Ada", "Linus"):
        ColumnPerson.create(name=name)
    # order_by is SQL (SQL-first ORM), so it names the column; every row it
    # returns must still hydrate onto the attribute, in the database's order.
    assert [p.name for p in ColumnPerson.all(order_by="full_name DESC")] == ["Linus", "Grace", "Ada"]
    assert [p.name for p in ColumnPerson.find(order_by="full_name ASC")] == ["Ada", "Grace", "Linus"]


def test_field_column_counts_and_loads(db):
    _create(db, ColumnPerson)
    saved = ColumnPerson.create(name="Ada")
    assert ColumnPerson.count("full_name = ?", ["Ada"]) == 1
    fresh = ColumnPerson()
    fresh.id = saved.id
    assert fresh.load() is True
    assert fresh.name == "Ada"


def test_field_column_updates_the_declared_column(db):
    _create(db, ColumnPerson)
    person = ColumnPerson.create(name="Ada")
    person.name = "Ada Lovelace"
    assert person.save() is person
    assert _raw_row(db, "SELECT full_name FROM colrb_person")["full_name"] == "Ada Lovelace"
    assert ColumnPerson.find(person.id).name == "Ada Lovelace"


def test_field_column_to_dict_uses_the_attribute_name(db):
    _create(db, ColumnPerson)
    saved = ColumnPerson.create(name="Ada")
    assert ColumnPerson.find(saved.id).to_dict() == {"id": saved.id, "name": "Ada"}


def test_get_db_column_resolves_field_column(db):
    assert ColumnPerson.get_db_column("name") == "full_name"
    assert ColumnPerson()._get_db_column("name") == "full_name"
    assert ColumnMixed.get_db_column("email") == "email_address"
    assert ColumnPlain.get_db_column("name") == "name"


# ── field_mapping and Field(column=) together ───────────────────────────────


def test_field_mapping_and_field_column_round_trip_together(db):
    _create(db, ColumnMixed)
    saved = ColumnMixed.create(name="Ada", email="ada@example.com")
    row = _raw_row(db, "SELECT full_name, email_address FROM colrb_mixed")
    assert row == {"full_name": "Ada", "email_address": "ada@example.com"}

    found = ColumnMixed.find(saved.id)
    assert (found.name, found.email) == ("Ada", "ada@example.com")
    _assert_no_stray_column_attribute(found, "full_name")
    _assert_no_stray_column_attribute(found, "email_address")

    by_name = ColumnMixed.find({"name": "Ada"})
    by_email = ColumnMixed.find({"email": "ada@example.com"})
    assert [m.id for m in by_name] == [saved.id]
    assert [m.id for m in by_email] == [saved.id]
    assert [m.name for m in ColumnMixed.all()] == ["Ada"]


# ── Neither set: the attribute name is the column ───────────────────────────


def test_plain_field_round_trips_unchanged(db):
    _create(db, ColumnPlain)
    saved = ColumnPlain.create(name="Ada")
    assert _raw_row(db, "SELECT name FROM colrb_plain")["name"] == "Ada"
    found = ColumnPlain.find(saved.id)
    assert found.name == "Ada"
    assert [p.name for p in ColumnPlain.find({"name": "Ada"})] == ["Ada"]
    assert [p.name for p in ColumnPlain.all()] == ["Ada"]


def test_undeclared_select_column_still_lands_as_an_extra_attribute(db):
    """Negative: a column that is NOT a declared field (a computed/joined column)
    keeps its own name on the instance -- the resolver only remaps declared
    columns."""
    _create(db, ColumnPerson)
    ColumnPerson.create(name="Ada")
    rows = ColumnPerson.select("SELECT id, full_name, 7 AS extra_value FROM colrb_person")
    person = rows[0]
    assert person.name == "Ada"
    extra = getattr(person, "extra_value", None)
    if extra is None:  # Firebird returns an unquoted alias upper-cased
        extra = getattr(person, "EXTRA_VALUE", None)
    assert extra == 7


# ── Relationships and soft delete use the same resolver ─────────────────────


def test_foreign_key_field_column_loads_lazy_and_eager(db):
    _create(db, ColumnOwner, ColumnPet)
    owner = ColumnOwner.create(name="Ada")
    ColumnPet.create(name="Rex", owner_id=owner.id)
    ColumnPet.create(name="Tom", owner_id=owner.id)

    assert _raw_row(db, "SELECT owner_ref FROM colrb_pet WHERE pet_name = ?", ["Rex"])["owner_ref"] == owner.id

    lazy = ColumnOwner.find(owner.id)
    assert sorted(pet.name for pet in lazy.pets) == ["Rex", "Tom"]
    assert lazy.pet.name in ("Rex", "Tom")

    eager = ColumnOwner.all(include=["pets"])[0]
    assert "pets" in eager._rel_cache
    assert sorted(pet.name for pet in eager.pets) == ["Rex", "Tom"]

    pet = ColumnPet.find({"name": "Rex"})[0]
    assert pet.owner_id == owner.id
    assert pet.owner.name == "Ada"
    eager_pet = ColumnPet.all(include=["owner"])[0]
    assert eager_pet.owner.name == "Ada"
    assert sorted(p.name for p in owner.has_many(ColumnPet, foreign_key="owner_id")) == ["Rex", "Tom"]
    # foreign_key may also be spelled as the COLUMN; it resolves to the same field.
    assert sorted(p.name for p in owner.has_many(ColumnPet, foreign_key="owner_ref")) == ["Rex", "Tom"]
    assert pet.belongs_to(ColumnOwner, foreign_key="owner_ref").name == "Ada"


def test_soft_delete_flag_honours_field_column(db):
    _create(db, ColumnSoft)
    keep = ColumnSoft.create(name="Ada")
    gone = ColumnSoft.create(name="Grace")
    assert gone.delete() is True
    assert _raw_row(db, "SELECT deleted_flag FROM colrb_soft WHERE full_name = ?", ["Grace"])["deleted_flag"] == 1
    assert [p.name for p in ColumnSoft.all()] == ["Ada"]
    assert ColumnSoft.find(gone.id) is None
    assert gone.restore() is True
    assert sorted(p.name for p in ColumnSoft.all()) == ["Ada", "Grace"]
    assert keep.id != gone.id


# ── A primary key with its own column ───────────────────────────────────────


def test_primary_key_field_column_round_trips(db):
    _create(db, ColumnKeyed)
    first = ColumnKeyed.create(name="Ada")
    second = ColumnKeyed.create(name="Grace")
    assert first.id is not None and second.id is not None and first.id != second.id
    assert _raw_row(db, "SELECT person_id, full_name FROM colrb_keyed WHERE person_id = ?", [first.id]) == {
        "person_id": first.id, "full_name": "Ada",
    }
    found = ColumnKeyed.find(first.id)
    assert (found.id, found.name) == (first.id, "Ada")
    _assert_no_stray_column_attribute(found, "person_id")

    found.name = "Ada Lovelace"
    assert found.save() is found
    assert ColumnKeyed.find(first.id).name == "Ada Lovelace"
    assert ColumnKeyed.find(second.id).name == "Grace", "an update must address only its own row"

    assert ColumnKeyed.find(second.id).delete() is True
    assert ColumnKeyed.find(second.id) is None
    assert [p.name for p in ColumnKeyed.all()] == ["Ada Lovelace"]


def test_non_id_auto_increment_key_is_set_after_save(db):
    """PostgreSQL read the new key from RETURNING only when the column was
    literally named "id", so any other key name came back None after save()."""
    _create(db, NamedKey)
    first = NamedKey.create(name="Ada")
    second = NamedKey.create(name="Grace")
    assert first.person_id is not None and second.person_id is not None
    assert first.person_id != second.person_id
    assert NamedKey.find(second.person_id).name == "Grace"


def test_seeder_draws_foreign_keys_from_a_mapped_parent_key(db):
    from tina4_python.seeder import seed_orm

    _create(db, ColumnKeyed, ColumnKeyedChild)
    parent_ids = {ColumnKeyed.create(name="Ada").id, ColumnKeyed.create(name="Grace").id}
    summary = seed_orm(ColumnKeyedChild, count=6, seed=7, strict=True)
    assert int(summary) == 6
    children = ColumnKeyedChild.all()
    assert len(children) == 6
    assert {child.keyed_id for child in children} <= parent_ids, (
        "the seeder must draw foreign keys from the parent's real key column"
    )
    # belongs_to a parent whose key column is mapped: lazy and eager.
    assert children[0].keyed.name in ("Ada", "Grace")
    eager_children = ColumnKeyedChild.all(include=["keyed"])
    # include= must fill the cache itself (not fall back to a lazy query).
    assert all("keyed" in child._rel_cache for child in eager_children)
    assert {child.keyed.name for child in eager_children} <= {"Ada", "Grace"}


def test_graphql_from_orm_resolves_a_field_column_model(db):
    from tina4_python.graphql import GraphQL

    _create(db, ColumnKeyed)
    saved = ColumnKeyed.create(name="Ada")
    graphql = GraphQL()
    graphql.schema.from_orm(ColumnKeyed)

    single = graphql.execute('{ columnkeyed(id: "%s") { id name } }' % saved.id)
    assert single.get("errors") in (None, []), single
    assert single["data"]["columnkeyed"]["name"] == "Ada"

    listed = graphql.execute("{ columnkeyeds { name } }")
    assert [row["name"] for row in listed["data"]["columnkeyeds"]] == ["Ada"]


def test_postgres_last_id_never_reports_a_stale_sequence_value(tmp_path):
    """Negative case for the non-"id" key fix: lastval() is session-wide, so an
    INSERT into a table WITHOUT a sequence must not report the value an earlier
    INSERT drew from another table's sequence."""
    db = _open("postgres", tmp_path)
    try:
        for table in ("colrb_named_key", "colrb_natural"):
            if db.table_exists(table):
                db.execute(f"DROP TABLE {table}")
        db.execute("CREATE TABLE colrb_named_key (person_id SERIAL PRIMARY KEY, name VARCHAR(100))")
        db.execute("CREATE TABLE colrb_natural (code VARCHAR(10) PRIMARY KEY, name VARCHAR(100))")
        db.commit()
        serial = db.insert("colrb_named_key", {"name": "Ada"})
        assert serial.last_id == 1
        natural = db.insert("colrb_natural", {"code": "A1", "name": "Grace"})
        assert natural.last_id is None, f"stale sequence value leaked: {natural.last_id!r}"
    finally:
        for table in ("colrb_named_key", "colrb_natural"):
            with contextlib.suppress(Exception):
                db.execute(f"DROP TABLE {table}")
                db.commit()
        db.close()
