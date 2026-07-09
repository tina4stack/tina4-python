# Lock-in tests for the v3.13.60 save() DX-hint pass.
#
# When save() hits a driver error for one of the two commonest ORM write
# footguns — a MISSING TABLE (you never called create_table()/ran a migration)
# or a MISSING is_deleted COLUMN on a soft_delete model — save() must APPEND a
# targeted, actionable hint to last_error / get_error() while keeping its
# contract intact: it returns ``self | False`` and NEVER raises. Any *other*
# driver error (e.g. NOT NULL) keeps its raw cause with no bogus hint.
#
# These also lock in the constructor-vs-save() asymmetry the docs describe:
# an explicit ``None`` on a required field RAISES at construction, but the same
# state reached via a setter makes save() return False (loud, not fatal).
#
# Engine-agnostic — real temp SQLite, no mocks.
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, Field, IntegerField


# ── Test Models ─────────────────────────────────────────────────


class GhostModel(ORM):
    # Auto-increment PK, table is never created — every save() hits
    # "no such table" and must return False WITH the create_table() hint.
    table_name = "ghost_hint_tbl"
    id = IntegerField(primary_key=True, auto_increment=True)
    label = Field(str)


class SoftPost(ORM):
    # soft_delete model that DECLARES is_deleted, but whose table is created
    # WITHOUT that column — the INSERT hits the missing column and must get
    # the "declare is_deleted / add a migration" hint.
    table_name = "soft_posts"
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    title = Field(str)
    is_deleted = IntegerField(default=0)


class NnUser(ORM):
    # name is NOT required in the model but NOT NULL at the DB, so a NULL name
    # passes ORM validation and is rejected by the driver — an UNRELATED error
    # that must keep its raw cause (no table/is_deleted hint bolted on).
    table_name = "nn_users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = Field(str)


class OkUser(ORM):
    # Happy-path model — its table exists, so save() succeeds.
    table_name = "ok_users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = Field(str)


class AsymUser(ORM):
    # required name with no default — the constructor-vs-save() asymmetry model.
    table_name = "asym_users"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = Field(str, required=True)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Fresh sqlite DB. Note which tables are deliberately absent/malformed:

    * ghost_hint_tbl — NOT created (missing-table path)
    * soft_posts     — created WITHOUT is_deleted (missing-column path)
    * nn_users       — name is NOT NULL at the DB (unrelated-error path)
    * ok_users       — well-formed (happy path)
    * asym_users     — well-formed (validation path)
    """
    d = Database(f"sqlite:///{tmp_path / 'orm_save_hints.db'}")
    d.execute("CREATE TABLE soft_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
    d.execute("CREATE TABLE nn_users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    d.execute("CREATE TABLE ok_users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    d.execute("CREATE TABLE asym_users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    d.commit()
    bind_database(d)
    yield d
    d.close()


# ── 1. Missing table → False + create_table() hint ──────────────


class TestMissingTableHint:
    def test_save_into_missing_table_returns_false_with_hint(self, db, capsys):
        """save() into a table that was never created returns False and the
        recorded cause carries the actionable create_table()/migration hint —
        naming the table and the model's create_table()."""
        g = GhostModel({"label": "x"})

        result = g.save()

        assert result is False                       # loud: documented False
        err = g.get_error()
        assert err == g.last_error                    # both surfaces agree
        assert err is not None
        low = err.lower()
        assert "no such table" in low                 # raw cause preserved...
        assert "ghost_hint_tbl" in err               # ...and the table named
        assert "create_table()" in err               # actionable next step
        assert "GhostModel.create_table()" in err    # names THIS model
        assert "migration" in low
        # Logged with model context.
        assert "GhostModel.save() failed" in capsys.readouterr().out


# ── 2. soft_delete missing is_deleted column → is_deleted hint ──


class TestSoftDeleteMissingColumnHint:
    def test_save_missing_is_deleted_column_returns_false_with_hint(self, db):
        """A soft_delete model whose table lacks is_deleted: save() returns
        False and the cause carries the 'declare is_deleted / add a migration'
        hint — not a bare driver message."""
        p = SoftPost({"title": "hello"})

        result = p.save()

        assert result is False
        err = p.get_error()
        assert err == p.last_error
        assert err is not None
        low = err.lower()
        assert "is_deleted" in low                    # raw driver cause mentions it
        assert "soft_delete=True requires an is_deleted column" in err
        assert "IntegerField(default=0)" in err       # the concrete fix
        assert "migration" in low
        # It did NOT get mis-tagged as a missing-table problem.
        assert "create_table()" not in err


# ── 3. Contract preserved: success is clean; unrelated errors stay raw ──


class TestContractPreserved:
    def test_success_returns_self_and_clears_error(self, db):
        """A normal successful save() returns the fluent instance and leaves
        last_error empty — no hint, no residue."""
        u = OkUser({"name": "Alice"})

        assert u.save() is u                          # fluent self
        assert u.last_error is None                   # clean
        assert u.get_error() is None
        assert OkUser.count() == 1                     # actually persisted

    def test_unrelated_driver_error_keeps_raw_cause_no_bogus_hint(self, db, capsys):
        """A NOT NULL violation (name NULL at the driver, but not required in
        the model so ORM validation passes) must return False with the RAW
        driver cause and NO table/is_deleted hint appended — we never mask an
        unrelated failure."""
        bad = NnUser({})                              # name defaults to None

        result = bad.save()

        assert result is False                        # loud: documented False
        err = bad.get_error()
        assert err == bad.last_error
        assert err is not None
        low = err.lower()
        assert "not null" in low                      # the real cause survives
        # None of the footgun hints were bolted on.
        assert "create_table()" not in err
        assert "does not exist" not in low
        assert "soft_delete=True requires" not in err
        assert "NnUser.save() failed" in capsys.readouterr().out
        assert NnUser.count() == 0                     # rolled back


# ── 4. Asymmetry lock-in: constructor RAISES / save() returns False ──


class TestConstructorVsSaveAsymmetry:
    def test_constructor_raises_on_explicit_none_required(self, db):
        """Passing an explicit None for a required field RAISES at construction
        — the model never gets built."""
        with pytest.raises(ValueError) as exc:
            AsymUser({"name": None})
        assert "required" in str(exc.value).lower()

    def test_save_returns_false_when_required_field_nulled_via_setter(self, db, capsys):
        """The SAME None reached through a setter is loud-but-not-fatal:
        Model() builds, then setting the required field to None makes save()
        return False (never raises) with the validation cause recoverable —
        proving the constructor-vs-save() asymmetry."""
        u = AsymUser()                                # builds fine (no raise)
        u.name = None                                 # now violates required=True

        result = u.save()                             # must NOT raise

        assert result is False
        err = u.get_error()
        assert err == u.last_error
        assert err is not None and "required" in err.lower()
        assert "validation failed" in capsys.readouterr().out.lower()
        assert AsymUser.count() == 0                   # never reached the driver
