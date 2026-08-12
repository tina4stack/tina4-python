# Boot-gate for the "ORM Lifecycle & Footguns" section of the
# tina4-developer-python skill (references/data-and-orm.md).
#
# Every test here pins one documented claim to real behaviour against a real
# SQLite database (no mocks). If the framework changes so a documented "safe"
# idiom stops running, or a documented negative stops biting, the matching
# test goes red — the doc and the framework can't silently drift apart.
#
# Run:  .venv/bin/python -m pytest tests/test_orm_footguns_doc.py -q
# Engine-agnostic; SQLite is the reference engine.
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database
from tina4_python import (
    IntegerField, StringField, TextField, BooleanField,
)


# ── Models ──────────────────────────────────────────────────────

class FUser(ORM):
    table_name = "fusers"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)          # required + NOT NULL
    email = StringField()
    role = StringField(choices=["admin", "user"])   # read-path constraint
    is_active = BooleanField(default=True)


class FGhost(ORM):
    # Table is never created — every save() hits "no such table".
    table_name = "fghost_missing"
    id = IntegerField(primary_key=True, auto_increment=True)
    label = StringField()


class ArticleGood(ORM):
    # Soft-delete DONE RIGHT: is_deleted is declared, so create_table()
    # emits the column the soft-delete machinery reads/writes.
    table_name = "articles_good"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    is_deleted = IntegerField(default=0)


class ArticleBad(ORM):
    # soft_delete=True but is_deleted is NOT declared. Since SOFTDEL-DEC-02
    # create_table() INJECTS the is_deleted column for a soft-delete model, so
    # this no-manual-column model gets a usable schema and the full soft-delete
    # lifecycle works (the old footgun — a table with no is_deleted column — is
    # closed).
    table_name = "articles_bad"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'footguns.db'}")
    bind_database(d)
    yield d
    d.close()


# ── Footgun: no auto table-create + save() returns False (never raises) ──

class TestNoAutoTableCreate:
    def test_save_into_missing_table_returns_false_not_raise(self, db):
        """save() into a table that doesn't exist returns False — it does NOT
        raise, and it does NOT create the table for you."""
        ghost = FGhost({"label": "x"})
        result = ghost.save()                       # no FGhost.create_table() called
        assert result is False                       # documented: False, not an exception
        assert ghost.get_error()                     # cause is recoverable...
        assert ghost.last_error == ghost.get_error() # ...on both surfaces
        assert "fghost_missing" in ghost.last_error or "no such table" in ghost.last_error.lower()

    def test_safe_idiom_create_table_then_save_runs(self, db):
        """The safe idiom: create_table() first (or a migration), THEN save()."""
        assert FUser.create_table() is True
        u = FUser({"name": "Alice", "email": "a@x.com"})
        assert u.save() is u                         # fluent self on success
        assert u.id is not None
        assert u.get_error() is None


# ── Footgun: constructor RAISES (the 500-vs-4xx trap) vs save() returns False ──

class TestConstructorRaisesVsSaveReturnsFalse:
    def test_construct_with_required_none_raises(self, db):
        """Model({"required": None}) validates on the READ path (_populate) and
        RAISES ValueError — an unhandled 500 if it wraps request.body."""
        with pytest.raises(ValueError):
            FUser({"name": None})

    def test_construct_non_dict_raises_typeerror(self, db):
        """A non-dict / non-JSON-string positional arg raises TypeError."""
        with pytest.raises(TypeError):
            FUser(["not", "a", "dict"])

    def test_construct_none_and_empty_are_safe(self, db):
        """FUser(None) / FUser() do NOT raise — defaults only (contrast with a
        dict carrying a bad value)."""
        FUser.create_table()
        assert FUser(None).name is None
        assert FUser().is_active is True             # default applied

    def test_read_path_choices_constraint_raises_on_construct(self, db):
        """Field constraints (choices/regex/length) validate on _populate too —
        an out-of-choices value raises at construction, not at save()."""
        with pytest.raises(ValueError):
            FUser({"name": "Bob", "role": "superadmin"})   # not in choices

    def test_set_then_save_returns_false_recoverable(self, db):
        """The recoverable path: build valid, null the required field by
        assignment, save() -> False with the cause on get_error() (4xx-able),
        NOT a raise. This is the asymmetry the doc warns about."""
        FUser.create_table()
        u = FUser({"name": "temp"})
        u.name = None                                # bypasses constructor validation
        result = u.save()
        assert result is False
        assert "required" in u.get_error().lower()


