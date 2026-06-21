# Lock-in regression tests for the v3.13.39 ORM "fail loud, never silent" pass.
#
# These contracts guard against silent-drift in the ORM/QueryBuilder failure
# paths. The principle (the same db.execute() already follows): a failure must
# never vanish silently — it returns the documented False/raises loudly AND the
# real cause stays recoverable. If any of these behaviours regresses to the old
# silent form, one of these named tests goes red.
#
# Engine-agnostic (sqlite is fine).
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, Field
from tina4_python.query_builder import QueryBuilder


# ── Test Models ─────────────────────────────────────────────────


class CUser(ORM):
    table_name = "cusers"
    id = Field(int, primary_key=True, auto_increment=True)
    name = Field(str, required=True)   # NOT NULL at the DB and required in the model
    email = Field(str)


class CWidget(ORM):
    table_name = "cwidgets"
    id = Field(int, primary_key=True, auto_increment=True)
    label = Field(str)


class CGhost(ORM):
    # Points at a table that is never created — every save() hits a driver
    # error ("no such table"), exercising create()'s failure propagation
    # through the DB-error path (construction + validate both succeed).
    table_name = "cghost_missing"
    id = Field(int, primary_key=True, auto_increment=True)
    label = Field(str)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Fresh sqlite DB with a NOT NULL column on cusers.name for the
    constraint-violation path."""
    d = Database(f"sqlite:///{tmp_path / 'orm_contracts.db'}")
    d.execute("CREATE TABLE cusers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
    d.execute("CREATE TABLE cwidgets (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT)")
    d.commit()
    bind_database(d)
    yield d
    d.close()


# ── 1. save() on a DB constraint violation: False + retrievable cause + logged ──


class TestSaveLoudOnDbError:
    def test_success_clears_error_and_returns_self(self, db):
        """Baseline: a valid save() returns the fluent self and clears any
        previously-recorded error."""
        u = CUser({"name": "Alice"})
        assert u.save() is u            # fluent self on success
        assert u.get_error() is None     # cleared on success
        assert u.last_error is None

    def test_db_error_is_loud_and_recoverable(self, db, capsys):
        """A genuine driver error (NOT NULL violation that validation cannot
        catch) must fail loud: save() returns False, the real cause is
        recoverable via get_error()/last_error, it is logged with model
        context, and nothing is committed.

        We make the model pass validation but null the NOT NULL column right
        after validate() runs, so the driver — not the validator — rejects the
        write. This isolates the DB-error path from the validation path."""
        bad = CUser({"name": "ok"})

        original_validate = bad.validate
        def _passing_then_null():
            errs = original_validate()   # validation passes (name is "ok")...
            bad.name = None               # ...then null the NOT NULL column
            return errs
        bad.validate = _passing_then_null

        result = bad.save()

        assert result is False                         # loud: documented False
        assert bad.get_error()                          # cause recoverable
        assert bad.last_error                            # same cause on attribute
        assert bad.get_error() == bad.last_error
        # It logged the failure with model context (Log writes to stdout).
        assert "CUser.save() failed" in capsys.readouterr().out
        assert CUser.count() == 0                       # rolled back — nothing landed


# ── 2. save() with validation errors: False, no row written, validate() ran ──


class TestSaveEnforcesValidation:
    def test_validation_failure_returns_false_and_writes_nothing(self, db, capsys):
        """A model failing validate() must not reach the driver: save() returns
        False, logs the validation errors, records them on last_error, and the
        row count is unchanged (proving the write was skipped).

        We construct a valid instance, then null the required field by direct
        attribute assignment (which bypasses the constructor's per-field
        validation) — the kind of state a setter or partial update can produce.
        save() must catch this via validate() before any DB write."""
        before = CUser.count()
        invalid = CUser({"name": "temp"})
        invalid.name = None                # now violates required=True

        # Sanity: validate() itself reports the error.
        assert invalid.validate(), "validate() should report the missing required field"

        result = invalid.save()

        assert result is False
        assert invalid.get_error()                     # cause recoverable
        assert "required" in invalid.get_error().lower()
        # It logged the validation failure (Log writes to stdout).
        assert "validation failed" in capsys.readouterr().out.lower()
        # The write never happened.
        assert CUser.count() == before


# ── 3. create() returns False when the underlying save fails ──


class TestCreatePropagatesFailure:
    def test_create_returns_false_when_save_fails(self, db):
        """create() must propagate save()'s failure: when the underlying save()
        returns False it returns False too, never a possibly-unsaved instance.
        CGhost points at a non-existent table, so its save() always hits a
        driver error and returns False."""
        result = CGhost.create({"label": "x"})
        assert result is False

    def test_create_returns_instance_on_success(self, db):
        """The happy path is unchanged: a valid create() returns the saved
        instance with its PK assigned."""
        user = CUser.create({"name": "Valid"})
        assert isinstance(user, CUser)
        assert user.id is not None
        assert CUser.count() == 1


# ── 4. QueryBuilder.get() with no .limit() returns ALL rows (>100) ──


class TestQueryBuilderNoSilentLimit:
    def test_get_returns_all_rows_with_no_limit(self, db):
        """No silent default LIMIT 100. Insert 150 rows, get() with no .limit()
        must return all 150 — not a silently-truncated 100."""
        for i in range(150):
            db.insert("cwidgets", {"label": f"w{i}"})
        db.commit()

        result = QueryBuilder.from_table("cwidgets", db).get()
        assert result.count == 150
        assert len(result.records) == 150

    def test_explicit_limit_is_still_honoured(self, db):
        """An explicit .limit(n) still caps the result — only the *silent*
        default was removed."""
        for i in range(150):
            db.insert("cwidgets", {"label": f"w{i}"})
        db.commit()

        result = QueryBuilder.from_table("cwidgets", db).limit(10).get()
        assert len(result.records) == 10

    def test_to_sql_injects_no_default_limit(self, db):
        """to_sql() must never inject a LIMIT clause on its own."""
        sql = QueryBuilder.from_table("cwidgets", db).to_sql().upper()
        assert "LIMIT" not in sql


# ── 5. to_mongo() raises ValueError (not a silent $where) on unparseable WHERE ──


class TestToMongoNoSilentWhere:
    def test_unparseable_condition_raises_valueerror(self, db):
        """An unparseable WHERE must raise a clear ValueError naming the clause
        — never get silently wrapped into a {'$where': <raw JS>} sink."""
        qb = QueryBuilder.from_table("cwidgets", db).where("label = label OR 1=1")
        # The raise itself proves no silent {'$where': <raw JS>} dict was
        # returned — to_mongo() never gets the chance to emit one.
        with pytest.raises(ValueError) as exc:
            qb.to_mongo()
        # The error names the offending clause so the caller can fix it.
        assert "label = label OR 1=1" in str(exc.value)

    def test_parseable_conditions_still_translate(self, db):
        """Supported forms still translate — only the silent fallback was
        removed."""
        mongo = (
            QueryBuilder.from_table("cwidgets", db)
            .where("label = ?", ["x"])
            .to_mongo()
        )
        assert mongo["filter"] == {"label": "x"}