# ── Footgun: delete()/restore() RAISE (asymmetry with save()) ──

class TestDeleteRestoreRaise:
    def test_delete_without_pk_raises(self, db):
        """delete() raises ValueError when there's no primary key value —
        unlike save(), it does not return False."""
        FUser.create_table()
        u = FUser({"name": "NoPk"})                  # never saved, id is None
        with pytest.raises(ValueError):
            u.delete()

    def test_restore_on_non_softdelete_model_raises(self, db):
        """restore() raises RuntimeError on a model without soft_delete."""
        FUser.create_table()
        u = FUser.create({"name": "Real"})
        with pytest.raises(RuntimeError):
            u.restore()


# ── SOFTDEL-DEC-02: soft_delete WITHOUT a manual is_deleted now works too ──

class TestSoftDeleteNeedsColumn:
    def test_softdelete_without_is_deleted_column_is_injected(self, db):
        """soft_delete=True with NO declared is_deleted: create_table() now
        INJECTS the is_deleted column (SOFTDEL-DEC-02), so the soft-delete
        read/write path works with no manual column declaration."""
        assert ArticleBad.create_table() is True
        # create_table() injected the flag column.
        cols = {c["name"] if isinstance(c, dict) else c for c in db.get_columns("articles_bad")}
        assert "is_deleted" in cols
        # The full lifecycle runs on the injected schema.
        a = ArticleBad.create({"title": "Auto"})
        assert len(ArticleBad.all()) == 1
        a.delete()                                   # soft: sets is_deleted = 1
        assert len(ArticleBad.all()) == 0            # excluded by default
        assert len(ArticleBad.with_trashed()) == 1   # still present in the DB

    def test_softdelete_with_is_deleted_column_works(self, db):
        """Declare is_deleted = IntegerField(default=0) and the full soft-delete
        lifecycle runs: all()/delete()/restore()/with_trashed()."""
        assert ArticleGood.create_table() is True
        a = ArticleGood.create({"title": "Hello"})
        assert a.id is not None
        assert len(ArticleGood.all()) == 1
        a.delete()                                   # soft: sets is_deleted = 1
        assert a.is_deleted == 1
        assert len(ArticleGood.all()) == 0           # excluded by default
        assert len(ArticleGood.with_trashed()) == 1  # still there
        a.restore()                                  # sets is_deleted = 0
        assert len(ArticleGood.all()) == 1


# ── Footgun: db.execute() RAISES (not False); DatabaseResult isn't a list ──

class TestRawSqlContracts:
    def test_execute_raises_on_bad_sql(self, db):
        """db.execute() fails LOUD — it raises, and never returns False."""
        with pytest.raises(Exception):
            db.execute("INSERT INTO nope_table (x) VALUES (?)", [1])
        assert db.get_error()                        # cause captured for get_error()

    def test_databaseresult_is_not_a_list(self, db):
        """db.fetch() returns a DatabaseResult — rows live on .records and are
        dict-access. The result object is not a plain list."""
        FUser.create_table()
        FUser.create({"name": "Row1", "email": "r1@x.com"})
        result = db.fetch("SELECT * FROM fusers")
        assert not isinstance(result, list)
        assert isinstance(result.records, list)
        assert result.records[0]["name"] == "Row1"   # dict access, not .name
        with pytest.raises(AttributeError):
            result.records.to_array()                 # a list has no .to_array()
